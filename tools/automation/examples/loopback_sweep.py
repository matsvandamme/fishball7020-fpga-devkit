#!/usr/bin/env python3
"""Sweep both TX -> RX loopbacks across frequency, and write what each one measured.

    # run from: tools/automation, as: .venv/bin/python examples/loopback_sweep.py
    # first, after looking at both transmit ports (each must go through its attenuator):
    #   ./devkit tx-guard affirm 0
    #   ./devkit tx-guard affirm 1

At each frequency, one TransmitCapture call plays a tone 1 MHz above the LO on
TX1 and TX2 together, records RX1 and RX2 while it plays, and mutes. From each
receiver's spectrum the script reads:

  level   the tone, in dBFS (0 dBFS is a full-scale receive sample)
  image   the tone's mirror, 1 MHz below the LO, relative to the tone: IQ balance
  LO      what sits on the LO itself, relative to the tone: carrier leakage
  spur    the largest other component in the band, relative to the tone

It prints a row per frequency, then writes them all to a CSV file in the
directory you run it from. Both transmitters end muted; if they do not, it
says so and exits non-zero.

Bench: TX1 -> 20 dB -> RX1 and TX2 -> 30 dB -> RX2, so RX2 reads about 10 dB
lower than RX1. Needs numpy (in the client's venv).
"""
import argparse
import csv
import os
import sys
import tempfile
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from fishball_automation.client import Fishball, FishballError   # noqa: E402

RATE = 4_800_000                    # samples per second, shared by TX and RX
TONE_HZ = 1_000_000                 # the tone's offset from the LO
TONE_N = 76_800                     # samples in the waveform: 16 000 whole cycles, so it repeats seamlessly
BLOCK = 1 << 16                     # FFT length
BLOCKS = 4                          # spectra averaged per measurement
FULL_SCALE = 2048                   # a receive sample is 12 bits: +-2048 counts
DEFAULT_MHZ = "100,200,433.92,600,868,1000,1500,2000,2400,3000,3500,4000,5000,5800"


def spectrum(x):
    """The averaged power spectrum of x in dBFS per bin, and the bin frequencies."""
    win = np.blackman(BLOCK)
    p = sum(np.abs(np.fft.fft(x[i * BLOCK:(i + 1) * BLOCK] * win)) ** 2 for i in range(BLOCKS)) / BLOCKS
    p = np.fft.fftshift(p) / (win.sum() * FULL_SCALE) ** 2          # a full-scale tone reads 0 dBFS
    return 10 * np.log10(p + 1e-30), np.fft.fftshift(np.fft.fftfreq(BLOCK, 1 / RATE))


