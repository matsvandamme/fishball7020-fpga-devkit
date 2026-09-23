#!/usr/bin/env python3
"""Survey 858-874 MHz and test whether 865.0 MHz is external. Receiver only."""
import subprocess, sys, numpy as np, dsp

def cap(freq, fs=16e6, lna=32, vga=32, n=1 << 20):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(freq), "--rate", str(fs),
                    "--n", str(n), "--out", "/tmp/b.cf32", "--lna", str(lna),
                    "--vga", str(vga), "--bw", "12e6"], check=True, capture_output=True)
    return np.fromfile("/tmp/b.cf32", dtype=np.complex64)

print("== does 865.000 MHz stay at 865.000 MHz when the receiver is retuned? ==")
print(f"  {'LO (MHz)':>9} {'865.0 sits at':>14} {'level':>9} {'floor':>9} {'above floor':>12}")
for lo in (858e6, 861e6, 863e6, 867e6, 870e6):
    x = cap(lo)
    f, p, _ = dsp.hi_dr_psd(x, 16e6, nfft=1 << 16)
    want = 865.0e6 - lo
    m = np.abs(f - want) < 40e3
    q = (np.abs(f) > 3.5e6) & (np.abs(f) < 6e6)
    fl = float(np.median(p[q]))
    print(f"  {lo/1e6:9.1f} {want/1e6:+13.3f} {p[m].max():9.1f} {fl:9.1f} {p[m].max()-fl:12.1f}")

print("\n== everything persistent between 858 and 874 MHz ==")
allpk = {}
for lo in (862e6, 870e6):
    x = cap(lo)
    f, p, _ = dsp.hi_dr_psd(x, 16e6, nfft=1 << 16)
    keep = (np.abs(f) > 100e3) & (np.abs(f) < 6e6)
    f, p = f[keep], p[keep]
    fl = float(np.median(p))
    pp = p.copy()
    for _ in range(10):
        i = int(np.argmax(pp))
        if pp[i] - fl < 8:
            break
        allpk.setdefault(round((f[i] + lo) / 1e5) / 10, []).append(round(float(p[i]) - fl, 1))
        pp[np.abs(f - f[i]) < 150e3] = -300
print(f"  {'MHz':>9} {'dB above floor (seen from each of two LOs)'}")
for k in sorted(allpk):
    if len(allpk[k]) >= 2:                      # seen from both -> genuinely on air
        print(f"  {k:9.1f}   {allpk[k]}   <- persistent, absolute frequency")
print("  (peaks seen from only one LO setting are listed below; they may be receiver artefacts)")
for k in sorted(allpk):
    if len(allpk[k]) == 1:
        print(f"  {k:9.1f}   {allpk[k]}")
