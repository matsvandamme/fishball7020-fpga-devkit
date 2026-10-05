#!/usr/bin/env python3
"""A receive beamformer across one or more boards: every RX is one element of a line array.

    # run from: tools/automation, as: .venv/bin/python examples/beamformer.py --emulate=-60,-30,0,30,60
    # first, after looking at both transmit ports (each must go through its attenuator):
    #   ./devkit tx-guard affirm 0
    #   ./devkit tx-guard affirm 1

With two boards (--boards a.local,b.local) the array is A:RX1, A:RX2, B:RX1,
B:RX2, in that order, spaced --spacing-mm apart (default half a wavelength).
Both boards must run from ONE reference clock on EXT_CLK, or their phases
drift apart and the lock check says so. Set-up: docs/radio/beamform-two-boards.md.

A beacon, a chirp burst repeating every 0.53 ms, plays on one board's
transmitter (--beacon, default the first board's TX1). Every snapshot plays
it, records every receiver on every board at once, and reduces each receiver
to one complex number: the matched filter's peak, whose phase is the carrier
phase at that element.

  1. The lock check: --check snapshots with nothing moving. Per element: the
     level, the SNR, the frequency offset from the beacon, how coherent the
     beacon stays across a capture, and how far the phase wanders between
     snapshots. Boards on separate references show up here.
  2. Calibration: with the beacon broadside (0 deg), the phase of each element
     relative to the first is recorded; afterwards it is removed.
  3. Scans: the beam is steered from -90 to +90 deg; the peak is the
     direction. Positive angles are towards the last element.

Over the air it is interactive: put the beacon broadside, press Enter, then
move it and press Enter for each scan (q ends). --leak first records what the
beacon board's transmitter leaks into its own receivers, with its antenna
replaced by a 50 ohm load, and removes it from every snapshot.

--emulate needs one board and the bench loops (TX1 -> 20 dB -> RX1,
TX2 -> 30 dB -> RX2): the beacon plays on both transmitters, and a phase step
on TX2 stands in for a wave arriving at each listed angle.

Writes beamformer.csv and SVG figures where you run it. Needs numpy.
Recalibrate after any retune, rate change or reboot: each one gives every
board's LO a new phase.
"""
import argparse
import csv
import math
import os
import sys
import tempfile
import threading

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fishball_automation.client import Fishball, FishballError   # noqa: E402
from svgplot import Panel, write                                  # noqa: E402  (beside this script)

RATE = 15_360_000          # samples per second
PERIOD = 8192              # beacon period, samples (0.53 ms)
PULSE = 1024               # chirp length, samples (67 us)
SPAN = 4e6                 # chirp sweep, -2 to +2 MHz: symmetric about the LO
SNAPSHOT = 1 << 17         # samples per capture: 16 beacon periods
FULL_SCALE = 2048          # a receive sample is 12 bits
C = 299_792_458.0
ANGLES = np.arange(-90.0, 90.05, 0.1)
MIN_COHERENCE = 0.9
MAX_PHASE_STD_DEG = 10.0


# ---- the signal processing: pure functions, tested in tests/test_beamformer.py ----

def beacon():
    """One period of the beacon: a chirp from -2 to +2 MHz, then silence."""
    t = np.arange(PULSE) / RATE
    rate_hz_per_s = SPAN / (PULSE / RATE)
    p = np.zeros(PERIOD, complex)
    p[:PULSE] = np.exp(1j * np.pi * rate_hz_per_s * t ** 2 - 2j * np.pi * (SPAN / 2) * t)
    return p


