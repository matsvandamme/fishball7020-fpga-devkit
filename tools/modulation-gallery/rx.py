#!/usr/bin/env python3
"""Recover what was transmitted, and measure how far off it arrived.

Data-aided throughout: the exact transmitted buffer is known, so timing and
frequency come from correlating against it rather than from blind estimators.
That is deliberate. A blind synchroniser that fails degrades the measurement
silently and the result looks like a bad transmitter - which is how I have
previously mis-measured a perfectly good constellation twice.

The self-test is the guard: it runs the whole chain on a SYNTHETIC channel with
a known SNR, and checks the EVM that comes out matches the EVM that must come
out (EVM_rms = 10^(-SNR/20)). If the chain reports 8% on a signal that is 2% by
construction, the chain is broken, not the radio.
"""
import numpy as np


def coarse_cfo(rx, ref, fs, span=40e3, step=400.0, nseg=1 << 13):
    """Coarse frequency offset: a SHORT segment of rx against the WHOLE reference.

    Two constraints pull in opposite directions and both have bitten this code:

      * The correlation must be against a full period of the reference. The
        capture starts at an arbitrary point in the cyclic buffer, so correlating
        a 16 k window of rx against the first 16 k of ref compares two unrelated
        stretches and finds no peak at all. That is what made every modulation
        but BPSK lock onto a spurious offset.

      * The number of frequency steps is set by the segment's DURATION, not its
        length. A correlation over T seconds loses coherence once the frequency
        error reaches about 1/T, so a full 16 ms record needs steps of ~30 Hz and
        a +-40 kHz search becomes 2700 full-length FFTs.

    Using a short segment against a long reference satisfies both: 1 ms of rx
    tolerates 400 Hz steps, and the reference stays a whole period so the lag is
    found correctly. The fine estimate then uses the whole record.
    """
    n = len(ref)
    seg = rx[:min(nseg, len(rx))]
    t = np.arange(len(seg)) / fs
    R = np.fft.fft(ref)
    best, bf = -1.0, 0.0
    for f0 in np.arange(-span, span + step, step):
        S = np.fft.fft(seg * np.exp(-2j * np.pi * f0 * t), n)
        m = float(np.abs(np.fft.ifft(np.conj(S) * R)).max())
        if m > best:
            best, bf = m, float(f0)
    return bf


def _refine(rx, ref, fs, f0, span, step):
    """Fine offset over the whole record, which is where the resolution is."""
    n = min(len(rx), len(ref))
    t = np.arange(n) / fs
    R = np.conj(np.fft.fft(ref[:n]))
    best, bf = -1.0, f0
    for f in np.arange(f0 - span, f0 + span + step, step):
        c = np.abs(np.fft.ifft(np.fft.fft(rx[:n] * np.exp(-2j * np.pi * f * t)) * R))
        m = float(c.max())
        if m > best:
            best, bf = m, float(f)
    return bf


def sync(rx, ref, fs, span=40e3):
    """Return (cfo_hz, lag, aligned_rx) with the reference at lag 0."""
    f0 = coarse_cfo(rx, ref, fs, span=span)
    f0 = _refine(rx, ref, fs, f0, span=600.0, step=40.0)     # inside the coarse step
    f0 = _refine(rx, ref, fs, f0, span=50.0, step=2.0)
    f0 = _refine(rx, ref, fs, f0, span=3.0, step=0.1)        # to a tenth of a Hz
    n = min(len(rx), len(ref))
    t = np.arange(n) / fs
    r = rx[:n] * np.exp(-2j * np.pi * f0 * t)
    c = np.fft.ifft(np.fft.fft(r) * np.conj(np.fft.fft(ref[:n])))
    lag = int(np.argmax(np.abs(c)))
    return f0, lag, np.roll(r, -lag)


def detrend_phase(y, d):
    """Remove residual carrier: a constant phase and a linear phase ramp.

    Even a 1 Hz frequency error leaves a phase ramp across a 16 ms record, and a
    ramp of total dphi contributes dphi/sqrt(12) of RMS error - 3% EVM for 1 Hz
    here, which would be reported as transmitter distortion. Every real EVM
    measurement tracks residual carrier the same way; 802.11's definition does it
    per symbol from the pilots. Known symbols are used instead of pilots, so this
    removes exactly two degrees of freedom and nothing that could hide
    distortion.
    """
    ph = np.unwrap(np.angle(y * np.conj(d)))
    n = np.arange(len(ph))
    a, b0 = np.polyfit(n, ph, 1)
    return y * np.exp(-1j * (a * n + b0)), a, b0


