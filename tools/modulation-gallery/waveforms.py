#!/usr/bin/env python3
"""The signal set: simple, moderate and complex, all cyclic-seamless.

Every waveform is generated to be PERIODIC over its buffer length, because the
board transmits from a cyclic DMA buffer that wraps forever. A waveform whose
end does not join its beginning sprays a burst of spurs across the whole span
once per wrap, and that seam then gets measured as if it were the modulation.

The pulse shaping is therefore done with CIRCULAR convolution (multiply in the
frequency domain) rather than a running filter: the filter's tail wraps into its
own head, so the buffer is periodic by construction.
"""
import numpy as np

FS = 4_000_000            # board TX sample rate
NSYM = 16384              # symbols per buffer for the 1 Msym/s set
SPS = 4                   # samples per symbol -> 1 Msym/s
N = NSYM * SPS            # 65536 samples per buffer
RRC_A = 0.35


def _rng(seed):
    return np.random.default_rng(seed)


def rrc(alpha, sps, span_sym):
    """Root-raised-cosine taps, with the two removable singularities handled."""
    n = np.arange(-span_sym * sps / 2, span_sym * sps / 2 + 1)
    t = n / sps
    h = np.empty_like(t, dtype=float)
    for i, ti in enumerate(t):
        if abs(ti) < 1e-12:
            h[i] = 1 - alpha + 4 * alpha / np.pi
        elif abs(abs(ti) - 1 / (4 * alpha)) < 1e-12:
            h[i] = alpha / np.sqrt(2) * (
                (1 + 2 / np.pi) * np.sin(np.pi / (4 * alpha))
                - (1 - 2 / np.pi) * np.cos(np.pi / (4 * alpha)))
        else:
            num = (np.sin(np.pi * ti * (1 - alpha))
                   + 4 * alpha * ti * np.cos(np.pi * ti * (1 + alpha)))
            den = np.pi * ti * (1 - (4 * alpha * ti) ** 2)
            h[i] = num / den
    return h / np.sqrt((h ** 2).sum())


def circ_shape(symbols, sps, taps):
    """Upsample and pulse-shape with circular convolution, so the result is
    exactly periodic over len(symbols)*sps samples."""
    n = len(symbols) * sps
    up = np.zeros(n, dtype=complex)
    up[::sps] = symbols
    H = np.fft.fft(taps, n)
    return np.fft.ifft(np.fft.fft(up) * H) * np.exp(0j)


def _norm(x):
    return x / np.abs(x).max()


def circ_interp(x, osr):
    """Interpolate by an integer factor while staying exactly periodic.

    Zero-padding the spectrum is the periodic form of interpolation: the output
    is the unique band-limited signal through the input samples, and it wraps
    seamlessly. scipy's resample_poly runs an FIR that does not wrap, which
    leaves a discontinuity at the buffer seam - measured here as a 15.6 dB rise
    in the noise floor when the buffer is repeated, which is exactly what the
    board's cyclic DMA would then transmit once per wrap.
    """
    m = len(x)
    X = np.fft.fft(x)
    Y = np.zeros(m * osr, dtype=complex)
    h = m // 2
    Y[:h] = X[:h]
    Y[-(m - h):] = X[h:]
    return np.fft.ifft(Y) * osr


# --- simple -----------------------------------------------------------------

def cw(offset_hz=600_000, n=N, fs=FS):
    """A single tone on an exact bin, so the wrap is perfectly continuous."""
    k = round(offset_hz * n / fs)
    x = np.exp(2j * np.pi * k * np.arange(n) / n)
    return _norm(x), dict(kind="cw", tone_hz=k * fs / n, sps=None)


def ook(baud=250_000, n=N, fs=FS, seed=3):
    """On-off keying: the whole message is in the envelope. RRC-shaped so the
    spectrum is bounded - rectangular OOK has sinc skirts that never end."""
    sps = int(round(fs / baud))
    nsym = n // sps
    bits = _rng(seed).integers(0, 2, nsym)
    sym = bits.astype(complex)
    x = circ_shape(sym, sps, rrc(0.5, sps, 12))
    return _norm(x), dict(kind="ook", baud=fs / sps, sps=sps, bits=bits, sym=sym)


