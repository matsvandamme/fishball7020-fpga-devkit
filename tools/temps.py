#!/usr/bin/env python3
"""Every die temperature this board can measure, against its rating.

    # run from: the repo root
    ./devkit temps                 # read once
    ./devkit temps --watch         # keep reading, until Ctrl-C
    ./devkit temps --json          # for scripts

The board has exactly **two** temperature sensors, and it is worth knowing that
up front so you do not go looking for a third:

    Zynq XC7Z020   read through the XADC, the Zynq's own on-die converter
    AD9361         read through the transceiver's internal AuxADC

There is no sensor on the PGA-102+ power amplifiers, the DDR, the Ethernet PHY
or the regulators, and no `hwmon` or thermal-zone entries at all - checked on
the board, not assumed. So "the board is at N degrees" is never something this
tool can tell you; it reports two dies and says which.

WHERE THE RATINGS COME FROM. A limit quoted without a source is a guess, so:

  Zynq 85 C   The fitted part is `xc7z020clg400-2` - recorded in the hardware
              platform's own sysdef.xml - with no industrial suffix, so it is
              commercial grade: 0 to 85 C junction. tools/selftest has used
              this limit all along.

  AD9361      The datasheet specifies operation over -40 to +85 C and gives an
              absolute maximum junction temperature of 150 C. NOTE: there is no
              AD9361 datasheet in docs/vendor/, so unlike the Zynq figure this
              one is not checkable from anything in this repository. It is
              reported as a datasheet value, and labelled as one.

The transmitter is the only part here that heats itself appreciably, and the
amplifier sits next to the AD9361. If you want the board to act on this rather
than just report it, patch 0018 added a limit that refuses to raise transmit
power above a die temperature:

    # run on the board - millidegrees C, 0 disables
    echo 60000 > /sys/bus/iio/devices/iio:device0/tx_temp_limit
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest"))
from board_addr import resolve as _board                          # noqa: E402
from iiod_min import Iiod                                         # noqa: E402

PHY, XADC = "ad9361-phy", "xadc"

# name, spec limit (C), absolute max (C) or None, where the number comes from
SENSORS = [
    ("Zynq XC7Z020", 85.0, None,
     "commercial grade (xc7z020clg400-2), 0-85 C junction"),
    ("AD9361", 85.0, 150.0,
     "datasheet: -40 to +85 C operating, 150 C absolute max junction"),
]

# Fractions of the spec limit at which to start saying something. Warning well
# before the limit is the point: by the time a die is AT its rating you have
# already been running it out of spec for a while.
WARN_AT = 0.80
HOT_AT = 0.94


def read_temps(c: Iiod) -> dict:
    """Both dies, in degrees C.

    The XADC reports a raw code with a separate offset and scale, exactly as
    tools/selftest does it; the AD9361 reports millidegrees directly.
    """
    raw = float(c.read(XADC, "temp0", "raw"))
    off = float(c.read(XADC, "temp0", "offset"))
    scale = float(c.read(XADC, "temp0", "scale"))
    zynq = (raw + off) * scale / 1000.0
    ad9361 = float(c.read(PHY, "temp0", "input")) / 1000.0
    return {"Zynq XC7Z020": zynq, "AD9361": ad9361}


def verdict(temp: float, limit: float) -> tuple[str, str]:
    """(label, ansi colour) for one reading."""
    if temp >= limit:
        return "OVER LIMIT", "\033[31m"
    if temp >= limit * HOT_AT:
        return "hot", "\033[31m"
    if temp >= limit * WARN_AT:
        return "warm", "\033[33m"
    return "ok", "\033[32m"


def render(temps: dict, colour: bool, extra: dict | None = None,
           sources: bool = True) -> str:
    out = []
    w = max(len(n) for n, _, _, _ in SENSORS)
    for name, limit, absmax, source in SENSORS:
        t = temps[name]
        label, col = verdict(t, limit)
        c0, c1 = (col, "\033[0m") if colour else ("", "")
        head = max(0.0, limit - t)
        line = (f"  {name:<{w}}  {t:6.1f} C   {c0}{label:<10}{c1}"
                f" {head:5.1f} C below the {limit:.0f} C limit")
        if absmax:
            line += f"  (absolute max {absmax:.0f} C)"
        out.append(line)
        if sources:
            out.append(f"  {'':<{w}}  {source}")
    if extra:
        out.append("")
        for k, v in extra.items():
            out.append(f"  {k}: {v}")
    return "\n".join(out)


def tx_state(c: Iiod) -> dict:
    """What the transmitter is doing, since it is what heats the board."""
    info = {}
    try:
        a0 = c.read(PHY, "voltage0", "hardwaregain", output=True).split()[0]
        a1 = c.read(PHY, "voltage1", "hardwaregain", output=True).split()[0]
        info["transmit attenuation"] = f"TX1 {a0} dB, TX2 {a1} dB"
    except Exception:
        pass
    # A device attribute, not a channel one, and it only exists with patch
    # 0018 - so distinguish "the knob is missing" from "the knob is off".
    # Reporting them the same way would tell somebody to go install a patch
    # they already have.
    try:
        lim = int(c.read_device(PHY, "tx_temp_limit"))
        info["tx_temp_limit"] = (
            f"{lim/1000:.1f} C - transmit power will not be raised above this"
            if lim else
            "0 - present but disabled; set it to refuse transmit when hot")
    except Exception:
        info["tx_temp_limit"] = "absent - this firmware predates patch 0018"
    return info


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog=__doc__.split("\n", 1)[1])
    p.add_argument("--uri", default=None,
                   help="libiio URI; by default the board is found by name")
    p.add_argument("--watch", action="store_true",
                   help="keep reading until Ctrl-C")
    p.add_argument("--interval", type=float, default=2.0, metavar="S",
                   help="seconds between readings with --watch (default 2)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    host = args.uri.split(":", 1)[1] if args.uri else _board()
    if not host:
        print("cannot find the board - is it powered and on the network?",
              file=sys.stderr)
        return 2

    colour = sys.stdout.isatty() and not args.json
    try:
        with Iiod(host) as c:
            if args.json:
                t = read_temps(c)
                print(json.dumps({
                    "host": host,
                    "celsius": {k: round(v, 2) for k, v in t.items()},
                    "limits_celsius": {n: {"spec": lim, "absolute_max": am}
                                       for n, lim, am, _ in SENSORS},
                    "verdict": {n: verdict(t[n], lim)[0]
                                for n, lim, _, _ in SENSORS},
                }, indent=1))
                return 0

            print(f"die temperatures on {host}")
            if not args.watch:
                print(render(read_temps(c), colour, tx_state(c)))
                return 0

            # Print where the limits come from once, then just the numbers -
            # repeating four lines of provenance every two seconds buries the
            # thing you are watching.
            print(render(read_temps(c), colour))
            print("\n  (Ctrl-C to stop)\n")
            while True:
                block = render(read_temps(c), colour, sources=False)
                print(f"  {time.strftime('%H:%M:%S')}")
                print(block)
                print()
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"could not read the board at {host}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