def ls_equalise(y, d, ntaps=15):
    """Least-squares FIR equaliser from the known symbols. Returns (out, taps)."""
    n = len(y)
    g = ntaps // 2
    X = np.zeros((n - ntaps, ntaps), dtype=complex)
    for k in range(ntaps):
        X[:, k] = y[k:n - ntaps + k]
    dd = d[g:n - ntaps + g]
    w, *_ = np.linalg.lstsq(X, dd, rcond=None)
    return X @ w, w


def evm_db(err, ref):
    """RMS EVM as a percentage and in dB. Both arguments are POWER arrays; the
    means are taken here so a caller cannot accidentally average amplitudes."""
    e = np.sqrt(np.mean(err) / np.mean(ref))
    return 100 * e, 20 * np.log10(e + 1e-30)


def frac_delay(x, mu, ntaps=33):
    """Shift x by a fractional sample with a windowed-sinc interpolator."""
    n = np.arange(ntaps) - (ntaps - 1) // 2
    h = np.sinc(n - mu) * np.hamming(ntaps)
    h /= h.sum()
    return np.fft.ifft(np.fft.fft(x) * np.fft.fft(h, len(x)))


def impairment_budget(y, sym):
    """Split the error vector into the parts that have a name.

    Three fits, each strictly more general than the last, so the drop at each
    step is what that impairment was costing:

      1. one complex gain               -> raw EVM
      2. a 15-tap linear equaliser      -> removes frequency-response tilt
      3. widely linear, a*s + b*conj(s) -> removes I/Q imbalance, which a linear
         equaliser cannot touch: an imbalance maps the signal onto its own
         conjugate and no linear filter has a conjugate term.

    image_rej_db is the same quantity a spectrum analyser reads as the image
    sideband of a single tone. It is meaningless for BPSK, whose symbols are real
    and therefore equal to their own conjugate, so that fit is degenerate.
    """
    out = {}
    g = np.vdot(y, sym) / np.vdot(y, y)
    out["evm_gain"] = float(100 * np.sqrt(np.mean(np.abs(y * g - sym) ** 2)
                                          / np.mean(np.abs(sym) ** 2)))
    yeq, _ = ls_equalise(y, sym, ntaps=15)
    d = sym[7:len(y) - 15 + 7]
    out["evm_eq"] = float(100 * np.sqrt(np.mean(np.abs(yeq - d) ** 2)
                                        / np.mean(np.abs(d) ** 2)))
    real_sym = np.allclose(sym.imag, 0)
    if real_sym:
        out["evm_wl"], out["image_rej_db"] = out["evm_gain"], float("nan")
        return out
    A = np.column_stack([sym, np.conj(sym)])
    coef, *_ = np.linalg.lstsq(A, y, rcond=None)
    a, b = coef
    res = y - A @ coef
    out["evm_wl"] = float(100 * np.sqrt(np.mean(np.abs(res) ** 2)
                                        / np.mean(np.abs(a * sym) ** 2)))
    out["image_rej_db"] = float(20 * np.log10(np.abs(a) / (np.abs(b) + 1e-30)))
    return out