def measure(x):
    """level (dBFS), image, LO and worst spur (dBc) of the loopback tone in x."""
    s, f = spectrum(x)

    def peak(hz, span=2e3):
        return s[np.abs(f - hz) <= span].max()

    level = peak(TONE_HZ)
    near = (np.abs(f - TONE_HZ) < 20e3) | (np.abs(f + TONE_HZ) < 20e3) | (np.abs(f) < 20e3)
    band = np.abs(f) < 0.4 * RATE                                      # inside the anti-alias filter
    return level, peak(-TONE_HZ) - level, peak(0) - level, s[band & ~near].max() - level


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default=os.environ.get("BOARD", "fishball.local"))
    ap.add_argument("--mhz", default=DEFAULT_MHZ, help="LO frequencies in MHz, comma separated")
    ap.add_argument("--attenuation", type=float, default=-40.0, help="both transmitters, in dB (default -40)")
    ap.add_argument("--pad", type=float, default=20.0,
                    help="the smaller of the two attenuators fitted between TX and RX, in dB (default 20)")
    ap.add_argument("--rx-gain", type=float, default=20.0, help="both receivers, manual gain in dB (default 20)")
    ap.add_argument("--csv", default="loopback_sweep.csv", help="where to write the results (default: here)")
    a = ap.parse_args()
    lo_list = [float(m) * 1e6 for m in a.mhz.split(",")]

    rows, failed = [], False
    with Fishball(a.host, timeout=60) as board:
        s = board.status()
        print(f"{s.model}, firmware {s.firmware}, server {s.server_version}, die {s.ad9361_temp_c:.1f} C")
        board.configure(sample_rate_hz=RATE, rx_rf_bandwidth_hz=RATE, tx_rf_bandwidth_hz=RATE,
                        rx1_gain_mode="manual", rx1_gain_db=a.rx_gain,
                        rx2_gain_mode="manual", rx2_gain_db=a.rx_gain)
        t = np.arange(TONE_N) / RATE
        wave = board.upload_waveform(0.5 * 32767 * np.exp(2j * np.pi * TONE_HZ * t))   # half scale
        print(f"TX1 and TX2 at {a.attenuation:g} dB, RX1 and RX2 at {a.rx_gain:g} dB gain, "
              f"tone {TONE_HZ / 1e6:g} MHz above the LO\n")
        print(f"{'LO MHz':>8}  {'RX1 dBFS':>8} {'image':>6} {'LO':>6} {'spur':>6}"
              f"   {'RX2 dBFS':>8} {'image':>6} {'LO':>6} {'spur':>6}   (image, LO, spur in dBc)")
        start = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                for lo in lo_list:
                    board.configure(rx_lo_hz=int(lo), tx_lo_hz=int(lo))
                    info = board.transmit_capture(wave, BLOCKS * BLOCK, tx_channels=[1, 2], rx_channels=[1, 2],
                                                  attenuation_db=a.attenuation, pad_db=a.pad, settle_s=0.3)
                    x = board.fetch(info, os.path.join(tmp, "c")).read()
                    board.delete(info.id)
                    m1, m2 = measure(x[0]), measure(x[1])
                    rows.append([lo / 1e6, *m1, *m2])
                    print(f"{lo / 1e6:8.2f}  {m1[0]:8.1f} {m1[1]:6.1f} {m1[2]:6.1f} {m1[3]:6.1f}"
                          f"   {m2[0]:8.1f} {m2[1]:6.1f} {m2[2]:6.1f} {m2[3]:6.1f}", flush=True)
        except FishballError as e:
            failed = True
            print(f"\nthe board refused: {e.code}: {e}")
        finally:
            board.delete_waveform(wave)
            board.mute()
            board.configure(sample_rate_hz=30_720_000, rx_lo_hz=2_400_000_000, tx_lo_hz=2_400_000_000,
                            rx1_gain_mode="slow_attack", rx2_gain_mode="slow_attack")
            s = board.status()
        tx = [ch.tx_attenuation_db for ch in s.channels]
        print(f"\n{len(rows)} frequencies in {time.monotonic() - start:.0f} s; die {s.ad9361_temp_c:.1f} C; "
              f"TX1 {tx[0]} dB, TX2 {tx[1]} dB")
        if any(v > -89.5 for v in tx):
            print("A TRANSMITTER IS NOT MUTED: treat both ports as live")
            failed = True

    if rows:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["lo_mhz", "rx1_dbfs", "rx1_image_dbc", "rx1_lo_dbc", "rx1_spur_dbc",
                        "rx2_dbfs", "rx2_image_dbc", "rx2_lo_dbc", "rx2_spur_dbc"])
            w.writerows([[f"{v:.2f}" for v in r] for r in rows])
        r = np.array(rows)
        for ch, col in (("RX1", 1), ("RX2", 5)):
            print(f"{ch}: level {r[:, col].min():.1f} to {r[:, col].max():.1f} dBFS "
                  f"(a {np.ptp(r[:, col]):.1f} dB spread), image at worst {r[:, col + 1].max():.1f} dBc "
                  f"at {r[np.argmax(r[:, col + 1]), 0]:g} MHz")
        print(f"written to {os.path.abspath(a.csv)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
