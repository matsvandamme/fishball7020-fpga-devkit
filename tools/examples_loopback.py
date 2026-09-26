#!/usr/bin/env python3
"""The AD9361's internal digital loopback - exercise transmit, emit nothing.

    # run from: the repo root
    ./devkit loopback            # what is it set to now?
    ./devkit loopback on         # digital TX -> RX, inside the chip
    ./devkit loopback off        # back to the antennas
    ./devkit loopback --json

WHAT IT IS. The AD9361 can route the digital transmit samples straight into the
digital receive path, inside the chip. The signal never reaches a mixer, never
reaches the power amplifier and never reaches an antenna port. Nothing is
radiated. It is how you check that a whole transmit-and-receive flowgraph -
modulator, timing recovery, carrier recovery, the lot - works, without making a
licensing decision first.

    0   off, normal operation
    1   digital TX -> RX  (what `on` sets)
    2   digital RX -> TX

WHAT IT IS NOT. It bypasses everything analogue, which is most of the radio.
A signal that comes back clean through loopback tells you the DSP is right and
tells you NOTHING about the mixers, the filters, the amplifier, the baluns or
the antennas. In particular:

  * there is no frequency translation, so a transmit LO offset and a receive
    LO offset do not cancel. Set them EQUAL in a flowgraph that uses both, or
    the carrier loop sees an offset it cannot pull in.
  * transmit attenuation is an analogue attenuator, so it does not apply. The
    loopback level is set by the digital scale alone.
  * it cannot substitute for a cabled measurement. For that, see
    docs/transmitter-safety.md, and fit at least 20 dB of pad.

WHY IT PRINTS SO LOUDLY WHEN IT IS ON. `loopback` is a debugfs attribute and it
is not reset by anything you are likely to do next - not by restarting a
flowgraph, not by reconfiguring the radio. A board left in loopback receives
nothing from its antennas and looks broken in a way that has no obvious cause.
This tool is arranged so that the state is hard to leave behind by accident,
because leaving it behind costs somebody an hour.

It IS cleared by a reboot, and by the debugfs `initialize` knob - which is also
an ungated jump to full transmit power, so do not reach for that one.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "selftest"))
from board_addr import resolve as _board                          # noqa: E402
from iiod_min import Iiod                                         # noqa: E402

PHY = "ad9361-phy"

MEANING = {
    "0": "off - the radio is connected to its antenna ports, normally",
    "1": "ON, digital TX -> RX: transmit samples are fed to the receiver "
         "inside the chip. NOTHING is radiated, and the antennas are deaf.",
    "2": "ON, digital RX -> TX: receive samples are fed to the transmitter.",
}


def read(c) -> str:
    return c.read_debug(PHY, "loopback").strip()


def describe(value: str) -> str:
    return MEANING.get(value, f"unrecognised value {value!r}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 1)[1])
    p.add_argument("state", nargs="?", default=None,
                   choices=["on", "off", "0", "1", "2"],
                   help="on = digital TX->RX (1); off = 0. Omit to just read.")
    p.add_argument("--uri", default=None,
                   help="libiio URI; by default the board is found by name")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    host = args.uri.split(":", 1)[1] if args.uri else _board()
    if not host:
        print("cannot find the board - is it powered and on the network?",
              file=sys.stderr)
        return 2

    want = {"on": "1", "off": "0"}.get(args.state, args.state)

    try:
        with Iiod(host) as c:
            before = read(c)
            if want is not None and want != before:
                c.write_debug(PHY, "loopback", want)
            after = read(c)

            if args.json:
                print(json.dumps({"host": host, "before": before,
                                  "after": after, "on": after != "0"}, indent=1))
                return 0

            if want is not None and after != want:
                print(f"asked for loopback={want} but the chip reads {after} - "
                      f"the write did not take.", file=sys.stderr)
                return 1

            print(f"loopback = {after} on {host}")
            print(f"  {describe(after)}")
            if after != "0":
                print()
                print("  ** THE ANTENNAS ARE DISCONNECTED FROM THE RECEIVER **")
                print("  Put it back when you are done, or the board will look")
                print("  broken the next time you use it:")
                print()
                print("      # run from: the repo root")
                print("      ./devkit loopback off")
                print()
                print("  In a flowgraph that offsets both LOs, set the transmit")
                print("  and receive offsets EQUAL: loopback does not translate")
                print("  frequency, so the two do not cancel.")
            elif want == "0" and before != "0":
                print(f"  (was {before} - the antennas are connected again)")
            return 0
    except Exception as exc:
        print(f"could not reach the board at {host}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
