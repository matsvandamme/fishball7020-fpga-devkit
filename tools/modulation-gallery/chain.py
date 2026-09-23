#!/usr/bin/env python3
"""The receive chain, designed so nothing folds into the answer.

Rates, and why:

  HackRF 16 MSPS, analog filter 12 MHz  span +-8 MHz, analog stopband begins at
                                        +-6 MHz, so the fold point at +-8 MHz is
                                        already 2 MHz into the analog stopband.
  offset tuning, +4.8 MHz               the receiver's own DC spike lands 4.8 MHz
                                        from the signal, not on top of it. The
                                        sign matters as much as the size: see
                                        below.
  digital LPF, pass 2.0 / stop 2.6 MHz  120 dB stopband, designed here rather
                                        than inherited.
  decimate by 2 -> 8 MSPS               output Nyquist is +-4 MHz while the
                                        signal has been filtered to +-2 MHz, so
                                        the decimation has 2 MHz of pure margin.

The anti-alias rule this follows is stopband_edge <= fs_out - f_pass: with
fs_out 8 MHz and f_pass 2 MHz that allows a stopband edge up to 6 MHz, and 2.6
MHz is far tighter than required. The widest signal in the set occupies 1.625
MHz, so it is entirely inside the passband.

Why the receiver tunes ABOVE the transmitter, not below
-------------------------------------------------------
A direct-conversion receiver makes second-order products: a strong input at
baseband offset d appears again at 2d. There is a strong carrier at 864.0 MHz in
this room, and with the receiver 3.5 MHz BELOW a 866.5 MHz transmission it sat at
+1.0 MHz baseband, putting its product at +2.0 MHz baseband - which is 865.0 MHz,
exactly 1.5 MHz below the signal, in the skirt where it is most visible. It was
the sharp peak in every spectrum of the first run.

The product always lands at 2*carrier - LO, so it is the RECEIVER's tuning that
decides where it falls, not the transmitter's. Tuning above instead of below
moves it to 858.0 MHz, 8.5 MHz away, where the digital filter removes it: measured,
-1.5 MHz drops from 21.5 dB above the noise floor to 2.3 dB, which is nothing.

That it is a product and not a signal was established by retuning: it appears at
exactly twice the carrier's baseband offset at every tuning tried, so it moves at
twice the rate and in the same direction, which no real signal does. See
spurhunt.py, band.py and ip2.py.
"""
import numpy as np
from scipy.signal import firwin, kaiserord, lfilter, freqz

HACK_FS   = 16_000_000
HACK_BW   = 12_000_000
OFFSET    = -4_800_000        # receiver ABOVE the board - see below
WORK_FS   = 8_000_000
DECIM     = HACK_FS // WORK_FS
F_PASS    = 2_000_000
F_STOP    = 2_600_000
ATT_DB    = 120


def aa_taps(fs=HACK_FS, fpass=F_PASS, fstop=F_STOP, att=ATT_DB):
    """A Kaiser-windowed low-pass with a specified stopband depth."""
    width = (fstop - fpass) / (fs / 2)
    ntaps, beta = kaiserord(att, width)
    ntaps |= 1
    cutoff = (fpass + fstop) / 2
    return firwin(ntaps, cutoff, window=("kaiser", beta), fs=fs)


TAPS = aa_taps()


def receive(x, fs=HACK_FS, offset=OFFSET, decim=DECIM):
    """Offset-tuned capture -> baseband at WORK_FS, DC artefact filtered out."""
    n = np.arange(len(x))
    y = x * np.exp(-2j * np.pi * offset * n / fs)
    y = lfilter(TAPS, [1.0], y)
    g = (len(TAPS) - 1) // 2                      # remove the filter's own delay
    y = y[g:]
    return y[::decim].astype(np.complex64), fs / decim


def describe():
    w, h = freqz(TAPS, worN=1 << 16, fs=HACK_FS)
    hdb = 20 * np.log10(np.abs(h) + 1e-30)
    passripple = hdb[w <= F_PASS].ptp()
    stop = hdb[w >= F_STOP].max()
    # What actually matters: attenuation at the frequency that would fold to DC
    fold = WORK_FS - 0            # energy at +-8 MHz folds onto 0 after decimation
    at_fold = hdb[np.argmin(np.abs(w - fold))]
    # freqz returns positive frequencies; the filter is symmetric, so a
    # negative offset must be looked up at its magnitude or it reads as DC.
    at_dcspike = hdb[np.argmin(np.abs(w - abs(OFFSET)))]
    return dict(ntaps=len(TAPS), pass_ripple_db=passripple, stopband_db=stop,
                at_fold_db=at_fold, at_dcspike_db=at_dcspike)


if __name__ == "__main__":
    d = describe()
    print(f"  anti-alias filter: {d['ntaps']} taps")
    print(f"  passband ripple (0-{F_PASS/1e6:.1f} MHz): {d['pass_ripple_db']:.3f} dB")
    print(f"  stopband (>{F_STOP/1e6:.1f} MHz):          {d['stopband_db']:.1f} dB")
    print(f"  at the fold frequency {WORK_FS/1e6:.0f} MHz:    {d['at_fold_db']:.1f} dB")
    print(f"  at the receiver's DC spike ({OFFSET/1e6:.1f} MHz): {d['at_dcspike_db']:.1f} dB")


def self_test():
    """Push a signal plus a huge out-of-band interferer through the real chain."""
    ok = True
    fs, n = HACK_FS, 1 << 19
    t = np.arange(n) / fs
    sig = 0.05 * np.exp(2j * np.pi * (OFFSET + 400e3) * t)      # wanted, small
    dc  = 0.60 * np.ones(n)                                     # DC spike, huge
    fold = 0.30 * np.exp(2j * np.pi * (OFFSET + 8e6) * t)       # would fold to DC
    x = (sig + dc + fold).astype(np.complex64)
    y, fs2 = receive(x)
    import dsp
    f, p, _ = dsp.hi_dr_psd(y, fs2, nfft=32768)
    want = p[np.abs(f - 400e3) < 20e3].max()
    rest = p[(np.abs(f - 400e3) > 60e3)].max()
    print(f"  wanted tone            {want:8.1f} dBFS")
    print(f"  worst everything else  {rest:8.1f} dBFS")
    print(f"  -> interferers 12x and 6x the wanted signal suppressed by {want - rest:.1f} dB")
    ok &= (want - rest) > 70
    print("  ->", "chain rejects out-of-band energy" if ok else "ALIASING NOT CONTROLLED")
    return ok
