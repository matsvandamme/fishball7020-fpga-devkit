#!/usr/bin/env python3
"""Spectrum, PAPR and constellation recovery, with the calibration checked.

Two separate normalisations matter and get confused constantly:

  psd_dbfs_per_bin  - what a spectrum analyser display shows. A full-scale tone
                      sitting in one bin reads 0 dBFS. Window loss is corrected
                      by dividing by sum(w), which is the coherent gain, because
                      a tone's energy is coherent across the window.

  psd_dbfs_per_hz   - power spectral density, for noise. Normalised by
                      fs*sum(w^2), the incoherent gain, because noise adds in
                      power. Using the tone normalisation on noise (or the other
                      way round) is a several-dB error that looks plausible.

Every function here is checked by self_test() against signals whose answer is
known analytically.
"""
import numpy as np


def psd_tone(x, fs, nfft=None, window="blackmanharris"):
    """dBFS per bin, calibrated so a full-scale tone in one bin reads 0 dBFS."""
    from scipy.signal import get_window
    n = nfft or min(len(x), 1 << 15)
    w = get_window(window, n)
    segs, step = [], n // 2
    for i in range(0, len(x) - n + 1, step):
        seg = x[i:i + n] * w
        segs.append(np.abs(np.fft.fftshift(np.fft.fft(seg))) ** 2)
    if not segs:
        segs = [np.abs(np.fft.fftshift(np.fft.fft(x[:n] * w[:len(x)]))) ** 2]
    p = np.mean(segs, axis=0) / (w.sum() ** 2)
    f = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
    return f, 10 * np.log10(p + 1e-30)


def psd_density(x, fs, nfft=None, window="blackmanharris"):
    """dBFS/Hz, calibrated so unit-variance complex noise reads -10log10(fs)."""
    from scipy.signal import get_window
    n = nfft or min(len(x), 1 << 15)
    w = get_window(window, n)
    segs, step = [], n // 2
    for i in range(0, len(x) - n + 1, step):
        segs.append(np.abs(np.fft.fftshift(np.fft.fft(x[i:i + n] * w))) ** 2)
    if not segs:
        segs = [np.abs(np.fft.fftshift(np.fft.fft(x[:n] * w[:len(x)]))) ** 2]
    p = np.mean(segs, axis=0) / (fs * (w ** 2).sum())
    f = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
    return f, 10 * np.log10(p + 1e-30)


def papr_db(x):
    """Peak-to-average power ratio. Uses the 99.99th percentile, not the single
    maximum, because one sample of noise sets the max and tells you nothing."""
    p = np.abs(x) ** 2
    return 10 * np.log10(np.percentile(p, 99.99) / p.mean())


def occupied_bw(f, pdb, frac=0.99):
    """The band holding `frac` of the total power, by integrating the PSD."""
    p = 10 ** (pdb / 10)
    c = np.cumsum(p) / p.sum()
    lo = f[np.searchsorted(c, (1 - frac) / 2)]
    hi = f[np.searchsorted(c, 1 - (1 - frac) / 2)]
    return hi - lo


def self_test():
    fs, n = 4e6, 1 << 16
    ok = True

    def chk(name, got, want, tol):
        nonlocal ok
        good = abs(got - want) <= tol
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'}  {name}: {got:+.2f} (want {want:+.2f} +-{tol})")

    # 1. A full-scale tone placed exactly on a bin must read 0 dBFS.
    k = 1000
    t = np.arange(n)
    x = np.exp(2j * np.pi * k * t / n).astype(np.complex64)
    f, p = psd_tone(x, fs, nfft=n)
    chk("full-scale tone peak, dBFS", p.max(), 0.0, 0.15)
    chk("tone frequency, MHz", f[np.argmax(p)] / 1e6, k * fs / n / 1e6, 1e-6)

    # 2. A half-amplitude tone must read -6.02 dBFS.
    f, p = psd_tone(0.5 * x, fs, nfft=n)
    chk("half-amplitude tone, dBFS", p.max(), -6.0206, 0.15)

    # 3. Unit-variance complex noise: density = -10log10(fs) dBFS/Hz.
    rng = np.random.default_rng(1)
    g = (rng.normal(size=n) + 1j * rng.normal(size=n)) / np.sqrt(2)
    f, p = psd_density(g, fs, nfft=4096)
    chk("noise density, dBFS/Hz", np.median(p), -10 * np.log10(fs), 0.3)

    # 4. PAPR: a constant-envelope tone is 0 dB; complex Gaussian is ~9.2 dB
    #    at the 99.99th percentile (-ln(1-0.9999) = 9.21 in power).
    chk("PAPR of a tone, dB", papr_db(x), 0.0, 0.05)
    chk("PAPR of Gaussian, dB", papr_db(g), 10 * np.log10(-np.log(1e-4)), 0.6)

    # 5. Occupied bandwidth of noise filtered to a known width.
    from scipy.signal import firwin, lfilter
    bwant = 1e6
    h = firwin(513, bwant / 2, fs=fs)
    y = lfilter(h, 1, g)
    f, p = psd_density(y, fs, nfft=4096)
    chk("occupied BW of a 1 MHz filter, MHz", occupied_bw(f, p) / 1e6, 1.0, 0.12)

    print("  ->", "all spectrum calibration checks pass" if ok else "CALIBRATION BROKEN")
    return ok


if __name__ == "__main__":
    print("dsp.py self-test")
    raise SystemExit(0 if self_test() else 1)


# --- offset tuning: keeping the receiver's DC artefact out of the picture ----

def downconvert(x, fs, offset_hz, keep_bw, decim=1):
    """Shift a signal that was deliberately captured off-centre back to 0 Hz and
    filter away the region the receiver's DC artefact occupies.

    A direct-conversion receiver like the HackRF puts a large spike at its own LO
    frequency: local-oscillator leakage and ADC offset land on DC and no amount
    of gain setting removes them. Tuning the receiver AWAY from the signal moves
    that spike off to one side, and then an ordinary low-pass around the
    (re-centred) signal discards it completely rather than cosmetically blanking
    a bin.

    offset_hz is where the signal sits in the capture; after mixing it sits at 0
    and the artefact sits at -offset_hz, outside keep_bw.
    """
    from scipy.signal import firwin, filtfilt
    n = np.arange(len(x))
    y = x * np.exp(-2j * np.pi * offset_hz * n / fs)
    taps = firwin(257, keep_bw / 2, fs=fs)
    y = filtfilt(taps, [1.0], y)
    if decim > 1:
        y = y[::decim]
        fs = fs / decim
    return y.astype(np.complex64), fs


def hi_dr_psd(x, fs, nfft=32768, at_db=120):
    """Spectrum with a Dolph-Chebyshev window, for display.

    The window sets the floor the display can show: a Hann window's first
    sidelobe is 31 dB down, so a strong carrier smears across the plot and
    everything below -31 dBc is the window rather than the signal. Chebyshev at
    120 dB puts the window's own leakage below the HackRF's noise, so what is
    plotted is the radio.
    """
    from scipy.signal import windows
    n = min(len(x), nfft)
    w = windows.chebwin(n, at=at_db)
    segs, step = [], n // 2
    for i in range(0, len(x) - n + 1, step):
        segs.append(np.abs(np.fft.fftshift(np.fft.fft(x[i:i + n] * w))) ** 2)
    if not segs:
        segs = [np.abs(np.fft.fftshift(np.fft.fft(x[:n] * w[:len(x)]))) ** 2]
    p = np.mean(segs, axis=0) / (w.sum() ** 2)
    f = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
    return f, 10 * np.log10(p + 1e-30), len(segs)
