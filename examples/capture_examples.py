#!/usr/bin/env python3
"""Capture what the examples' figures are drawn from, off the real board.

    # run from: the repo root
    python3 examples/capture_examples.py                  # all three
    python3 examples/capture_examples.py 01 03            # just these
    python3 examples/capture_examples.py --uri ip:1.2.3.4

Writes docs/img/data/examples.json, which examples/plot_examples.py renders.
Same pattern as tools/plot_throughput.py: the measurement and the drawing are
separate programs, so a figure can be redrawn without a radio and cannot
quietly become a drawing of nothing.

WHAT EACH ONE MEASURES

  01  One real capture, processed three times with three windows. This is the
      honest version of the window lesson: not a synthetic two-tone, but
      whatever is actually on the air where you are, seen through each window
      in turn. The synthetic two-tone numbers go in as well, because they are
      the only way to state an error against a KNOWN answer.

  02  The full modulated link through the AD9361's internal DIGITAL loopback,
      at three constellation orders. Nothing is radiated: the samples never
      reach a mixer, and the analogue attenuator is left at 89.75 dB as well.
      Needs `./devkit loopback on` first; this script refuses to run 02
      otherwise rather than quietly measure silence.

  03  One two-channel capture, then the band-select filter swept in software.
      Sweeping offline rather than on the board means every width sees the
      SAME samples, so the coherence curve is a property of the filter and not
      of what happened to be on the air thirty seconds later. It shows the
      trap: widen the filter until DC is inside it and coherence climbs toward
      1 because the receiver's own LO leak is correlated with itself.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tools", "selftest"))

import qam                                                        # noqa: E402
import evm_meter                                                  # noqa: E402
import spectrum_engine as se                                      # noqa: E402

OUT = os.path.join(os.path.dirname(HERE), "docs", "img", "data", "examples.json")

NFFT = 4096
CENTRE_HZ = 2_437_000_000
FS_01 = 5_000_000
FS_03 = 5_000_000
LO_FRAC_01 = 0.25
LO_FRAC_03 = 0.15


# ---------------------------------------------------------------- capture
#: Buffer for the captures here, in samples. Deliberately smaller than the
#: examples' own: a receive buffer as large as the whole capture does not
#: return at all on this firmware (a 262144-sample buffer with a 262144-sample
#: head request hung; 65536 delivered the same 262144 samples in 1.4 s). The
#: examples themselves run fine at 262144 because they stream continuously
#: rather than asking for exactly one bufferful and stopping.
CAPTURE_BUF = 65536

#: The capture runs in its own process, and this is it. A wedged radio blocks
#: inside `tb.wait()`, where no in-process timeout can reach it - the thread is
#: in a futex, the flowgraph never returns, and the whole measurement run stops
#: with no output. Several runs were lost that way before this was isolated.
#: A subprocess can simply be killed.
_CAPTURE_CHILD = r"""
import sys, numpy as np
from gnuradio import gr, blocks, iio
uri, fs, freq, gains, nsamp, channels, out = (
    sys.argv[1], float(sys.argv[2]), float(sys.argv[3]),
    [float(g) for g in sys.argv[4].split(',')], int(sys.argv[5]),
    int(sys.argv[6]), sys.argv[7])
tb = gr.top_block()
two = channels == 2
src = iio.fmcomms2_source_fc32(uri, [True, True, two, two], %d)
src.set_samplerate(int(fs))
src.set_frequency(int(freq))
for i, g in enumerate(gains[:channels]):
    src.set_gain_mode(i, 'manual')
    src.set_gain(i, float(g))
src.set_quadrature(True); src.set_rfdc(True); src.set_bbdc(True)
src.set_filter_params('Auto', '', 0, 0)
sinks = []
for i in range(channels):
    h = blocks.head(gr.sizeof_gr_complex, nsamp)
    sk = blocks.vector_sink_c()
    tb.connect((src, i), h, sk)
    sinks.append(sk)