def snapshot(captures, pulse):
    """Reduce one snapshot to numbers per element.

    captures: one complex array per board, shape (channels, samples), in
    counts. Returns a dict of per-element arrays: y (complex, the matched
    filter's peak averaged over the periods), mf (the averaged matched-filter
    output, shifted so the peak is at index 0), level_dbfs, snr_db,
    offset_hz (the beacon's frequency as each element sees it), coherence
    (|mean| / mean|.| of the per-period peaks: 1 when the element is locked
    to the beacon)."""
    ref = np.conj(np.fft.fft(pulse))
    out = {k: [] for k in ("y", "mf", "level_dbfs", "snr_db", "offset_hz", "coherence")}
    for x in captures:
        n = x.shape[1] // PERIOD
        m = np.fft.ifft(np.fft.fft(x[:, :n * PERIOD].reshape(x.shape[0], n, PERIOD), axis=2) * ref, axis=2)
        k = int(np.argmax(np.abs(m).sum(axis=(0, 1))))       # one peak per board: its channels share a clock
        for ch in range(x.shape[0]):
            z = m[ch, :, k]
            folded = np.roll(m[ch].mean(axis=0), -k)
            noise = np.mean(np.abs(folded[2 * PULSE:PERIOD - 2 * PULSE]) ** 2)
            out["y"].append(z.mean())
            out["mf"].append(folded)
            out["level_dbfs"].append(20 * np.log10(np.abs(z).mean() / PULSE / FULL_SCALE + 1e-30))
            out["snr_db"].append(10 * np.log10(np.abs(folded[0]) ** 2 / (noise + 1e-30)))
            out["offset_hz"].append(np.angle(np.sum(z[1:] * np.conj(z[:-1]))) / (2 * np.pi * PERIOD / RATE))
            out["coherence"].append(np.abs(z.mean()) / (np.abs(z).mean() + 1e-30))
    return {k: np.array(v) for k, v in out.items()}


def steering(n, spacing_m, wavelength_m, angles_deg=ANGLES):
    """Steering vectors, shape (angles, elements): the phase a plane wave from
    each angle puts on each element, relative to the first."""
    x = np.arange(n) * spacing_m
    return np.exp(2j * np.pi * np.outer(np.sin(np.radians(angles_deg)), x) / wavelength_m)


def calibrate(ys, spacing_m, wavelength_m, angle_deg=0.0):
    """The phase correction per element, from snapshots taken with the beacon
    at angle_deg: each element's phase relative to the first, less what the
    geometry puts there. Phase only: a weaker element is not amplified."""
    a = steering(len(ys[0]), spacing_m, wavelength_m, [angle_deg])[0]
    r = sum(y * np.conj(y[0]) / np.abs(y * y[0] + 1e-30) for y in ys)    # averaged unit phasors
    return np.exp(1j * np.angle(r / a))


def pattern(y, cal, spacing_m, wavelength_m):
    """The beam's power against angle, in dB; 0 dB where every element adds in phase."""
    u = y / cal
    a = steering(len(y), spacing_m, wavelength_m)
    p = np.abs(np.conj(a) @ u) ** 2 / np.sum(np.abs(u)) ** 2
    return 10 * np.log10(p + 1e-12)


def beam_snr_db(mf, cal, spacing_m, wavelength_m, angle_deg):
    """SNR of the beam steered to angle_deg, from the per-element matched filter outputs."""
    a = steering(len(cal), spacing_m, wavelength_m, [angle_deg])[0]
    b = (np.conj(a) / cal) @ mf
    noise = np.mean(np.abs(b[2 * PULSE:PERIOD - 2 * PULSE]) ** 2)
    return 10 * np.log10(np.abs(b[0]) ** 2 / (noise + 1e-30))


def phase_spread_deg(ys):
    """Per element: the standard deviation of its phase relative to the first, over snapshots."""
    rel = np.array([np.angle(y * np.conj(y[0])) for y in ys])
    centred = np.angle(np.exp(1j * (rel - np.angle(np.exp(1j * rel).mean(axis=0)))))
    return np.degrees(centred.std(axis=0))


# ---- the boards ----