def fsk2(baud=250_000, dev_hz=250_000, n=N, fs=FS, seed=4):
    """Continuous-phase 2-FSK. The deviation and the buffer length are chosen so
    the accumulated phase closes on a multiple of 2*pi, which is what makes the
    cyclic wrap seamless for a phase-continuous modulation."""
    sps = int(round(fs / baud))
    nsym = n // sps
    rng = _rng(seed)
    bits = rng.integers(0, 2, nsym)
    # Force an equal number of +1 and -1 symbols: the net phase then returns to 0.
    half = nsym // 2
    bits = np.concatenate([np.ones(half, int), np.zeros(nsym - half, int)])
    rng.shuffle(bits)
    d = np.repeat(2 * bits - 1, sps)
    ph = 2 * np.pi * dev_hz * np.cumsum(d) / fs
    x = np.exp(1j * (ph - ph[0]))
    return _norm(x), dict(kind="fsk2", baud=fs / sps, sps=sps, dev_hz=dev_hz, bits=bits)


# --- moderate ---------------------------------------------------------------

def _qam(order, nsym, seed):
    m = int(np.sqrt(order))
    rng = _rng(seed)
    if order == 2:                                   # BPSK
        s = 2 * rng.integers(0, 2, nsym) - 1.0
        return s.astype(complex), None
    if order == 4:                                   # QPSK
        a = 2 * rng.integers(0, 2, nsym) - 1.0
        b = 2 * rng.integers(0, 2, nsym) - 1.0
        return (a + 1j * b) / np.sqrt(2), None
    lev = np.arange(-(m - 1), m, 2, dtype=float)
    i = rng.choice(lev, nsym); q = rng.choice(lev, nsym)
    s = i + 1j * q
    return s / np.sqrt((np.abs(s) ** 2).mean()), lev


def linear(order, nsym=NSYM, sps=SPS, alpha=RRC_A, fs=FS, seed=7):
    """BPSK / QPSK / 16-QAM / 64-QAM with RRC shaping."""
    sym, lev = _qam(order, nsym, seed)
    taps = rrc(alpha, sps, 12)
    x = circ_shape(sym, sps, taps)
    name = {2: "bpsk", 4: "qpsk", 16: "qam16", 64: "qam64"}[order]
    return _norm(x), dict(kind=name, order=order, sym=sym, sps=sps, alpha=alpha,
                          baud=fs / sps, taps=taps, levels=lev)


def gmsk(baud=1_000_000, bt=0.3, n=N, fs=FS, seed=11):
    """GMSK: constant envelope, so the PA can be driven hard. Gaussian-filtered
    MSK, the modulation GSM used."""
    sps = int(round(fs / baud))
    nsym = n // sps
    rng = _rng(seed)
    half = nsym // 2
    bits = np.concatenate([np.ones(half, int), np.zeros(nsym - half, int)])
    rng.shuffle(bits)
    d = 2 * bits - 1.0
    # Gaussian pulse, circularly applied to the symbol stream
    span = 4
    t = np.arange(-span * sps, span * sps + 1) / sps
    sigma = np.sqrt(np.log(2)) / (2 * np.pi * bt)
    g = np.exp(-t ** 2 / (2 * sigma ** 2)); g /= g.sum()
    up = np.zeros(n); up[::sps] = d
    G = np.fft.fft(g, n)
    freq = np.real(np.fft.ifft(np.fft.fft(up) * G))
    ph = np.pi / 2 * np.cumsum(freq)                 # h = 0.5
    x = np.exp(1j * (ph - ph[0]))
    return _norm(x), dict(kind="gmsk", baud=fs / sps, sps=sps, bt=bt, bits=bits)


# --- complex ----------------------------------------------------------------

def ofdm(nfft=128, ncp=32, used=52, nsymb=409, fs=FS, seed=13):
    """An 802.11a-shaped OFDM burst: 52 used carriers with QPSK on each and a
    quarter-length cyclic prefix, on a 128-point FFT so the whole thing occupies
    1.625 MHz and sits clear of every filter edge in the chain. A whole number of OFDM symbols, so the buffer
    is periodic. High PAPR by construction - that is the point of including it."""
    rng = _rng(seed)
    half = used // 2
    idx = np.r_[np.arange(-half, 0), np.arange(1, half + 1)]     # DC left empty
    syms = np.empty((nsymb, used), dtype=complex)
    out = []
    for s in range(nsymb):
        a = (2 * rng.integers(0, 2, used) - 1) + 1j * (2 * rng.integers(0, 2, used) - 1)
        a /= np.sqrt(2)
        syms[s] = a
        X = np.zeros(nfft, dtype=complex)
        X[idx % nfft] = a
        t = np.fft.ifft(X) * nfft / np.sqrt(used)
        out.append(np.r_[t[-ncp:], t])
    x = np.concatenate(out)
    return _norm(x), dict(kind="ofdm", nfft=nfft, ncp=ncp, used=used, idx=idx,
                          nsymb=nsymb, syms=syms, sps=None,
                          scs=fs / nfft, occupied=used * fs / nfft)


