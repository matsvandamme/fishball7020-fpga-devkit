#!/usr/bin/env python3
"""One snapshot of the Fishball7020: board health, radio settings, GitHub
repo and CI, and the local build. Prints one JSON object on stdout.

    python3 collect.py [REPO_DIR] [--sections board,radio,repo,build]

REPO_DIR is the fishball7020-fpga-devkit checkout whose tools read the board;
by default, the one this file sits in (tools/claude-pane/bin/).

Only the sections named are probed and printed (all four by default), so a
caller can poll the board often and GitHub rarely. Each section is {"ok": true, ...} or {"ok": false, "error": "..."}; one section
failing (the board unplugged, gh logged out) never blanks the others, and the
exit code is always 0 once the JSON is printed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

ALL_SECTIONS = ("board", "radio", "repo", "build")


def parse_args(argv: list[str]) -> tuple[str, list[str]]:
    # bin/ -> the plugin -> tools/ -> the repo: the checkout this file came with
    repo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..")
    sections = list(ALL_SECTIONS)
    it = iter(argv)
    for a in it:
        if a == "--sections":
            sections = [x for x in next(it, "").split(",") if x in ALL_SECTIONS] or list(ALL_SECTIONS)
        elif a.startswith("--sections="):
            sections = [x for x in a.split("=", 1)[1].split(",") if x in ALL_SECTIONS] or list(ALL_SECTIONS)
        elif not a.startswith("-"):
            repo = a
    return os.path.abspath(repo), sections


REPO, SECTIONS = parse_args(sys.argv[1:])
TOOLS = os.path.join(REPO, "tools")
sys.path[:0] = [TOOLS, os.path.join(TOOLS, "selftest")]

PHY, XADC = "ad9361-phy", "xadc"
SSH_KEY = os.environ.get("FISHBALL_SSH_KEY") or os.path.expanduser("~/.ssh/fishball")   # as tools/ssh-key.sh
DEADLINE_S = 20


def run(argv: list[str], timeout: float = 10, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                          cwd=REPO, **kw)


# -- links -----------------------------------------------------------------
# The board is reached three ways, and the pane says which are up:
#   usb  - the USB cable's own network (the board's RNDIS/CDC gadget)
#   eth  - any other network path to it: a direct Ethernet cable, a switch, a LAN
#   iio  - libiio straight over USB, with no network at all (`usb:` URIs)
# Nothing here knows an address. Every place board_addr.py would look (its
# names and the USB gadget's address, or only $BOARD / $SDR_URI when set) is
# probed at once; each one that answers is told apart by the interface the
# route to it leaves on, which is "usb" when that interface is the board's own
# USB device. Data is read over the first network link that answers (usb, then
# eth), else over libiio USB.

USB_VENDOR = "0456"                    # Analog Devices: the board's USB gadget
USB_ID = USB_VENDOR + ":b673"
PROBE_DEADLINE_S = 2.5


def route_iface(addr: str) -> str | None:
    """The interface the route to addr leaves on, from `ip route get`."""
    try:
        r = run(["ip", "-o", "route", "get", addr], timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"\bdev (\S+)", r.stdout)
    return m.group(1) if m else None


def is_board_usb(iface: str) -> bool:
    """True when iface is the board's own USB network gadget."""
    try:
        with open(f"/sys/class/net/{iface}/device/../idVendor") as f:
            return f.read().strip() == USB_VENDOR
    except OSError:
        return False


def resolve_ip(host: str) -> str | None:
    import socket
    try:
        return socket.getaddrinfo(host, None, socket.AF_INET)[0][4][0]
    except (OSError, IndexError):
        return None


def probe_candidates() -> list[dict]:
    """Every board_addr candidate that answers, one entry per distinct address."""
    import threading
    from board_addr import candidates, identify                   # noqa: E402

    cands = candidates()
    # As board_addr.check(): an address in $BOARD / $SDR_URI is the only one probed.
    if os.environ.get("BOARD") or os.environ.get("SDR_URI"):
        cands = cands[:1]
    found: dict[str, dict] = {}

    def work(c: str) -> None:
        try:
            kind = identify(c)
            if kind not in ("iiod", "dropbear", "openssh-debian"):
                return
            ip = resolve_ip(c) or c
            iface = route_iface(ip)
            found[c] = {"host": c, "ip": ip, "iface": iface, "iiod": kind != "openssh-debian",
                        "kind": "usb" if iface and is_board_usb(iface) else "eth"}
        except Exception:
            pass

    threads = [threading.Thread(target=work, args=(c,), daemon=True) for c in cands]
    for t in threads:
        t.start()
    end = time.time() + PROBE_DEADLINE_S
    for t in threads:
        t.join(max(0.0, end - time.time()))
    seen: dict[str, dict] = {}
    for c in cands:                      # board_addr's priority order
        hit = found.get(c)
        if hit and hit["ip"] not in seen:
            seen[hit["ip"]] = hit
        elif hit and hit["iiod"] and not seen[hit["ip"]]["iiod"]:
            seen[hit["ip"]] = hit
    return list(seen.values())


