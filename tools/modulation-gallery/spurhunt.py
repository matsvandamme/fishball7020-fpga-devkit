#!/usr/bin/env python3
"""What is the peak 1.5 MHz below centre? Diagnosed with the transmitter off.

Three hypotheses, each with a different signature:

  external signal   fixed ABSOLUTE frequency; its baseband offset moves 1:1 when
                    the receiver is retuned.
  LO-related spur   fixed BASEBAND offset; retuning moves its absolute frequency
                    1:1 and its baseband offset not at all.
  clock/ADC spur    baseband offset is a fixed FRACTION of the sample rate, so it
                    scales when fs changes and is unaffected by retuning.

Nothing is transmitted, so this is purely a receiver question.
"""
import subprocess, sys, numpy as np, dsp

def cap(freq, fs, lna=24, vga=24, n=1 << 19):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(freq), "--rate", str(fs),
                    "--n", str(n), "--out", "/tmp/sh.cf32", "--lna", str(lna),
                    "--vga", str(vga), "--bw", str(min(fs * 0.75, 28e6))],
                   check=True, capture_output=True)
    return np.fromfile("/tmp/sh.cf32", dtype=np.complex64)

def peaks(x, fs, n=6):
    f, p, _ = dsp.hi_dr_psd(x, fs, nfft=1 << 15)
    keep = np.abs(f) > 60e3                      # ignore the DC artefact itself
    f, p = f[keep], p[keep]
    out, pp = [], p.copy()
    for _ in range(n):
        i = int(np.argmax(pp))
        out.append((float(f[i]), float(pp[i])))
        pp[np.abs(f - f[i]) < 120e3] = -300
    return out

print("== A. retune the receiver, sample rate fixed at 16 MSPS ==")
print(f"  {'LO (MHz)':>9} {'strongest baseband peaks: offset MHz (dBFS)'}")
A = []
for lo in (857e6, 860e6, 863e6, 866e6, 869e6):
    x = cap(lo, 16e6)
    pk = peaks(x, 16e6, 4)
    A.append((lo, pk))
    print(f"  {lo/1e6:9.1f}  " + "   ".join(f"{a/1e6:+.3f} ({b:6.1f})" for a, b in pk))

print("\n== B. change the sample rate, receiver fixed at 863.0 MHz ==")
print(f"  {'fs (MSPS)':>10} {'strongest baseband peaks: offset MHz (dBFS)':<52} {'offset/fs'}")
for fs in (8e6, 10e6, 12e6, 16e6, 20e6):
    x = cap(863e6, fs)
    pk = peaks(x, fs, 3)
    s = "   ".join(f"{a/1e6:+.3f} ({b:6.1f})" for a, b in pk)
    print(f"  {fs/1e6:10.0f}  {s:<52} " + " ".join(f"{a/fs:+.4f}" for a, _ in pk))

print("\n== C. does it scale with receiver gain, like a real signal would? ==")
print(f"  {'LNA':>4} {'VGA':>4} {'peak at +2.0 MHz':>17} {'noise floor':>12} {'peak-floor':>11}")
for lna, vga in ((8, 8), (16, 16), (24, 24), (32, 32), (40, 40)):
    x = cap(863e6, 16e6, lna, vga)
    f, p, _ = dsp.hi_dr_psd(x, 16e6, nfft=1 << 15)
    m = np.abs(f - 2.0e6) < 60e3
    q = (np.abs(f) > 3e6) & (np.abs(f) < 6e6)
    print(f"  {lna:4d} {vga:4d} {p[m].max():17.1f} {np.median(p[q]):12.1f} "
          f"{p[m].max()-np.median(p[q]):11.1f}")
