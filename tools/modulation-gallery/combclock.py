#!/usr/bin/env python3
"""Whose clock is the 8 kHz comb tied to - the board's or the HackRF's?

If the comb belongs to the receiver's sampling it moves when the receiver's
sample rate changes. If it belongs to the transmitter it moves when the
transmit sample rate changes. If it moves with neither, it is a fixed-frequency
source perturbing an oscillator, and the next question is which board it sits on.
"""
import os, subprocess, sys, numpy as np, board as B

HOST = os.environ.get("BOARD", "192.168.2.1")
BLO, RXLO, CH = 866_500_000, 871_300_000, 1

def cap(fs, n):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(RXLO), "--rate", str(fs),
                    "--n", str(n), "--out", "/tmp/cc.cf32", "--lna", "24", "--vga", "24",
                    "--bw", "12e6"], check=True, capture_output=True)
    return np.fromfile("/tmp/cc.cf32", dtype=np.complex64)

def comb(x, fs, guess):
    n = np.arange(len(x))
    F = np.fft.fftshift(np.fft.fft(x[:1 << 16]))
    ax = np.fft.fftshift(np.fft.fftfreq(1 << 16, 1 / fs))
    w0 = np.abs(ax - guess) < 250e3
    f0 = float(ax[w0][np.argmax(np.abs(F[w0]))])
    for st in (3e3, 300., 30., 3., 0.3):
        c = np.arange(f0 - 10 * st, f0 + 10 * st + st, st)
        f0 = c[int(np.argmax([abs(np.sum(x * np.exp(-2j * np.pi * t * n / fs))) for t in c]))]
    y = x * np.exp(-2j * np.pi * f0 * n / fs)
    ph = np.unwrap(np.angle(y)); ph -= np.polyval(np.polyfit(n, ph, 1), n)
    w = np.hanning(len(y))
    P = 20 * np.log10(np.abs(np.fft.rfft(ph * w) * 2 / w.sum()) / 2 + 1e-20)
    f = np.fft.rfftfreq(len(y), 1 / fs)
    k = (f > 20e3) & (f < 120e3)
    ff, pp = f[k], P[k].copy()
    out = []
    for _ in range(9):
        i = int(np.argmax(pp))
        if pp[i] < -60:
            break
        out.append(float(ff[i]))
        pp[np.abs(ff - ff[i]) < 3e3] = -300
    out.sort()
    d = np.diff(out)
    return out, (float(np.median(d)) if len(d) else float("nan"))

b = B.Board(HOST)
try:
    print("== A. change the RECEIVER's sample rate, transmitter fixed at 4 MSPS ==")
    b.configure_tx(BLO, 4_000_000, bw=4_000_000)
    nb = 4096; k = round(600e3 * nb / 4e6)
    b.transmit(np.exp(2j * np.pi * k * np.arange(nb) / nb), -16, pair=CH, cyclic=True, scale=0.9)
    for fs in (12e6, 16e6, 20e6):
        lines, sp = comb(cap(fs, 1 << 20), fs, BLO + k * 4e6 / nb - RXLO)
        print(f"  RX {fs/1e6:4.0f} MSPS  comb spacing {sp/1e3:7.3f} kHz   "
              + " ".join(f"{v/1e3:.1f}" for v in lines[:6]))
    b.stop()

    print("\n== B. change the TRANSMITTER's sample rate, receiver fixed at 16 MSPS ==")
    for txfs in (4_000_000, 5_000_000, 8_000_000):
        b.configure_tx(BLO, txfs, bw=4_000_000)
        nb = 4096; k = round(600e3 * nb / txfs)
        b.transmit(np.exp(2j * np.pi * k * np.arange(nb) / nb), -16, pair=CH,
                   cyclic=True, scale=0.9)
        lines, sp = comb(cap(16e6, 1 << 20), 16e6, BLO + k * txfs / nb - RXLO)
        print(f"  TX {txfs/1e6:4.0f} MSPS  comb spacing {sp/1e3:7.3f} kHz   "
              + " ".join(f"{v/1e3:.1f}" for v in lines[:6]))
        b.stop()
finally:
    print("\n  stop:", b.stop()); b.close()
