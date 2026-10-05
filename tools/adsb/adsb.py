#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "PyQt6"]
# ///
"""Receive ADS-B on 1090 MHz and show the aircraft live.

    # run from: the repo root, on your HOST (not the board)
    ./devkit adsb                         # the window: aircraft table + raw messages
    ./devkit adsb --text                  # the same in the terminal, no Qt needed
    ./devkit adsb --channel 2             # the antenna is on RX2A
    ./devkit adsb --gain 20               # strong signals near an airport
    ./devkit adsb --lat 50.85 --lon 4.35  # positions from the first message
    ./devkit adsb --record flight         # also save the samples (SigMF)
    ./devkit adsb --replay flight.sigmf-meta    # play a recording back, no board

RECEIVE ONLY. It configures one receiver (LO 1090 MHz, 4 MSPS, manual gain)
and reads its samples with iio_readdev; it never opens a transmit buffer. Put
a 1090 MHz antenna on RX1A, or on RX2A and add --channel 2.

The window needs PyQt6. `./devkit adsb` runs it through uv, which fetches PyQt6
(about 100 MB, once) into its cache; or, in a venv, `.venv/bin/pip install PyQt6
numpy`. --text needs
only numpy.

What the columns and the log mean: docs/adsb.md.
"""

import argparse
import json
import os
import signal
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from source import BoardError, BoardSource, FileSource, Recorder   # noqa: E402
from engine import Receiver, log_line                               # noqa: E402


