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

WHERE THE RATINGS COME FROM - AND HOW FAR TO TRUST THEM. Read this before
quoting a number out of this tool.

  **Neither limit has been read from a datasheet.** No datasheet for either
  part is in docs/vendor/, which holds only the board schematic, and AMD's
  documentation site cannot be fetched non-interactively. So:

  Zynq 85 C   What IS established: the fitted part is `xc7z020clg400-2`, with
              no industrial suffix, so it is commercial grade. That comes from
              the hardware platform's own sysdef.xml and is checkable here.
              What is NOT: that commercial grade means 0-85 C junction. That
              figure is inherited from tools/selftest, which has used it all
              along, and is consistent with what Xilinx specifies for
              commercial parts - but nobody in this repository has opened
              DS187 to confirm it.

  AD9361      -40 to +85 C operating and 150 C absolute maximum junction are
              quoted from memory of the ADI datasheet. Treat them as
              approximately right and not as citations.

  Both are almost certainly the right order of magnitude, and both are the
  right SHAPE of limit - the XADC and the AuxADC each report junction
  temperature, which is what an operating-range figure constrains. If you are
  making a thermal decision that matters, get the datasheets: DS187 for the
  Zynq, the AD9361 data sheet from Analog Devices. Dropping them in
  docs/vendor/ would let this tool cite them properly.

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
     "commercial grade, confirmed (xc7z020clg400-2). The 85 C itself is"
     " UNVERIFIED - no DS187 here. --help explains."),
    ("AD9361", 85.0, 150.0,
     "85 / 150 C quoted from memory, NOT from a datasheet. --help explains."),
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
            if k.startswith("_"):
                continue
            out.append(f"  {k}: {v}")
        for line in extra.get("_limit_lines", []):
            out.append(f"  {line}" if line else "")
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
        info["_tx_temp_limit_mC"] = int(c.read_device(PHY, "tx_temp_limit"))
    except Exception:
        info["_tx_temp_limit_mC"] = None
    return info


#: What to suggest when the limit is off. The AD9361 is specified to 85 C and
#: idles around 45 C on this board, so 70 C acts well before the rating while
#: leaving room for a warm room and a busy transmitter.
SUGGEST_C = 70


def tx_limit_lines(limit_mC, ad9361_c: float, host: str) -> list[str]:
    """What the thermal limit is, and exactly how to change it."""
    if limit_mC is None:
        return ["tx_temp_limit: absent - this firmware predates patch 0018.",
                "    Build and flash a current devkit kernel to get it."]

    if limit_mC:
        lim_c = limit_mC / 1000
        head = lim_c - ad9361_c
        return [
            f"tx_temp_limit: {lim_c:.1f} C - ACTIVE. Above this the driver",
            "    refuses to lower the attenuation, so transmit power cannot be",
            f"    raised. Muting is never blocked. AD9361 is at {ad9361_c:.1f} C,"
            + (f" {head:.1f} C below the limit." if head >= 0
               else f" {-head:.1f} C OVER the limit - transmit is being refused."),
            "    To turn it off:",
            f"        # run on your HOST",
            f"        iio_attr -u ip:{host} -d ad9361-phy tx_temp_limit 0",
        ]

    return [
        "tx_temp_limit: 0 - OFF. Nothing stops the board transmitting hot.",
        f"    To refuse transmit above {SUGGEST_C} C, either:",
        "",
        "        # run on your HOST",
        f"        iio_attr -u ip:{host} -d ad9361-phy tx_temp_limit {SUGGEST_C * 1000}",
        "",
        "        # or run on the board",
        f"        echo {SUGGEST_C * 1000} > /sys/bus/iio/devices/iio:device0/tx_temp_limit",
        "",
        "    The value is MILLIdegrees C, so 70 C is 70000. Above it, requests",
        "    to lower the attenuation are refused and muting still works - the",
        "    failure direction is silence, never a stuck-on transmitter.",
        "    It does NOT survive a reboot; the driver starts at 0. To make it",
        "    stick, set it from /mnt/jffs2/autorun.sh - but read docs/kernel.md",
        "    first, because that partition survives reflashing and is the usual",
        "    reason a board behaves unlike its firmware.",
    ]


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
                temps = read_temps(c)
                extra = tx_state(c)
                extra["_limit_lines"] = tx_limit_lines(
                    extra.get("_tx_temp_limit_mC"), temps["AD9361"], host)
                print(render(temps, colour, extra))
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