def probe_iio_usb() -> str | None:
    r = run(["iio_info", "-s"], timeout=8)
    for line in r.stdout.splitlines():
        if USB_ID in line:
            m = re.search(r"\[(usb:[^\]]+)\]", line)
            if m:
                return m.group(1)
    return None


def link_row(name: str, hit: dict | None, fallback: str) -> dict:
    if hit is None:
        return {"name": name, "addr": fallback, "up": False, "iiod": False}
    addr = hit["host"] if hit["host"] == hit["ip"] else f"{hit['host']} ({hit['ip']})"
    return {"name": name, "addr": addr, "iface": hit["iface"], "up": True, "iiod": hit["iiod"]}


def links() -> dict:
    """{"links": [...], "host": addr or None, "iiod": bool, "usb_uri": uri or None}"""
    from board_addr import USB                                     # noqa: E402
    ex = ThreadPoolExecutor(2)
    nets_f = ex.submit(probe_candidates)
    usb_f = ex.submit(probe_iio_usb)
    try:
        nets = nets_f.result(timeout=PROBE_DEADLINE_S + 4)
    except Exception:
        nets = []
    try:
        usb_uri = usb_f.result(timeout=8)
    except Exception:
        usb_uri = None
    ex.shutdown(wait=False)

    def pick(kind: str) -> dict | None:
        hits = [n for n in nets if n["kind"] == kind]
        return next((n for n in hits if n["iiod"]), hits[0] if hits else None)

    usb, eth = pick("usb"), pick("eth")
    out: dict = {"links": [link_row("usb", usb, USB), link_row("eth", eth, "no answer"),
                           {"name": "iio", "addr": usb_uri or "usb:", "up": usb_uri is not None,
                            "iiod": usb_uri is not None}],
                 "host": None, "iiod": False, "usb_uri": usb_uri}
    best = next((n for n in (usb, eth) if n and n["iiod"]), usb or eth)
    if best:
        out["host"], out["iiod"] = best["ip"], best["iiod"]
    return out


# -- readers: the same attribute reads over iiod (TCP) or libiio USB ----------

class NetReader:
    def __init__(self, host: str):
        from iiod_min import Iiod                                 # noqa: E402
        self.c = Iiod(host, timeout=5.0)
        self.c.connect()
        self.via = f"iiod {host}"

    def read(self, dev, ch, attr, output=False) -> str:
        return self.c.read(dev, ch, attr, output=output)

    def context_attrs(self) -> dict:
        return self.c.context_attrs()

    def close(self):
        self.c.close()


class UsbReader:
    def __init__(self, uri: str):
        self.uri = uri
        self.via = f"libiio {uri}"

    def read(self, dev, ch, attr, output=False) -> str:
        r = run(["iio_attr", "-u", self.uri, "-c", "-o" if output else "-i",
                 dev, ch, attr], timeout=5)
        if r.returncode != 0 or not r.stdout.strip():
            raise OSError(f"iio_attr {dev} {ch} {attr}: {r.stderr.strip() or 'no value'}")
        return r.stdout.strip()

    def context_attrs(self) -> dict:
        r = run(["iio_attr", "-u", self.uri, "-C"], timeout=5)
        attrs = {}
        for line in r.stdout.splitlines()[1:]:
            k, sep, v = line.partition(": ")
            if sep:
                attrs[k.strip()] = v.strip()
        return attrs

    def close(self):
        pass


def reader(link: dict):
    if link["host"] and link["iiod"]:
        try:
            return NetReader(link["host"])
        except OSError:
            pass
    if link["usb_uri"]:
        return UsbReader(link["usb_uri"])
    return None


# -- board -----------------------------------------------------------------