tb.run()
for i, sk in enumerate(sinks):
    np.save('%%s.%%d.npy' %% (out, i), np.array(sk.data()))
print('CAPTURED', ' '.join(str(len(sk.data())) for sk in sinks))
""" % CAPTURE_BUF


def capture(uri, fs, freq, gains, nsamp, channels=1, deadline=60.0):
    """nsamp complex samples from one or both receivers, in a child process.

    Bounded by construction: a radio that never delivers gets its process
    killed rather than hanging the whole measurement run.
    """
    import subprocess
    import tempfile

    d = tempfile.mkdtemp(prefix="fishball-capture-")
    out = os.path.join(d, "iq")
    cmd = [sys.executable, "-c", _CAPTURE_CHILD, uri, str(fs), str(freq),
           ",".join(str(g) for g in gains), str(int(nsamp)), str(channels), out]
    try:
        r = subprocess.run(cmd, timeout=deadline, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        raise SystemExit(
            f"the radio did not deliver {int(nsamp)} samples in {deadline:.0f} s.\n"
            f"  Something is probably holding it. Check with:\n"
            f"      # run from: the repo root\n"
            f"      ./devkit status\n"
            f"  A killed libiio client leaves its session open ON THE BOARD, "
            f"holding the DMA;\n  `killall iiod` there clears it, and so does "
            f"a reboot.")
    if r.returncode != 0 or "CAPTURED" not in r.stdout:
        raise SystemExit(f"capture failed:\n{r.stdout}\n{r.stderr}")
    got = [np.load(f"{out}.{i}.npy") for i in range(channels)]
    return got[0] if channels == 1 else got


def tx_sink(iio, uri, chans, buf, cyclic, tries=8):
    """A transmit sink, retried.

    The board holds the transmit DMA for a moment after a client disconnects,
    so the next request can come back EBUSY (-16). It is not about size: a
    4 MB buffer allocates fine as a fresh process's first request, and a 1 MB
    one is refused as the same process's second. Waiting is the whole fix.
    """
    # A settle before the FIRST attempt as well as between retries: a
    # request that fails can still have started the DMA before it raised, so
    # retrying too eagerly keeps the thing you are waiting for alive.
    time.sleep(3.0)
    for k in range(tries):
        try:
            return iio.fmcomms2_sink_fc32(uri, chans, buf, cyclic)
        except RuntimeError as exc:
            if '-16' not in str(exc) or k == tries - 1:
                raise
            print(f"   transmit DMA still busy, waiting ({k + 1}/{tries})...",
                  flush=True)
            time.sleep(6.0)


def loopback_state(host):
    from iiod_min import Iiod
    with Iiod(host) as c:
        return c.read_debug('ad9361-phy', 'loopback').strip()


# ------------------------------------------------------------------- 01
def frames(x, n):
    k = len(x) // n
    return x[:k * n].reshape(k, n)


def spectrum(x, window, nfft=NFFT):
    """Power-averaged spectrum in dBFS, exactly as the example computes it."""
    w = se.make_window(window, nfft)
    norm = float(w.sum()) ** 2
    acc = None
    for f in frames(x, nfft):
        p = np.abs(np.fft.fftshift(np.fft.fft(f * w))) ** 2 / norm
        acc = p if acc is None else acc + p
    acc /= max(1, len(frames(x, nfft)))
    return 10 * np.log10(acc + 1e-30)


#: Where to look for 01, and why this is a compromise worth knowing about.
#:
#: The window lesson is most visible with something STRONG in the span: against
#: a quiet band every window reports about the same range and the picture makes
#: a different (also true) point. FM broadcast would be ideal, since it is the
#: one transmitter that is on everywhere all the time - but 98 MHz would not
#: capture at all on the board this was written against, immediately after a
#: reboot, while 2.4 GHz captured fine. Rather than ship a default that fails,
#: this looks at Wi-Fi channel 6 and the figure says plainly what it found.
#: Pass --centre to look wherever is loud for you; FM is worth trying.
#:
#: This is ONE capture on purpose. An earlier version probed four candidate
#: bands and picked the best, and those extra sessions were themselves enough
#: to wedge the board's receive DMA - see references/debugging.md in the agent
#: skill.
CENTRE_01 = 2_437_000_000
GAIN_01 = 55


def do_01(uri, centre=CENTRE_01, gain=GAIN_01):
    what = ("FM broadcast" if centre < 200e6
            else "2.4 GHz Wi-Fi" if 2.4e9 < centre < 2.5e9
            else f"{centre/1e6:.1f} MHz")
    x = capture(uri, FS_01, centre - LO_FRAC_01 * FS_01, [gain], 32 * NFFT,
                deadline=40.0)
    # Shift back, so the axis reads true frequency and the LO leak sits at
    # -lo_off rather than in the middle - the example's offset tuning.
    n = np.arange(len(x))
    x = x * np.exp(-2j * np.pi * LO_FRAC_01 * n)

    out = {"samp_rate": FS_01, "centre_hz": centre, "nfft": NFFT,
           "lo_frac": LO_FRAC_01, "gain_db": gain, "what": what,
           "frames": len(frames(x, NFFT)), "traces": {}, "synthetic": {}}
    for wname in ("rectangular", "hann", "blackman-harris"):
        tr = spectrum(x, wname)
        floor = float(10 * np.log10(np.percentile(10 ** (tr / 10), 10.0)))
        out["traces"][wname] = {
            "peak_dbfs": float(tr.max()), "floor_dbfs": floor,
            "range_db": float(tr.max()) - floor,
            "sidelobes_db": se.SIDELOBES_DB[wname],
            # Every 2nd bin: 2048 points is plenty for a figure and keeps the
            # JSON a sane size.
            "db": [round(float(v), 2) for v in tr[::2]],
        }

    # The known-answer case, which real air cannot provide: a full-scale
    # carrier and a tone 60 dB below it, 40 bins away, both half a bin off
    # centre so that the rectangular window actually leaks.
    k = np.arange(NFFT)
    two = (np.exp(2j * np.pi * 700.5 * k / NFFT)
           + 1e-3 * np.exp(2j * np.pi * 740.5 * k / NFFT)).astype(np.complex64)
    one = np.exp(2j * np.pi * 700.5 * k / NFFT).astype(np.complex64)
    for wname in ("rectangular", "hann", "blackman-harris"):
        t2 = spectrum(two, wname)
        t1 = spectrum(one, wname)
        out["synthetic"][wname] = {
            "weak_tone_true_dbfs": -60.0,
            "weak_tone_read_dbfs": float(t2[NFFT // 2 + 738:NFFT // 2 + 743].max()),
            "leakage_40_bins_dbfs": float(t1[NFFT // 2 + 740]),
            "sidelobes_db": se.SIDELOBES_DB[wname],
        }
    return out


# ------------------------------------------------------------------- 02
def do_02_software(snr_db=40.0, rot_deg=0.0, nsym=200_000):
    """The same receive chain, fed by the modulator directly - no radio.

    WHY THIS EXISTS. The hardware route for this measurement is the AD9361's
    internal digital loopback, and on this firmware that route is not reliable:
    with loopback engaged, allocating a large transmit buffer makes IIOD reset
    the session (errno -104), and the reset leaves the transmit DMA allocated so
    that every later attempt fails with -16 EBUSY until iiod is restarted.
    Smaller buffers and normal (non-loopback) operation are unaffected. Rather
    than publish a figure measured through a path that wedges the board, this
    runs the identical chain in one process.

    WHAT IT DOES AND DOES NOT PROVE. Every block is the real one, including the
    embedded EVM meter, the Gardner timing recovery and the Costas loop, so it
    proves the chain recovers symbols and the EVM figures are right. It proves
    NOTHING about the radio: no converter, no mixer, no amplifier, no clock.
    The figure and the README both say so.

    A fixed rotation is applied on purpose, so that the two EVM figures differ
    the way they do on a real link with a mistuned carrier loop - which is the
    thing the pair exists to show.
    """
    from gnuradio import gr, blocks, digital, filter as gfilter, analog
    from gnuradio.filter import firdes
    FS, SPS, A = 2_000_000, 4, 0.35
    # NOT scaled by the example's 0.20 transmit scale. That number exists to
    # keep a root raised cosine's peaks inside a converter's full scale, and
    # there is no converter here. Scaling the signal but not the noise is how
    # the first version of this measurement reported 26% EVM at a nominal
    # 26 dB SNR: the real SNR was 20*log10(0.20/0.05) = 12 dB.
    out = {"path": "software", "samp_rate": FS, "sps": SPS, "alpha": A,
           "snr_db": snr_db, "rotation_deg": rot_deg,
           "loopback": False, "orders": {}, "snr_sweep": []}
    for order in (4, 16, 64):
        cnst = digital.constellation_calcdist(
            qam.points(order), list(range(order)), 4, 1,
            digital.constellation.POWER_NORMALIZATION).base()
        tb = gr.top_block()
        src = blocks.vector_source_b(
            list(map(int, np.random.randint(0, 256, 100_000))), True)
        mod = digital.generic_mod(constellation=cnst, differential=False,
                                  samples_per_symbol=SPS, pre_diff_code=True,
                                  excess_bw=A, verbose=False, log=False,
                                  truncate=False)
        # Noise referenced to the signal's own RMS, which the modulator sets
        # to 1.0, so the requested SNR is the SNR that arrives.
        sigma = 10 ** (-snr_db / 20.0)
        noise = analog.noise_source_c(analog.GR_GAUSSIAN, sigma, 0)
        add = blocks.add_cc()
        rot = blocks.rotator_cc(0.0)
        rot.set_phase_inc(0.0)
        fixed = blocks.multiply_const_cc(
            complex(np.cos(np.radians(rot_deg)), np.sin(np.radians(rot_deg))))
        mf = gfilter.fir_filter_ccf(
            1, firdes.root_raised_cosine(SPS, FS, FS / SPS, A, 11 * SPS + 1))
        sy = digital.symbol_sync_cc(digital.TED_MOD_MUELLER_AND_MULLER, SPS,
                                    0.045, 1.0, 1.0, 1.5, 1, cnst,
                                    digital.IR_MMSE_8TAP, 128, [])
        co = digital.costas_loop_cc(0.030, 4, False)
        ev = evm_meter.blk(order=order, chunk=2048)
        head = blocks.head(gr.sizeof_gr_complex, nsym * SPS)
        sym, e1, e2, mr = (blocks.vector_sink_c(), blocks.vector_sink_f(),
                           blocks.vector_sink_f(), blocks.vector_sink_f())
        tb.connect(src, mod, fixed, (add, 0))
        tb.connect(noise, (add, 1))
        tb.connect(add, head, mf, sy, co, ev)
        tb.connect((ev, 0), sym); tb.connect((ev, 1), e1)
        tb.connect((ev, 2), e2); tb.connect((ev, 3), mr)
        tb.run()

        s_ = np.array(sym.data()); a = np.array(e1.data())
        b = np.array(e2.data()); m = np.array(mr.data())
        if len(a) == 0:
            raise SystemExit(f"order {order}: no symbols recovered")
        tail = slice(len(a) // 2, None)
        out["orders"][str(order)] = {
            "symbols": int(len(s_)),
            "evm_pct": float(a[tail].mean()),
            "evm_eq_pct": float(b[tail].mean()),
            "mer_db": float(m[tail].mean()),
            "rms": float(np.sqrt((np.abs(s_[tail]) ** 2).mean())),
            "ideal": [[float(p.real), float(p.imag)] for p in qam.points(order)],
            "cloud": [[round(float(v.real), 4), round(float(v.imag), 4)]
                      for v in s_[tail][-4000:][::2]],
        }

    # QPSK against SNR, which is the quantitative check on the whole chain:
    # EVM should track 100 * 10^(-SNR/20) until the matched filter's noise
    # rejection pulls it below that, and it must NOT keep falling once symbol
    # decisions start failing - at that point the meter is measuring distance
    # to the WRONG reference point and saturates. Both effects are real and
    # worth being able to see.
    cnst4 = digital.constellation_calcdist(
        qam.points(4), list(range(4)), 4, 1,
        digital.constellation.POWER_NORMALIZATION).base()
    for snr in (6, 10, 14, 18, 22, 26, 30, 34):
        tb = gr.top_block()
        src = blocks.vector_source_b(
            list(map(int, np.random.randint(0, 256, 100_000))), True)
        mod = digital.generic_mod(constellation=cnst4, differential=False,
                                  samples_per_symbol=SPS, pre_diff_code=True,
                                  excess_bw=A, verbose=False, log=False,
                                  truncate=False)
        add = blocks.add_cc()
        tb.connect(src, mod, (add, 0))
        tb.connect(analog.noise_source_c(analog.GR_GAUSSIAN,
                                        10 ** (-snr / 20.0), 0), (add, 1))
        mf = gfilter.fir_filter_ccf(
            1, firdes.root_raised_cosine(SPS, FS, FS / SPS, A, 11 * SPS + 1))
        sy = digital.symbol_sync_cc(digital.TED_MOD_MUELLER_AND_MULLER, SPS,
                                    0.045, 1.0, 1.0, 1.5, 1, cnst4,
                                    digital.IR_MMSE_8TAP, 128, [])
        ev = evm_meter.blk(order=4, chunk=2048)
        e1 = blocks.vector_sink_f()
        tb.connect(add, blocks.head(gr.sizeof_gr_complex, 80_000 * SPS), mf, sy,
                   digital.costas_loop_cc(0.030, 4, False), ev)
        tb.connect((ev, 1), e1)
        for i in (0, 2, 3):
            tb.connect((ev, i), blocks.null_sink(
                gr.sizeof_gr_complex if i == 0 else gr.sizeof_float))
        tb.run()
        a = np.array(e1.data())
        if len(a) == 0:
            continue
        out["snr_sweep"].append({
            "snr_db": snr,
            "evm_pct": float(a[len(a) // 2:].mean()),
            "evm_theory_pct": 100.0 * 10 ** (-snr / 20.0),
        })
    return out


def do_02(uri, host, secs=12.0):
    if loopback_state(host) == '0':
        raise SystemExit(
            "02 needs the chip's digital loopback, and it is off.\n"
            "  # run from: the repo root\n"
            "  ./devkit loopback on      # nothing is radiated\n"
            "  ...then re-run this, and ./devkit loopback off afterwards.")

    from gnuradio import gr, blocks, digital, filter as gfilter, iio
    from gnuradio.filter import firdes
    FS, SPS, A, SCALE, OFF, BUF = 2_000_000, 4, 0.35, 0.20, 0.20, 1_048_576
    out = {"samp_rate": FS, "sps": SPS, "alpha": A, "tx_scale": SCALE,
           "lo_frac": OFF, "buffer": BUF, "loopback": True, "orders": {}}
    for order in (4, 16, 64):
        cnst = digital.constellation_calcdist(
            qam.points(order), list(range(order)), 4, 1,
            digital.constellation.POWER_NORMALIZATION).base()
        tb = gr.top_block()
        src = blocks.vector_source_b(
            list(map(int, np.random.randint(0, 256, 200000))), True)
        mod = digital.generic_mod(constellation=cnst, differential=False,
                                  samples_per_symbol=SPS, pre_diff_code=True,
                                  excess_bw=A, verbose=False, log=False,
                                  truncate=False)
        tx = tx_sink(iio, uri, [True, True, False, False], BUF, False)
        tx.set_len_tag_key('')
        tx.set_bandwidth(int(FS)); tx.set_frequency(CENTRE_HZ)
        tx.set_samplerate(int(FS))
        # Analogue attenuator at maximum as well as the digital loopback.
        tx.set_attenuation(0, 89.75); tx.set_attenuation(1, 89.75)
        tx.set_filter_params('Auto', '', 0, 0)
        # Offsets EQUAL at both ends: loopback does not translate frequency.
        tb.connect(src, mod, blocks.rotator_cc(2 * np.pi * OFF),
                   blocks.multiply_const_cc(SCALE), tx)

        rx = iio.fmcomms2_source_fc32(uri, [True, True, False, False], BUF)
        rx.set_samplerate(int(FS)); rx.set_frequency(CENTRE_HZ)
        rx.set_gain_mode(0, 'manual'); rx.set_gain(0, 20)
        rx.set_quadrature(True); rx.set_rfdc(True); rx.set_bbdc(True)
        rx.set_filter_params('Auto', '', 0, 0)
        mf = gfilter.fir_filter_ccf(
            1, firdes.root_raised_cosine(SPS, FS, FS / SPS, A, 11 * SPS + 1))
        sy = digital.symbol_sync_cc(digital.TED_MOD_MUELLER_AND_MULLER, SPS,
                                    0.045, 1.0, 1.0, 1.5, 1, cnst,
                                    digital.IR_MMSE_8TAP, 128, [])
        co = digital.costas_loop_cc(0.030, 4, False)
        ev = evm_meter.blk(order=order, chunk=2048)
        sym, e1, e2, mr = (blocks.vector_sink_c(), blocks.vector_sink_f(),
                           blocks.vector_sink_f(), blocks.vector_sink_f())
        tb.connect(rx, blocks.rotator_cc(-2 * np.pi * OFF), mf, sy, co, ev)
        tb.connect((ev, 0), sym); tb.connect((ev, 1), e1)
        tb.connect((ev, 2), e2); tb.connect((ev, 3), mr)
        tb.start(); time.sleep(secs); tb.stop(); tb.wait()
        tb = None

        s = np.array(sym.data()); a = np.array(e1.data())
        b = np.array(e2.data()); m = np.array(mr.data())
        if len(a) == 0 or not np.isfinite(a).any():
            raise SystemExit(f"order {order}: no symbols recovered")
        tail = slice(len(a) // 2, None)            # after the loops settle
        out["orders"][str(order)] = {
            "symbols": int(len(s)),
            "evm_pct": float(a[tail].mean()),
            "evm_eq_pct": float(b[tail].mean()),
            "mer_db": float(m[tail].mean()),
            "rms": float(np.sqrt((np.abs(s[tail]) ** 2).mean())),
            "ideal": [[float(p.real), float(p.imag)] for p in qam.points(order)],
            # A sample of the cloud for the scatter plot, from the settled tail.
            "cloud": [[round(float(v.real), 4), round(float(v.imag), 4)]
                      for v in s[tail][-4000:][::2]],
        }
        time.sleep(3.0)
    return out


# ------------------------------------------------------------------- 03
def do_03(uri):
    a, b = capture(uri, FS_03, CENTRE_HZ - LO_FRAC_03 * FS_03, [40, 40],
                   24 * NFFT, channels=2, deadline=30.0)
    off_hz = LO_FRAC_03 * FS_03
    n = np.arange(len(a))
    # One shift, applied identically to both channels, bringing the offset
    # signal to baseband. Identical, so it cannot change the phase BETWEEN them.
    sh = np.exp(-2j * np.pi * LO_FRAC_03 * n)
    a, b = a * sh, b * sh

    out = {"samp_rate": FS_03, "centre_hz": CENTRE_HZ, "lo_frac": LO_FRAC_03,
           "lo_offset_hz": off_hz, "gain_db": [40, 40], "chunk": NFFT,
           "dc_enters_at_khz": 2 * off_hz / 1e3, "sweep": []}

    from numpy.fft import rfft, irfft
    for w_khz in (100, 200, 400, 800, 1200, 1600, 2000, 2600, 3200):
        half = w_khz * 1e3 / 2
        # The same low-pass on both channels. Done in the frequency domain so
        # the two are bit-for-bit identical filters.
        f = np.fft.fftfreq(len(a), 1 / FS_03)
        keep = np.abs(f) <= half
        fa = np.fft.ifft(np.fft.fft(a) * keep)
        fb = np.fft.ifft(np.fft.fft(b) * keep)
        r = np.vdot(fb, fa) / len(fa)
        p = float((np.abs(fa) ** 2).mean() * (np.abs(fb) ** 2).mean())
        coh = float(np.abs(r) / np.sqrt(p)) if p > 0 else 0.0
        out["sweep"].append({
            "width_khz": w_khz,
            "includes_dc": bool(half > off_hz),
            "coherence": min(coh, 1.0),
            "phase_deg": float(np.degrees(np.angle(r))),
        })

    # Stability: the phase estimated chunk by chunk at the default width,
    # which is what the example's "phase over time" display shows.
    half = 400e3 / 2
    f = np.fft.fftfreq(len(a), 1 / FS_03)
    keep = np.abs(f) <= half
    fa = np.fft.ifft(np.fft.fft(a) * keep)
    fb = np.fft.ifft(np.fft.fft(b) * keep)
    k = len(fa) // NFFT
    ph, co = [], []
    for i in range(k):
        s = slice(i * NFFT, (i + 1) * NFFT)
        r = np.vdot(fb[s], fa[s]) / NFFT
        p = float((np.abs(fa[s]) ** 2).mean() * (np.abs(fb[s]) ** 2).mean())
        ph.append(float(np.degrees(np.angle(r))))
        co.append(min(float(np.abs(r) / np.sqrt(p)) if p > 0 else 0.0, 1.0))
    out["stability"] = {"width_khz": 400,
                        "phase_deg": [round(v, 3) for v in ph],
                        "coherence": [round(v, 4) for v in co]}
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n", 1)[1])
    p.add_argument("which", nargs="*", default=["01", "02", "03"],
                   choices=["01", "02", "03"],
                   help="which examples to measure (default: all)")
    p.add_argument("--uri", default=None,
                   help="libiio URI; by default the board is found by name")
    p.add_argument("--centre", type=float, default=CENTRE_01, metavar="HZ",
                   help="centre frequency for 01 (default %(default).0f, FM "
                        "broadcast - pick whatever is loud where you are)")
    p.add_argument("--gain", type=float, default=GAIN_01, metavar="DB",
                   help="manual receive gain for 01 (default %(default).0f)")
    p.add_argument("--software-02", action="store_true",
                   help="measure 02 without the radio at all - the same chain "
                        "fed by the modulator through added noise. Use this "
                        "when the chip's digital loopback misbehaves; the "
                        "figure is labelled accordingly.")
    args = p.parse_args(argv)

    from board_addr import resolve
    host = args.uri.split(":", 1)[1] if args.uri else resolve()
    if not host:
        print("cannot find the board", file=sys.stderr)
        return 2
    uri = f"ip:{host}"

    data = {}
    if os.path.exists(OUT):
        with open(OUT) as f:
            data = json.load(f)
    data.setdefault("board", host)
    data["measured_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    for key in args.which:
        print(f"measuring {key} ...", flush=True)
        data[key] = {
            "01": lambda: do_01(uri, args.centre, args.gain),
            "02": (do_02_software if args.software_02
                   else (lambda: do_02(uri, host))),
            "03": lambda: do_03(uri),
        }[key]()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, indent=1)
    print(f"wrote {OUT}  ({os.path.getsize(OUT) // 1024} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
