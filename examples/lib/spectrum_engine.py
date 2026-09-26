"""Spectrum, max-hold, and the dynamic range you are actually getting.

This block exists because GNU Radio's stock QT frequency sink takes its FFT
window as a constructor argument and offers no callback to change it. You
cannot switch window while it runs, so you cannot *watch* what the window
costs you - which is the whole lesson of example 01. Doing the transform here
buys three things at once:

  * the window changes while the flowgraph runs,
  * the averaging happens in the POWER domain, where it belongs,
  * the dynamic-range number is computed from the very trace on screen,
    so the picture and the number can never disagree.

That last point is not hypothetical. An earlier tool in this repository scored
a max-hold trace against a noise floor derived from an *averaged* trace, and
reported about 13 dB more dynamic range than the board had. Two traces, two
different noise floors, one number: it was wrong and it looked plausible.
The metric here is taken from one trace only, and `hold` is display-only.

FULL SCALE. gr-iio's fc32 sources hand you samples already normalised, so a
tone at the converter's full scale arrives as amplitude 1.0 - it is NOT raw
converter LSBs. Everything below is therefore dBFS: decibels relative to full
scale, not dBm. There is no calibration to absolute power anywhere in this
repository, and a dBFS figure says nothing about what is at the antenna until
you add one.
"""

import numpy as np
from gnuradio import gr

#: Amplitude of a full-scale tone as gr-iio's fc32 source presents it.
#:
#: Measured rather than assumed, because a wrong guess here shifts every level
#: in this repository's examples by 24 dB and nothing would look broken. The
#: same signal was captured twice back to back, once with `iio_readdev` (raw
#: converter counts) and once through gr-iio's fc32 source: per-component RMS
#: 5.1006 counts against 0.002509, a ratio of 2033. That is 2048 to within the
#: drift between two captures of thermal noise - so gr-iio divides out the
#: 12-bit converter's +/-2048 full scale (see RX_FULL_SCALE in
#: tools/selftest/sdr_selftest.py) and hands you +/-1.0.
FULL_SCALE = 1.0

#: Sidelobe level of each window, for the label in the GUI. The whole point of
#: the control: a rectangular window's first sidelobe is 13 dB down, so a
#: strong carrier smears over everything within a few bins of it and a weak
#: neighbour simply is not there. Blackman-Harris pays about 2 bins of extra
#: width to put that skirt 92 dB down.
SIDELOBES_DB = {'rectangular': -13, 'hann': -31, 'blackman-harris': -92}


def make_window(name, n):
    """One of three windows, by name. numpy only - no scipy dependency."""
    if name == 'rectangular':
        return np.ones(n)
    k = np.arange(n)
    if name == 'hann':
        return 0.5 - 0.5 * np.cos(2 * np.pi * k / n)
    if name == 'blackman-harris':
        a = (0.35875, 0.48829, 0.14128, 0.01168)   # 4-term, -92 dB sidelobes
        return (a[0] - a[1] * np.cos(2 * np.pi * k / n)
                + a[2] * np.cos(4 * np.pi * k / n)
                - a[3] * np.cos(6 * np.pi * k / n))
    raise ValueError('unknown window %r - one of %s'
                     % (name, sorted(SIDELOBES_DB)))


