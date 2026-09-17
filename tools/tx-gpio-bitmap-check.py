#!/usr/bin/env python3
"""Verify the TX-sample-nibble-to-GPIO feature on real hardware.

    ./tx-gpio-bitmap-check.py [ip:192.168.2.1]

Answers one question: do the four header pins actually carry the low nibble of
the transmit samples? It needs no scope, no jumper wire and no antenna - only
the board, over the network.

HOW IT AVOIDS TRANSMITTING
--------------------------
The nibble lives in the four bits the 12-bit DAC discards, so the analog path
sees zeros no matter what pattern is authored. TX attenuation is pinned to
maximum (-89.75 dB) before anything streams and checked again at the end, so
the transmitter stays in the same state it idles in.

TWO TRAPS THIS SCRIPT EXISTS TO AVOID
-------------------------------------
1. With `direction=out`, sysfs returns the value you WROTE, not the pin. EMIO
   bits wired to no pad at all read back perfectly. Every read here sets
   `direction=in` first, and gpio 982 - routed to nothing - is read alongside
   as a control that must never go high.

2. A pin's level alone proves nothing about who is driving it. With the flag
   clear the fabric releases the pins and the XDC pull-down holds them low -
   which is also what the fabric drives for a zero nibble. The flag test
   therefore streams two DIFFERENT nibbles: if the pin follows the data the
   fabric owns it, and if it reads the same either way the fabric has let go.

Needs: python3, sshpass, and network access to the board.
"""
import subprocess
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0] + "/selftest")
from iiod_min import Iiod, mask_for                      # noqa: E402

TXDEV = "cf-ad9361-dds-core-lpc"
PHY = "ad9361-phy"
NSAMP = 8192
MUTED = "-89.750000"
CONTROL_OFFSET = 22          # EMIO 22: routed to no pad in this design


class Board:
    """The parts of the test that need a shell rather than IIO."""

    def __init__(self, host):
        self.host = host
        self.base = None
        self.dds = None

    def sh(self, cmd):
        r = subprocess.run(
            ["sshpass", "-p", "analog", "ssh", "-o", "StrictHostKeyChecking=no",
             "-o", "ConnectTimeout=10", f"root@{self.host}", cmd],
            capture_output=True, text=True, timeout=60)
        return r.stdout.strip()

    def discover(self):
        self.base = int(self.sh("cat /sys/class/gpio/gpiochip*/base | head -1"))
        # The DDS core's sysfs directory, matched by name rather than index.
        self.sysfs = self.sh(
            'for d in /sys/bus/iio/devices/iio:device*; do '
            f'[ "$(cat $d/name)" = "{TXDEV}" ] && echo $d; done')
        if not self.sysfs:
            raise SystemExit(f"could not find {TXDEV} in sysfs")
        self.pins = [self.base + 54 + 18 + n for n in range(4)]
        self.control = self.base + 54 + CONTROL_OFFSET
        for n in self.pins + [self.control]:
            self.sh(f"[ -d /sys/class/gpio/gpio{n} ] || echo {n} > /sys/class/gpio/export")

    def set_flag(self, on):
        """Enable/disable via the IIO attribute, the documented interface."""
        self.sh(f"echo {1 if on else 0} > {self.sysfs}/tx_sample_gpio_en")
        return self.sh(f"cat {self.sysfs}/tx_sample_gpio_en")

    def read_pins(self):
        """Read the four pads plus the control, always as inputs."""
        pins = self.pins + [self.control]
        cmd = "; ".join(
            f"echo in > /sys/class/gpio/gpio{n}/direction; "
            f'printf "%s " $(cat /sys/class/gpio/gpio{n}/value)' for n in pins)
        v = [int(x) for x in self.sh(cmd).split()]
        return v[:4], v[4]

    def release(self):
        for n in self.pins + [self.control]:
            self.sh(f"echo {n} > /sys/class/gpio/unexport 2>/dev/null")


