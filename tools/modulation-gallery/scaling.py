#!/usr/bin/env python3
"""Does the 1 MHz pair scale with the BOARD's oscillator frequency?

A perturbation of the board's 40 MHz reference reaches the local oscillator
multiplied by N = f_LO / 40 MHz, so its phase deviation grows with frequency:
from 865 MHz to 2448 MHz is 20*log10(2448/865) = +9.0 dB. A spur belonging to
the HackRF has no reason to follow the BOARD's multiplier at all.

The HackRF transmits and the board receives in both cases, so the board's
receive oscillator is the only one whose multiplier changes in the way the
reference hypothesis predicts.
"""
import os, subprocess, sys, time, threading, numpy as np, board as B, dsp
from iiod_min import mask_for
import sys as _s, pathlib as _pl                     # noqa: E402
_s.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from board_addr import resolve as _board             # name first, USB last


HOST = _board()
RATE = 12_288_000

def run(htx, brx, tag):
    b = B.Board(HOST)
    try:
        b.mute()
        try: b.wr(B.PHY, "altvoltage1", "powerdown", 1, out=True)
        except Exception: pass
        b.wr(B.PHY, "voltage0", "sampling_frequency", RATE)
        b.wr(B.PHY, "voltage0", "rf_bandwidth", 10_000_000)
        b.wr(B.PHY, "altvoltage0", "frequency", brx, out=True)
        b.wr(B.PHY, "altvoltage0", "powerdown", 0, out=True)
        b.wr(B.PHY, "voltage0", "gain_control_mode", "manual")
        b.wr(B.PHY, "voltage0", "hardwaregain", 60)
        did, nch = b.dev[B.RX]
        fs = float(b.rd(B.RX, "voltage0", "sampling_frequency"))
        t = threading.Thread(target=lambda: subprocess.run(
            [sys.executable, "hackrf_tx.py", "--freq", str(htx), "--rate", "8e6",
             "--tone", "1e6", "--secs", "12", "--vga", "44", "--amp", "14"],
            capture_output=True))
        t.start(); time.sleep(2.5)
        a = np.array(b.c.read_samples(did, 1 << 19, mask_for([0, 1], nch), nchannels=2), dtype=float)
        t.join()
        x = (a[0::2] + 1j * a[1::2]) / 2048.0
        clip = 100 * float(np.mean(np.abs(x.real) > 0.98))
        n = np.arange(len(x))
        F = np.fft.fftshift(np.fft.fft(x)); ax = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / fs))
        w0 = np.abs(ax - (htx + 1e6 - brx)) < 500e3
        f0 = float(ax[w0][np.argmax(np.abs(F[w0]))])
        for st in (3e3, 300., 30., 3., 0.3):
            c = np.arange(f0 - 10 * st, f0 + 10 * st + st, st)
            f0 = c[int(np.argmax([abs(np.sum(x * np.exp(-2j * np.pi * v * n / fs))) for v in c]))]
        y = x * np.exp(-2j * np.pi * f0 * n / fs)
        ph = np.unwrap(np.angle(y)); ph -= np.polyval(np.polyfit(n, ph, 1), n)
        w = np.hanning(len(y))
        P = 20 * np.log10(np.abs(np.fft.rfft(ph * w) * 2 / w.sum()) / 2 + 1e-20)
        f = np.fft.rfftfreq(len(y), 1 / fs)
        fl = float(np.median(P[(f > 1.3e6) & (f < 1.9e6)]))
        fq, pq, _ = dsp.hi_dr_psd(x, fs, nfft=1 << 15)
        car = float(pq[np.abs(fq - f0) < 50e3].max())
        i = np.argmin(np.abs(f - 1.0e6)); one = float(P[max(0, i-5):i+6].max())
        j = np.argmin(np.abs(f - 1.4e6)); ctl = float(P[max(0, j-5):j+6].max())
        print(f"  {tag}: carrier {car:.1f} dBFS, clip {clip:.3f} %, PM floor {fl:.1f} dBc")
        print(f"      1.000 MHz {one:6.1f} dBc ({one-fl:+.1f} above floor) | "
              f"control 1.400 MHz {ctl:6.1f} dBc ({ctl-fl:+.1f})")
        return one, fl
    finally:
        b.stop(); b.close()

a1 = run(866_500_000, 865_000_000, "board RX at  865 MHz (N=21.6)")
print()
a2 = run(2_449_000_000, 2_448_000_000, "board RX at 2448 MHz (N=61.2)")
print(f"\n  reference hypothesis predicts +9.0 dB; measured {a2[0]-a1[0]:+.1f} dB")
