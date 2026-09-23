#!/usr/bin/env python3
"""Does the +-1 MHz pair follow a quarter of the TRANSMIT sample rate?"""
import os, subprocess, sys, numpy as np, dsp
import board as B
HOST = os.environ.get("BOARD", "192.168.2.1")
BLO, RXLO, CH = 866_500_000, 871_300_000, 1

def cap(n=1 << 20):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(RXLO), "--rate", "16e6",
                    "--n", str(n), "--out", "/tmp/f4.cf32", "--lna", "24", "--vga", "24",
                    "--bw", "12e6"], check=True, capture_output=True)
    return np.fromfile("/tmp/f4.cf32", dtype=np.complex64)

b = B.Board(HOST)
try:
    print(f"  {'TX rate':>9} {'fs/4':>8} {'tone':>9} {'at tone-fs/4':>13} {'at tone+fs/4':>13} "
          f"{'dBc':>7} | {'at tone+-1 MHz fixed':>21}")
    for txfs in (4_000_000, 5_000_000, 8_000_000):
        b.configure_tx(BLO, txfs, bw=4_000_000)
        nb = 4096; k = round(600e3 * nb / txfs)
        b.transmit(np.exp(2j * np.pi * k * np.arange(nb) / nb), -16, pair=CH,
                   cyclic=True, scale=0.9)
        x = cap()
        f, p, _ = dsp.hi_dr_psd(x, 16e6, nfft=1 << 16)
        t = BLO + k * txfs / nb - RXLO
        def lv(at, w=40e3):
            m = np.abs(f - at) < w
            return float(p[m].max())
        c = lv(t); lo_, hi_ = lv(t - txfs / 4), lv(t + txfs / 4)
        f1 = max(lv(t - 1e6), lv(t + 1e6))
        print(f"  {txfs/1e6:8.0f}M {txfs/4e6:7.2f}M {c:9.1f} {lo_:13.1f} {hi_:13.1f} "
              f"{max(lo_,hi_)-c:7.1f} | {f1-c:20.1f}")
        b.stop()
finally:
    print("\n  stop:", b.stop()); b.close()
