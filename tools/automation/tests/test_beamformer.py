#!/usr/bin/env python3
"""The beamformer example's signal processing, on synthetic arrays.

    # run from: tools/automation
    .venv/bin/python tests/test_beamformer.py

No board: each test builds the captures two boards would return (a plane wave
from a known angle, a random LO phase per element, a capture that starts at a
different moment on each board, noise) and checks what examples/beamformer.py
makes of them.
"""
import pathlib
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "examples"))
import beamformer as bf   # noqa: E402

LAMBDA = bf.C / 2.45e9
D = LAMBDA / 2


def scene(rng, angle_deg, lo_phase, boards=2, amplitude=None, offset_hz=None, noise=20.0, leak=None):
    """What `boards` boards record, RX1 and RX2 each, of the beacon arriving from angle_deg."""
    n = boards * 2
    amplitude = np.ones(n) * 600 if amplitude is None else np.asarray(amplitude, float)
    period = np.tile(bf.beacon(), bf.SNAPSHOT // bf.PERIOD + 2)
    geo = np.exp(2j * np.pi * np.arange(n) * D * np.sin(np.radians(angle_deg)) / LAMBDA)
    t = np.arange(bf.SNAPSHOT) / bf.RATE
    out = []
    for b in range(boards):
        start = int(rng.integers(0, bf.PERIOD))           # each board starts recording at its own moment
        chans = []
        for ch in range(2):
            k = 2 * b + ch
            x = amplitude[k] * np.exp(1j * lo_phase[k]) * geo[k] * period[start:start + bf.SNAPSHOT]
            if offset_hz is not None:
                x = x * np.exp(2j * np.pi * offset_hz[b] * t)
            if leak is not None:
                x = x + leak[k] * period[start:start + bf.SNAPSHOT]
            x = x + noise * (rng.standard_normal(bf.SNAPSHOT) + 1j * rng.standard_normal(bf.SNAPSHOT))
            chans.append(x)
        out.append(np.array(chans))
    return out


class Beamformer(unittest.TestCase):
    def setUp(self):
        self.rng = np.random.default_rng(7020)
        self.lo = self.rng.uniform(-np.pi, np.pi, 4)          # every element's LO phase: unknown, fixed per tune
        self.pulse = bf.beacon()

    def calibrated(self, **k):
        ys = [bf.snapshot(scene(self.rng, 0, self.lo, **k), self.pulse)["y"] for _ in range(3)]
        return bf.calibrate(ys, D, LAMBDA)

    def found(self, cal, angle, **k):
        s = bf.snapshot(scene(self.rng, angle, self.lo, **k), self.pulse)
        return float(bf.ANGLES[np.argmax(bf.pattern(s["y"], cal, D, LAMBDA))]), s

    def test_the_beacon_spans_minus_to_plus_2_mhz(self):
        spec = np.abs(np.fft.fftshift(np.fft.fft(bf.beacon()))) ** 2
        f = np.fft.fftshift(np.fft.fftfreq(bf.PERIOD, 1 / bf.RATE))
        inside = spec[np.abs(f) < 1.9e6].sum() / spec.sum()
        self.assertGreater(inside, 0.95)
        self.assertAlmostEqual(spec[f < 0].sum() / spec[f > 0].sum(), 1.0, delta=0.05)   # symmetric about the LO

    def test_finds_the_direction(self):
        cal = self.calibrated()
        for angle in (-60, -25, 0, 10, 45):
            est, _ = self.found(cal, angle)
            self.assertAlmostEqual(est, angle, delta=1.0, msg=f"{angle} deg")

    def test_when_each_board_starts_recording_does_not_matter(self):
        # Every call to scene() starts each board at a new random sample, as two
        # network calls do; the matched filter's peak phase does not move.
        cal = self.calibrated()
        ests = [self.found(cal, 30)[0] for _ in range(5)]
        self.assertLess(max(ests) - min(ests), 1.0)
        self.assertAlmostEqual(np.mean(ests), 30, delta=1.0)

    def test_a_fractional_sample_of_timing_does_not_move_the_phase(self):
        # Two boards' sample instants can sit a fraction of a sample apart. The
        # sweep is symmetric about the LO, so the matched filter's peak stays
        # real near its top and the phase holds; a 0 to +4 MHz sweep would
        # turn by 2 pi x 2 MHz x 0.5 / 15.36 MHz = 23 degrees.
        x = np.tile(bf.beacon(), bf.SNAPSHOT // bf.PERIOD)[None, :] * 600
        f = np.fft.fftfreq(x.shape[1])
        phases = []
        for frac in (0.0, 0.25, 0.5):
            shifted = np.fft.ifft(np.fft.fft(x, axis=1) * np.exp(-2j * np.pi * f * frac), axis=1)
            phases.append(np.angle(bf.snapshot([np.vstack([shifted, shifted])], self.pulse)["y"][0]))
        self.assertLess(np.degrees(np.ptp(np.unwrap(phases))), 2.0)

    def test_without_calibration_the_lo_phases_point_it_wrong(self):
        s = bf.snapshot(scene(self.rng, 30, self.lo), self.pulse)
        est = float(bf.ANGLES[np.argmax(bf.pattern(s["y"], np.ones(4), D, LAMBDA))])
        self.assertGreater(abs(est - 30), 5)

    def test_a_board_on_its_own_reference_fails_the_lock_check(self):
        # 2 ppm apart at 2.45 GHz is 4.9 kHz; even 300 Hz scrambles a capture's periods.
        snaps = [bf.snapshot(scene(self.rng, 0, self.lo, offset_hz=[0, 300]), self.pulse) for _ in range(3)]
        coh = np.min([s["coherence"] for s in snaps], axis=0)
        self.assertTrue(all(coh[:2] > 0.99), coh)
        self.assertTrue(all(coh[2:] < bf.MIN_COHERENCE), coh)

    def test_locked_boards_hold_their_phase(self):
        ys = [bf.snapshot(scene(self.rng, 0, self.lo), self.pulse)["y"] for _ in range(5)]
        self.assertLess(max(bf.phase_spread_deg(ys)), 2.0)
        snaps = [bf.snapshot(scene(self.rng, 0, self.lo), self.pulse) for _ in range(2)]
        self.assertLess(max(abs(o) for s in snaps for o in s["offset_hz"]), 5)

    def test_calibration_is_phase_only(self):
        cal = self.calibrated(amplitude=[600, 190, 600, 400])
        np.testing.assert_allclose(np.abs(cal), 1.0)

    def test_four_elements_buy_about_6_db(self):
        cal = self.calibrated()
        est, s = self.found(cal, 20, noise=200.0)
        gain = bf.beam_snr_db(s["mf"], cal, D, LAMBDA, est) - np.mean(s["snr_db"])
        self.assertAlmostEqual(gain, 10 * np.log10(4), delta=1.0)

    def test_the_leak_is_removed(self):
        leak = np.array([300, 60, 0, 0]) * np.exp(1j * self.rng.uniform(-np.pi, np.pi, 4))
        alone = bf.snapshot(scene(self.rng, 0, self.lo, amplitude=[0, 0, 0, 0], leak=leak), self.pulse)["y"]

        def ys(angle):
            return bf.snapshot(scene(self.rng, angle, self.lo, leak=leak), self.pulse)["y"]
        raw = bf.calibrate([ys(0) for _ in range(3)], D, LAMBDA)
        clean = bf.calibrate([ys(0) - alone for _ in range(3)], D, LAMBDA)
        y = ys(40)
        wrong = float(bf.ANGLES[np.argmax(bf.pattern(y, raw, D, LAMBDA))])
        right = float(bf.ANGLES[np.argmax(bf.pattern(y - alone, clean, D, LAMBDA))])
        self.assertAlmostEqual(right, 40, delta=1.0)
        self.assertGreater(abs(wrong - 40), abs(right - 40))

    def test_the_figures_draw(self):
        cal = self.calibrated()
        rows, scans = [], []
        for angle in (-30, 30):
            est, s = self.found(cal, angle)
            scans.append((f"{angle} deg", bf.pattern(s["y"], cal, D, LAMBDA), est))
            rows.append({"set_deg": angle, "found_deg": est})
        ys = [bf.snapshot(scene(self.rng, 0, self.lo), self.pulse)["y"] for _ in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            for path in (bf.plot_check(["A:RX1", "A:RX2", "B:RX1", "B:RX2"], ys, f"{tmp}/c.svg"),
                         bf.plot_scan(scans, f"{tmp}/s.svg"),
                         bf.plot_emulation(rows, scans, f"{tmp}/e.svg")):
                text = pathlib.Path(path).read_text()
                self.assertTrue(text.startswith("<svg") and text.endswith("</svg>"))
                self.assertIn("prefers-color-scheme", text)


if __name__ == "__main__":
    unittest.main(verbosity=1)
