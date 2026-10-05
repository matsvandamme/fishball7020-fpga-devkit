#!/usr/bin/env python3
"""Stress the AD9361's clocking through the automation server.

    # run from: tools/automation, as: .venv/bin/python examples/clock_stress.py
    # first, after looking at TX1A (it must go through the 20 dB attenuator to RX1A):
    #   ./devkit tx-guard affirm 0

The same test that checked the board after the reference-clock rework, with
no libiio in it: every step is a call to the server on the board.

  A  sample-rate changes, 2.5 to 61.44 MS/s and back, three times: the BBPLL
     relocks after every one
  B  200 RX and TX LO retunes, 70 MHz to 6 GHz: both synthesizers lock each time
  C  a 1 MHz tone on TX1 at -40 dB into the 20 dB loop, received on RX1 at
     433.92, 868 and 2400 MHz: within 1 Hz, worst spur below -55 dBc
  D  the reference, timed for 30 s against the board's own crystal: within 20 ppm

Prints PASS when all four hold and both transmitters end at -89.75 dB.
Bench: TX1 -> 20 dB -> RX1. Needs numpy (in the client's venv).
"""
import argparse
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fishball_automation.client import Fishball, FishballError   # noqa: E402

RATES = [2.5e6, 5e6, 7.68e6, 10e6, 15.36e6, 20e6, 30.72e6, 61.44e6]
TONE_RATE, TONE_HZ, TONE_N = 4_800_000, 1_000_000, 76_800     # 76 800 samples: 16 000 whole cycles
BLOCK = 1 << 18


def note(fails, ok, msg):
    print(("  ok    " if ok else "  FAIL  ") + msg, flush=True)
    if not ok:
        fails.append(msg)


def rates(board, fails):
    print("A. sample-rate changes (BBPLL relock each time)")
    n, bad = 0, []
    for _ in range(3):
        for r in RATES + RATES[::-1]:
            s = board.configure(sample_rate_hz=int(r))
            n += 1
            if s.sample_rate_hz != int(r) or not s.clock.bbpll_locked:
                bad.append(f"{r / 1e6:g} MS/s: read back {s.sample_rate_hz}, BBPLL locked {s.clock.bbpll_locked}")
    for b in bad:
        print("  FAIL  " + b)
    note(fails, not bad, f"{n} rate changes, BBPLL locked after {n - len(bad)}")


def retunes(board, fails):
    print("B. LO retunes, 70 MHz to 6 GHz")
    board.configure(sample_rate_hz=TONE_RATE)
    steps = list(np.geomspace(70e6, 6e9, 80)) + [random.uniform(70e6, 6e9) for _ in range(120)]
    bad = 0
    for f in steps:
        c = board.configure(rx_lo_hz=int(f), tx_lo_hz=int(f)).clock
        if not (c.rx_synth_locked and c.tx_synth_locked):
            bad += 1
            print(f"  FAIL  {f / 1e6:.1f} MHz: RX lock {c.rx_synth_locked}, TX lock {c.tx_synth_locked}")
    note(fails, bad == 0, f"{len(steps)} retunes, RX and TX synthesizers locked after {len(steps) - bad}")