class Array:
    """The boards as one array: configure them alike, play the beacon, record every receiver at once."""

    def __init__(self, hosts, lo_hz, rx_gain, beacon_at, attenuation, pad):
        self.boards = [Fishball(h, timeout=60) for h in hosts]
        self.hosts, self.attenuation, self.pad = hosts, attenuation, pad
        self.beacon_board, self.beacon_tx = beacon_at
        for b in self.boards:
            b.configure(sample_rate_hz=RATE, rx_rf_bandwidth_hz=RATE, tx_rf_bandwidth_hz=RATE,
                        rx_lo_hz=int(lo_hz), tx_lo_hz=int(lo_hz),
                        rx1_gain_mode="manual", rx1_gain_db=rx_gain, rx2_gain_mode="manual", rx2_gain_db=rx_gain)
        self.waves = {}
        self.tmp = tempfile.TemporaryDirectory()

    def wave(self, tx2_phase=None):
        """The beacon on the beacon's transmitter, or on both with a phase step on TX2."""
        key = None if tx2_phase is None else round(float(tx2_phase), 6)
        if key not in self.waves:
            p = 0.5 * 32767 * beacon()
            iq = p if key is None else np.stack([p, p * np.exp(1j * key)])
            self.waves[key] = self.boards[self.beacon_board].upload_waveform(iq)
        return self.waves[key]

    def take(self, tx2_phase=None, beacon_on=True):
        """One snapshot: the beacon plays while every board records RX1 and RX2."""
        results, errors = [None] * len(self.boards), []

        def record(i):
            try:
                rec = self.boards[i].capture(samples=SNAPSHOT, channels=[1, 2],
                                             path=os.path.join(self.tmp.name, f"b{i}"))
                results[i] = rec.read()
            except Exception as e:      # noqa: BLE001 - reported below, with the board's name
                errors.append(f"{self.hosts[i]}: {e}")

        tx = None
        if beacon_on:
            channels = [self.beacon_tx] if tx2_phase is None else [1, 2]
            tx = self.boards[self.beacon_board].transmit(self.wave(tx2_phase), channels, self.attenuation,
                                                         pad_db=self.pad)
        try:
            threads = [threading.Thread(target=record, args=(i,)) for i in range(len(self.boards))]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        finally:
            if tx is not None:
                tx.stop()                    # mutes, and confirms both transmitters read the floor
        if errors:
            raise FishballError("FAILED_PRECONDITION", "; ".join(errors))
        return results

    def close(self):
        """Mute everything, remove the waveforms, put every board back to its defaults."""
        for i, b in enumerate(self.boards):
            if i == self.beacon_board:
                for w in self.waves.values():
                    try:
                        b.delete_waveform(w)
                    except FishballError:
                        pass
            b.mute()
            b.configure(sample_rate_hz=30_720_000, rx_lo_hz=2_400_000_000, tx_lo_hz=2_400_000_000,
                        rx1_gain_mode="slow_attack", rx2_gain_mode="slow_attack")
        tx = [[ch.tx_attenuation_db for ch in b.status().channels] for b in self.boards]
        self.tmp.cleanup()
        for b in self.boards:
            b.close()
        return tx


# ---- figures ----

def plot_check(names, ys, path, theme="auto"):
    rel = np.degrees(np.array([np.angle(y * np.conj(y[0])) for y in ys]))
    p = Panel("Phase of each element relative to the first, snapshot by snapshot", "snapshot",
              "degrees", ylim=(-180, 180), yticks=[-180, -90, 0, 90, 180], height=200)
    for k in range(1, len(names)):
        p.line(range(1, len(ys) + 1), rel[:, k], names[k], (k - 1) % 4 + 1, markers=True)
    p.note("flat lines: the elements hold their phase; a wandering line: that board is not locked")
    return write(path, [p], theme, title="Lock check")


def _floor(scans):
    """The beam panel's lower limit: the deepest null, within reason."""
    return max(-40.0, 5 * math.floor((min(float(np.min(p)) for _, p, _ in scans) - 2) / 5))


def plot_scan(scans, path, theme="auto", title="Beam patterns"):
    """scans: (label, pattern_db, estimate_deg) per scan."""
    p = Panel("Beam power against steering angle", "steering angle (degrees)", "dB",
              xlim=(-90, 90), ylim=(_floor(scans), 2), xticks=list(range(-90, 91, 30)), height=240)
    for i, (label, pat, est) in enumerate(scans):
        p.line(ANGLES, pat, label, i % 4 + 1, dashed=i >= 4)
    return write(path, [p], theme, title=title)