def board(link: dict) -> dict:
    out: dict = {"links": link["links"]}
    host = link["host"]
    if host is None and link["usb_uri"] is None:
        return {**out, "ok": False, "online": False, "error": "board not found on USB or the network"}
    out.update({"ok": True, "online": True, "host": host})

    # uptime and load over ssh: the one thing iiod does not publish. Every
    # board shares the USB address and a reflashed one gets a new host key, so
    # this read-only call neither checks nor records one (as tools/net.sh).
    if host:
        try:
            r = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3",
                     "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                     "-o", "LogLevel=ERROR", "-o", "IdentitiesOnly=yes", "-i", SSH_KEY,
                     f"root@{host}", "cat /proc/uptime /proc/loadavg"], timeout=8)
            if r.returncode == 0:
                lines = r.stdout.split("\n")
                out["uptime_s"] = float(lines[0].split()[0])
                out["load"] = [float(x) for x in lines[1].split()[:3]]
        except (subprocess.TimeoutExpired, IndexError, ValueError):
            pass

    c = reader(link)
    if c is None:
        out["error"] = "iiod not answering (only ssh does)"
        return out
    try:
        from board_info import describe                           # noqa: E402
        attrs = c.context_attrs()
        out.update(dict(describe(attrs)))
        out["fw_build"] = attrs.get("fw_build")
        out["via"] = c.via
        out.update(compare_build(out["fw_build"]))
        raw, off, scale = (float(c.read(XADC, "temp0", k)) for k in ("raw", "offset", "scale"))
        out["temps_c"] = {"zynq": round((raw + off) * scale / 1000.0, 1),
                          "ad9361": round(float(c.read(PHY, "temp0", "input")) / 1000.0, 1)}
    finally:
        c.close()
    return out


def compare_build(fw_build: str | None) -> dict:
    """How the board's firmware build relates to the local checkout.

    fw_build is a `git describe` of the devkit at build time (v2.0-9-g5ae29d94
    -dirty); the g<sha> in it is a commit of this repo, so `rev-list --count`
    says how many local commits the board has not got. Cheap: local git only.
    """
    out: dict = {"local_describe": run(["git", "describe", "--always", "--dirty"],
                                       timeout=5).stdout.strip() or None}
    m = re.search(r"-g([0-9a-f]{7,40})", fw_build or "")
    if not m:
        return out
    sha = m.group(1)
    r = run(["git", "rev-list", "--count", f"{sha}..HEAD"], timeout=5)
    if r.returncode == 0 and r.stdout.strip().isdigit():
        out["behind"] = int(r.stdout.strip())
        ahead = run(["git", "rev-list", "--count", f"HEAD..{sha}"], timeout=5).stdout.strip()
        out["ahead"] = int(ahead) if ahead.isdigit() else 0
    else:
        out["behind_error"] = f"commit {sha} not in the local history"
    return out


# -- radio -----------------------------------------------------------------
# The same (device, channel, attr, direction) the repo's own tools read:
# LOs as in clock-cal.py, TX attenuation as in temps.py, the rest as the
# automation server's sysfs names (in_voltage_sampling_frequency and so on).

def radio(link: dict) -> dict:
    c = reader(link)
    if c is None:
        return {"ok": False, "error": "board offline" if link["host"] is None else "iiod not answering"}

    def num(v: str) -> float:
        return float(v.split()[0])

    try:
        out = {
            "ok": True,
            "via": c.via,
            "rx_lo_hz": num(c.read(PHY, "altvoltage0", "frequency", output=True)),
            "tx_lo_hz": num(c.read(PHY, "altvoltage1", "frequency", output=True)),
            "sample_rate_hz": num(c.read(PHY, "voltage0", "sampling_frequency")),
            "rx_bw_hz": num(c.read(PHY, "voltage0", "rf_bandwidth")),
            "tx_bw_hz": num(c.read(PHY, "voltage0", "rf_bandwidth", output=True)),
            "channels": [],
        }
        for ch in (0, 1):
            out["channels"].append({
                "rx_gain_db": num(c.read(PHY, f"voltage{ch}", "hardwaregain")),
                "gain_mode": c.read(PHY, f"voltage{ch}", "gain_control_mode").strip(),
                "tx_atten_db": num(c.read(PHY, f"voltage{ch}", "hardwaregain", output=True)),
            })
    finally:
        c.close()
    return out


# -- GitHub ------------------------------------------------------------------

