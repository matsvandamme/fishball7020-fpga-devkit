#!/usr/bin/env python3
"""Which oscillator is making the phase-modulation comb - the board's or the HackRF's?

The spurs are pure PM, so an LO is being perturbed. Both radios use fractional-N
synthesisers, whose spurs sit at offsets that depend on the exact frequency
programmed and therefore MOVE when the synthesiser is retuned by a little.

So retune one at a time:
  A: change the board's TX LO, leave the receiver alone.
  B: change the receiver, leave the board alone.
Whichever change moves the comb owns it.
"""
import os, subprocess, sys, numpy as np, board as B, dsp
import sys as _s, pathlib as _pl                     # noqa: E402
_s.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from board_addr import resolve as _board             # name first, USB last


HOST = _board()
FS_TX, TONE, CH = 4_000_000, 600_000, 1

def cap(lo, n=1 << 20):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(lo), "--rate", "16e6",
                    "--n", str(n), "--out", "/tmp/w.cf32", "--lna", "24", "--vga", "24",
                    "--bw", "12e6"], check=True, capture_output=True)
    return np.fromfile("/tmp/w.cf32", dtype=np.complex64)

def pm_lines(x, fs, guess):
    """Lock to the tone and return its phase-modulation sidebands.

    The tone's position in the capture is SIGNED - the receiver is tuned above
    the transmitter here, so it sits at a negative offset. Taking a magnitude
    (which an earlier version did) sends the fine search 8 MHz away from the
    tone, it locks onto noise, and the phase spectrum that follows is nonsense
    that still looks like a list of spurs.
    """
    n = np.arange(len(x))
    # Start from the actual strongest bin near the predicted spot, not the
    # prediction itself, so a small tuning error cannot lose the tone.
    F = np.fft.fftshift(np.fft.fft(x[:1 << 16]))
    ax = np.fft.fftshift(np.fft.fftfreq(1 << 16, 1 / fs))
    win = np.abs(ax - guess) < 200e3
    f0 = float(ax[win][np.argmax(np.abs(F[win]))])
    for st in (3e3, 300., 30., 3., 0.3):
        c = np.arange(f0 - 10 * st, f0 + 10 * st + st, st)
        f0 = c[int(np.argmax([abs(np.sum(x * np.exp(-2j * np.pi * t * n / fs))) for t in c]))]
    y = x * np.exp(-2j * np.pi * f0 * n / fs)
    ph = np.unwrap(np.angle(y)); ph -= np.polyval(np.polyfit(n, ph, 1), n)
    w = np.hanning(len(y))
    P = 20 * np.log10(np.abs(np.fft.rfft(ph * w) * 2 / w.sum()) / 2 + 1e-20)
    f = np.fft.rfftfreq(len(y), 1 / fs)
    keep = (f > 15e3) & (f < 900e3)
    ff, pp = f[keep], P[keep].copy()
    out = []
    for _ in range(8):
        i = int(np.argmax(pp))
        if pp[i] < -80:
            break
        out.append((round(float(ff[i]) / 1e3, 1), round(float(pp[i]), 1)))
        pp[np.abs(ff - ff[i]) < 8e3] = -300
    return sorted(out)

b = B.Board(HOST)
try:
    nb = 4096; k = round(TONE * nb / FS_TX)
    iq = np.exp(2j * np.pi * k * np.arange(nb) / nb)
    for tag, txlo, rxlo in (("baseline      TX 866.5  RX 871.3", 866_500_000, 871_300_000),
                            ("A: TX moved   TX 866.7  RX 871.3", 866_700_000, 871_300_000),
                            ("A: TX moved   TX 867.1  RX 871.3", 867_100_000, 871_300_000),
                            ("B: RX moved   TX 866.5  RX 871.5", 866_500_000, 871_500_000),
                            ("B: RX moved   TX 866.5  RX 871.9", 866_500_000, 871_900_000)):
        b.configure_tx(txlo, FS_TX, bw=4_000_000)
        b.transmit(iq, -16, pair=CH, cyclic=True, scale=0.9)
        x = cap(rxlo)
        guess = txlo + k * FS_TX / nb - rxlo          # signed
        lines = pm_lines(x, 16e6, guess)
        print(f"  {tag}  tone at {guess/1e6:+.4f} MHz")
        print("      PM lines (kHz, dBc): "
              + "  ".join(f"{a}({b_})" for a, b_ in lines))
        b.stop()
finally:
    print("\n  stop:", b.stop()); b.close()
