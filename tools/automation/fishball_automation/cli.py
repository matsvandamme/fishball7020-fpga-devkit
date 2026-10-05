"""The command line behind `./devkit automation status|clock|capture|smoke`."""
import argparse
import os
import sys
import tempfile
import time

from .client import Fishball, FishballError, status_text


def smoke(board):
    """A short end-to-end check against a real board: status, a capture of
    both receivers, a live stream, and both transmitters still muted."""
    def muted(s):
        return all(ch.tx_attenuation_db <= -89.5 for ch in s.channels)

    s = board.status()
    print(f"status        {s.model}, {s.sample_rate_hz / 1e6:g} MS/s, RX LO {s.rx_lo_hz / 1e6:g} MHz")
    if not muted(s):
        sys.exit("FAIL: a transmitter is not muted before the test; not touching the receiver")
    samples = min(2_000_000, s.sample_rate_hz // 4)
    with tempfile.TemporaryDirectory() as tmp:
        rec = board.capture(samples=samples, channels=[1, 2], path=os.path.join(tmp, "smoke"))
        size = os.path.getsize(rec.data_path)
        ok = size == samples * 8 and rec.lost_samples == 0
        print(f"capture       {rec.samples} samples x 2 channels, {size} bytes, {rec.lost_samples} lost: "
              f"{'ok' if ok else 'FAIL'}")
        if not ok:
            sys.exit("FAIL: the capture is not the size it should be")
    got = dropped = 0
    t0 = time.monotonic()
    for blk in board.stream(channels=[1], samples=s.sample_rate_hz // 2):
        got += len(blk.data) // 4
        dropped = blk.dropped_samples
    print(f"stream        {got} samples in {time.monotonic() - t0:.2f} s, {dropped} dropped by the board")
    if not got:
        sys.exit("FAIL: the stream delivered nothing")
    after = board.status()
    print(f"transmitters  TX1 {after.channels[0].tx_attenuation_db:g} dB, TX2 {after.channels[1].tx_attenuation_db:g} dB")
    if not muted(after):
        sys.exit("FAIL: a transmitter is not muted after the test")
    print("smoke test: PASS")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="./devkit automation", description=__doc__)
    ap.add_argument("--host", default=os.environ.get("BOARD", "fishball.local"),
                    help="the board (default: $BOARD, else fishball.local)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="the board, the radio's settings, the clock, who holds the buffers")
    c = sub.add_parser("clock", help="the reference clock; --measure times it against the board's own crystal")
    c.add_argument("--measure", action="store_true")
    c.add_argument("--seconds", type=float, default=30.0)
    k = sub.add_parser("capture", help="record on the board and fetch a SigMF recording")
    k.add_argument("path", help="output name, relative to where you run the command: "
                                "writes PATH.sigmf-data and PATH.sigmf-meta")
    k.add_argument("--samples", type=float, required=True, help="samples per channel, e.g. 2e6")
    k.add_argument("--channels", default="1", help="1, 2 or 1,2 (default: 1)")
    sub.add_parser("smoke", help="an end-to-end check: status, a capture, a stream, transmitters still muted")
    sub.add_parser("mute", help="both transmitters to maximum attenuation, read back")
    a = ap.parse_args(argv)
    try:
        with Fishball(a.host) as board:
            if a.cmd == "status":
                print(status_text(board.status()))
            elif a.cmd == "clock":
                s = board.status()
                s.clock.CopyFrom(board.clock(measure=a.measure, seconds=a.seconds))
                print("\n".join(l for l in status_text(s).splitlines() if l.startswith(("Clock", "Reference"))))
            elif a.cmd == "capture":
                rec = board.capture(samples=int(a.samples), channels=[int(x) for x in a.channels.split(",")], path=a.path)
                print(f"{rec.samples} samples per channel, RX{', RX'.join(map(str, rec.channels))}, "
                      f"{rec.sample_rate_hz / 1e6:g} MS/s at {rec.rx_lo_hz / 1e6:g} MHz, {rec.lost_samples} lost")
                print(f"{os.path.abspath(rec.data_path)}\n{os.path.abspath(rec.meta_path)}")
            elif a.cmd == "smoke":
                smoke(board)
            elif a.cmd == "mute":
                m = board.mute()
                print(f"TX1 {m.tx1_attenuation_db:g} dB, TX2 {m.tx2_attenuation_db:g} dB: {'muted' if m.muted else 'NOT MUTED'}")
                return 0 if m.muted else 1
    except FishballError as e:
        print(f"{e.code}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
