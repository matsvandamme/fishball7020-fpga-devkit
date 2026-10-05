#!/usr/bin/env python3
"""Execute ./devkit's help, its typo hints and its no-board path. No board needed.

    # run from: the repo root
    python3 tools/selftest/test_devkit_cli.py

Every check runs ./devkit and asserts on the exit code AND the output. The board
is pointed at 203.0.113.1 (TEST-NET-3, reserved by RFC 5737; nothing answers
there), so the no-board path is the one exercised, on any machine. Exit 0 if
every behaviour holds, 1 otherwise. Python 3.8.
"""
import os
import pathlib
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEVKIT = str(ROOT / "devkit")
NOBOARD = {"BOARD": "203.0.113.1"}
COMMANDS = ("doctor setup sim build verify flash write-card status selftest gpio-check net "
            "ssh-key tx-guard matlab clock completion uboot-contract temps loopback container adsb "
            "automation claude-pane").split()
FAILURES = []
CHECKS = 0


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok or not detail else "\n        " + detail))
    if not ok:
        FAILURES.append(name)


def run(args, env=None):
    e = dict(os.environ)
    e.update(env or {})
    t0 = time.monotonic()
    r = subprocess.run([DEVKIT] + args, capture_output=True, text=True, timeout=120, cwd=str(ROOT), env=e)
    return r.returncode, r.stdout + r.stderr, time.monotonic() - t0


# ---- help ------------------------------------------------------------------------
rc, out, _ = run([])
check("bare ./devkit prints one screen, not the whole manual",
      rc == 0 and len(out.splitlines()) <= 50 and "./devkit help <command>" in out,
      "exit=%s, %d lines" % (rc, len(out.splitlines())))
rc, out, _ = run(["help", "--all"])
check("help --all is the full text", rc == 0 and "---- Getting it onto the board" in out
      and len(out.splitlines()) > 100, "exit=%s, %d lines" % (rc, len(out.splitlines())))
for c in COMMANDS:
    rc, out, took = run(["help", c], env=NOBOARD)
    check("help %s says something, quickly" % c, rc in (0, 1) and len(out.strip().splitlines()) >= 2
          and took < 10, "exit=%s, %.1fs, out=%r" % (rc, took, out.strip()[:120]))

# Wrapped scripts whose own --help would act: their help must come from devkit.
for c, needle in (("setup", "Fetch the kernel and boot-loader source"), ("tx-guard", "The transmit gate"),
                  ("container", "pinned Vivado 2022.2"), ("status", "Where am I?"),
                  ("doctor", "Can this machine build?")):
    rc, out, took = run([c, "--help"], env=NOBOARD)
    check("%s --help prints devkit's own help and does nothing" % c,
          rc == 0 and needle in out and took < 5, "exit=%s, %.1fs, out=%r" % (rc, took, out.strip()[:120]))

# ---- typos and version -------------------------------------------------------------
rc, out, _ = run(["flsh"])
check("a typo is refused with a suggestion, not the manual",
      rc == 2 and "did you mean 'flash'" in out and len(out.splitlines()) <= 3, "exit=%s out=%r" % (rc, out[:160]))
rc, out, _ = run(["xyzzy"])
check("an unknown command with nothing close gets no suggestion",
      rc == 2 and "did you mean" not in out and "unknown command: xyzzy" in out, "exit=%s out=%r" % (rc, out[:160]))
rc, out, _ = run(["--version"])
check("--version names the devkit and each target's build",
      rc == 0 and out.startswith("devkit ") and "factory" in out and "modern" in out, "exit=%s out=%r" % (rc, out[:160]))

# ---- no board: every board command fails the same way, quickly -------------------
for args, code in ((["temps", "--once"], 1), (["loopback"], 1), (["clock"], 1), (["selftest"], 2),
                   (["net"], 1), (["gpio-check"], 1), (["uboot-contract"], 1), (["tx-guard", "status"], 4)):
    rc, out, took = run(args, env=NOBOARD)
    check("no board: %s exits %d with the shared message, in seconds" % (" ".join(args), code),
          rc == code and "No board found" in out and "203.0.113.1" in out and took < 10,
          "exit=%s, %.1fs, out=%r" % (rc, took, out.strip()[:160]))
rc, out, took = run(["status"], env=NOBOARD)
check("no board: status still reports the builds, and says the board was not found",
      rc == 0 and "== board ==" in out and "not found" in out and took < 10,
      "exit=%s, %.1fs, out=%r" % (rc, took, out.strip()[-160:]))
rc, out, _ = run(["clock", "--uri", "ip:203.0.113.1"])
check("an explicit unreachable address is a message, not a traceback",
      rc == 1 and "Traceback" not in out and "could not reach the board" in out, "exit=%s out=%r" % (rc, out[-160:]))

# ---- ssh-key --check tells "no key" from "no board" ------------------------------
with tempfile.TemporaryDirectory() as d:
    rc, out, _ = run(["ssh-key", "--check"], env=dict(NOBOARD, FISHBALL_SSH_KEY=d + "/none"))
    check("ssh-key --check with no key says to set it up",
          rc == 1 and "not set up yet" in out, "exit=%s out=%r" % (rc, out[-160:]))
    key = pathlib.Path(d) / "key"
    key.write_text("not really a key\n")
    rc, out, _ = run(["ssh-key", "--check"], env=dict(NOBOARD, FISHBALL_SSH_KEY=str(key)))
    check("ssh-key --check with a key but no board says the board is unreachable",
          rc == 1 and "not reachable" in out and "not set up" not in out, "exit=%s out=%r" % (rc, out[-160:]))

# ---- the Claude Code pane: start needs `claude`, and says where to get it ------------
rc, out, took = run(["claude-pane", "start"], env={"PATH": "/usr/bin:/bin"})
check("claude-pane start without Claude Code says where to get it, quickly",
      rc == 1 and "claude.com/claude-code" in out and took < 5, "exit=%s, %.1fs, out=%r" % (rc, took, out[-160:]))

print("\n%d/%d devkit behaviours hold" % (CHECKS - len(FAILURES), CHECKS))
if FAILURES:
    print("\nFAILED:")
    for n in FAILURES:
        print("  - " + n)
sys.exit(1 if FAILURES else 0)