def slug() -> str:
    url = run(["git", "remote", "get-url", "origin"]).stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    if not m:
        raise RuntimeError(f"origin is not a GitHub remote: {url or 'none'}")
    return m.group(1)


def gh_json(args: list[str]):
    r = run(["gh", *args], timeout=15)
    if r.returncode != 0:
        raise RuntimeError((r.stderr.strip().splitlines() or ["gh failed"])[-1])
    return json.loads(r.stdout)


def repo() -> dict:
    s = slug()
    with ThreadPoolExecutor(5) as ex:
        runs = ex.submit(gh_json, ["run", "list", "-R", s, "-L", "30", "--json",
                                   "workflowName,conclusion,status,createdAt,headBranch,url"])
        view = ex.submit(gh_json, ["repo", "view", s, "--json",
                                   "stargazerCount,forkCount,watchers"])
        prs = ex.submit(gh_json, ["pr", "list", "-R", s, "--json", "number", "-L", "200"])
        issues = ex.submit(gh_json, ["issue", "list", "-R", s, "--json", "number", "-L", "200"])
        runners = ex.submit(gh_json, ["api", f"repos/{s}/actions/runners"])

        # newest run per workflow
        latest: dict[str, dict] = {}
        for r in runs.result():
            latest.setdefault(r["workflowName"], r)
        v = view.result()
        out = {
            "ok": True,
            "slug": s,
            "stars": v["stargazerCount"],
            "forks": v["forkCount"],
            "open_prs": len(prs.result()),
            "open_issues": len(issues.result()),
            "workflows": [{"name": k, "status": r["status"], "conclusion": r["conclusion"],
                           "branch": r["headBranch"], "at": r["createdAt"]}
                          for k, r in sorted(latest.items())],
        }
        try:
            out["runners"] = [{"name": r["name"], "status": r["status"], "busy": r["busy"]}
                              for r in runners.result().get("runners", [])]
        except RuntimeError as e:
            out["runners_error"] = str(e)
    return out


# -- local build --------------------------------------------------------------

def build() -> dict:
    head = run(["git", "log", "-1", "--format=%h %s"]).stdout.strip()
    describe = run(["git", "describe", "--always", "--dirty"]).stdout.strip()
    dirty = bool(run(["git", "status", "--porcelain"]).stdout.strip())
    r = run(["./devkit", "status"], timeout=DEADLINE_S - 2)
    sections: dict[str, list[str]] = {}
    name = None
    for line in r.stdout.splitlines():
        m = re.match(r"^== (.+) ==$", line)
        if m:
            name = m.group(1)
            sections[name] = []
        elif name and line.strip():
            sections[name].append(line.strip())
    sections.pop("board", None)        # the board section has its own, live
    sections.pop("repo", None)         # head and describe say it better
    return {"ok": True, "head": head, "describe": describe, "dirty": dirty,
            "sections": sections}


# -- all of it ----------------------------------------------------------------

def guarded(fn, *args) -> dict:
    try:
        return fn(*args)
    except Exception as e:                       # one section, never the whole
        return {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}


def main() -> None:
    started = time.time()
    want = set(SECTIONS)
    ex = ThreadPoolExecutor(6)      # not a with: its exit would wait on a hung thread
    futures: dict = {}
    if "repo" in want:
        futures["repo"] = ex.submit(guarded, repo)
    if "build" in want:
        futures["build"] = ex.submit(guarded, build)
    if want & {"board", "radio"}:
        found_f = ex.submit(links)
        try:
            found = found_f.result(timeout=10)
        except Exception:
            found = {"links": [], "host": None, "iiod": False, "usb_uri": None}
        if "board" in want:
            futures["board"] = ex.submit(guarded, board, found)
        if "radio" in want:
            futures["radio"] = ex.submit(guarded, radio, found)

    def take(f) -> dict:
        try:
            return f.result(timeout=max(1, DEADLINE_S - (time.time() - started)))
        except Exception as e:
            return {"ok": False, "error": f"timed out ({type(e).__name__})"}

    snap = {name: take(futures[name]) for name in ALL_SECTIONS if name in futures}
    snap["sections"] = [name for name in ALL_SECTIONS if name in futures]
    snap["took_s"] = round(time.time() - started, 1)
    print(json.dumps(snap))
    sys.stdout.flush()
    os._exit(0)        # do not wait on a name lookup still running in a thread


if __name__ == "__main__":
    main()