def parse(argv=None):
    p = argparse.ArgumentParser(
        prog="devkit adsb",
        description="Receive ADS-B on 1090 MHz and show the aircraft live. "
                    "Receive only.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""examples:
  ./devkit adsb                              the window
  ./devkit adsb --channel 2                  the antenna is on RX2A
  ./devkit adsb --text --seconds 60          a minute in the terminal
  ./devkit adsb --text --json --seconds 30   the aircraft table as JSON, then exit
  ./devkit adsb --record flight              also save the samples as SigMF
  ./devkit adsb --replay flight.sigmf-meta   play them back, no board needed

the window needs PyQt6; ./devkit adsb fetches it with uv the first time
(about 100 MB). --text needs only numpy. More: docs/adsb.md""")
    src = p.add_argument_group("where the samples come from")
    src.add_argument("--uri", help="the board's address as ip:HOST; found by "
                     "tools/board_addr.py when not given")
    src.add_argument("--replay", metavar="FILE",
                     help="a recording (.sigmf-meta, or raw int16 I/Q with --rate)")
    src.add_argument("--rate", type=float, default=4e6,
                     help="sample rate, a multiple of 2 MSPS (default 4e6)")
    src.add_argument("--fast", action="store_true", help="replay as fast as possible")
    src.add_argument("--loop", action="store_true", help="replay over and over")
    rf = p.add_argument_group("the receiver")
    rf.add_argument("--channel", type=int, choices=(1, 2), default=1,
                    help="which receiver the antenna is on: 1 = RX1A, 2 = RX2A (default 1)")
    rf.add_argument("--gain", default="25",
                    help="gain in dB, or 'agc' (default 25; above ~35 a strong signal on "
                         "another band can overload the receiver)")
    rf.add_argument("--freq", type=float, default=1090e6,
                    help="LO in Hz (default 1090e6)")
    rf.add_argument("--min-snr", type=float, default=9.0,
                    help="preamble threshold over the noise floor, dB (default 9)")
    rf.add_argument("--lat", type=float, help="your latitude, for single-message positions")
    rf.add_argument("--lon", type=float, help="your longitude")
    out = p.add_argument_group("output")
    out.add_argument("--text", action="store_true",
                     help="no window: messages and a table in the terminal")
    out.add_argument("--json", action="store_true",
                     help="with --text: print only the final table, as JSON")
    out.add_argument("--seconds", type=float, help="stop after this long")
    out.add_argument("--record", metavar="NAME", help="also write the samples as SigMF")
    a = p.parse_args(argv)
    if (a.lat is None) != (a.lon is None):
        p.error("--lat and --lon go together")
    if a.json and not a.text:
        p.error("--json is a --text option")
    if a.gain != "agc":
        try:
            float(a.gain)
        except ValueError:
            p.error(f"--gain is a number of dB or 'agc', not {a.gain!r}")
    return a


def make_receiver(a):
    if a.replay:
        source = FileSource(a.replay, rate=a.rate, fast=a.fast, loop=a.loop)
    else:
        source = BoardSource(uri=a.uri, freq=a.freq, rate=a.rate, channel=a.channel,
                             gain="agc" if a.gain == "agc" else float(a.gain))
    ref = (a.lat, a.lon) if a.lat is not None else None
    rb = source.configure()
    recorder = Recorder(a.record, rb) if a.record else None
    rx = Receiver(source, ref=ref, min_snr_db=a.min_snr, recorder=recorder)
    rx.start(rb)
    return rx, rb


def describe(rb):
    gain = "recording" if rb.get("gain_db") is None else \
        f"{rb['gain_db']:g} dB {rb.get('gain_mode', '')}".strip()
    rx = f"  RX{rb['channel']}" if "channel" in rb else ""
    return (f"{rb['uri']}{rx}  LO {rb['frequency'] / 1e6:.3f} MHz  "
            f"{rb['sample_rate'] / 1e6:g} MSPS  gain {gain}")


def table(rows, now):
    hdr = (f"{'ICAO':6} {'call':8} {'sqk':4} {'alt ft':>6} {'kt':>4} {'trk':>5} "
           f"{'fpm':>6} {'lat':>9} {'lon':>10} {'msgs':>5} {'dBFS':>6} {'age':>4}")
    lines = [hdr]
    for r in sorted(rows, key=lambda r: -r["last_seen"]):
        def f(v, fmt):
            width = int(fmt[1:].split(".")[0])
            return format(v, fmt) if v is not None else " " * width
        lines.append(
            f"{r['icao']:06X} {r['callsign'] or '':8} {r['squawk'] or '':4} "
            f"{f(r['altitude'], '>6')} {f(r['speed'], '>4')} {f(r['track'], '>5')} "
            f"{f(r['vrate'], '>6')} {f(r['lat'], '>9.4f')} {f(r['lon'], '>10.4f')} "
            f"{r['messages']:>5} {f(r['rssi'], '>6.1f')} {now - r['last_seen']:>4.0f}")
    return "\n".join(lines)


def run_text(a):
    rx, rb = make_receiver(a)
    print("# " + describe(rb), file=sys.stderr)
    signal.signal(signal.SIGINT, lambda *_: rx.stop.set())
    signal.signal(signal.SIGTERM, lambda *_: rx.stop.set())
    t_end = time.time() + a.seconds if a.seconds else None
    last_table = time.time()
    try:
        while not rx.stop.is_set() and not rx.done.is_set():
            time.sleep(0.2)
            for e in rx.drain_log():
                if not a.json:
                    print(log_line(e), flush=True)
            now = time.time()
            if not a.json and now - last_table > 10:
                rows, stats = rx.snapshot()
                print("\n" + table(rows, now) + "\n" + status_line(stats) + "\n", flush=True)
                last_table = now
            if t_end and now >= t_end:
                break
    finally:
        rx.close()
    for e in rx.drain_log(10**9):
        if not a.json:
            print(log_line(e))
    rows, stats = rx.snapshot()
    if a.json:
        print(json.dumps({"receiver": rb, "stats": stats, "aircraft": [
            {**r, "icao": f"{r['icao']:06X}"} for r in rows]}, indent=2, default=str))
    else:
        print("\n" + table(rows, time.time()) + "\n" + status_line(stats))
    if rx.error:
        print("error: " + rx.error, file=sys.stderr)
        return 1
    return 0


def status_line(st):
    if st.get("stalled_s"):
        return (f"NO SAMPLES for {st['stalled_s']:.0f} s: the stream from the board has "
                "stopped. Is it powered from mains? Restart, or check ./devkit status")
    return (f"{st['samples_per_s'] / 1e6:.2f} MS/s in  {st['preambles']} preambles  "
            f"{st['frames']} messages: {st['ok']} CRC ok, {st['fixed']} fixed, "
            f"{st['addr']} AP ok, {st['dropped']} rejected"
            + (f"  {st['blocks_dropped']} BLOCKS DROPPED (host too slow)"
               if st.get("blocks_dropped") else "")
            # Real time is the only rate that works: short means the link drops
            # samples and messages are lost before anything here sees them.
            + ("  LINK TOO SLOW for this rate: try --uri ip:192.168.2.1 (USB)"
               if st.get("rate") and 0 < st["samples_per_s"] < 0.9 * st["rate"]
               and not st.get("replay") else "")
            + (f"  RECORDING STOPPED: {st['record_error']}" if st.get("record_error") else ""))


def main(argv=None):
    a = parse(argv)
    try:
        if a.text:
            return run_text(a)
        try:
            import gui
        except ImportError as e:
            if "PyQt6" not in str(e):
                raise
            sys.exit("the window needs PyQt6: run it as ./devkit adsb (which uses uv), "
                     "or in a venv: .venv/bin/pip install PyQt6 numpy, or use --text")
        return gui.run(a, make_receiver, describe, status_line)
    except BoardError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
