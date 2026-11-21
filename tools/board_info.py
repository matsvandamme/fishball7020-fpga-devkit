#!/usr/bin/env python3
"""What is the board running? Read over IIOD, so no password and no ssh.

    # run from: the repo root
    python3 tools/board_info.py            # the board found by board_addr.py
    python3 tools/board_info.py HOST

Prints one "key: value" line each for where the board is, its model, the
firmware it runs (factory or modern, and the version) and its kernel. Exit 0
if the board answered, 3 if only its ssh did (iiod is down), 1 if nothing did.
`./devkit status` uses it.

The firmware is told apart by what the board publishes. The modern (Debian)
firmware's fishball-identity service adds `fw_build`, the full `git describe`
of the build - but only when that differs from the release tag, so a board
running a release (fw_version v2.3, no fw_build) does not have it. The kernel
settles those: the modern target is Linux 6.x, the factory one 5.15. With
neither to go on the answer is "unknown", not a guess.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.join(HERE, "selftest")]
from board_addr import check                                     # noqa: E402
from iiod_min import Iiod                                        # noqa: E402


def describe(attrs: dict[str, str]) -> list[tuple[str, str]]:
    kernel = attrs.get("local,kernel", "?")
    version = attrs.get("fw_version", "?")
    major = kernel.split(".")[0]
    if "fw_build" in attrs:
        fw = f"modern (Debian), {attrs['fw_build']}"
    elif version.startswith("debian-"):
        # fishball-identity's fallback when the root has no /opt/VERSIONS.
        fw = f"modern (Debian), {version}"
    elif major.isdigit() and int(major) >= 6:
        # A release build: fw_version is the bare tag and fw_build is left out.
        # The context does not say which root is mounted, so "(Debian)" is not
        # claimed here - a 6.x kernel can also be booted onto the ramdisk.
        fw = f"modern, {version}"
    elif major.isdigit():
        fw = f"factory (Buildroot), {version}"
    else:
        fw = f"unknown, {version}"
    return [("model", attrs.get("hw_model", "?")),
            ("firmware", fw),
            ("kernel", kernel)]


def main(argv: list[str]) -> int:
    code, host = check(argv[0] if argv else None)
    if code == 3:
        print(f"address: {host}")
        print("iiod: not answering - only ssh does")
    if code != 0:
        return code
    try:
        with Iiod(host, timeout=5.0) as io:
            attrs = io.context_attrs()
    except OSError:
        return 1
    print(f"address: {host}")
    for k, v in describe(attrs):
        print(f"{k}: {v}")
    return 0


if __name__ == "__main__":
    if any(a in ("-h", "--help") for a in sys.argv[1:]):
        print(__doc__.strip())
        raise SystemExit(0)
    rc = main(sys.argv[1:])
    sys.stdout.flush()
    os._exit(rc)        # do not wait on a name lookup still running in a thread