def plot_emulation(rows, scans, path, theme="auto"):
    beams = Panel("Beam power against steering angle", "steering angle (degrees)", "dB",
                  xlim=(-90, 90), ylim=(_floor(scans), 2), xticks=list(range(-90, 91, 30)), height=220)
    for i, (label, pat, est) in enumerate(scans):
        beams.line(ANGLES, pat, label, i % 4 + 1, dashed=i >= 4)
    found = Panel("Direction found against direction emulated", "emulated (degrees)", "found (degrees)",
                  xlim=(-90, 90), ylim=(-90, 90), xticks=list(range(-90, 91, 30)),
                  yticks=list(range(-90, 91, 30)), height=200)
    found.line([-90, 90], [-90, 90], "exact", 4, dashed=True)
    found.points([r["set_deg"] for r in rows], [r["found_deg"] for r in rows], "found", 1)
    return write(path, [beams, found], theme, title="Emulated directions, one board")


# ---- the run ----

def report(names, snaps):
    """Print the lock check; return (ok, the y of every snapshot)."""
    ys = [s["y"] for s in snaps]
    spread = phase_spread_deg(ys)
    ok = True
    print(f"{'element':>10} {'level':>9} {'SNR':>6} {'offset':>9} {'coherence':>10} {'phase spread':>13}")
    for k, name in enumerate(names):
        lvl = np.mean([s["level_dbfs"][k] for s in snaps])
        snr = np.mean([s["snr_db"][k] for s in snaps])
        off = np.mean([s["offset_hz"][k] for s in snaps])
        coh = min(s["coherence"][k] for s in snaps)
        bad = coh < MIN_COHERENCE or (k and spread[k] > MAX_PHASE_STD_DEG)
        ok &= not bad
        print(f"{name:>10} {lvl:7.1f} dBFS {snr:5.1f} dB {off:+7.1f} Hz {coh:10.3f} "
              f"{'' if k == 0 else f'{spread[k]:9.1f} deg':>13}{'   NOT LOCKED' if bad else ''}")
    return ok, ys


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--boards", default=os.environ.get("BOARD", "fishball.local"),
                    help="the boards, in array order, comma separated (default: one board)")
    ap.add_argument("--lo-mhz", type=float, default=2450.0, help="LO for every board, MHz (default 2450)")
    ap.add_argument("--spacing-mm", type=float, default=0.0,
                    help="element spacing (default: half a wavelength at the LO)")
    ap.add_argument("--beacon", default="1:1", help="BOARD:TX the beacon plays on, counting from 1 (default 1:1)")
    ap.add_argument("--attenuation", type=float, default=-40.0, help="the beacon's TX attenuation, dB (default -40)")
    ap.add_argument("--pad", type=float, default=20.0, help="the attenuator after the beacon's TX, dB (default 20)")
    ap.add_argument("--rx-gain", type=float, default=30.0, help="every receiver, manual gain, dB (default 30)")
    ap.add_argument("--check", type=int, default=5, help="snapshots in the lock check (default 5)")
    ap.add_argument("--leak", action="store_true", help="record the beacon board's own leak first, and remove it")
    ap.add_argument("--emulate", help="one board, bench loops: emulate these angles, e.g. -60,-30,0,30,60")
    a = ap.parse_args()

    hosts = [h.strip() for h in a.boards.split(",") if h.strip()]
    bb, btx = (int(v) for v in a.beacon.split(":"))
    wavelength = C / (a.lo_mhz * 1e6)
    spacing = a.spacing_mm / 1000 if a.spacing_mm else wavelength / 2
    names = [f"{'AB'[i] if len(hosts) > 1 else ''}{':' if len(hosts) > 1 else ''}RX{ch}"
             for i in range(len(hosts)) for ch in (1, 2)]
    if a.emulate and len(hosts) != 1:
        ap.error("--emulate needs exactly one board: it stands TX2's phase in for the angle")

    print(f"{len(names)} elements ({', '.join(names)}), {spacing * 1000:.1f} mm apart, "
          f"LO {a.lo_mhz:g} MHz (wavelength {wavelength * 1000:.1f} mm); beacon on board {bb} TX{btx}")
    arr = Array(hosts, a.lo_mhz * 1e6, a.rx_gain, (bb - 1, btx), a.attenuation, a.pad)
    rows, failed = [], False
    pulse = beacon()
    try:
        leak_y = 0
        if a.leak:
            input("\nLeak: replace the beacon's antenna with a 50 ohm load, then press Enter ")
            leak_y = snapshot(arr.take(), pulse)["y"]
            input("Put the antenna back, then press Enter ")

        def take(**k):
            s = snapshot(arr.take(**k), pulse)
            s["y"] = s["y"] - leak_y
            return s

        if not a.emulate:
            input("\nPut the beacon broadside (0 degrees), in the far field, then press Enter ")
        print(f"\nLock check, {a.check} snapshots, nothing moving:")
        snaps = [take(tx2_phase=0.0 if a.emulate else None) for _ in range(a.check)]
        ok, ys = report(names, snaps)
        plot_check(names, ys, "beamformer-check.svg")
        if not ok:
            failed = True
            print("\nAn element is not locked to the beacon: check every board runs from the same reference "
                  "(docs/radio/beamform-two-boards.md). Stopping before calibration.")
            return 1
        cal = calibrate(ys, spacing, wavelength)
        print("calibrated at 0 degrees: " + ", ".join(f"{n} {np.degrees(np.angle(c)):+.1f} deg"
                                                      for n, c in zip(names, cal)))
        mean_snr = np.mean([s["snr_db"] for s in snaps], axis=0)

        scans = []

        def scan(label, set_deg=None, **k):
            s = take(**k)
            pat = pattern(s["y"], cal, spacing, wavelength)
            est = float(ANGLES[np.argmax(pat)])
            beam = beam_snr_db(s["mf"], cal, spacing, wavelength, est)
            best = float(np.max(s["snr_db"]))
            scans.append((label, pat, est))
            row = {"label": label, "set_deg": set_deg, "found_deg": est, "beam_snr_db": beam,
                   "best_element_snr_db": best, **{f"{n}_snr_db": v for n, v in zip(names, s["snr_db"])}}
            rows.append(row)
            print(f"{label:>12}: found {est:+6.1f} deg"
                  f"{'' if set_deg is None else f' ({est - set_deg:+.1f} from {set_deg:+g})'}; "
                  f"beam SNR {beam:.1f} dB, best single element {best:.1f} dB")

        if a.emulate:
            print("\nEmulated directions (TX2's phase stands in for the angle):")
            for deg in (float(v) for v in a.emulate.split(",")):
                phase = 2 * np.pi * spacing * np.sin(np.radians(deg)) / wavelength
                scan(f"{deg:+g} deg", deg, tx2_phase=phase)
            plot_emulation(rows, scans, "beamformer-emulate.svg")
        else:
            print("\nMove the beacon, then press Enter to find it (q and Enter to stop).")
            n = 0
            while input(f"scan {n + 1}> ").strip().lower() != "q":
                n += 1
                scan(f"scan {n}")
                plot_scan(scans, "beamformer-scans.svg")
        print(f"\nmean SNR per element during the lock check: "
              + ", ".join(f"{n} {v:.1f} dB" for n, v in zip(names, mean_snr)))
    except FishballError as e:
        failed = True
        print(f"\nthe board refused: {e.code}: {e}")
    finally:
        tx = arr.close()
        print("transmitters now: " + "; ".join(f"{h} TX1 {t[0]} dB, TX2 {t[1]} dB" for h, t in zip(hosts, tx)))
        if any(v > -89.5 for t in tx for v in t):
            print("A TRANSMITTER IS NOT MUTED: treat its ports as live")
            failed = True
        if rows:
            with open("beamformer.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            print(f"written to {os.path.abspath('beamformer.csv')}, figures beside it")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