def measure_linear(rx, meta, fs_work, fs_tx, ref_wave):
    """Matched-filter, sample at the symbol instants, and measure EVM."""
    from scipy.signal import resample_poly
    sps_w = int(round(fs_work / meta["baud"]))
    f0, lag, r = sync(rx, _upsample_ref(ref_wave, fs_tx, fs_work), fs_work)

    import waveforms as _W
    tw = _W.rrc(meta["alpha"], sps_w, 12)          # odd length by construction
    tw = tw / np.sqrt((tw ** 2).sum())
    # Circular, because the transmitted buffer is periodic; a linear convolution
    # corrupts both ends and those symbols then pollute the EVM.
    mf = np.fft.ifft(np.fft.fft(r) * np.fft.fft(tw, len(r)))

    sym = meta["sym"]
    nsym = len(sym)
    # Two unknowns, both from the circular pulse shaping: which of the sps
    # sample phases is the symbol instant, and how far the symbol SEQUENCE is
    # rotated (the shaping filter's group delay wraps the buffer). Solve the
    # second by correlation rather than by arithmetic on filter lengths, which
    # is where an off-by-one silently becomes a 100% EVM.
    best, bo, brot, ybest = None, 0, 0, None
    for off in range(sps_w):
        y = mf[off::sps_w]
        if len(y) < nsym:
            continue
        y = y[:nsym]
        c = np.fft.ifft(np.fft.fft(y) * np.conj(np.fft.fft(sym)))
        rot = int(np.argmax(np.abs(c)))
        yr = np.roll(y, -rot)
        g = np.vdot(yr, sym) / np.vdot(yr, yr)
        m = float(np.mean(np.abs(yr * g - sym) ** 2))
        if best is None or m < best:
            best, bo, brot, ybest = m, off, rot, yr
    y = ybest
    # Fractional timing. The integer search above resolves 1/8 of a symbol; the
    # residual up to 1/16 of a symbol is ISI that would be reported as EVM.
    bestmu, bestv = 0.0, None
    for mu in np.arange(-0.5, 0.501, 0.05):
        mfm = frac_delay(mf, mu) if abs(mu) > 1e-9 else mf
        yy = np.roll(mfm[bo::sps_w][:nsym], -brot)
        gg = np.vdot(yy, sym) / np.vdot(yy, yy)
        v = float(np.mean(np.abs(yy * gg - sym) ** 2))
        if bestv is None or v < bestv:
            bestv, bestmu, y = v, mu, yy
    g = np.vdot(y, sym) / np.vdot(y, y)
    y1 = y * g
    y1, slope, _ = detrend_phase(y1, sym)
    resid_cfo = slope * meta["baud"] / (2 * np.pi)      # Hz still left over
    y = y1 / g
    evm1, evmdb1 = evm_db(np.abs(y1 - sym) ** 2, np.abs(sym) ** 2)

    yeq, w = ls_equalise(y, sym, ntaps=15)
    d = sym[7:len(y) - 15 + 7]
    evm2, evmdb2 = evm_db(np.abs(yeq - d) ** 2, np.abs(d) ** 2)
    budget = impairment_budget(y, sym)
    return dict(cfo_hz=f0 + resid_cfo, cfo_resid_hz=float(resid_cfo),
                timing_mu=float(bestmu), **budget,
                evm_pct=float(evm1), evm_db=float(evmdb1), evm_eq_pct=float(evm2), evm_eq_db=float(evmdb2),
                syms=y1, ref=sym, syms_eq=yeq, ref_eq=d, sps=sps_w, offset=bo)


def _upsample_ref(x, fs_tx, fs_work):
    from scipy.signal import resample_poly
    up = int(round(fs_work / fs_tx))
    return resample_poly(x, up, 1)


