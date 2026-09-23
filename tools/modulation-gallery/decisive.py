#!/usr/bin/env python3
"""The HackRF transmits, the board receives on RX1. Nothing is shared.

This is the measurement the board-loopback could not be. There, the board's
transmit and receive synthesisers came from one 40 MHz reference and a
perturbation OF that reference cancelled by about 53 dB. Here the transmitter is
the HackRF and the receiver is the board: two references, no cancellation.

  comb present  -> it is in the HackRF's synthesiser (its TX and RX share one)
                   OR in the board's RX oscillator, i.e. the board's reference.
                   Still two possibilities, but both are now measurable.
  comb absent   -> it is in neither of those, which leaves something specific to
                   the HackRF's RECEIVE path.
"""
import os, subprocess, sys, time, threading, numpy as np, board as B, dsp
from iiod_min import mask_for

HOST = os.environ.get("BOARD", "192.168.2.1")
HTX_LO, TONE, BRX, RATE = 866_500_000, 1_000_000, 865_000_000, 12_288_000

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
    b.wr(B.PHY, "voltage0", "hardwaregain", 52)
    did, nch = b.dev[B.RX]
    fs = float(b.rd(B.RX, "voltage0", "sampling_frequency"))

    t = threading.Thread(target=lambda: subprocess.run(
        [sys.executable, "hackrf_tx.py", "--freq", str(HTX_LO), "--rate", "8e6",
         "--tone", str(TONE), "--secs", "12", "--vga", "44"], capture_output=True))
    t.start(); time.sleep(2.5)
    a = np.array(b.c.read_samples(did, 1 << 19, mask_for([0, 1], nch), nchannels=2), dtype=float)
    t.join()
    x = (a[0::2] + 1j * a[1::2]) / 2048.0
    clip = 100 * float(np.mean(np.abs(x.real) > 0.98))

    n = np.arange(len(x))
    F = np.fft.fftshift(np.fft.fft(x)); ax = np.fft.fftshift(np.fft.fftfreq(len(x), 1 / fs))
    w0 = np.abs(ax - (HTX_LO + TONE - BRX)) < 400e3
    f0 = float(ax[w0][np.argmax(np.abs(F[w0]))])
    for st in (3e3, 300., 30., 3., 0.3):
        c = np.arange(f0 - 10 * st, f0 + 10 * st + st, st)
        f0 = c[int(np.argmax([abs(np.sum(x * np.exp(-2j * np.pi * v * n / fs))) for v in c]))]
    y = x * np.exp(-2j * np.pi * f0 * n / fs)
    amp = np.abs(y); am = amp / amp.mean() - 1.0
    ph = np.unwrap(np.angle(y)); ph -= np.polyval(np.polyfit(n, ph, 1), n)
    w = np.hanning(len(y))
    def sp(v):
        return 20 * np.log10(np.abs(np.fft.rfft(v * w) * 2 / w.sum()) / 2 + 1e-20)
    P, A = sp(ph), sp(am)
    f = np.fft.rfftfreq(len(y), 1 / fs)
    fl = float(np.median(P[(f > 300e3) & (f < 700e3)]))
    fq, pq, _ = dsp.hi_dr_psd(x, fs, nfft=1 << 15)
    car = float(pq[np.abs(fq - f0) < 50e3].max())
    print(f"  HackRF's tone received by the board at {f0/1e6:+.4f} MHz, {car:.1f} dBFS, "
          f"clipping {clip:.3f} %")
    print(f"  PM floor {fl:.1f} dBc   (need about -58 to see a -48 dBc comb)\n")
    print(f"  {'offset':>12} {'PM dBc':>9} {'AM dBc':>9} {'above PM floor':>16}")
    got = []
    for name, t_ in (("8 kHz x3", 24e3), ("8 kHz x4", 32e3), ("8 kHz x5", 40e3),
                     ("8 kHz x6", 48e3), ("8 kHz x7", 56e3), ("8 kHz x8", 64e3),
                     ("8 kHz x12", 96e3), ("8 kHz x13", 104e3), ("8 kHz x25", 200e3),
                     ("1.000 MHz", 1.0e6)):
        i = np.argmin(np.abs(f - t_)); j = np.argmin(np.abs(f - t_))
        v = float(P[max(0, i - 4):i + 5].max()); va = float(A[max(0, j - 4):j + 5].max())
        got.append(v - fl)
        print(f"  {name:>12} {v:9.1f} {va:9.1f} {v-fl:+16.1f}")
    print(f"\n  median of the 8 kHz lines: {np.median(got[:-1]):+.1f} dB above the PM floor")
finally:
    print("\n  stop:", b.stop()); b.close()