def tones(board, fails, attenuation, pad):
    print(f"C. TX1 -> {pad:g} dB -> RX1 tone, {TONE_RATE / 1e6:g} MS/s, tone 1 MHz above the LO")
    board.configure(sample_rate_hz=TONE_RATE, rx_rf_bandwidth_hz=TONE_RATE, tx_rf_bandwidth_hz=TONE_RATE,
                    rx1_gain_mode="manual", rx1_gain_db=20)
    t = np.arange(TONE_N) / TONE_RATE
    wave = board.upload_waveform(0.5 * 2 ** 15 * np.exp(2j * np.pi * TONE_HZ * t))
    win = np.blackman(BLOCK)
    f = np.fft.fftshift(np.fft.fftfreq(BLOCK, 1 / TONE_RATE))
    df = TONE_RATE / BLOCK
    try:
        for lo in (433_920_000, 868_000_000, 2_400_000_000):
            board.configure(rx_lo_hz=lo, tx_lo_hz=lo)
            info = board.transmit_capture(wave, 4 * BLOCK, tx_channels=[1], rx_channels=[1],
                                          attenuation_db=attenuation, pad_db=pad, settle_s=0.3)
            path = os.path.join(os.environ.get("TMPDIR", "/tmp"), f"clock-stress-{lo}")
            x = board.fetch(info, path).read()[0]
            board.delete(info.id)
            os.unlink(path + ".sigmf-data")
            os.unlink(path + ".sigmf-meta")
            spec = sum(np.abs(np.fft.fftshift(np.fft.fft(x[i * BLOCK:(i + 1) * BLOCK] * win))) ** 2 for i in range(4))
            s = 10 * np.log10(spec / spec.max())
            k = int(np.argmax(s))
            a, b, c = s[k - 1], s[k], s[k + 1]
            peak = f[k] + 0.5 * (a - c) / (a - 2 * b + c) * df          # parabolic interpolation
            near = (np.abs(f - TONE_HZ) < 20e3) | (np.abs(f + TONE_HZ) < 20e3) | (np.abs(f) < 20e3)
            band = np.abs(f) < 0.4 * TONE_RATE
            spur = s[band & ~near].max()
            at = f[band & ~near][np.argmax(s[band & ~near])]
            image = s[np.abs(f + TONE_HZ) < 100].max()
            print(f"  {lo / 1e6:8.2f} MHz: tone {peak - TONE_HZ:+.2f} Hz off, floor {np.median(s):.1f} dBc, "
                  f"worst spur {spur:.1f} dBc at {at / 1e6:+.3f} MHz, image {image:.1f} dBc")
            note(fails, abs(peak - TONE_HZ) < 1 and spur < -55, f"{lo / 1e6:g} MHz: tone exact and clean")
    finally:
        board.delete_waveform(wave)


def reference(board, fails):
    print("D. the reference, timed against the board's own crystal")
    board.configure(sample_rate_hz=20_000_000)
    c = board.clock(measure=True, seconds=30)
    print(f"  reference {c.measured_reference_hz / 1e6:.5f} MHz, {c.measured_ppm:+.1f} ppm over "
          f"{c.measured_seconds:.0f} s; BBPLL {c.bbpll_locked}, RX {c.rx_synth_locked}, TX {c.tx_synth_locked}")
    note(fails, abs(c.measured_ppm) <= 20 and c.bbpll_locked, "reference within 20 ppm of 40 MHz")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("BOARD", "fishball.local"))
    ap.add_argument("--attenuation", type=float, default=-40.0, help="TX1 attenuation for the tones (default -40)")
    ap.add_argument("--pad", type=float, default=20.0, help="the attenuator between TX1 and RX1, in dB (default 20)")
    a = ap.parse_args()
    fails = []
    with Fishball(a.host, timeout=60) as board:
        s = board.status()
        print(f"{s.model}, firmware {s.firmware}, server {s.server_version}")
        try:
            rates(board, fails)
            retunes(board, fails)
            tones(board, fails, a.attenuation, a.pad)
            reference(board, fails)
        except FishballError as e:
            fails.append(str(e))
            print(f"  FAIL  {e.code}: {e}")
        finally:
            board.mute()
            board.configure(sample_rate_hz=30_720_000, rx_lo_hz=2_400_000_000, tx_lo_hz=2_400_000_000,
                            rx1_gain_mode="slow_attack", rx2_gain_mode="slow_attack")
            s = board.status()
            tx = [ch.tx_attenuation_db for ch in s.channels]
        print(f"die {s.ad9361_temp_c:.1f} C; TX1 {tx[0]} dB, TX2 {tx[1]} dB")
        if any(t > -89.5 for t in tx):
            fails.append("a transmitter is not muted at the end")
    print("RESULT:", "PASS" if not fails else f"{len(fails)} FAILURE(S)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
