#!/usr/bin/env python3
"""Is the peak second-order distortion of the 864.0 MHz carrier, made in the mixer?

A direct-conversion receiver with finite second-order intercept turns a strong
input at baseband offset d into a spurious product at 2d. Two falsifiable
predictions follow, and neither is true of a real signal:

  1. Retune the receiver and the product must land at exactly TWICE the
     carrier's new baseband offset - so it moves at twice the rate the carrier
     does, and in the same direction.
  2. It must grow 2 dB for every 1 dB of gain applied BEFORE the mixer (the
     LNA), and 1 dB for every 1 dB applied after it (the VGA).
"""
import subprocess, sys, numpy as np, dsp

CARRIER = 864.0e6

def cap(freq, fs=16e6, lna=32, vga=32, n=1 << 20):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(freq), "--rate", str(fs),
                    "--n", str(n), "--out", "/tmp/i.cf32", "--lna", str(lna),
                    "--vga", str(vga), "--bw", "12e6"], check=True, capture_output=True)
    return np.fromfile("/tmp/i.cf32", dtype=np.complex64)

def lvl(f, p, at, w=50e3):
    m = np.abs(f - at) < w
    return float(p[m].max()) if m.any() else float("nan")

print("== 1. retune: does the product sit at exactly twice the carrier's offset? ==")
print(f"  {'LO (MHz)':>9} {'carrier at':>11} {'level':>8} | {'2x offset':>10} {'level':>8} "
      f"{'above floor':>12} | {'control at 2x+0.4':>18}")
for lo in (862.5e6, 863.0e6, 863.5e6, 864.5e6, 865.0e6):
    x = cap(lo)
    f, p, _ = dsp.hi_dr_psd(x, 16e6, nfft=1 << 16)
    q = (np.abs(f) > 5e6) & (np.abs(f) < 7e6)
    fl = float(np.median(p[q]))
    d = CARRIER - lo
    a, b = lvl(f, p, d), lvl(f, p, 2 * d)
    ctl = lvl(f, p, 2 * d + 400e3)
    print(f"  {lo/1e6:9.2f} {d/1e6:+10.3f} {a:8.1f} | {2*d/1e6:+9.3f} {b:8.1f} {b-fl:12.1f}"
          f" | {ctl-fl:17.1f}")

print("\n== 2. gain: LNA is before the mixer, VGA after it ==")
print(f"  {'change':<26} {'carrier':>9} {'product':>9} {'carrier d':>10} {'product d':>10} {'ratio':>7}")
base = None
for tag, lna, vga in (("LNA 16 / VGA 32", 16, 32), ("LNA 24 / VGA 32", 24, 32),
                      ("LNA 32 / VGA 32", 32, 32), ("LNA 32 / VGA 40", 32, 40),
                      ("LNA 32 / VGA 24", 32, 24)):
    x = cap(863.0e6, lna=lna, vga=vga)
    f, p, _ = dsp.hi_dr_psd(x, 16e6, nfft=1 << 16)
    c, s = lvl(f, p, 1.0e6), lvl(f, p, 2.0e6)
    if base is None:
        base = (c, s)
        print(f"  {tag:<26} {c:9.1f} {s:9.1f} {'(ref)':>10} {'(ref)':>10} {'':>7}")
    else:
        dc, ds = c - base[0], s - base[1]
        print(f"  {tag:<26} {c:9.1f} {s:9.1f} {dc:+10.1f} {ds:+10.1f} "
              f"{(ds/dc if abs(dc) > 0.5 else float('nan')):7.2f}")
