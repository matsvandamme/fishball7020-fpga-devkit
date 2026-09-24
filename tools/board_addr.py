#!/usr/bin/env python3
"""Where is the board? One answer, so every tool here agrees.

The board has more than one address and the useful one changes. Over USB it is
always 192.168.2.1. Over Ethernet it is whatever the router gave it, which moves
- so the thing to reach for is the NAME it announces over mDNS, not an address
anybody typed.

Order tried:

    1. an address passed in explicitly      (--uri / --host / an argument)
    2. $BOARD, or $SDR_URI                  (per-shell override)
    3. Fishball7020.local                   this repo's default hostname
    4. pluto.local, fishball.local          older rootfs, and a common rename
    5. 192.168.2.1                          the USB gadget, which never moves

A candidate counts as "the board" when something answers on the IIOD port or on
ssh. Resolving a .local name needs mDNS on THIS machine (avahi and nss-mdns on
Linux, built in on macOS); where that is missing the names simply fail to
resolve and the USB address still works, which is why it stays last in the list
rather than first.

    from board_addr import resolve, uri
    host = resolve()                  # "Fishball7020.local"
    u    = uri()                      # "ip:Fishball7020.local"

or from a shell script:

    BOARD="${BOARD:-$(python3 tools/board_addr.py)}"
"""
from __future__ import annotations

import os
import socket
import threading
import time

NAMES = ("Fishball7020.local", "pluto.local", "fishball.local")
USB = "192.168.2.1"
PORTS = (30431, 22)          # iiod, then ssh - a board answers both
_cache: dict[str, str] = {}


def strip_uri(s: str) -> str:
    """'ip:host:port' or 'ip:host' -> 'host'. Anything else is returned as is."""
    if s.startswith("ip:"):
        s = s[3:]
        # An IPv6 literal is bracketed; a trailing :port is not part of the host.
        if not s.startswith("[") and s.count(":") == 1:
            s = s.split(":")[0]
    return s


def reachable(host: str, timeout: float = 0.8) -> bool:
    """Is this host the BOARD - not merely something with a port open?

    "Something answered on 30431 or 22" is not the same question, and getting
    them confused sends every tool at the wrong machine. 192.168.2.1 is a
    private address that plenty of networks use for something else, and a VPN
    routing it elsewhere is enough: on the machine this was written for, a
    tunnel carried 192.168.2.1 to a host that accepted TCP and dropped the
    handshake, which looked exactly like a broken board.

    So ask each service to identify itself. IIOD answers VERSION with its
    protocol version; dropbear says so in its SSH banner. Either is proof; an
    open port is not.
    """
    try:
        with socket.create_connection((host, 30431), timeout=timeout) as c:
            c.settimeout(timeout)
            c.sendall(b"VERSION\r\n")
            reply = c.recv(64)
            # e.g. b"0.25.(git tag)..." - a version triple is enough.
            if reply[:1].isdigit() and b"." in reply:
                return True
    except OSError:
        pass
    try:
        with socket.create_connection((host, 22), timeout=timeout) as c:
            c.settimeout(timeout)
            banner = c.recv(128)
            if banner.startswith(b"SSH-") and b"dropbear" in banner.lower():
                return True
    except OSError:
        pass
    return False


def candidates(explicit: str | None = None) -> list[str]:
    out: list[str] = []
    for c in (explicit, os.environ.get("BOARD"),
              strip_uri(os.environ.get("SDR_URI", "")) or None,
              *NAMES, USB):
        if c and c not in out:
            out.append(strip_uri(c))
    return out


def probe_all(cands: list[str], timeout: float = 0.8,
              deadline: float = 2.0) -> dict[str, bool]:
    """Probe every candidate at once, and give up on the slow ones.

    Concurrency is not about speed here, it is about a name that does NOT
    resolve. create_connection resolves before it connects, and a failing mDNS
    lookup can block for ten seconds or more - long enough that probing four
    candidates in turn took twenty seconds and every tool would have paid it on
    every run. Run them together, wait a short deadline, and use whatever came
    back. Threads are daemons so a lookup still blocking at exit cannot hold the
    process open.
    """
    done: dict[str, bool] = {}
    def work(c: str) -> None:
        try:
            done[c] = reachable(c, timeout)
        except Exception:
            done[c] = False
    threads = [threading.Thread(target=work, args=(c,), daemon=True) for c in cands]
    for t in threads:
        t.start()
    end = time.monotonic() + deadline
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    return done


def first_answering(cands: list[str], timeout: float = 0.8,
                    deadline: float = 2.0) -> str | None:
    """Like probe_all, but stops as soon as the best candidate is confirmed.

    Joining every thread before deciding costs the full deadline on every run,
    even when the first name answers in a millisecond. Waiting on them in
    PRIORITY order and returning on the first success means the common case -
    the board is on its own name - costs nothing, while an unresolvable name
    still cannot stall things for longer than the deadline.
    """
    done: dict[str, bool] = {}
    def work(c: str) -> None:
        try:
            done[c] = reachable(c, timeout)
        except Exception:
            done[c] = False
    threads = {c: threading.Thread(target=work, args=(c,), daemon=True) for c in cands}
    for t in threads.values():
        t.start()
    end = time.monotonic() + deadline
    for c in cands:
        threads[c].join(max(0.0, end - time.monotonic()))
        if done.get(c):
            return c
    return None


