#!/usr/bin/env python3
"""The board receives a carrier neither radio made. Nothing transmits.

The +-1 MHz pair shows at the same level whichever of the two radios is
transmitting, which fits two stories equally well: it is in the HackRF's
synthesiser (used for both its transmit and its receive), or it is on the
board's 40 MHz reference (and so on the board's transmit oscillator in one
direction and its receive oscillator in the other).

A third-party carrier separates them. If the board's receive oscillator carries
the pair, it will stamp it onto ANY carrier - including the one at 864.0 MHz
that comes from somewhere else in the building. If that carrier comes back
without it, the pair is not the board's, and the HackRF is the only thing left.
"""
import os, numpy as np, board as B, dsp
from iiod_min import mask_for

HOST = os.environ.get("BOARD", "192.168.2.1")
EXT, BRX, RATE = 864_000_000, 862_000_000, 12_288_000

b = B.Board(HOST)
try:
    b.mute()
    try: b.wr(B.PHY, "altvoltage1", "powerdown", 1, out=True)
    except Exception: pass
    b.wr(B.PHY, "voltage0", "sampling_frequency", RATE)
    b.wr(B.PHY, "voltage0", "rf_bandwidth", 10_000_000)
    b.wr(B.PHY, "altvoltage0", "frequency", BRX, out=True)
    b.wr(B.PHY, "altvoltage0", "powerdown", 0, out=True)
    b.wr(B.PHY, "voltage0", "gain_control_mode", "manual")
    did, nch = b.dev[B.RX]
    fs = float(b.rd(B.RX, "voltage0", "sampling_frequency"))
    for gain in (50, 62, 70):
        b.wr(B.PHY, "voltage0", "hardwaregain", gain)
        a = np.array(b.c.read_samples(did, 1 << 19, mask_for([0, 1], nch), nchannels=2), dtype=float)
        x = (a[0::2] + 1j * a[1::2]) / 2048.0
        clip = 100 * float(np.mean(np.abs(x.real) > 0.98))
        n = np.arange(len(x))
        F = np.fft.fftshift(np.fft.fft(x)); ax = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / fs))
        w0 = np.abs(ax - (EXT - BRX)) < 300e3
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
        i = np.argmin(np.abs(f - 1.0e6))
        one = float(P[max(0, i - 5):i + 6].max())
        j = np.argmin(np.abs(f - 1.4e6))
        ctl = float(P[max(0, j - 5):j + 6].max())
        print(f"  RX gain {gain:2d}: carrier {car:6.1f} dBFS at {f0/1e6:+.4f} MHz, "
              f"clip {clip:.3f} %, PM floor {fl:.1f} dBc")
        print(f"      at 1.000 MHz: {one:6.1f} dBc ({one-fl:+.1f} above floor)   "
              f"control at 1.400 MHz: {ctl:6.1f} dBc ({ctl-fl:+.1f})")
finally:
    print("\n  stop:", b.stop()); b.close()