def css(sf=9, bw=1_000_000, nsymb=128, fs=FS, seed=17):
    """LoRa-style chirp spread spectrum.

    Each symbol is a linear up-chirp across `bw`, cyclically shifted by the symbol
    value, which is why a spectrogram looks like a staircase of diagonal lines.
    Constant envelope, so the amplifier can be driven hard.

    The shift is applied at the chirp's OWN bandwidth and the result is then
    interpolated up to the transmit rate. That ordering matters: the base chirp
    exp(j2pi(n^2/2N - n/2)) is exactly periodic over N = 2**sf samples, so a
    cyclic shift of it is still a chirp and dechirps to a single tone. Build it
    oversampled and it is no longer periodic, a large shift wraps into a
    DIFFERENT tone, and symbols near the top of the alphabet decode wrong while
    the spectrogram still looks perfect.

    The interpolation is circular (spectral zero-padding) so the buffer the board
    repeats forever has no seam.
    """
    osr = int(round(fs / bw))
    nbase = 1 << sf
    rng = _rng(seed)
    vals = rng.integers(0, nbase, nsymb)
    n = np.arange(nbase)
    base = np.exp(2j * np.pi * (n ** 2 / (2 * nbase) - n / 2))   # exactly periodic
    x_bw = np.concatenate([np.roll(base, -int(v)) for v in vals])
    x = circ_interp(x_bw, osr) if osr > 1 else x_bw
    return _norm(x), dict(kind="css", sf=sf, bw=bw, nsymb=nsymb, vals=vals,
                          nbase=nbase, osr=osr, sps=None, symbol_s=nbase / bw)


SET = [
    ("CW tone",        "simple",   lambda: cw()),
    ("OOK",            "simple",   lambda: ook()),
    ("2-FSK",          "simple",   lambda: fsk2()),
    ("BPSK",           "moderate", lambda: linear(2)),
    ("QPSK",           "moderate", lambda: linear(4)),
    ("GMSK",           "moderate", lambda: gmsk()),
    ("16-QAM",         "complex",  lambda: linear(16)),
    ("64-QAM",         "complex",  lambda: linear(64)),
    ("OFDM 52x QPSK",  "complex",  lambda: ofdm()),
    ("LoRa-style CSS", "complex",  lambda: css()),
]


def self_test():
    """Two properties per waveform: normalised, and genuinely periodic.

    The periodicity test is the one that matters. It compares the spectrum of one
    buffer against the spectrum of four buffers laid end to end. If the wrap is
    discontinuous the seam adds broadband energy that shows up as a rise in the
    noise floor of the concatenated version, so a few tenths of a dB is fine and
    several dB means the seam is being transmitted.
    """
    import dsp
    ok = True
    print(f"  {'waveform':17s} {'samples':>8} {'|x|max':>7} {'PAPR dB':>8} "
          f"{'seam penalty':>13}")
    for name, tier, fn in SET:
        x, meta = fn()
        pk = np.abs(x).max()
        f1, p1 = dsp.psd_density(x, FS, nfft=4096)
        f4, p4 = dsp.psd_density(np.tile(x, 4), FS, nfft=4096)
        # Compare the noise floors away from where the signal lives.
        quiet = p1 < (p1.max() - 35)
        seam = float(np.median(p4[quiet]) - np.median(p1[quiet])) if quiet.sum() > 50 else 0.0
        good = abs(pk - 1.0) < 1e-9 and abs(seam) < 1.0
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {name:12s} {len(x):8d} {pk:7.3f} "
              f"{dsp.papr_db(x):8.2f} {seam:+10.2f} dB")
    print("  ->", "all waveforms normalised and cyclic-seamless" if ok else "PROBLEM")
    return ok


if __name__ == "__main__":
    print("waveforms.py self-test")
    raise SystemExit(0 if self_test() else 1)
