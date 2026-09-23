#!/usr/bin/env python3
"""Capture IQ from the Fishball7020 / PlutoSky and write it as SigMF.

A bare .bin has no sample rate, no centre frequency, no gain and no date, so a
year later it is a file you are afraid to delete. SigMF fixes that with a JSON
sidecar: the samples are untouched, and every tool that read the bare file still
reads it.

    # one channel, wrap a capture you already took
    ./sigmf-capture.py wrap capture.bin

    # one channel, capture and wrap together
    ./sigmf-capture.py record out --rate 10e6 --freq 900e6 --seconds 5

    # BOTH receivers, coherently, into one recording
    ./sigmf-capture.py record out --channels both --rate 3e6 --freq 900e6 --seconds 5

    # ... or as two separate single-channel recordings
    ./sigmf-capture.py record out --channels both --split --rate 3e6 --seconds 5

Everything written into the sidecar is READ BACK from the board after
configuration, never taken from the arguments: the AD9361 quantises gain to its
own table, rf_bandwidth snaps to what the filter design supports, and
sampling_frequency lands on what the clock tree can produce. A value you wrote
is an intention; a value you read back is a fact.

Needs only python3 and libiio's command-line tools. numpy is required only for
--split and --verify.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys

PHY = "ad9361-phy"
RX = "cf-ad9361-lpc"

# Two different numbering schemes, and mixing them up is the easiest mistake here:
#
#   ad9361-phy     input voltage0 = RX1, voltage1 = RX2        (gain, rate, bandwidth)
#   cf-ad9361-lpc  input voltage0/1 = RX1 I/Q, voltage2/3 = RX2 I/Q   (the sample stream)
#
# Verified on hardware: setting phy voltage0 to 10 dB while voltage1 sat at 73 dB
# made words 0,1 of the stream 32 dB quieter than words 2,3.
def phy_ch(n):
    return "voltage%d" % n


def dma_iq(n):
    return ("voltage%d" % (2 * n), "voltage%d" % (2 * n + 1))


# The AD9361's converters are 12-bit, delivered sign-extended into an int16, so
# full scale is +-2047 and NOT +-32767. SigMF's ci16_le describes the container
# and cannot express that, so it is recorded explicitly in the sidecar.
# Divide by 32768 instead and every absolute level you quote is 24 dB too low.
RX_FULL_SCALE = 2047


def attr(uri, *args):
    """One iio_attr call. Returns the value as a string, or None."""
    try:
        out = subprocess.run(["iio_attr", "-u", uri, *args],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    # iio_attr prints the value first and any unit after it, e.g. "73.000000 dB",
    # so take the FIRST token - the last one is "dB" and parses as a string.
    lines = out.stdout.strip().splitlines()
    if not lines:
        return None
    parts = lines[-1].split()
    return parts[0] if parts else None


def num(value):
    """Best-effort numeric conversion; keeps the string if it is not a number."""
    if value is None:
        return None
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value


def read_back(uri, channels):
    """Everything worth recording, read from the board rather than assumed."""
    first = phy_ch(channels[0])
    info = {
        # rate, bandwidth and the LO are shared by both receivers - there is only
        # one RX_LO on this chip, which is exactly why the two chains are coherent.
        "sample_rate":  num(attr(uri, "-i", "-c", PHY, first, "sampling_frequency")),
        "rf_bandwidth": num(attr(uri, "-i", "-c", PHY, first, "rf_bandwidth")),
        # RX_LO is an OUTPUT channel of ad9361-phy, hence -o. Reading it with -i
        # silently returns nothing and the sidecar ends up with a null frequency.
        "frequency":    num(attr(uri, "-o", "-c", PHY, "altvoltage0", "frequency")),
        "fabric_rate":  num(attr(uri, "-i", "-c", RX, "voltage0", "sampling_frequency")),
        "temp_millideg": num(attr(uri, "-c", PHY, "temp0", "input")),
        "per_channel": {},
    }
    # gain is the one thing that really is per-channel
    for n in channels:
        ch = phy_ch(n)
        info["per_channel"][n] = {
            "hardwaregain_db":    num(attr(uri, "-i", "-c", PHY, ch, "hardwaregain")),
            "gain_control_mode":  attr(uri, "-i", "-c", PHY, ch, "gain_control_mode"),
            "rssi_db_below_fs":   num(attr(uri, "-i", "-c", PHY, ch, "rssi")),
        }
    return info


def configure(uri, channels, rate, freq, bandwidth, gain, gain_mode):
    """Set only what was asked for. Receive side only - nothing here transmits."""
    first = phy_ch(channels[0])
    if rate is not None:
        attr(uri, "-i", "-c", PHY, first, "sampling_frequency", str(int(rate)))
    if bandwidth is not None:
        attr(uri, "-i", "-c", PHY, first, "rf_bandwidth", str(int(bandwidth)))
    if freq is not None:
        attr(uri, "-o", "-c", PHY, "altvoltage0", "frequency", str(int(freq)))
    for n in channels:
        ch = phy_ch(n)
        if gain_mode is not None:
            attr(uri, "-i", "-c", PHY, ch, "gain_control_mode", gain_mode)
        if gain is not None:
            attr(uri, "-i", "-c", PHY, ch, "hardwaregain", str(gain))


def capture(uri, path, samples, channels, buffer_size):
    """Run iio_readdev into path. Returns wall-clock seconds."""
    chans = []
    for n in channels:
        chans.extend(dma_iq(n))
    cmd = ["iio_readdev", "-u", uri, "-b", str(buffer_size), "-s", str(int(samples)),
           RX, *chans]
    print("+ " + " ".join(cmd) + " > " + path, file=sys.stderr)
    start = datetime.datetime.now()
    with open(path, "wb") as f:
        rc = subprocess.run(cmd, stdout=f).returncode
    elapsed = (datetime.datetime.now() - start).total_seconds()
    if rc != 0:
        sys.exit("iio_readdev failed with exit code %d" % rc)
    return elapsed


def global_block(info, channels, description, author, n_channels, integrity=None):
    chans = info["per_channel"]
    fabric = info.get("fabric_rate")
    converter = info.get("sample_rate")
    decimated = bool(fabric and converter and fabric != converter)
    g = {
        "core:datatype": "ci16_le",
        "core:sample_rate": fabric or converter,
        "core:version": "1.2.0" if n_channels > 1 else "1.0.0",
        "core:hw": "Fishball7020 / PlutoSky (Zynq XC7Z020 + AD9361), "
                   + ", ".join("RX%d" % (n + 1) for n in channels),
        "core:recorder": "tools/sigmf-capture.py",
        "core:description": description,
        # --- outside core: SigMF cannot express a 12-bit converter in a 16-bit
        # container, and getting this wrong is a silent 24 dB error.
        "fishball:full_scale": RX_FULL_SCALE,
        "fishball:scaling_note":
            "Samples are signed 12-bit sign-extended into int16. Divide by %d "
            "for full scale, NOT 32768." % RX_FULL_SCALE,
        "fishball:rf_bandwidth_hz": info.get("rf_bandwidth"),
        "fishball:converter_rate_hz": converter,
        "fishball:fabric_decimator": "engaged" if decimated else "bypassed",
        "fishball:die_temp_millideg": info.get("temp_millideg"),
        # A recording should carry its own verdict. Absence of a check is recorded
        # explicitly, so "no integrity field" never reads as "it was fine".
        "fishball:integrity": integrity if integrity is not None else {
            "checked": False,
            "reason": "not requested - re-run with --verify to test for dropped samples",
        },
    }
    if n_channels > 1:
        g["core:num_channels"] = n_channels
        g["fishball:channel_order"] = (
            "Interleaved per sample instant: RX%d I, RX%d Q, RX%d I, RX%d Q."
            % (channels[0] + 1, channels[0] + 1, channels[1] + 1, channels[1] + 1))
        g["fishball:coherent"] = (
            "Both receivers share one RX_LO, so the phase relationship between "
            "them is stable - but it is NOT calibrated. Measure the fixed offset "
            "with a splitter and equal cables before trusting any angle.")
        for n in channels:
            for k, v in chans[n].items():
                g["fishball:rx%d_%s" % (n + 1, k)] = v
    else:
        for k, v in chans[channels[0]].items():
            g["fishball:" + k] = v
    if author:
        g["core:author"] = author
    return {k: v for k, v in g.items() if v is not None}, decimated, converter, fabric


def write_sidecar(binpath, info, channels, description, author, n_channels,
                  integrity=None, extra_annotations=None):
    """Rename to .sigmf-data and write the .sigmf-meta beside it."""
    base = os.path.splitext(binpath)[0]
    data, meta = base + ".sigmf-data", base + ".sigmf-meta"
    if os.path.abspath(binpath) != os.path.abspath(data):
        os.rename(binpath, data)

    g, decimated, converter, fabric = global_block(
        info, channels, description, author, n_channels, integrity)

    # Every discontinuity becomes a SigMF annotation, so a reader that ignores our
    # private namespace still trips over the problem in a standard field.
    annotations = []
    for r in (integrity or []):
        for pos in r.get("jump_at_samples", []):
            annotations.append({
                "core:sample_start": pos,
                "core:sample_count": 1,
                "core:label": "dropped samples (%s)" % r.get("channel", "RX1"),
                "core:comment": "phase discontinuity: the stream is not continuous "
                                "across this point",
            })
    annotations.extend(extra_annotations or [])
    annotations.sort(key=lambda a: (a["core:sample_start"],
                                    a.get("core:freq_lower_edge", 0)))

    doc = {
        "global": g,
        "captures": [{
            "core:sample_start": 0,
            "core:frequency": info.get("frequency"),
            "core:datetime": datetime.datetime.now(
                datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        }],
        "annotations": annotations,
    }
    with open(meta, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")

    n_bytes = os.path.getsize(data)
    per_inst = 4 * n_channels
    n_inst = n_bytes // per_inst
    rate = g["core:sample_rate"]
    print("%s  %.1f MB, %d sample instants x %d channel%s%s"
          % (data, n_bytes / 1e6, n_inst, n_channels, "s" if n_channels > 1 else "",
             ", %.3f s" % (n_inst / rate) if rate else ""))
    print("%s  %s" % (meta, description))
    if decimated:
        print("note: fabric decimator engaged - converter %s, delivered %s"
              % (converter, fabric))
    if annotations:
        print("%d annotation%s written" % (len(annotations),
                                           "s" if len(annotations) > 1 else ""))
    for r in (integrity or []):
        v = r.get("verdict", "not checked")
        mark = "ok  " if v == "continuous" else "WARN"
        print("%s integrity %s: %s%s"
              % (mark, r.get("channel", "RX1"), v,
                 "" if r.get("checked") else " (%s)" % r.get("reason", "")))
    return data, meta


def split_channels(binpath, info, channels, description, author, integrity=None,
                   extra_annotations=None):
    """Write two independent single-channel SigMF recordings."""
    try:
        import numpy as np
    except ImportError:
        sys.exit("--split needs numpy")
    base = os.path.splitext(binpath)[0]
    a = np.fromfile(binpath, dtype="<i2").reshape(-1, 4)
    out = []
    for idx, n in enumerate(channels):
        part = base + "-rx%d.bin" % (n + 1)
        a[:, 2 * idx:2 * idx + 2].tofile(part)
        one = [integrity[idx]] if integrity and idx < len(integrity) else None
        tag = "RX%d" % (n + 1)
        mine = [a for a in (extra_annotations or [])
                if a.get("fishball:channel", tag) == tag]
        out.append(write_sidecar(part, info, [n],
                                 description + " (RX%d)" % (n + 1), author, 1,
                                 one, mine))
    os.remove(binpath)
    return out


def verify(path, n_channels, rate, block=1000, jump_rad=0.5, min_tone_db=30.0,
           max_flagged_frac=0.2):
    """Look for the phase discontinuities a dropped chunk of samples leaves behind.

    A capture that completes is not a capture that is intact: iio_readdev returns
    the byte count you asked for whether or not the DMA overflowed underneath it.
    What a drop does leave is a step in phase.

    So: find the strongest tone, de-rotate by it, and the residual phase should be
    flat. Average it over blocks and any step bigger than `jump_rad` is a lost
    chunk. This needs a dominant tone - inject one with the AD9361's own BIST
    generator if the air is quiet - and says so rather than guessing when there
    is not one.

    Returns one dict per channel.
    """
    try:
        import numpy as np
    except ImportError:
        return [{"checked": False, "reason": "numpy not available"}]

    a = np.fromfile(path, dtype="<i2").reshape(-1, 2 * n_channels).astype(np.float64)
    results = []
    for c in range(n_channels):
        x = a[:, 2 * c] + 1j * a[:, 2 * c + 1]
        r = {
            "checked": True,
            "channel": "RX%d" % (c + 1),
            "method": "phase continuity of the strongest tone, averaged over "
                      "%d-sample blocks" % block,
            "jump_threshold_rad": jump_rad,
        }
        n = min(65536, len(x))
        if n < block * 4:
            r.update(checked=False, reason="too few samples to test")
            results.append(r)
            continue

        P = np.abs(np.fft.fft(x[:n] * np.hanning(n))) ** 2
        # Blank the bins around DC. Every zero-IF receiver leaks its own local
        # oscillator to 0 Hz, so with nothing on air that spike IS the strongest
        # bin - and de-rotating by ~0 Hz then measures the phase of noise, which
        # flags almost every block. Measured: it reported 2968 jumps out of 3000.
        guard_dc = max(3, int(round(5000.0 / (rate / n))))     # about +-5 kHz
        P[:guard_dc] = 0.0
        P[-guard_dc:] = 0.0
        k = int(P.argmax())
        med = np.median(P[P > 0])
        tone_db = 10 * np.log10(P[k] / med) if med > 0 else float("inf")
        f0 = float(np.fft.fftfreq(n, 1 / rate)[k])
        r["tone_hz"] = round(f0, 1)
        r["tone_above_median_db"] = round(float(tone_db), 1)

        # No dominant tone means the de-rotation has nothing to lock to and the
        # residual phase is just noise. Say so - a false "clean" is worse than none.
        if tone_db < min_tone_db:
            r.update(checked=False, verdict="inconclusive",
                     reason="no dominant tone away from DC (%.1f dB above the "
                            "noise, need %.0f). Inject one with debugfs "
                            "bist_tone and re-run."
                            % (tone_db, min_tone_db))
            results.append(r)
            continue

        d = x * np.exp(-2j * np.pi * f0 * np.arange(len(x)) / rate)
        ph = np.unwrap(np.angle(d))
        usable = len(ph) // block * block
        blocks = ph[:usable].reshape(-1, block).mean(axis=1)
        step = np.diff(blocks)
        resid = np.abs(step - np.median(step))
        idx = np.flatnonzero(resid > jump_rad)

        r["blocks_tested"] = int(len(blocks))
        r["phase_jumps"] = int(len(idx))
        r["worst_jump_rad"] = round(float(resid.max()), 4) if len(resid) else 0.0
        flagged = len(idx) / max(1, len(step))
        if flagged > max_flagged_frac:
            # Real drops are occasional. Flagging a fifth of the capture means the
            # de-rotation never locked - report that, rather than a scary verdict
            # the data does not support.
            r.update(checked=False, verdict="inconclusive",
                     phase_jumps=int(len(idx)),
                     reason="%.0f%% of blocks flagged - the tone at %.1f Hz is not "
                            "coherent enough to test against. This is the test "
                            "failing, not necessarily the capture."
                            % (100 * flagged, f0))
        elif len(idx) == 0:
            r["verdict"] = "continuous"
        else:
            r["verdict"] = "DISCONTINUOUS - samples were dropped"
            # sample index of each discontinuity, for the annotations below
            r["jump_at_samples"] = [int((i + 1) * block) for i in idx[:64]]
            if len(idx) > 64:
                r["jump_at_samples_truncated"] = True
        results.append(r)
    return results


def scan(path, n_channels, rate, centre, full_scale=RX_FULL_SCALE,
         seg=65536, max_segs=64, peak_db=10.0):
    """Find what is in the capture and describe it as SigMF annotations.

    Two passes, both cheap:

      spectrum  Average periodograms spread across the file, then pick out bins
                that stand well above the noise floor. Each one becomes an
                annotation with absolute frequency edges, so a reader sees
                "something at 900.000 MHz" rather than a bin index.

      clipping  Any sample at or beyond full scale. On this board that is +-2047,
                not +-32767, and a clipped capture is not worth analysing.

    The spike at 0 Hz offset is labelled as the local-oscillator leak rather than
    a signal. Every zero-IF receiver has one; it is an artefact of the
    architecture and mistaking it for a carrier is a rite of passage.
    """
    try:
        import numpy as np
    except ImportError:
        return []

    itemsize = 2 * 2 * n_channels                      # int16 I + int16 Q per channel
    total = os.path.getsize(path) // itemsize
    if total < seg * 2:
        return []

    ann = []
    starts = np.linspace(0, total - seg, min(max_segs, max(1, total // seg)),
                         dtype=np.int64)
    win = np.hanning(seg)
    freqs = np.fft.fftshift(np.fft.fftfreq(seg, 1 / rate))

    for c in range(n_channels):
        acc = np.zeros(seg)
        for st in starts:
            raw = np.fromfile(path, dtype="<i2", count=seg * 2 * n_channels,
                              offset=int(st) * itemsize)
            a = raw.reshape(-1, 2 * n_channels).astype(np.float64)
            x = a[:, 2 * c] + 1j * a[:, 2 * c + 1]
            if len(x) < seg:
                continue
            acc += np.abs(np.fft.fftshift(np.fft.fft(x[:seg] * win))) ** 2
        if not acc.any():
            continue
        p_db = 10 * np.log10(acc / acc.size + 1e-30)
        floor = np.median(p_db)

        # Pick PEAKS, not everything above a threshold. A strong tone's window
        # skirts sit well above any sensible floor, so a plain threshold reports
        # one 850 kHz-wide "signal" where there is a single carrier.
        cand = np.flatnonzero(p_db > floor + peak_db)
        peaks = []
        guard = max(4, seg // 4096)             # bins to either side that must be lower
        for k in cand:
            lo_n, hi_n = max(0, k - guard), min(len(p_db), k + guard + 1)
            if p_db[k] >= p_db[lo_n:hi_n].max():
                if peaks and k - peaks[-1] <= guard:
                    if p_db[k] > p_db[peaks[-1]]:
                        peaks[-1] = int(k)      # keep the taller of two close bins
                else:
                    peaks.append(int(k))

        for k in peaks:
            # width where the peak has fallen 20 dB, or where it starts rising again
            cut = p_db[k] - 20.0
            lo = k
            while lo > 0 and p_db[lo - 1] > cut and p_db[lo - 1] <= p_db[lo]:
                lo -= 1
            hi = k
            while hi < len(p_db) - 1 and p_db[hi + 1] > cut and p_db[hi + 1] <= p_db[hi]:
                hi += 1
            f_off = float(freqs[k])
            snr = float(p_db[k] - floor)
            dc = abs(f_off) < (rate / seg) * 3            # within a few bins of DC
            ann.append({
                "core:sample_start": 0,
                "core:sample_count": int(total),
                "core:freq_lower_edge": (centre or 0) + float(freqs[lo]),
                "core:freq_upper_edge": (centre or 0) + float(freqs[hi]),
                "core:label": ("LO leakage (artefact, not a signal)" if dc
                               else "signal at %+.1f kHz offset" % (f_off / 1e3)),
                "core:comment":
                    ("Zero-IF receivers leak their own local oscillator to 0 Hz. "
                     "This is the receiver, not the air." if dc else
                     "peak %.1f dB above the noise floor, RX%d" % (snr, c + 1)),
                "core:generator": "tools/sigmf-capture.py --annotate",
                "fishball:peak_hz": (centre or 0) + f_off,
                "fishball:snr_db": round(snr, 1),
                "fishball:width_hz": round(float(freqs[hi] - freqs[lo]), 1),
                "fishball:channel": "RX%d" % (c + 1),
            })

        # clipping, in the time domain
        clipped = 0
        for st in starts:
            raw = np.fromfile(path, dtype="<i2", count=seg * 2 * n_channels,
                              offset=int(st) * itemsize)
            a = raw.reshape(-1, 2 * n_channels)
            pair = a[:, 2 * c:2 * c + 2]
            clipped += int((np.abs(pair) >= full_scale).any(axis=1).sum())
        if clipped:
            ann.append({
                "core:sample_start": 0,
                "core:sample_count": int(total),
                "core:label": "CLIPPING (RX%d)" % (c + 1),
                "core:comment":
                    "%d of %d sampled instants reached full scale (+-%d). Reduce "
                    "gain - a clipped capture generates harmonics that are not on "
                    "the air." % (clipped, len(starts) * seg, full_scale),
                "core:generator": "tools/sigmf-capture.py --annotate",
                "fishball:channel": "RX%d" % (c + 1),
            })

    ann.sort(key=lambda a: (a["core:sample_start"], a.get("core:freq_lower_edge", 0)))
    return ann


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mode", choices=["wrap", "record"])
    p.add_argument("path", help="existing .bin for wrap, or output basename for record")
    p.add_argument("--uri", default=os.environ.get("SDR_URI", "ip:192.168.129.200"),
                   help="libiio URI (default: $SDR_URI or ip:192.168.129.200)")
    p.add_argument("--channels", default="0", choices=["0", "1", "both"],
                   help="0 = RX1A, 1 = RX2A, both = coherent pair (default 0)")
    p.add_argument("--split", action="store_true",
                   help="with --channels both, write two single-channel recordings")
    p.add_argument("--rate", type=float, help="sample rate in Hz, e.g. 3e6")
    p.add_argument("--freq", type=float, help="centre frequency in Hz, e.g. 900e6")
    p.add_argument("--bandwidth", type=float, help="RF bandwidth in Hz")
    p.add_argument("--gain", type=float, help="manual gain in dB, applied to every channel")
    p.add_argument("--gain-mode", choices=["manual", "slow_attack", "fast_attack", "hybrid"])
    p.add_argument("--seconds", type=float, help="record length; or use --samples")
    p.add_argument("--samples", type=float, help="record length in sample instants")
    p.add_argument("--buffer", type=int, default=1 << 20, help="iio_readdev -b (default 1048576)")
    p.add_argument("--annotate", action="store_true",
                   help="scan the capture and annotate signals, the LO artefact "
                        "and any clipping")
    p.add_argument("--verify", action="store_true",
                   help="test for dropped samples and record the verdict in the "
                        "sidecar; needs a dominant tone (see docs/capturing-iq.md)")
    p.add_argument("--description", default=None)
    p.add_argument("--author", default=None)
    args = p.parse_args()

    channels = [0, 1] if args.channels == "both" else [int(args.channels)]
    nch = len(channels)

    if args.mode == "record":
        configure(args.uri, channels, args.rate, args.freq, args.bandwidth,
                  args.gain, args.gain_mode)

    info = read_back(args.uri, channels)
    if info["sample_rate"] is None:
        sys.exit("cannot reach the board at %s - check the URI" % args.uri)
    rate = info.get("fabric_rate") or info["sample_rate"]

    if args.mode == "record":
        if args.samples:
            n = int(args.samples)
        elif args.seconds:
            n = int(args.seconds * rate)
        else:
            sys.exit("record needs --seconds or --samples")
        binpath = args.path if args.path.endswith(".bin") else args.path + ".bin"
        mbps = rate * 4 * nch / 1e6
        print("recording %d instants (%.2f s) x %d channel%s at %.6f MSPS "
              "= %.1f MB/s, %.1f MB total"
              % (n, n / rate, nch, "s" if nch > 1 else "", rate / 1e6,
                 mbps, n * 4 * nch / 1e6), file=sys.stderr)
        if mbps > 30:
            print("warning: above about 30 MB/s this link starts dropping samples. "
                  "Measured clean: 3 MSPS x 2 channels = 24 MB/s. Use --verify.",
                  file=sys.stderr)
        elapsed = capture(args.uri, binpath, n, channels, args.buffer)
        print("captured in %.2f s wall (%.1f MB/s sustained)"
              % (elapsed, n * 4 * nch / 1e6 / elapsed), file=sys.stderr)
    else:
        binpath = args.path
        if not os.path.exists(binpath):
            sys.exit("no such file: " + binpath)

    integrity = verify(binpath, nch, rate) if args.verify else None
    marks = (scan(binpath, nch, rate, info.get("frequency"))
             if args.annotate else None)
    for a in (marks or []):
        print("annotate: %s" % a["core:label"], file=sys.stderr)
    if integrity:
        for r in integrity:
            print("verify %s: %s" % (r.get("channel", "RX1"),
                                     r.get("verdict") or r.get("reason", "?")),
                  file=sys.stderr)

    desc = args.description or ("%.6f MSPS, %s Hz centre, %s"
                                % (rate / 1e6, info.get("frequency"),
                                   " + ".join("RX%d" % (c + 1) for c in channels)))
    if nch > 1 and args.split:
        split_channels(binpath, info, channels, desc, args.author, integrity, marks)
    else:
        write_sidecar(binpath, info, channels, desc, args.author, nch, integrity, marks)


if __name__ == "__main__":
    main()
