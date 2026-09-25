#!/usr/bin/env python3
"""Sweep the 2.4 GHz and 5 GHz Wi-Fi bands with the Fishball7020 and record
which channels are busy.

    # run from: tools/wifi-scan/
    ./wifi_scan.py --uri ip:fishball.local --band both -o scan.json
    ./plot_scan.py scan.json                     # the pictures

This is a GNU Radio application: the receive stream, the window, the FFT and
the magnitude are GNU Radio blocks, and a sweep controller retunes the source
between dwells while the flowgraph keeps running.

    fmcomms2_source_fc32 -> stream_to_vector -> fft_vcc(window, shift)
                         -> complex_to_mag_squared -> FrameSink

WHY IT IS BUILT THIS WAY. Five choices do all the work, and every one of them
is about dynamic range - the ratio between the strongest thing you can measure
without clipping and the weakest thing you can still see.

1.  A FOUR-TERM BLACKMAN-HARRIS WINDOW, not the usual Hann. A window is the
    taper applied to each block of samples before the transform; without one, a
    signal that does not fit a whole number of cycles in the block smears across
    the whole spectrum. Hann's worst leakage is -31 dB, Blackman-Harris's is
    -92 dB. That is the difference between being able to say "channel 9 is
    quiet" next to a loud channel 11 and not being able to say it at all. It
    costs resolution - the main lobe is wider - which does not matter when the
    thing being measured is 20 MHz wide.

2.  NOTHING IS MEASURED NEAR DC. The AD9361 is a direct-conversion receiver, so
    its own local oscillator leaks into its own output and lands exactly at the
    centre of whatever you tune to, along with the converters' DC offset. In the
    first test capture of this band that artefact sat 17.8 dB above everything
    else. So each dwell throws away +-EXCISE_MHZ around its own centre, and the
    tuning steps overlap enough that the discarded sliver is covered by a
    neighbouring dwell, where it lands well away from that dwell's centre.

3.  OVERLAPPED DWELLS ARE COMBINED BY TAKING THE MINIMUM of the averaged trace.
    An artefact of the receiver - LO leak, the quadrature image, a harmonic of
    the sample clock - sits at a fixed offset from the LO, so it MOVES in
    absolute frequency when the LO moves. A real transmitter does not. Taking
    the lowest reading among the dwells that covered a frequency therefore
    deletes the receiver's own artefacts and keeps the radio traffic. The
    max-hold trace is combined with maximum instead, because there the job is
    to catch a burst, not to reject a spur.

4.  THE GAIN IS FIXED, AND SET BY A PRE-PASS. Automatic gain control would move
    the reference level between dwells, and a stitched spectrum whose reference
    level moves is not a spectrum. So the scanner measures the band once, picks
    a manual gain that puts the strongest thing it saw HEADROOM_DB below full
    scale, and then does not touch it. The gain used is recorded in the output.

5.  THE DWELL IS LONG ENOUGH TO CATCH A BEACON. Wi-Fi is bursty: an idle
    channel with an access point on it is silent except for a beacon roughly
    every 100 ms. A short dwell sees nothing and calls the channel free. Each
    dwell here spans several beacon intervals of wall-clock time, and the
    detector for occupancy is max-hold rather than the average.

WHAT THIS CANNOT TELL YOU. The levels are dBFS - decibels relative to the
converter's full scale - and NOT dBm. Turning them into absolute power would
need a calibrated reference, and comparing 2.4 GHz against 5 GHz would need the
frequency response of the antenna and of the board's own front end. The board's
flatness is only established from 200 MHz to 1 GHz, and the RF baluns carry no
part number in the schematic, so nobody can say from the documents what they do
at 5 GHz. Within one band the numbers are comparable to each other. Across the
two bands they are not.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np
from gnuradio import blocks, fft, gr, iio

try:
    from scipy.signal.windows import blackmanharris
except ImportError:                                        # scipy < 1.1
    from scipy.signal import blackmanharris

# One resolver for the whole repository, so this tool finds the board by name
# wherever DHCP put it instead of hard-coding an address that works on one desk.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from board_addr import uri as board_uri                     # noqa: E402

# --------------------------------------------------------------------------
# parameters - every one of these appears in the output file
# --------------------------------------------------------------------------

SAMPLE_RATE = 61_440_000     # the AD9361's maximum: fewest dwells per band
RF_BANDWIDTH = 56_000_000    # the widest analog filter the chip has
NFFT = 4096                  # -> resolution bandwidth = 15.0 kHz
FRAMES = 1024                # averaged transforms per dwell
SETTLE_S = 0.08              # discarded after each retune, for the PLL to lock
EXCISE_MHZ = 1.0             # dropped either side of each dwell's own centre
EDGE_MHZ = 9.0               # dropped at each end - see below
STEP_MHZ = 24.0              # LO step: well under the kept width, so dwells overlap
# EDGE_MHZ is not cosmetic. The analog filter is 56 MHz wide, so it is already
# turning over at +-28 MHz, and half the sample rate is +-30.72. Keeping bins
# out to the corner means measuring on the filter's shoulder, and because every
# dwell has the same shoulder in the same place relative to ITS OWN centre, the
# stitched result grows a ripple with exactly the period of the LO step. It was
# measured at 14.9 dB peak to peak, periodic at 24.0 MHz, in a part of the band
# with nothing transmitting in it. Dropping 9 MHz at each end keeps only the
# flat middle (+-21.7 MHz), which still leaves 41 MHz per dwell against a
# 24 MHz step.
HEADROOM_DB = 12.0           # how far below full scale the strongest signal is put
GAIN_PROBE_DB = 40.0         # gain used for the pre-pass that picks the real gain
# NOT a constant: the AD9361 has three gain tables and swaps them with
# frequency, so the legal range genuinely differs between these two bands -
# -3..71 dB at 2.4 GHz but -10..62 dB above 4 GHz. The radio publishes the
# current range in hardwaregain_available, and this scanner reads it after every
# retune rather than assuming. See .claude/skills/fishball7020-firmware/
# references/ad9361-gain-tables.md, which states the rule outright; ignoring it
# had the 5 GHz sweep silently running at the pre-pass gain while the output
# claimed 71 dB.
GAIN_FALLBACK = (-3.0, 1.0, 62.0)

BANDS = {
    "2.4": (2400.0, 2500.0),
    "5":   (5150.0, 5850.0),
}

# 802.11 channel plans. Centre frequencies in MHz, 20 MHz wide.
CHANNELS_24 = {n: 2412.0 + 5.0 * (n - 1) for n in range(1, 14)}
CHANNELS_5 = {n: 5000.0 + 5.0 * n for n in
              [36, 40, 44, 48, 52, 56, 60, 64,
               100, 104, 108, 112, 116, 120, 124, 128, 132, 136, 140,
               149, 153, 157, 161, 165]}
UNII = [(36, 48, "U-NII-1"), (52, 64, "U-NII-2A"),
        (100, 140, "U-NII-2C"), (149, 165, "U-NII-3")]

PHY = "ad9361-phy"


# --------------------------------------------------------------------------
# the flowgraph
# --------------------------------------------------------------------------

class FrameSink(gr.sync_block):
    """Accumulates power spectra: a running sum for the average, and a max-hold.

    The sweep controller calls arm() before a dwell and then waits on .count.
    Everything is plain numpy on whole frames, so the GIL is enough to keep the
    controller and the flowgraph thread out of each other's way.
    """

    def __init__(self, nfft):
        gr.sync_block.__init__(self, name="frame_sink",
                               in_sig=[(np.float32, nfft)], out_sig=None)
        self.nfft = nfft
        self.arm(0)

    def arm(self, want):
        self.total = np.zeros(self.nfft, dtype=np.float64)
        self.peak = np.zeros(self.nfft, dtype=np.float64)
        self.count = 0
        self.want = want

    def work(self, input_items, output_items):
        frames = input_items[0]
        if self.count < self.want:
            take = frames[: self.want - self.count]
            self.total += take.sum(axis=0, dtype=np.float64)
            np.maximum(self.peak, take.max(axis=0), out=self.peak)
            self.count += len(take)
        return len(frames)

    def result(self):
        """(average, max-hold) as power, normalised so a full-scale tone is 1.0."""
        if self.count == 0:
            return None, None
        return self.total / self.count, self.peak.copy()


class Scanner:
    def __init__(self, uri, sample_rate=SAMPLE_RATE, nfft=NFFT):
        self.uri, self.fs, self.nfft = uri, sample_rate, nfft
        self._ctl = None

        # A window's own gain has to be divided back out or every level is
        # wrong. Normalising by (sum w)^2 puts a full-scale tone at 0 dBFS.
        self.window = blackmanharris(nfft)
        self.norm = float(self.window.sum()) ** 2

        self.tb = gr.top_block()
        self.src = iio.fmcomms2_source_fc32(uri, [True, True, False, False], nfft * 4)
        self.src.set_samplerate(sample_rate)
        self.src.set_gain_mode(0, "manual")
        self.src.set_gain(0, GAIN_PROBE_DB)
        # The AD9361's own tracking loops. Quadrature tracking is what keeps a
        # strong signal from putting a mirror image of itself on the other side
        # of the centre; the two DC loops keep the LO leak from growing.
        self.src.set_quadrature(True)
        self.src.set_rfdc(True)
        self.src.set_bbdc(True)

        s2v = blocks.stream_to_vector(gr.sizeof_gr_complex, nfft)
        xform = fft.fft_vcc(nfft, True, list(self.window), True)
        mag2 = blocks.complex_to_mag_squared(nfft)
        self.sink = FrameSink(nfft)
        self.tb.connect(self.src, s2v, xform, mag2, self.sink)

        self._set_rf_bandwidth(RF_BANDWIDTH)
        self.gain_db = GAIN_PROBE_DB

    def _control(self):
        """A plain IIOD connection, for the attributes gr-iio does not expose.

        Reuses tools/selftest/iiod_min.py rather than adding a libiio
        dependency: it speaks the protocol with the standard library alone.
        """
        if self._ctl is None:
            here = os.path.dirname(os.path.abspath(__file__))
            sys.path.insert(0, os.path.join(here, "..", "selftest"))
            from iiod_min import Iiod
            self._ctl = Iiod(self.uri.split(":", 1)[1]).connect()
        return self._ctl

    def _set_rf_bandwidth(self, hz):
        """gr-iio has no setter for the analog filter, so write the attribute."""
        try:
            self._control().write(PHY, "voltage0", "rf_bandwidth", int(hz))
            self.rf_bandwidth = int(
                float(self._control().read(PHY, "voltage0", "rf_bandwidth")))
        except Exception as exc:                            # not fatal
            print(f"  note: could not set RF bandwidth ({exc}); "
                  f"leaving it as the driver had it", file=sys.stderr)
            self.rf_bandwidth = None

    def start(self):
        self.tb.start()

    @staticmethod
    def _dB(raw):
        """hardwaregain reads back as '40.000000 dB' - unit and all."""
        return float(str(raw).strip().split()[0])

    def gain_limits(self):
        """(min, step, max) the radio will accept AT THE CURRENT FREQUENCY."""
        try:
            raw = self._control().read(PHY, "voltage0", "hardwaregain_available")
            lo, step, hi = (float(x) for x in raw.strip("[] ").split())
            return lo, step, hi
        except Exception:
            return GAIN_FALLBACK

    def set_gain(self, db):
        """Set manual gain to a legal value, and prove it took.

        Two ways this goes wrong quietly, both seen on this board:

        - a fractional gain is rejected outright (EINVAL), because the step is
          1 dB;
        - a gain that is legal in one band is rejected in another, because the
          chip swaps gain tables at 4 GHz.

        gr-iio only *logs* either refusal, so the gain stays where it was while
        every level in the output claims otherwise. Clamp to what the radio says
        it accepts, write, read back, and refuse to continue if they disagree -
        a sweep with an unknown reference level is not a measurement.
        """
        lo, step, hi = self.gain_limits()
        want = float(np.clip(round(float(db) / step) * step, lo, hi))
        self.src.set_gain(0, want)
        got = self._dB(self._control().read(PHY, "voltage0", "hardwaregain"))
        if abs(got - want) > step / 2 + 0.01:
            raise RuntimeError(
                f"asked for {want:g} dB of gain, radio reports {got:.2f} dB "
                f"(legal range here is {lo:g}..{hi:g} in {step:g} dB steps). "
                f"Every level in a sweep is referred to this number.")
        self.gain_db = got
        return got

    def dwell(self, lo_hz, frames=FRAMES, timeout=20.0):
        """Retune, let the synthesiser settle, then collect `frames` spectra."""
        self.src.set_frequency(float(lo_hz))
        self.sink.arm(0)                       # drop everything while it settles
        time.sleep(SETTLE_S)
        self.sink.arm(frames)
        deadline = time.time() + timeout
        while self.sink.count < frames and time.time() < deadline:
            time.sleep(0.01)
        avg, mx = self.sink.result()
        if avg is None:
            raise RuntimeError(f"no samples arrived at {lo_hz/1e6:.1f} MHz")
        got = self.sink.count
        # Linear power, normalised so a full-scale tone reads 1.0. Everything
        # downstream - averaging neighbouring bins, combining dwells - is an
        # arithmetic operation on power, and doing it in dB would be wrong.
        return avg / self.norm, mx / self.norm, got

    def stop(self):
        self.tb.stop()
        self.tb.wait()


# --------------------------------------------------------------------------
# the sweep
# --------------------------------------------------------------------------

def dwell_plan(f_lo_mhz, f_hi_mhz, fs_hz, step_mhz=STEP_MHZ):
    """LO positions covering [f_lo, f_hi], overlapping by design."""
    half = (fs_hz / 2) / 1e6
    keep = half - EDGE_MHZ
    first = f_lo_mhz + keep - (keep - EXCISE_MHZ) / 2
    out, f = [], first
    while f - keep < f_hi_mhz:
        out.append(f)
        f += step_mhz
    return out


def baseband_axis(fs_hz, nfft):
    return np.fft.fftshift(np.fft.fftfreq(nfft, 1.0 / fs_hz)) / 1e6


def usable_mask(fb_mhz, fs_hz):
    """Bins we trust: away from DC, and inside the analog filter."""
    half = (fs_hz / 2) / 1e6
    return (np.abs(fb_mhz) >= EXCISE_MHZ) & (np.abs(fb_mhz) <= half - EDGE_MHZ)


def autorange(sc, los, frames=96):
    """Pick one manual gain for the whole band.

    Measured at a known gain, the strongest peak tells us how much gain we can
    afford: enough to lift the noise floor as far as possible, while leaving
    HEADROOM_DB between that peak and full scale. Wi-Fi bursts are much stronger
    than the average, which is why the headroom is not smaller.
    """
    # Retune into the band FIRST: the legal gain range depends on frequency,
    # and so does the gain table the probe reading is referred to.
    sc.src.set_frequency(float(los[len(los) // 2] * 1e6))
    time.sleep(SETTLE_S)
    sc.set_gain(GAIN_PROBE_DB)
    worst_p = 0.0
    fb = baseband_axis(sc.fs, sc.nfft)
    keep = usable_mask(fb, sc.fs)
    for lo in los:
        _, mx, _ = sc.dwell(lo * 1e6, frames=frames)
        worst_p = max(worst_p, float(mx[keep].max()))
    worst = 10 * np.log10(worst_p + 1e-30)
    lo_g, step, hi_g = sc.gain_limits()
    gain = GAIN_PROBE_DB + (-HEADROOM_DB - worst)
    return float(np.clip(round(gain / step) * step, lo_g, hi_g)), worst


def _to_grid(f_abs, power, grid, how):
    """Reduce one dwell's bins onto the output grid.

    Several transform bins land in each grid cell - 15 kHz bins into 100 kHz
    cells - and the two traces want different reductions. The average trace
    wants the MEAN of those bins, because that is what the power in the cell
    is. The max-hold wants the MAXIMUM, because it is a peak detector and its
    whole job is to keep the largest thing seen.
    """
    idx = np.searchsorted(grid, f_abs)
    ok = (idx > 0) & (idx < grid.size)
    idx, power = idx[ok], power[ok]
    if how == "mean":
        total = np.zeros(grid.size)
        n = np.zeros(grid.size)
        np.add.at(total, idx, power)
        np.add.at(n, idx, 1.0)
        return np.where(n > 0, total / np.maximum(n, 1e-30), np.nan), n > 0
    out = np.zeros(grid.size)
    np.maximum.at(out, idx, power)
    n = np.zeros(grid.size)
    np.add.at(n, idx, 1.0)
    return np.where(n > 0, out, np.nan), n > 0


def stitch(dwells, f_lo_mhz, f_hi_mhz, rbw_hz, grid_khz=100.0):
    """Combine overlapping dwells onto one frequency grid, in linear power.

    Within a dwell: neighbouring bins are reduced to the grid (mean, or max for
    the max-hold trace). Across dwells:

      average  -> MINIMUM. A receiver artefact sits at a fixed offset from the
                  LO, so it moves in absolute frequency when the LO moves; a
                  transmitter does not. The lowest reading is the one with no
                  artefact in it.
      max-hold -> MAXIMUM. Here the job is to catch a burst, not reject a spur.
    """
    grid = np.arange(f_lo_mhz, f_hi_mhz + grid_khz / 1e3, grid_khz / 1e3)
    acc_min = np.full(grid.size, np.inf)
    acc_max = np.zeros(grid.size)
    seen = np.zeros(grid.size, dtype=int)

    for d in dwells:
        f_abs = d["lo_mhz"] + d["fb_mhz"]
        a, ok = _to_grid(f_abs, d["avg"], grid, "mean")
        m, _ = _to_grid(f_abs, d["max"], grid, "max")
        acc_min = np.where(ok, np.minimum(acc_min, np.nan_to_num(a, nan=np.inf)),
                           acc_min)
        acc_max = np.where(ok, np.maximum(acc_max, np.nan_to_num(m, nan=0.0)),
                           acc_max)
        seen += ok.astype(int)

    covered = seen > 0
    to_db = lambda p: 10 * np.log10(np.asarray(p) + 1e-30)
    return {
        "freq_mhz": grid[covered].tolist(),
        "avg_dbfs": to_db(acc_min[covered]).tolist(),
        "max_dbfs": to_db(acc_max[covered]).tolist(),
        "dwells_per_point": seen[covered].tolist(),
        "rbw_hz": rbw_hz,
    }


def occupancy(st, plan, width_mhz=20.0):
    """Per 802.11 channel: how far it rises above an EMPTY channel.

    Each trace is measured against a floor taken from ITS OWN statistic - the
    quiet tenth of the band on that same trace. This matters more than it
    sounds. The max-hold of pure noise sits well above the average of the same
    noise (the largest of 1024 random draws beats their mean by about 8 dB), so
    scoring a max-hold against an average-derived floor adds that offset to
    every channel including the empty ones, and an idle band comes out looking
    30 dB busy. Comparing like with like puts an empty channel at roughly 0.

    Two numbers per channel, because they answer different questions:
      burst_db     how far the loudest moment rose - "is anything transmitting"
      sustained_db how far the long-term average rose - "how heavily is it used"
    """
    f = np.asarray(st["freq_mhz"])
    mx = np.asarray(st["max_dbfs"])
    av = np.asarray(st["avg_dbfs"])
    floor_avg = float(np.nanpercentile(av, 10))     # the quiet 10% of the band
    floor_max = float(np.nanpercentile(mx, 10))     # ... on the max-hold trace
    out = {}
    for ch, centre in plan.items():
        m = np.abs(f - centre) <= width_mhz / 2
        if m.sum() < 4:
            continue
        out[ch] = {
            "centre_mhz": centre,
            "peak_dbfs": float(np.nanmax(mx[m])),
            "mean_dbfs": float(np.nanmean(av[m])),
            "burst_db": float(np.nanmax(mx[m]) - floor_max),
            "sustained_db": float(np.nanmean(av[m]) - floor_avg),
            "bins": int(m.sum()),
        }
    return out, floor_avg, floor_max


def scan_band(sc, name, args):
    f_lo, f_hi = BANDS[name]
    los = dwell_plan(f_lo, f_hi, sc.fs)
    fb = baseband_axis(sc.fs, sc.nfft)
    keep = usable_mask(fb, sc.fs)
    rbw = sc.fs / sc.nfft

    print(f"\n{name} GHz band: {f_lo:.0f}-{f_hi:.0f} MHz, "
          f"{len(los)} dwells of {sc.fs/1e6:.2f} MHz")

    gain, probe_peak = autorange(sc, los)
    gain = sc.set_gain(gain)                     # read back, so this is the truth
    print(f"  pre-pass: strongest {probe_peak:+.1f} dBFS at {GAIN_PROBE_DB:.0f} dB "
          f"-> using {gain:.0f} dB of gain (confirmed by read-back)")

    dwells, t0 = [], time.time()
    for i, lo in enumerate(los, 1):
        avg, mx, got = sc.dwell(lo * 1e6, frames=args.frames)
        if i == 1:
            # gr-iio re-applies the gain whenever the frequency changes, so the
            # value that matters is the one in force AFTER a retune, not before.
            back = sc._dB(sc._control().read(PHY, "voltage0", "hardwaregain"))
            if abs(back - gain) > 0.51:
                raise RuntimeError(
                    f"gain moved to {back:.2f} dB after retuning (wanted "
                    f"{gain:g}); the sweep would not share one reference level")
        dwells.append({"lo_mhz": lo, "fb_mhz": fb[keep],
                       "avg": avg[keep], "max": mx[keep], "frames": got})
        print(f"  [{i:2d}/{len(los)}] LO {lo:8.2f} MHz  {got:5d} frames  "
              f"peak {10*np.log10(mx[keep].max()+1e-30):+7.1f} dBFS", flush=True)
    elapsed = time.time() - t0

    st = stitch(dwells, f_lo, f_hi, rbw)
    plan = CHANNELS_24 if name == "2.4" else CHANNELS_5
    occ, floor_avg, floor_max = occupancy(st, plan)
    st.update({
        "band": name, "gain_db": gain, "noise_floor_dbfs": floor_avg,
        "maxhold_floor_dbfs": floor_max,
        "gain_limits": sc.gain_limits(),
        "lo_mhz": [float(x) for x in los], "seconds": round(elapsed, 1),
        "channels": {str(k): v for k, v in occ.items()},
    })
    return st


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--uri", default=None,
                   help="libiio URI; by default the board is found by name")
    p.add_argument("--band", choices=["2.4", "5", "both"], default="both")
    p.add_argument("--frames", type=int, default=FRAMES,
                   help=f"averaged transforms per dwell (default {FRAMES}); "
                        f"more is a longer dwell and a smoother floor")
    p.add_argument("--sample-rate", type=float, default=SAMPLE_RATE)
    p.add_argument("--nfft", type=int, default=NFFT)
    p.add_argument("-o", "--out", default="scan.json")
    args = p.parse_args(argv)

    args.uri = board_uri(args.uri)
    sc = Scanner(args.uri, int(args.sample_rate), args.nfft)
    print(f"Fishball7020 Wi-Fi band scan via {args.uri}")
    print(f"  sample rate {sc.fs/1e6:.2f} MSPS, RF bandwidth "
          f"{(sc.rf_bandwidth or 0)/1e6:.0f} MHz, {sc.nfft}-point transform "
          f"-> {sc.fs/sc.nfft/1e3:.1f} kHz resolution")
    print(f"  window: 4-term Blackman-Harris (-92 dB sidelobes)")
    print(f"  {args.frames} transforms averaged per dwell, "
          f"+-{EXCISE_MHZ:g} MHz excised around each centre")

    sc.start()
    out = {"uri": args.uri, "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "parameters": {
               "sample_rate_hz": sc.fs, "rf_bandwidth_hz": sc.rf_bandwidth,
               "nfft": sc.nfft, "rbw_hz": sc.fs / sc.nfft,
               "frames_per_dwell": args.frames, "window": "blackman-harris-4",
               "excise_mhz": EXCISE_MHZ, "edge_mhz": EDGE_MHZ,
               "step_mhz": STEP_MHZ, "headroom_db": HEADROOM_DB,
               "settle_s": SETTLE_S,
           },
           "bands": {}}
    try:
        for name in (["2.4", "5"] if args.band == "both" else [args.band]):
            out["bands"][name] = scan_band(sc, name, args)
    finally:
        sc.stop()

    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    print(f"\nwrote {args.out}")

    for name, st in out["bands"].items():
        busy = sorted(st["channels"].items(),
                      key=lambda kv: -kv[1]["burst_db"])[:6]
        print(f"\n{name} GHz - noise floor {st['noise_floor_dbfs']:.1f} dBFS "
              f"(max-hold floor {st['maxhold_floor_dbfs']:.1f}), "
              f"busiest channels:")
        print(f"    {'ch':>4} {'centre':>9}  {'peak':>9}   "
              f"{'burst':>7} {'sustained':>10}")
        for ch, v in busy:
            print(f"    {ch:>4} {v['centre_mhz']:8.0f} MHz {v['peak_dbfs']:+8.1f} "
                  f"dBFS {v['burst_db']:+6.1f} dB {v['sustained_db']:+9.1f} dB")

    sys.stdout.flush()
    # gr-iio does not always release the device at interpreter shutdown, and a
    # scan that has already written its results should not hang because of it.
    os._exit(0)


if __name__ == "__main__":
    main()
