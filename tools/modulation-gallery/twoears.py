#!/usr/bin/env python3
"""The same transmitted tone, heard by two different receivers.

A spur made in the TRANSMITTER is in the signal and both receivers see it. A
spur made in a RECEIVER's local oscillator is stamped on by that receiver alone.
Comparing the board's own receiver against the HackRF therefore attributes each
one - which the dBc-versus-power test cannot do, because a receiver's LO
sidebands scale with the carrier exactly as a transmitter's do.

The board's RX oscillator is deliberately offset from its TX oscillator: at the
same frequency, a perturbation of the shared 40 MHz reference would appear
identically on both and cancel.
"""
import os, subprocess, sys, numpy as np, board as B
from iiod_min import mask_for

HOST = os.environ.get("BOARD", "192.168.2.1")
TXLO, TXFS, CH = 866_500_000, 8_000_000, 1
BRX, HRX = 864_500_000, 871_300_000

def pm(x, fs, guess):
    n = np.arange(len(x))
    F = np.fft.fftshift(np.fft.fft(x)); ax = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / fs))
    w0 = np.abs(ax - guess) < 300e3
    f0 = float(ax[w0][np.argmax(np.abs(F[w0]))])
    for st in (3e3, 300., 30., 3., 0.3):
        c = np.arange(f0 - 10 * st, f0 + 10 * st + st, st)
        f0 = c[int(np.argmax([abs(np.sum(x * np.exp(-2j * np.pi * t * n / fs))) for t in c]))]
    y = x * np.exp(-2j * np.pi * f0 * n / fs)
    ph = np.unwrap(np.angle(y)); ph -= np.polyval(np.polyfit(n, ph, 1), n)
    w = np.hanning(len(y))
    P = 20 * np.log10(np.abs(np.fft.rfft(ph * w) * 2 / w.sum()) / 2 + 1e-20)
    return f0, np.fft.rfftfreq(len(y), 1 / fs), P

def look(f, P, floor):
    out = {}
    for name, t in (("8 kHz x3", 24e3), ("8 kHz x5", 40e3), ("8 kHz x7", 56e3),
                    ("8 kHz x12", 96e3), ("8 kHz x13", 104e3), ("8 kHz x25", 200e3),
                    ("1.000 MHz", 1.0e6)):
        i = np.argmin(np.abs(f - t))
        v = float(P[max(0, i - 4):i + 5].max())
        out[name] = (v, v - floor)
    return out

b = B.Board(HOST)
try:
    b.configure_tx(TXLO, TXFS, bw=4_000_000)
    nb = 4096; k = round(600e3 * nb / TXFS); tone_bb = k * TXFS / nb
    b.transmit(np.exp(2j * np.pi * k * np.arange(nb) / nb), -10, pair=CH, cyclic=True, scale=0.9)

    # --- the board's own receiver -------------------------------------------
    b.wr(B.PHY, "altvoltage0", "frequency", BRX, out=True)
    b.wr(B.PHY, "altvoltage0", "powerdown", 0, out=True)
    b.wr(B.PHY, "voltage0", "gain_control_mode", "manual")
    b.wr(B.PHY, "voltage0", "hardwaregain", 10)
    did, nch = b.dev[B.RX]
    raw = b.c.read_samples(did, 1 << 19, mask_for([2, 3], nch), nchannels=2)
    a = np.array(raw, dtype=np.float64)
    xb = (a[0::2] + 1j * a[1::2]) / 2048.0
    fsb = float(b.rd(B.RX, "voltage0", "sampling_frequency"))
    f0b, fb, Pb = pm(xb, fsb, TXLO + tone_bb - BRX)
    flb = float(np.median(Pb[(fb > 400e3) & (fb < 800e3)]))

    # --- the HackRF ----------------------------------------------------------
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(HRX), "--rate", "16e6",
                    "--n", str(1 << 21), "--out", "/tmp/t.cf32", "--lna", "24",
                    "--vga", "24", "--bw", "12e6"], check=True, capture_output=True)
    xh = np.fromfile("/tmp/t.cf32", dtype=np.complex64).astype(np.complex128)
    f0h, fh, Ph = pm(xh, 16e6, TXLO + tone_bb - HRX)
    flh = float(np.median(Ph[(fh > 400e3) & (fh < 800e3)]))

    B_, H_ = look(fb, Pb, flb), look(fh, Ph, flh)
    print(f"  board's own RX: tone {f0b/1e6:+.4f} MHz at {fsb/1e6:.3f} MSPS, "
          f"PM floor {flb:.1f} dBc")
    print(f"  HackRF        : tone {f0h/1e6:+.4f} MHz at 16 MSPS, PM floor {flh:.1f} dBc\n")
    print(f"  {'sideband':>11} {'board RX dBc':>14} {'above floor':>12} | "
          f"{'HackRF dBc':>11} {'above floor':>12} | {'difference':>11}")
    for kk in B_:
        (vb, db), (vh, dh) = B_[kk], H_[kk]
        verdict = "receiver" if dh - db > 12 else ("transmitter" if db > 8 and dh > 8 else "-")
        print(f"  {kk:>11} {vb:14.1f} {db:+12.1f} | {vh:11.1f} {dh:+12.1f} | "
              f"{dh-db:+8.1f}  {verdict}")
finally:
    print("\n  stop:", b.stop()); b.close()
