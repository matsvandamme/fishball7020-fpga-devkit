"""The phase between two receivers that share one oscillator.

This is the measurement the Fishball7020 can make and a single-channel radio
cannot. RX1 and RX2 sit in one AD9361 behind one LO and one sample clock, so
the phase difference between them is a property of the signal and the cabling
rather than of two drifting clocks. Nothing else in this repository shows it.

AVERAGE THE CORRELATION, NEVER THE ANGLE. The estimate is

    r = mean( x1 * conj(x2) )

and the phase is angle(r) taken AFTER the averaging. Averaging angles is
wrong, and wrong in a way that looks fine: angles wrap at +/-180 degrees, so a
true phase sitting near 180 has samples landing at +179 and -179 that average
to about zero. A signal hard against the wrap point would read as no phase
shift at all. Summing complex numbers has no wrap to fall foul of.

COHERENCE IS WHY YOU CAN BELIEVE THE ANGLE.

    coherence = |mean(x1 conj(x2))| / sqrt( mean|x1|^2 * mean|x2|^2 )

It runs from 0 to 1. Two independent noise streams give a correlation that
random-walks toward zero as it averages, so their angle is a random number
that still displays as confidently as a real one. Near 1 the two inputs are
the same signal and the angle means something; near 0 you are reading noise.
Watch this before believing anything on the dial.

REPEATABLE IS NOT CALIBRATED. Each receive path has its own fixed delay
through its own balun and its own trace, so there is a phase offset that has
nothing to do with what is in the air. `zero` latches the current reading and
subtracts it, which makes subsequent readings relative to that moment - useful
and honest. It does NOT make the angle a direction of arrival. That needs a
splitter, matched cables and a known geometry, and the offset changes with
frequency, so a calibration at 2.4 GHz does not hold at 5 GHz. See
docs/measured-performance.md.
"""

import numpy as np
from gnuradio import gr


class blk(gr.decim_block):
    """RX1/RX2 phase + coherence

      in  0  RX1        in  1  RX2
      out 0  phase difference, degrees, after the zero offset
      out 1  coherence, 0 to 1
      out 2  phase difference, degrees, raw
      out 3  coherence * exp(j * phase) - one point for a polar display

    Decimates by `chunk`: one estimate per chunk input samples, which is what
    a display can use and roughly a thousand times less work than one per
    sample. Port 3 is the neat one - feed it to a constellation sink and you
    have a dial whose ANGLE is the phase and whose RADIUS is how much you
    should trust it. A point pinned to the rim is a real measurement; one
    wandering near the origin is noise wearing the same clothes.
    """

    def __init__(self, chunk=4096, avg=8.0, zero=False):
        gr.decim_block.__init__(
            self, name='RX1/RX2 phase + coherence',
            in_sig=[np.complex64, np.complex64],
            out_sig=[np.float32, np.float32, np.float32, np.complex64],
            decim=int(chunk))
        self._chunk = int(chunk)
        self._avg = max(1.0, float(avg))
        self._zero = bool(zero)
        self._r = None            # running complex correlation
        self._p = 0.0             # running mean power product
        self._offset = 0.0        # latched calibration, radians

    @property
    def avg(self):
        return self._avg

    @avg.setter
    def avg(self, v):
        self._avg = max(1.0, float(v))

    @property
    def zero(self):
        return self._zero

    @zero.setter
    def zero(self, v):
        v = bool(v)
        # Latch on the rising edge only. Holding the box ticked would keep
        # re-zeroing, and the reading would sit at zero no matter what the
        # antennas did - which is a convincing way to measure nothing.
        if v and not self._zero and self._r is not None:
            self._offset = float(np.angle(self._r))
        self._zero = v
        if not v:
            self._offset = 0.0

    def work(self, input_items, output_items):
        a, b = input_items[0], input_items[1]
        n = len(output_items[0])
        for i in range(n):
            s = slice(i * self._chunk, (i + 1) * self._chunk)
            x1, x2 = a[s], b[s]
            r = np.vdot(x2, x1) / self._chunk        # mean(x1 * conj(x2))
            p = float((np.abs(x1) ** 2).mean() * (np.abs(x2) ** 2).mean())

            if self._r is None:
                self._r, self._p = r, p
            else:
                self._r += (r - self._r) / self._avg
                self._p += (p - self._p) / self._avg

            coh = float(np.abs(self._r) / np.sqrt(self._p)) if self._p > 0 else 0.0
            coh = min(coh, 1.0)
            raw = float(np.angle(self._r))
            # Wrap into +/-pi after subtracting the offset, so the display does
            # not jump by 360 when a zeroed reading crosses the boundary.
            cal = (raw - self._offset + np.pi) % (2 * np.pi) - np.pi

            output_items[0][i] = np.degrees(cal)
            output_items[1][i] = coh
            output_items[2][i] = np.degrees(raw)
            output_items[3][i] = coh * np.exp(1j * cal)
        return n