def main():
    host = (sys.argv[1] if len(sys.argv) > 1 else "ip:192.168.2.1").split(":")[-1]
    board = Board(host)
    board.discover()
    print(f"board {host}: gpio base {board.base}, pins {board.pins}, "
          f"control {board.control}")

    c = Iiod(host, timeout=20).connect()
    for ch in ("voltage0", "voltage1"):
        c.write(PHY, ch, "hardwaregain", MUTED, output=True)
    print(f"transmitter pinned at {c.read(PHY, 'voltage0', 'hardwaregain', True)}\n")

    def stream_and_read(nibble):
        vals = []
        for _ in range(NSAMP):
            vals += [nibble & 0xF, 0]              # I carries the nibble, Q is zero
        c.write_samples(TXDEV, vals, mask_for([0, 1], 4), nchannels=2, cyclic=True)
        time.sleep(0.5)
        pins, ctrl = board.read_pins()
        c.close_buffer(TXDEV)
        time.sleep(0.3)
        return pins, ctrl

    ok = []
    print("flag ON - each pin must carry its own bit of the nibble")
    board.set_flag(True)
    for name, nib, want in [("all high", 0xF, [1, 1, 1, 1]),
                            ("all low", 0x0, [0, 0, 0, 0]),
                            ("only bit 0", 0x1, [1, 0, 0, 0]),
                            ("only bit 1", 0x2, [0, 1, 0, 0]),
                            ("only bit 2", 0x4, [0, 0, 1, 0]),
                            ("only bit 3", 0x8, [0, 0, 0, 1])]:
        pins, ctrl = stream_and_read(nib)
        good = pins == want and ctrl == 0
        ok.append(good)
        print(f"  0x{nib:X} {name:11s} -> {pins}  want {want}  control {ctrl}  "
              f"{'ok' if good else 'MISMATCH'}")

    print("\nflag OFF - the fabric must let go, so the pins stop following the data")
    board.set_flag(False)
    low, _ = stream_and_read(0x0)
    high, _ = stream_and_read(0xF)
    released = low == high
    ok.append(released)
    print(f"  nibble 0x0 -> {low}   nibble 0xF -> {high}   "
          f"{'released (pull-down holds them low)' if released else 'STILL DRIVEN - flag not gating'}")

    ok.append(timing_test(board, c))

    print(f"\ntransmitter still at {c.read(PHY, 'voltage0', 'hardwaregain', True)}")
    board.set_flag(False)
    board.release()
    c.close()
    print("\nRESULT:", "PASS" if all(ok) else "FAIL")
    return 0 if all(ok) else 1


def timing_test(board, c):
    """Do the pins track the pattern IN TIME, at the rate the samples imply?

    Static levels only prove the wiring. This authors a square wave whose
    period is set by the buffer length and the sample rate - one cycle per
    buffer on bit 0, four on bit 1 - and measures what comes out. If the pins
    were driven by anything other than the sample stream, the period would not
    land on N/fs.

    The rate is dropped to the AD9361's minimum and the buffer made large, so
    the pattern is slow enough to sample through sysfs (~50-150 reads/s).
    """
    print("\ntiming - the pins must track the pattern at the rate the samples imply")
    rate_attr = "/sys/bus/iio/devices/iio:device0/in_voltage_sampling_frequency"
    original = board.sh(f"cat {rate_attr}").strip()
    board.sh(f"echo 2100000 > {rate_attr}")          # the exact minimum is rejected
    fs = int(board.sh(f"cat {rate_attr}").strip())
    N = 1 << 20
    try:
        vals = []
        for n in range(N):
            vals += [(1 if n < N // 2 else 0) | (2 if (n % (N // 4)) < (N // 8) else 0), 0]
        board.set_flag(True)
        c.write_samples(TXDEV, vals, mask_for([0, 1], 4), nchannels=2, cyclic=True)
        time.sleep(0.5)
        pins = board.pins[:2]
        raw = board.sh(
            "".join(f"([ -d /sys/class/gpio/gpio{n} ] || echo {n} > /sys/class/gpio/export); "
                    f"echo in > /sys/class/gpio/gpio{n}/direction; " for n in pins) +
            'i=0; while [ $i -lt 700 ]; do echo "$(cut -d\\  -f1 /proc/uptime) '
            + "".join(f"$(cat /sys/class/gpio/gpio{n}/value)" for n in pins) +
            '"; i=$((i+1)); done')
        c.close_buffer(TXDEV)
        rows = [l.split() for l in raw.strip().split("\n") if len(l.split()) == 2]
        if len(rows) < 50:
            print("  could not sample the pins fast enough"); return False
        t0 = float(rows[0][0])
        seq = [(float(t) - t0, v) for t, v in rows]
        good = True
        for idx, cycles in ((0, 1), (1, 4)):
            edges, prev = [], seq[0][1][idx]
            for t, v in seq:
                if v[idx] != prev:
                    edges.append(t); prev = v[idx]
            expect = N / fs / cycles
            if len(edges) < 4:
                print(f"  bit{idx}: only {len(edges)} edges seen"); good = False; continue
            periods = [edges[i + 2] - edges[i] for i in range(len(edges) - 2)]
            meas = sum(periods) / len(periods)
            err = abs(meas - expect) / expect * 100
            good &= err < 2.0
            print(f"  bit{idx}: {len(edges):3d} edges, period {meas*1000:7.1f} ms, "
                  f"expected {expect*1000:7.1f} ms, error {err:.1f}%  "
                  f"{'ok' if err < 2.0 else 'OUT OF TOLERANCE'}")
        return good
    finally:
        board.sh(f"echo {original} > {rate_attr}")


if __name__ == "__main__":
    sys.exit(main())