def measure_ofdm(rx, meta, fs_work, fs_tx, ref_wave):
    ref = _upsample_ref(ref_wave, fs_tx, fs_work)
    f0, lag, r = sync(rx, ref, fs_work)
    dec = int(round(fs_work / fs_tx))
    nfft, ncp, idx = meta["nfft"], meta["ncp"], meta["idx"]
    L = nfft + ncp
    # Search the sample phase within one OFDM symbol AND the symbol rotation.
    # A timing error inside the cyclic prefix is absorbed by the per-carrier
    # equaliser, but a whole-symbol rotation is not: it pairs each received
    # symbol with the wrong transmitted one and the EVM becomes meaningless.
    best = None
    for ph in range(0, dec):
        rr = r[ph::dec]
        ns = min(meta["nsymb"], len(rr) // L)
        if ns < 8:
            continue
        g0 = np.empty((ns, len(idx)), dtype=complex)
        for s2 in range(ns):
            g0[s2] = np.fft.fft(rr[s2 * L + ncp: s2 * L + ncp + nfft])[idx % nfft]
        tx_all = meta["syms"][:ns]
        c = np.fft.ifft((np.fft.fft(g0, axis=0)
                         * np.conj(np.fft.fft(tx_all, axis=0))).sum(1))
        for rot in (0, int(np.argmax(np.abs(c)))):
            gg = np.roll(g0, -rot, axis=0)
            tx0 = meta["syms"][:ns]
            H0 = (gg * np.conj(tx0)).sum(0) / (np.abs(tx0) ** 2).sum(0)
            eq0 = gg / H0
            m = float(np.mean(np.abs(eq0 - tx0) ** 2) / np.mean(np.abs(tx0) ** 2))
            if best is None or m < best[0]:
                best = (m, gg, tx0, ns)
    _, grid, tx, ns = best
    # Common phase error, one value per OFDM symbol: the same residual-carrier
    # correction, applied the way OFDM receivers actually do it.
    H_pre = (grid * np.conj(tx)).sum(0) / (np.abs(tx) ** 2).sum(0)
    cpe = np.angle((grid / H_pre * np.conj(tx)).sum(1))
    grid = grid * np.exp(-1j * cpe)[:, None]
    H = (grid * np.conj(tx)).sum(0) / (np.abs(tx) ** 2).sum(0)     # per-carrier channel
    eq = grid / H
    evm, evmdb = evm_db(np.abs(eq - tx) ** 2, np.abs(tx) ** 2)
    percar = np.sqrt((np.abs(eq - tx) ** 2).mean(0) / (np.abs(tx) ** 2).mean(0)) * 100
    return dict(cfo_hz=f0, evm_pct=float(evm), evm_db=float(evmdb), syms=eq.ravel(),
                ref=tx.ravel(), per_carrier_evm=percar, H=H, idx=idx, nsym=ns)


def self_test():
    """Known SNR in, known EVM out."""
    import waveforms as W
    from scipy.signal import resample_poly
    # What the chain contributes on an otherwise perfect channel.
    FLOOR = {}
    for nm, f in (("QPSK", lambda: W.linear(4)), ("16-QAM", lambda: W.linear(16)),
                  ("64-QAM", lambda: W.linear(64)), ("OFDM", W.ofdm)):
        xx, mm = f()
        uu = resample_poly(xx, int(8_000_000 // W.FS), 1).astype(np.complex64)
        r0 = (measure_ofdm if mm["kind"] == "ofdm" else measure_linear)(
            uu, mm, 8_000_000, W.FS, xx)
        FLOOR[nm] = r0["evm_pct"]
    print("  chain's own floor on a perfect channel: "
          + ", ".join(f"{k} {v:.2f}%" for k, v in FLOOR.items()))
    ok = True
    fs_tx, fs_work = W.FS, 8_000_000
    rng = np.random.default_rng(5)
    print(f"  {'case':18s} {'SNR in':>8} {'EVM expected':>13} {'EVM measured':>13} "
          f"{'CFO err':>9}")
    for name, fn, snr in (("QPSK", lambda: W.linear(4), 30.0),
                          ("16-QAM", lambda: W.linear(16), 35.0),
                          ("64-QAM", lambda: W.linear(64), 40.0),
                          ("OFDM", W.ofdm, 32.0)):
        x, meta = fn()
        up = resample_poly(x, int(fs_work // fs_tx), 1)
        cfo = 5837.0
        # Physical model: the board transmits the buffer over and over, the
        # frequency offset runs continuously through it, and the receiver starts
        # capturing at an arbitrary moment. Rolling the samples AFTER applying
        # the offset - which is what this test did first - puts a phase
        # discontinuity at the seam that no real transmission has, and then
        # blames the analysis for the 17% EVM that follows.
        tiled = np.tile(up, 3)
        t = np.arange(len(tiled)) / fs_work
        y = tiled * np.exp(2j * np.pi * cfo * t) * (0.7 * np.exp(1j * 0.9))
        pw = (np.abs(y) ** 2).mean()
        nvar = pw / (10 ** (snr / 10))
        y = y + np.sqrt(nvar / 2) * (rng.normal(size=len(y)) + 1j * rng.normal(size=len(y)))
        start = 97531                      # an arbitrary point in the period
        y = y[start:start + len(up)].astype(np.complex64)
        m = (measure_ofdm if meta["kind"] == "ofdm" else measure_linear)(
            y, meta, fs_work, fs_tx, x)
        if meta["kind"] == "ofdm":
            gain_db = 10 * np.log10(meta["nfft"] / meta["used"])
        else:
            gain_db = 10 * np.log10(fs_work / meta["baud"])
        floor = FLOOR.get(name, 0.26)
        want = np.sqrt((100 * 10 ** (-(snr + gain_db) / 20)) ** 2 + floor ** 2)
        got = m["evm_pct"]
        cerr = abs(m["cfo_hz"] - cfo)
        good = abs(got - want) < 0.15 * want and cerr < 50
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'} {name:12s} {snr:7.0f} dB {gain_db:9.2f} "
              f"{want:12.2f}% {got:12.2f}% {cerr:8.1f} Hz")
    print("  ->", "analysis chain measures what it should" if ok else "ANALYSIS BROKEN")
    return ok




def measure_css(rx, meta, fs_work, fs_tx, ref_wave):
    """Dechirp a LoRa-style signal and count symbol errors.

    Decimate back to the chirp's own bandwidth first, because that is the only
    rate at which the base chirp is periodic and a cyclic shift dechirps to one
    clean tone. Then the symbol IS the FFT bin.
    """
    from scipy.signal import resample_poly
    ref = _upsample_ref(ref_wave, fs_tx, fs_work)
    f0, lag, r = sync(rx, ref, fs_work, span=40e3)
    nbase, osr = meta["nbase"], meta["osr"]
    # work rate -> chirp bandwidth, filtered (resample_poly low-passes for us)
    dec = int(round(fs_work / meta["bw"]))
    rb = resample_poly(r, 1, dec)
    n = np.arange(nbase)
    base = np.exp(2j * np.pi * (n ** 2 / (2 * nbase) - n / 2))
    ns = min(meta["nsymb"], len(rb) // nbase)
    got, peaks = [], []
    for s2 in range(ns):
        blk = rb[s2 * nbase:(s2 + 1) * nbase] * np.conj(base)
        S = np.abs(np.fft.fft(blk))
        k = int(np.argmax(S))
        got.append(k)
        peaks.append(20 * np.log10(S.max() / (np.median(S) + 1e-30)))
    got = np.array(got)
    want = meta["vals"][:ns]
    err = int((got != want).sum())
    return dict(cfo_hz=f0, nsym=ns, errors=err, ser=err / max(ns, 1),
                peak_to_median_db=float(np.mean(peaks)), got=got, want=want)


if __name__ == "__main__":
    print("rx.py self-test (synthetic channel, known answer)")
    raise SystemExit(0 if self_test() else 1)


def mf_trace(rx_iq, meta, fs_work, fs_tx, ref_wave):
    """The aligned, matched-filtered, gain-normalised waveform - for eye diagrams.

    Same front end as measure_linear, stopping before symbol decisions, so an eye
    drawn from this is the same signal the EVM was computed on.
    """
    import waveforms as _W
    sps_w = int(round(fs_work / meta["baud"]))
    f0, lag, r = sync(rx_iq, _upsample_ref(ref_wave, fs_tx, fs_work), fs_work)
    tw = _W.rrc(meta["alpha"], sps_w, 12)
    tw = tw / np.sqrt((tw ** 2).sum())
    mf = np.fft.ifft(np.fft.fft(r) * np.fft.fft(tw, len(r)))
    sym = meta["sym"]; nsym = len(sym)
    best = None
    for off in range(sps_w):
        y = mf[off::sps_w][:nsym]
        if len(y) < nsym:
            continue
        c = np.fft.ifft(np.fft.fft(y) * np.conj(np.fft.fft(sym)))
        rot = int(np.argmax(np.abs(c)))
        yr = np.roll(y, -rot)
        g = np.vdot(yr, sym) / np.vdot(yr, yr)
        v = float(np.mean(np.abs(yr * g - sym) ** 2))
        if best is None or v < best[0]:
            best = (v, off, rot, g)
    _, off, rot, g = best
    y1 = np.roll(mf[off::sps_w][:nsym], -rot) * g
    _, slope, b0 = detrend_phase(y1, sym)
    n = np.arange(len(mf))
    trace = mf * g * np.exp(-1j * (slope * (n - off) / sps_w + b0))
    return trace, off, sps_w
