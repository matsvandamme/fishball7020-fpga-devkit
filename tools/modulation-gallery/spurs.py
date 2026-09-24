#!/usr/bin/env python3
"""Is a spur ADDITIVE or MULTIPLICATIVE? Vary the transmit power and watch.

A spur that grows faster than the carrier is additive and made in the receiver -
second-order distortion of some other signal, for instance. A spur whose ratio
in dBc stays constant is multiplicative: proportional to the carrier.

WHAT THIS DOES NOT DO is say which radio made a multiplicative one. A sideband
that a RECEIVER's local oscillator stamps onto a carrier scales with that
carrier exactly as a transmitter's own sideband does, so a constant dBc ratio is
equally consistent with either radio. This script was once read as proving the
+-1 MHz pair was the board's; a second receiver later showed it 26 dB weaker
through the board than through the HackRF. Use atlas2.py for attribution.
"""
import os, subprocess, sys, json, numpy as np, board as B, chain, dsp
import sys as _s, pathlib as _pl                     # noqa: E402
_s.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from board_addr import resolve as _board             # name first, USB last


HOST, BLO, TONE, CH = _board(), 866_500_000, 600_000, 1

def cap(n=1 << 20):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(BLO - chain.OFFSET),
                    "--rate", str(chain.HACK_FS), "--n", str(n), "--out", "/tmp/s.cf32",
                    "--lna", "24", "--vga", "24", "--bw", str(chain.HACK_BW)],
                   check=True, capture_output=True)
    return np.fromfile("/tmp/s.cf32", dtype=np.complex64)

rows = []
b = B.Board(HOST)
try:
    b.configure_tx(BLO, 4_000_000, bw=4_000_000)
    n = 4096; k = round(TONE * n / 4e6)
    iq = np.exp(2j * np.pi * k * np.arange(n) / n); tone = k * 4e6 / n
    print(f"  tone at {tone/1e3:+.1f} kHz; spurs looked for at tone +-1 MHz (the board's fs/4)\n")
    print(f"  {'atten':>6} {'carrier':>9} {'spur -1MHz':>11} {'spur +1MHz':>11} "
          f"{'worst dBc':>10} {'rx spur -1.5MHz':>16}")
    for atten in (-36, -30, -24, -20, -16):
        b.transmit(iq, atten, pair=CH, cyclic=True, scale=0.9)
        y, fsw = chain.receive(cap())
        f, p, _ = dsp.hi_dr_psd(y, fsw, nfft=1 << 15)
        def peak(fc, w=30e3):
            m = np.abs(f - fc) < w
            return float(p[m].max())
        c = peak(tone)
        lo, hi = peak(tone - 1e6), peak(tone + 1e6)
        rxs = peak(-1.5e6)
        rows.append(dict(atten=atten, carrier=c, spur_lo=lo, spur_hi=hi,
                         worst_dbc=max(lo, hi) - c, rx_spur=rxs))
        print(f"  {atten:6.0f} {c:9.1f} {lo:11.1f} {hi:11.1f} {max(lo,hi)-c:10.1f} {rxs:16.1f}")
        b.stop()
finally:
    print("\n  stop:", b.stop()); b.close()
    json.dump(rows, open("results/spurs.json", "w"), indent=1)
