"""Error vector magnitude, the way a real analyser reports it.

Feed this the recovered symbols - after the matched filter, the symbol
synchroniser and the carrier loop - and it tells you how far they land from
where they should. That single number is what every loop-bandwidth slider in
example 02 is really adjusting, and watching it move is the point.

TWO EVM FIGURES, ON PURPOSE. Port 1 is the error as it arrives. Port 2 is the
error after dividing out ONE complex gain, fitted by least squares across the
block - that is, after correcting a fixed amplitude and a fixed rotation
common to every symbol. A real vector analyser does this equalisation before
quoting a number, and the GAP BETWEEN THE TWO is the useful part: it is the
share of your error that is a static rotation you could have calibrated away,
as opposed to noise you could not. A mistuned carrier loop leaves a large gap.
Thermal noise leaves almost none.

NORMALISATION, because it is easy to get subtly wrong. EVM(rms) divides the
error by the RMS of the REFERENCE SYMBOLS ACTUALLY SENT, not by the ideal
constellation's ensemble RMS, and the measured symbols are scaled so their
mean power matches those same reference symbols. Scaling to the ideal set's
unit power instead looks equivalent and is not: a finite block of a
non-constant-modulus constellation has a sample mean power that differs from 1
by about std(P)/sqrt(n), and that mismatch appears as error. It put a floor of
roughly 0.35% on 16-QAM over 2048 symbols here - small, but it meant a
perfect stream never read zero, and a floor you cannot explain is a floor you
will later mistake for a real impairment. Matching the decided reference makes
a perfect stream read exactly 0.000% at any order.

A PYTHON BLOCK THAT IS TOO SLOW WILL SILENCE YOUR TRANSMITTER. This is not a
style note, it is a measured defect this block used to have. The first version
decided symbols with a brute-force distance matrix - `abs(y[:,None] -
ref[None,:])`, so 2048 by `order` complex values - and it did it on every
single call to work(). At a megasymbol a second that pegged a core, the GNU
Radio scheduler had less left for the transmit thread, buffers were pushed
late, and example 02 logged 40 DAC underflows in 45 seconds while a bare
transmit stream at the same rate and buffer size logged none. Sustained
starvation is worse than untidy: patch 0015 mutes the transmitter after 250 ms
of it, so a slow display block can take your signal off the air entirely.

Two changes fixed it, and both are worth copying into any embedded block:

  * Decide separably. A square QAM grid is the product of two independent
    level sets, so the nearest point is found by quantising the real and
    imaginary parts on their own - O(n) instead of O(n x order), with no
    intermediate matrix. It is not an approximation; it is the same answer.
  * Measure once per bufferful, not on every call. Statistics are recomputed
    when `chunk` new symbols have arrived; in between, work() only rescales its
    input, which is one multiply. That is O(1) amortised per symbol, the same
    order as the rescaling itself, so it costs nothing measurable.

    The first attempt at that throttle used a WALL CLOCK - recompute at most
    every 40 ms, on the grounds that the display only refreshes ten times a
    second. It was wrong, and wrong in the worst way: correct in the live
    flowgraph and silently broken everywhere else. An offline run of the same
    chain finishes in under 40 ms, so the meter measured exactly ONCE, on the
    first bufferful, which is the acquisition transient before the loops have
    locked - and then reported that stale number for every symbol afterwards.
    It read 23% on a stream that was measurably 0.3%, held flat against
    changing SNR, and looked entirely plausible. Counting SAMPLES instead of
    seconds cannot do that: the unit of "recent" for a sample stream is
    samples.

WHAT EVM DOES NOT TELL YOU. It is dimensionless and says nothing about
absolute power. And a receiver listening to a transmitter that shares its own
reference clock - which is exactly what example 02 does on one board - has no
frequency offset to track and no independent phase noise. The figure it
produces is real but flattering; docs/modulation-gallery.md made the same
point when it measured this path with a separate radio instead.
"""

import numpy as np
from gnuradio import gr


def levels(order):
    """The one-dimensional level set of a square QAM, unit mean power.

    A square QAM constellation is this set crossed with itself, which is what
    makes the nearest-point decision separable.
    """
    m = int(round(np.sqrt(order)))
    if m * m != int(order) or m < 2:
        raise ValueError('order must be a square: 4, 16, 64 ...')
    lv = (2 * np.arange(m) - (m - 1)).astype(np.float64)
    # Mean power of the 2-D constellation is 2 * mean(lv**2); dividing the
    # levels by sqrt of that puts the 2-D set at unit mean power.
    return lv / np.sqrt(2.0 * (lv ** 2).mean())


def square_qam(order):
    """Unit-mean-power square QAM points. order 4 is QPSK.

    Gray mapping is irrelevant here: EVM is measured against the nearest point
    in the set, and nothing in this block decodes bits.
    """
    lv = levels(order)
    return (lv[:, None] + 1j * lv[None, :]).ravel().astype(np.complex64)


