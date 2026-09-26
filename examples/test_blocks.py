#!/usr/bin/env python3
"""Check the examples' embedded Python blocks, without a radio.

    # run from: the repo root
    python3 examples/test_blocks.py

Two things are checked, and they are different kinds of check.

  1. GNU Radio's own `epy_block_io.extract` accepts each block. This is the
     exact call GRC makes when it opens a flowgraph, so passing it means the
     .grc files will load: right ports, right widths, and - importantly - the
     right set of live controls. A parameter becomes a live control if and only
     if it is also an instance attribute or a property, so this test pins down
     which knobs GRC will generate setters for. `nfft` must NOT be one: a
     setter for it would look live and could not resize a port.

  2. The DSP is right. A window that mislabels a level by 24 dB, an EVM that
     flatters by ignoring rotation, or a phase average taken over angles
     instead of complex numbers all produce output that looks entirely
     reasonable. Each is caught below by a case with a known answer.

Everything here runs on numpy and GNU Radio's Python bindings alone.
"""
from __future__ import annotations

import importlib.util
import os
import sys

import numpy as np

LIB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")

fails = []


def check(name, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"   {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def load(mod):
    spec = importlib.util.spec_from_file_location(mod, os.path.join(LIB, mod + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run(blk, ins, n_out, out_specs):
    """Call work() once. out_specs is (dtype, vlen) per output port."""
    outs = [np.zeros((n_out, v), d) if v > 1 else np.zeros(n_out, d)
            for d, v in out_specs]
    blk.work(ins, outs)
    return outs


# ---------------------------------------------------------------- extraction
def test_extraction():
    from gnuradio.grc.core.utils import epy_block_io

    want = {
        "spectrum_engine": (["avg", "floor_pct", "hold", "window"],
                            [("0", "complex", 4096)],
                            [("0", "float", 4096), ("1", "float", 4096)]
                            + [(str(i), "float", 1) for i in range(2, 6)]),
        "evm_meter": ([],
                      [("0", "complex", 1)],
                      [("0", "complex", 1)]
                      + [(str(i), "float", 1) for i in range(1, 4)]),
        "phase_meter": (["avg", "zero"],
                        [("0", "complex", 1), ("1", "complex", 1)],
                        [(str(i), "float", 1) for i in range(3)]
                        + [("3", "complex", 1)]),
    }
    print("GRC can load these blocks")
    for mod, (cbs, sinks, sources) in want.items():
        with open(os.path.join(LIB, mod + ".py")) as f:
            io = epy_block_io.extract(f.read())
        check(f"{mod}: extracts", True, io.name)
        check(f"{mod}: live controls are exactly {cbs}",
              sorted(io.callbacks) == cbs, str(sorted(io.callbacks)))
        check(f"{mod}: input ports", list(io.sinks) == sinks, str(io.sinks))
        check(f"{mod}: output ports", list(io.sources) == sources, str(io.sources))
    # The one that would silently lie if it slipped through.
    with open(os.path.join(LIB, "spectrum_engine.py")) as f:
        io = epy_block_io.extract(f.read())
    check("spectrum_engine: nfft is NOT a live control", "nfft" not in io.callbacks)


# ------------------------------------------------------------------ spectrum
def test_spectrum():
    m = load("spectrum_engine")
    N = 4096
    specs = [(np.float32, N), (np.float32, N)] + [(np.float32, 1)] * 4
    print("\nspectrum_engine: levels are dBFS and the metric matches the trace")

    for w, scallop in (("rectangular", 3.92), ("hann", 1.42),
                       ("blackman-harris", 0.83)):
        b = m.blk(nfft=N, window=w, avg=1, hold=False)
        # A full-scale tone exactly on a bin centre must read 0 dBFS. If the
        # window's own gain were not divided back out this would be wrong by
        # tens of dB, differently for each window.
        x = np.exp(2j * np.pi * 700 * np.arange(N) / N).astype(np.complex64)
        o = run(b, [x.reshape(1, N)], 1, specs)
        check(f"{w}: full-scale tone reads 0 dBFS",
              abs(float(o[3][0])) < 0.01, f"{float(o[3][0]):+.4f} dBFS")

        # Half a bin off centre: the textbook scalloping loss for each window.
        # Getting these right means the window really is the one it is named.
        b = m.blk(nfft=N, window=w, avg=1, hold=False)
        x = np.exp(2j * np.pi * 700.5 * np.arange(N) / N).astype(np.complex64)
        o = run(b, [x.reshape(1, N)], 1, specs)
        got = -float(o[3][0])
        check(f"{w}: scalloping loss is {scallop} dB",
              abs(got - scallop) < 0.05, f"{got:.2f} dB")

    # Sidelobes: the reason the control exists at all. A full-scale carrier and
    # a tone 60 dB below it, 40 bins away. The weak tone's true level is known,
    # so each window can be scored on how badly it misreads it.
    #
    # Both tones sit HALF A BIN off centre, and that detail is the test. A tone
    # exactly on a bin centre leaks nothing at all through a rectangular window
    # - every other bin is mathematically zero - so an on-bin test makes the
    # worst window look perfect. Real signals are never on a bin centre.
    print("\nspectrum_engine: a rectangular window really does hide a weak tone")
    k = np.arange(N)
    x = (np.exp(2j * np.pi * 700.5 * k / N)
         + 1e-3 * np.exp(2j * np.pi * 740.5 * k / N)).astype(np.complex64)
    seen = {}
    for w in ("rectangular", "hann", "blackman-harris"):
        b = m.blk(nfft=N, window=w, avg=1, hold=False)
        o = run(b, [x.reshape(1, N)], 1, specs)
        tr = np.asarray(o[0][0])
        seen[w] = float(tr[N // 2 + 738:N // 2 + 743].max())
    check("rectangular misreads a -60 dBFS tone by over 10 dB",
          seen["rectangular"] > -50,
          f"reads {seen['rectangular']:.1f} dBFS, truth -60.0 "
          f"({seen['rectangular'] + 60:+.1f} dB)")
    for w in ("hann", "blackman-harris"):
        check(f"{w} reads it within 2 dB", abs(seen[w] + 60.0) < 2.0,
              f"reads {seen[w]:.2f} dBFS")

    # And the same strong carrier ALONE, to show what each window leaves
    # behind: this is the noise floor the window itself manufactures.
    x1 = np.exp(2j * np.pi * 700.5 * k / N).astype(np.complex64)
    alone = {}
    for w in ("rectangular", "hann", "blackman-harris"):
        b = m.blk(nfft=N, window=w, avg=1, hold=False)
        alone[w] = float(np.asarray(run(b, [x1.reshape(1, N)], 1, specs)[0][0])
                         [N // 2 + 740])
    check("the window's own leakage floor improves with each window",
          alone["rectangular"] > alone["hann"] > alone["blackman-harris"],
          "40 bins from a full-scale carrier: "
          + ", ".join(f"{w} {alone[w]:.0f}" for w in alone) + " dBFS")

    # The metric must come from the displayed average trace, not from max-hold.
    print("\nspectrum_engine: dynamic range is peak minus floor of ONE trace")
    b = m.blk(nfft=N, window="blackman-harris", avg=1, hold=True, floor_pct=10.0)
    rng = np.random.default_rng(7)
    x = (0.5 * np.exp(2j * np.pi * 300 * np.arange(N) / N)
         + 1e-4 * (rng.standard_normal(N) + 1j * rng.standard_normal(N))
         ).astype(np.complex64)
    o = run(b, [x.reshape(1, N)], 1, specs)
    tr = np.asarray(o[0][0])
    want = float(tr.max()) - 10 * np.log10(
        np.percentile(10 ** (tr / 10), 10.0))
    check("range = peak - 10th percentile of the average trace",
          abs(float(o[2][0]) - want) < 0.05,
          f"reported {float(o[2][0]):.2f} dB, recomputed {want:.2f} dB")
    b2 = m.blk(nfft=N, window="blackman-harris", avg=1, hold=True, floor_pct=90.0)
    o2 = run(b2, [x.reshape(1, N)], 1, specs)
    check("a higher percentile reports a higher floor",
          float(o2[4][0]) > float(o[4][0]) + 1,
          f"10% -> {float(o[4][0]):.1f} dBFS, 90% -> {float(o2[4][0]):.1f} dBFS")

    # Power-domain averaging: the mean of two powers, not of two dB values.
    print("\nspectrum_engine: averaging happens in power, not in dB")
    b = m.blk(nfft=16, window="rectangular", avg=2.0, hold=False)
    sp = [(np.float32, 16), (np.float32, 16)] + [(np.float32, 1)] * 4
    lo = (1e-3 * np.ones(16)).astype(np.complex64)
    hi = (1.0 * np.ones(16)).astype(np.complex64)
    run(b, [lo.reshape(1, 16)], 1, sp)
    o = run(b, [hi.reshape(1, 16)], 1, sp)
    p_lo, p_hi = (1e-3 * 16) ** 2 / 16 ** 2, (1.0 * 16) ** 2 / 16 ** 2
    want = 10 * np.log10(p_lo + (p_hi - p_lo) / 2.0)
    # A DC input puts all its power in bin 0, and the block returns a SHIFTED
    # trace, so that bin is at the middle of the array, not the start.
    got = float(np.asarray(o[0][0])[16 // 2])
    check("one IIR step lands on the power mean, not the dB mean",
          abs(got - want) < 0.01,
          f"{got:.2f} dB (power mean {want:.2f}, dB mean "
          f"{(10*np.log10(p_lo)+10*np.log10(p_hi))/2:.2f})")


# ----------------------------------------------------------------------- EVM
def test_evm():
    m = load("evm_meter")
    print("\nevm_meter: known errors produce the known figures")
    specs = [(np.complex64, 1), (np.float32, 1), (np.float32, 1), (np.float32, 1)]

    for order in (4, 16, 64):
        ref = m.square_qam(order)
        check(f"order {order}: reference has unit mean power",
              abs(float((np.abs(ref) ** 2).mean()) - 1.0) < 1e-6,
              f"{len(ref)} points")

    rng = np.random.default_rng(3)
    for order in (4, 16, 64):
        ref = m.square_qam(order)
        sym = ref[rng.integers(0, len(ref), 4096)]

        b = m.blk(order=order, chunk=4096)
        o = run(b, [sym.astype(np.complex64)], 4096, specs)
        # Exactly zero, at every order. This is the check that catches
        # normalising to the ideal set's unit power instead of to the decided
        # reference: that mistake reads about 0.35% here for 16-QAM and 0.6%
        # for 64-QAM, which looks like a plausible impairment and is not one.
        check(f"order {order}: perfect symbols read 0.000% EVM",
              float(o[1][0]) < 0.001, f"{float(o[1][0]):.5f}%")

        # A known noise power. EVM is normalised to the reference RMS power,
        # which is 1, so an error power of (0.05)^2 is exactly 5% EVM.
        b = m.blk(order=order, chunk=4096)
        e = (rng.standard_normal(4096) + 1j * rng.standard_normal(4096)) / np.sqrt(2)
        noisy = (sym + 0.05 * e).astype(np.complex64)
        o = run(b, [noisy], 4096, specs)
        check(f"order {order}: 5% error power reads ~5% EVM",
              abs(float(o[1][0]) - 5.0) < 0.6, f"{float(o[1][0]):.2f}%")
        mer = float(o[3][0])
        check(f"order {order}: MER is -20log10(EVM/100)",
              abs(mer - (-20 * np.log10(float(o[1][0]) / 100))) < 0.01,
              f"{mer:.2f} dB")

    # The pair that matters: a fixed rotation is a large raw EVM and almost no
    # equalised EVM. This is the check that would catch an EVM meter quietly
    # correcting rotation and reporting a flattering single number.
    ref = m.square_qam(4)
    sym = ref[rng.integers(0, 4, 4096)]
    b = m.blk(order=4, chunk=4096)
    rot = (sym * np.exp(1j * np.radians(20))).astype(np.complex64)
    o = run(b, [rot], 4096, specs)
    raw, eq = float(o[1][0]), float(o[2][0])
    # A 20 degree rotation moves each unit-power symbol by 2 sin(10 deg).
    want = 100 * 2 * np.sin(np.radians(10))
    check("20 deg rotation: raw EVM is the chord length",
          abs(raw - want) < 0.5, f"{raw:.2f}% (expected {want:.2f}%)")
    check("20 deg rotation: equalised EVM is ~0",
          eq < 0.01, f"{eq:.4f}%")
    check("the gap exposes the rotation", raw - eq > 30,
          f"raw {raw:.1f}% vs equalised {eq:.2f}%")

    # The separable decision must be EXACTLY the brute-force one, not merely
    # close. It replaced a distance matrix that was starving the transmitter,
    # and a decision rule that is right 99.9% of the time would show up as a
    # small unexplained EVM floor rather than as an obvious bug.
    print()
    for order in (4, 16, 64):
        ref = m.square_qam(order)
        b = m.blk(order=order)
        y = ((rng.standard_normal(20000) + 1j * rng.standard_normal(20000))
             * 0.6).astype(np.complex64)
        sep = b._decide(y)
        brute = ref[np.argmin(np.abs(y[:, None] - ref[None, :]), axis=1)]
        check(f"order {order}: separable decision == brute force on 20k points",
              np.allclose(sep, brute))
        check(f"order {order}: levels() crossed with itself IS the point set",
              np.allclose(np.sort_complex(
                  (m.levels(order)[:, None]
                   + 1j * m.levels(order)[None, :]).ravel()),
                  np.sort_complex(ref)))

    # The reported value must TRACK the input, and the unit of "recent" must be
    # samples rather than seconds. A wall-clock throttle here measured once and
    # then reported that one number forever in any run that finished quickly -
    # it read 23% on a stream that was 0.3% and held flat against changing SNR.
    # So: feed clean symbols, then noisy ones, and require the number to move.
    b = m.blk(order=4, chunk=2048)
    clean = m.square_qam(4)[rng.integers(0, 4, 8192)].astype(np.complex64)
    o = run(b, [clean], 8192, specs)
    first = float(o[1][-1])
    check("a clean stream reads ~0%", first < 0.01, f"{first:.5f}%")
    noisy = (m.square_qam(4)[rng.integers(0, 4, 8192)]
             + 0.15 * (rng.standard_normal(8192)
                       + 1j * rng.standard_normal(8192))).astype(np.complex64)
    o = run(b, [noisy], 8192, specs)
    last = float(o[1][-1])
    check("the number follows the data, it does not hold a stale value",
          last > 10.0, f"{first:.3f}% clean then {last:.2f}% noisy")

    # And it must not recompute on every call, or a fast Python block starves
    # the transmit thread. One measurement per bufferful: with chunk 2048 and
    # calls of 512, only every fourth call may measure.
    b = m.blk(order=4, chunk=2048)
    seen = []
    for _ in range(8):
        before = b._last
        run(b, [clean[:512]], 512, specs)
        seen.append(b._last is not before)
    # Three, not two: one immediately on the first call so the display shows
    # something rather than a silent zero, then one per 2048 symbols.
    check("measures once per bufferful, not on every call",
          sum(seen) == 3, f"{sum(seen)} measurements in 8 calls of 512 "
                          f"(chunk 2048: one at startup + two bufferfuls)")

    # Port 0 must be at the reference's scale, or the picture and the number
    # disagree even when both are individually right.
    b = m.blk(order=16, chunk=4096)
    sym = m.square_qam(16)[rng.integers(0, 16, 4096)]
    o = run(b, [(sym * 37.0).astype(np.complex64)], 4096, specs)
    check("port 0 is rescaled to the reference RMS",
          abs(float(np.sqrt((np.abs(np.asarray(o[0])) ** 2).mean())) - 1.0) < 0.02,
          f"rms {float(np.sqrt((np.abs(np.asarray(o[0]))**2).mean())):.4f}")


# --------------------------------------------------------------------- phase
def test_phase():
    m = load("phase_meter")
    print("\nphase_meter: the angle, and whether to trust it")
    C = 4096
    specs = [(np.float32, 1)] * 3 + [(np.complex64, 1)]
    rng = np.random.default_rng(11)

    def two(theta_deg, n=1, snr=None):
        x1 = (rng.standard_normal(C * n) + 1j * rng.standard_normal(C * n)
              ).astype(np.complex64)
        x2 = (x1 * np.exp(-1j * np.radians(theta_deg))).astype(np.complex64)
        if snr is not None:
            s = 10 ** (-snr / 20.0)
            x2 = (x2 + s * (rng.standard_normal(C * n)
                            + 1j * rng.standard_normal(C * n))).astype(np.complex64)
        return x1, x2

    for th in (0.0, 37.0, 120.0, -95.0):
        b = m.blk(chunk=C, avg=1.0)
        x1, x2 = two(th)
        o = run(b, [x1, x2], 1, specs)
        check(f"phase {th:+.0f} deg recovered",
              abs(float(o[2][0]) - th) < 0.5, f"{float(o[2][0]):+.2f} deg")
        check(f"phase {th:+.0f} deg: coherence ~1",
              float(o[1][0]) > 0.999, f"{float(o[1][0]):.4f}")

    # The wrap case. A true phase at 179 degrees, noisy enough that individual
    # chunks land either side of the boundary. Averaging the ANGLES would give
    # something near zero; averaging the correlation gives 179.
    b = m.blk(chunk=C, avg=8.0)
    x1, x2 = two(179.0, n=8, snr=3.0)
    o = run(b, [x1, x2], 8, specs)
    got = float(o[2][7])
    check("a phase at the +/-180 wrap still reads ~180, not ~0",
          min(abs(got - 179.0), abs(abs(got) - 179.0)) < 6.0, f"{got:+.2f} deg")

    # Independent noise: the angle is meaningless and coherence must say so.
    b = m.blk(chunk=C, avg=1.0)
    a = (rng.standard_normal(C) + 1j * rng.standard_normal(C)).astype(np.complex64)
    c = (rng.standard_normal(C) + 1j * rng.standard_normal(C)).astype(np.complex64)
    o = run(b, [a, c], 1, specs)
    check("independent inputs give near-zero coherence",
          float(o[1][0]) < 0.06, f"{float(o[1][0]):.4f} (1/sqrt(N) = "
                                 f"{1/np.sqrt(C):.4f})")

    # Zeroing: rising edge latches, and it must not keep re-zeroing.
    b = m.blk(chunk=C, avg=1.0, zero=False)
    x1, x2 = two(60.0)
    run(b, [x1, x2], 1, specs)
    b.zero = True
    x1, x2 = two(60.0)
    o = run(b, [x1, x2], 1, specs)
    check("zero latches: a held reading reads ~0 after zeroing",
          abs(float(o[0][0])) < 1.0, f"{float(o[0][0]):+.2f} deg")
    x1, x2 = two(90.0)
    o = run(b, [x1, x2], 1, specs)
    check("zero does not re-latch: a 30 deg change still shows",
          abs(float(o[0][0]) - 30.0) < 1.5, f"{float(o[0][0]):+.2f} deg")
    check("raw port is unaffected by zeroing",
          abs(float(o[2][0]) - 90.0) < 1.0, f"{float(o[2][0]):+.2f} deg")

    # The dial: radius is coherence, angle is phase.
    b = m.blk(chunk=C, avg=1.0)
    x1, x2 = two(45.0)
    o = run(b, [x1, x2], 1, specs)
    d = complex(np.asarray(o[3])[0])
    check("dial radius is coherence and angle is phase",
          abs(abs(d) - float(o[1][0])) < 1e-5
          and abs(np.degrees(np.angle(d)) - 45.0) < 0.5,
          f"|d|={abs(d):.4f}, angle={np.degrees(np.angle(d)):+.2f} deg")


def main():
    test_extraction()
    test_spectrum()
    test_evm()
    test_phase()
    print()
    if fails:
        print(f"{len(fails)} FAILED: " + ", ".join(fails))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