def resolve(explicit: str | None = None, timeout: float = 0.8,
            probe: bool = True, deadline: float = 2.0) -> str:
    """The highest-priority candidate that answers.

    Priority is kept: of everything that answered inside the deadline, the one
    earliest in the list wins, so a board reachable by BOTH its name and the USB
    gadget is addressed by name.
    """
    key = f"{explicit}|{timeout}|{probe}"
    if key in _cache:
        return _cache[key]
    cands = candidates(explicit)
    # An address given explicitly, or via $BOARD/$SDR_URI, is not second-guessed:
    # the caller said where to look, and probing would only add latency.
    if explicit or not probe or os.environ.get("BOARD") or os.environ.get("SDR_URI"):
        _cache[key] = cands[0]
        return cands[0]
    found = first_answering(cands, timeout, deadline)
    _cache[key] = found or USB           # nothing answered; let the tool say so
    return _cache[key]


def uri(explicit: str | None = None, **kw) -> str:
    h = resolve(explicit, **kw)
    return h if h.startswith("ip:") else f"ip:{h}"


def self_test() -> bool:
    """Checks that hold with no board present, so CI can run them."""
    ok = True

    def chk(name, got, want):
        nonlocal ok
        good = got == want
        ok &= good
        print(f"  {'PASS' if good else 'FAIL'}  {name}: {got!r}" + ("" if good else f" != {want!r}"))

    chk("strip ip: prefix", strip_uri("ip:Fishball7020.local"), "Fishball7020.local")
    chk("strip a trailing port", strip_uri("ip:192.168.2.1:30431"), "192.168.2.1")
    chk("leave a bare host alone", strip_uri("pluto.local"), "pluto.local")
    # An IPv6 literal is bracketed; its colons must not be read as a port.
    chk("leave a v6 literal alone", strip_uri("ip:[fe80::1]"), "[fe80::1]")

    env = {k: os.environ.pop(k, None) for k in ("BOARD", "SDR_URI")}
    try:
        c = candidates()
        chk("the repo's own name comes first", c[0], "Fishball7020.local")
        chk("the USB gadget comes last", c[-1], USB)
        chk("no duplicates", len(c), len(set(c)))
        chk("an explicit address wins", candidates("10.0.0.7")[0], "10.0.0.7")
        os.environ["BOARD"] = "10.0.0.8"
        chk("$BOARD wins", candidates()[0], "10.0.0.8")
        chk("$BOARD is not probed away", resolve(), "10.0.0.8")
        _cache.clear(); del os.environ["BOARD"]
        os.environ["SDR_URI"] = "ip:10.0.0.9:30431"
        chk("$SDR_URI wins, port stripped", candidates()[0], "10.0.0.9")
        _cache.clear(); del os.environ["SDR_URI"]

        # Nothing answers: must fall back rather than hang or raise. 203.0.113.0/24
        # is TEST-NET-3, reserved by RFC 5737 for exactly this.
        global NAMES
        keep = NAMES
        NAMES = ("host-that-does-not-exist.invalid",)
        _cache.clear()
        t0 = time.monotonic()
        got = resolve(timeout=0.3, deadline=1.5)
        took = time.monotonic() - t0
        NAMES = keep
        _cache.clear()
        chk("falls back to the USB address", got, USB)
        bounded = took < 4.0
        ok &= bounded
        print(f"  {'PASS' if bounded else 'FAIL'}  bounded by the deadline: {took:.2f}s")
    finally:
        for k, v in env.items():
            if v is not None:
                os.environ[k] = v
        _cache.clear()

    print("  ->", "board_addr behaves" if ok else "BROKEN")
    return ok


if __name__ == "__main__":
    import argparse
    a = argparse.ArgumentParser(description="print where the board is")
    a.add_argument("--uri", action="store_true", help="print ip:<host>")
    a.add_argument("--all", action="store_true", help="show every candidate and whether it answers")
    a.add_argument("--no-probe", action="store_true", help="do not connect, just pick the first")
    a.add_argument("--list", action="store_true", help="print the candidates, one per line, no probing")
    a.add_argument("--self-test", action="store_true", help="checks that need no board")
    a.add_argument("host", nargs="?", help="an address to prefer")
    g = a.parse_args()
    if g.self_test:
        raise SystemExit(0 if self_test() else 1)
    if g.list:
        print("\n".join(candidates(g.host)))
        raise SystemExit(0)
    if g.all:
        cands = candidates(g.host)
        answered = probe_all(cands)
        for c in cands:
            print(f"  {'answers' if answered.get(c) else '   -   '}  {c}")
        raise SystemExit(0)
    print(uri(g.host, probe=not g.no_probe) if g.uri
          else resolve(g.host, probe=not g.no_probe))