class blk(gr.sync_block):
    """EVM meter

      in  0  recovered symbols, one per symbol
      out 0  the same symbols, scaled so their RMS matches the reference
      out 1  EVM %, as received
      out 2  EVM %, after removing one complex gain
      out 3  MER dB, from port 1

    Port 0 exists so the constellation display and the number agree: it is the
    stream the EVM was computed from, at the scale the ideal points are drawn
    at, so a cloud that looks tight cannot be reporting 30%.

    ROTATION AMBIGUITY is not corrected and does not need to be. A carrier loop
    locks to a multiple of 90 degrees, and every square QAM constellation maps
    onto itself under those rotations, so the nearest-point decision is
    unaffected. The bits would be wrong; the error vectors are not. Nothing
    here decodes.

    MODULATION ORDER is fixed at construction. GNU Radio's constellation
    modulator takes its constellation object when it is built, and the number
    of bits packed per symbol upstream is fixed too, so no GUI control could
    change the order of a running link. Edit the `order` variable and re-run.
    """

    def __init__(self, order=4, chunk=2048):
        gr.sync_block.__init__(
            self, name='EVM meter',
            in_sig=[np.complex64],
            out_sig=[np.complex64, np.float32, np.float32, np.float32])
        # Underscored: neither is a live control, so GRC must not generate a
        # setter that appears to be one. See the class docstring.
        self._order = int(order)
        self._chunk = max(64, int(chunk))
        self._lv = levels(self._order)
        self._step = float(self._lv[1] - self._lv[0])
        self._buf = np.zeros(0, np.complex64)
        self._last = (0.0, 0.0, 0.0, 1.0)
        self._since = 0          # symbols since the last measurement

    def _decide(self, y):
        """Nearest constellation point for each symbol, separably.

        Exact, not approximate: a square QAM grid is the product of one level
        set with itself, so quantising each axis on its own lands on the same
        point a full search would. O(n) with no n-by-order matrix - see the
        module docstring for what the matrix version cost.
        """
        lo, m = self._lv[0], len(self._lv)
        i = np.clip(np.rint((y.real - lo) / self._step), 0, m - 1).astype(np.intp)
        q = np.clip(np.rint((y.imag - lo) / self._step), 0, m - 1).astype(np.intp)
        return self._lv[i] + 1j * self._lv[q]

    def _measure(self, buf):
        """(evm %, evm % after one complex gain, MER dB, scale) over a block."""
        rms = np.sqrt((np.abs(buf) ** 2).mean())
        if rms <= 0:
            return self._last

        # Decide against the unit-power ideal set first. The scale is not yet
        # exact, but it is within a fraction of a percent - far inside the
        # decision regions - so the decisions are right and can be used to fix
        # the scale properly on the next line.
        ref = self._decide(buf / rms)

        # Power-match the measured symbols to the symbols actually decided,
        # and normalise by those same symbols' RMS. See the module docstring:
        # normalising to the ideal set's unit power instead leaves a floor.
        rref = float(np.sqrt((np.abs(ref) ** 2).mean()))
        if rref <= 0:
            return self._last
        scale = rref / rms
        y = buf * scale

        err = y - ref
        evm = 100.0 * np.sqrt((np.abs(err) ** 2).mean()) / rref

        # One complex tap, least squares: g = <ref, y> / <ref, ref>. Dividing
        # it out removes the amplitude and rotation common to every symbol.
        denom = (np.abs(ref) ** 2).sum()
        g = (np.vdot(ref, y) / denom) if denom > 0 else 1.0 + 0j
        if abs(g) > 1e-9:
            e2 = y / g - ref
            evm_eq = 100.0 * np.sqrt((np.abs(e2) ** 2).mean()) / rref
        else:
            evm_eq = evm

        mer = -20.0 * np.log10(max(evm, 1e-9) / 100.0)
        return float(evm), float(evm_eq), float(mer), float(scale)

    def work(self, input_items, output_items):
        x = input_items[0]
        n = len(x)

        self._buf = np.concatenate([self._buf, x])[-self._chunk:]
        self._since += n

        # Once per bufferful of new symbols - counted in SAMPLES, not seconds.
        # See the module docstring for what a wall clock did here instead.
        if (self._since >= self._chunk
                and len(self._buf) >= self._chunk // 4):
            self._last = self._measure(self._buf)
            self._since = 0
        elif self._last == (0.0, 0.0, 0.0, 1.0) and len(self._buf) >= 64:
            # Nothing measured yet: report something rather than a silent zero.
            self._last = self._measure(self._buf)
        evm, evm_eq, mer, scale = self._last

        # The same scale the measurement used, so the cloud on screen sits
        # exactly where the ideal points are drawn.
        output_items[0][:n] = x * scale
        output_items[1][:n] = evm
        output_items[2][:n] = evm_eq
        output_items[3][:n] = mer
        return n