class blk(gr.sync_block):
    """Spectrum + dynamic range

    Takes one complex vector per FFT and produces:

      0  averaged spectrum, dBFS      1  max-hold spectrum, dBFS
      2  dynamic range, dB            3  peak, dBFS
      4  noise floor, dBFS            5  window sidelobe level, dB

    DYNAMIC RANGE here means peak minus noise floor on the averaged trace,
    and 'noise floor' means the `floor_pct` percentile of that same trace.
    That definition is a choice, and the slider exists so you can see it is a
    choice: raise the percentile through a band that is half occupied and the
    'floor' climbs into the signals, because a percentile cannot tell noise
    from traffic. It is honest for a quiet band and optimistic for a busy one.

    AVERAGING is a one-pole IIR on power, p_avg += (p - p_avg) / avg. Averaging
    power is correct and averaging dB is not: dB is logarithmic, so a mean of
    dB values is a geometric mean of powers and biases every noisy bin low.

    FFT SIZE is fixed when the flowgraph starts. It sets the width of this
    block's vector ports, and GNU Radio fixes port widths at construction, so
    no amount of GUI would make it live. Edit the `nfft` variable and re-run.
    """

    def __init__(self, nfft=4096, window='blackman-harris', avg=16,
                 hold=True, floor_pct=10.0):
        gr.sync_block.__init__(
            self, name='Spectrum + dynamic range',
            in_sig=[(np.complex64, nfft)],
            out_sig=[(np.float32, nfft), (np.float32, nfft),
                     np.float32, np.float32, np.float32, np.float32])
        # Deliberately _nfft, not nfft: GRC turns every __init__ argument that
        # is also an instance attribute into a live setter, and a setter for
        # nfft would be a lie - it cannot resize the ports.
        self._nfft = int(nfft)
        self._avg = max(1.0, float(avg))
        self._hold = bool(hold)
        self._floor_pct = float(np.clip(floor_pct, 0.1, 99.9))
        self._acc = None
        self._peak = None
        self._win_name = None
        self.window = window          # property: builds coefficients and norm

    # ---- live controls --------------------------------------------------
    # Properties rather than plain attributes so the window is rebuilt once
    # per change instead of once per FFT, and so the clamping cannot be
    # bypassed by the GUI handing us a value from the edge of a slider.

    @property
    def window(self):
        return self._win_name

    @window.setter
    def window(self, name):
        w = make_window(name, self._nfft)
        self._win_name = name
        self._win = w.astype(np.float32)
        # A window has gain of its own and it has to be divided back out or
        # every level is wrong. Dividing by (sum w)^2 puts a full-scale tone
        # at 0 dBFS for every window, so the traces stay comparable when you
        # switch - which is the only way the control teaches anything.
        self._norm = float(w.sum()) ** 2 * FULL_SCALE ** 2
        self._sidelobe = float(SIDELOBES_DB.get(name, 0))

    @property
    def avg(self):
        return self._avg

    @avg.setter
    def avg(self, v):
        self._avg = max(1.0, float(v))

    @property
    def hold(self):
        return self._hold

    @hold.setter
    def hold(self, v):
        self._hold = bool(v)
        if not self._hold:
            self._peak = None         # unticking the box is also the reset

    @property
    def floor_pct(self):
        return self._floor_pct

    @floor_pct.setter
    def floor_pct(self, v):
        self._floor_pct = float(np.clip(v, 0.1, 99.9))

    # ---- work -----------------------------------------------------------
    def work(self, input_items, output_items):
        x = input_items[0]
        n = len(x)
        for i in range(n):
            spec = np.fft.fftshift(np.fft.fft(x[i] * self._win))
            p = (spec.real ** 2 + spec.imag ** 2) / self._norm

            if self._acc is None or self._acc.shape != p.shape:
                self._acc = p.copy()
            else:
                self._acc += (p - self._acc) / self._avg

            if self._hold:
                self._peak = p.copy() if self._peak is None \
                    else np.maximum(self._peak, p)
            shown = self._peak if self._peak is not None else self._acc

            # 1e-30 keeps an empty bin from becoming -inf and taking the whole
            # display's autoscale with it.
            avg_db = 10.0 * np.log10(self._acc + 1e-30)
            output_items[0][i] = avg_db
            output_items[1][i] = 10.0 * np.log10(shown + 1e-30)

            # Peak and floor from the SAME trace. See the class docstring.
            floor = 10.0 * np.log10(
                np.percentile(self._acc, self._floor_pct) + 1e-30)
            peak = float(avg_db.max())
            output_items[2][i] = peak - floor
            output_items[3][i] = peak
            output_items[4][i] = floor
            output_items[5][i] = self._sidelobe
        return n
