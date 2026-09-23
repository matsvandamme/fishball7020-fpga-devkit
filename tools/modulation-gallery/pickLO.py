#!/usr/bin/env python3
"""Choose the receiver tuning by measuring, not by arithmetic.

Two constraints bound the search:
  |offset| >= 2.6 MHz  so the receiver's DC artefact lands in the digital
                       filter's stopband;
  |offset| <= 5.1 MHz  so the widest signal (+-0.825 MHz) stays inside the
                       12 MHz analog filter.

Within that, every tuning puts the mixer's second-order products somewhere
different. This measures where, with nothing transmitting, and reports the worst
peak that lands inside the +-2 MHz analysis band.
"""
import subprocess, sys, numpy as np, dsp, chain

BLO = 866.5e6

def cap(freq, n=1 << 19):
    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(freq), "--rate", "16e6",
                    "--n", str(n), "--out", "/tmp/k.cf32", "--lna", "24", "--vga", "24",
                    "--bw", "12e6"], check=True, capture_output=True)
    return np.fromfile("/tmp/k.cf32", dtype=np.complex64)

rows = []
los = list(np.arange(861.4e6, 863.95e6, 0.2e6)) + list(np.arange(869.1e6, 871.75e6, 0.2e6))
for lo in los:
    off = BLO - lo
    y, fsw = chain.receive(cap(lo), offset=off)
    f, p, _ = dsp.hi_dr_psd(y, fsw, nfft=1 << 15)
    band = np.abs(f) < 2.0e6
    fl = float(np.median(p[band]))
    pk = float(p[band].max()); fpk = float(f[band][np.argmax(p[band])])
    # how much of the band is clean: fraction of bins within 6 dB of the floor
    clean = float(np.mean(p[band] < fl + 6))
    rows.append((lo, off, pk - fl, fpk, clean, fl))

rows.sort(key=lambda r: r[2])
print(f"  {'LO (MHz)':>9} {'offset':>8} {'worst peak above floor':>23} {'at (MHz)':>10} "
      f"{'band within 6 dB of floor':>26}")
for lo, off, d, fpk, clean, fl in rows:
    mark = "  <-- cleanest" if (lo, off) == (rows[0][0], rows[0][1]) else ""
    print(f"  {lo/1e6:9.2f} {off/1e6:+8.2f} {d:23.1f} {fpk/1e6:+10.3f} {100*clean:25.1f} %{mark}")
