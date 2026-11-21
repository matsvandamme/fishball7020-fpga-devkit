#!/usr/bin/env python3
"""The host tools on a machine that is not the one they were written on. No board needed.

    # run from: the repo root
    python3 tools/selftest/test_host_tools.py

These tools grew up on Linux with bash 5, GNU coreutils and sshpass. This runs
what can be run without a board, the way a Mac runs it: macOS's /bin/bash is
3.2, its userland is BSD, and it has no sshpass. Every check here is a
behaviour that was broken there, and CI runs the file on Linux and macOS both.

`ssh` and `sshpass` are fakes first on PATH, so no check can reach a board;
BOARD points at 203.0.113.1 (TEST-NET-3) besides. Two kinds of fake: one that
only records its arguments, and a board (FAKE_BOARD below) whose ssh checks the
login the way a board does and then runs the remote command against a fake
root - a card, /proc/mounts, mount, umount and reboot - so flash, ssh-key and
net run from end to end, failures included.
Exit 0 if every behaviour holds, 1 otherwise. Python 3.8.
"""
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
DEVKIT = str(ROOT / "devkit")
MAC = sys.platform == "darwin"
FAILURES = []
CHECKS = 0

# Every shell script the host runs. All of them must parse under the oldest
# bash anyone has, and none may use what only bash 4 or GNU has.
HOST_SCRIPTS = [ROOT / "devkit", TOOLS / "flash.sh", TOOLS / "net.sh", TOOLS / "ssh-key.sh",
                TOOLS / "uboot-contract.sh", TOOLS / "throughput-ab.sh", TOOLS / "board-busy.sh",
                TOOLS / "automation" / "automation.sh", TOOLS / "matlab.sh",
                TOOLS / "lib" / "board-ssh.sh", TOOLS / "devkit-completion.bash",
                ROOT / "firmware-modern" / "write_card.sh", ROOT / "firmware" / "scripts" / "doctor.sh"]


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok or not detail else "\n        " + detail))
    if not ok:
        FAILURES.append(name)


def run(argv, env=None, cwd=ROOT, stdin=subprocess.DEVNULL):
    r = subprocess.run([str(a) for a in argv], capture_output=True, text=True, timeout=120,
                       cwd=str(cwd), env=env, stdin=stdin)
    return r.returncode, r.stdout + r.stderr


def fake_path(d, sshpass):
    """A PATH with a recording `ssh`, with or without a recording `sshpass`,
    and no real one of either. A machine that has sshpass installed has it in
    /usr/bin beside everything else, so "without" cannot be done by leaving a
    directory out: every other program is linked into one directory instead."""
    d = pathlib.Path(d)
    bin_ = d / "bin"
    bin_.mkdir()
    for p in os.environ["PATH"].split(os.pathsep) + [str(pathlib.Path(sys.executable).parent)]:
        try:
            names = os.listdir(p)
        except OSError:
            continue
        for n in names:
            if n not in ("ssh", "sshpass") and not (bin_ / n).exists():
                try:
                    os.symlink(os.path.join(p, n), str(bin_ / n))
                except OSError:
                    pass
    log = d / "calls"
    # One line per call: the program, then its arguments, tab-separated.
    fake = '#!/bin/sh\n{ printf "%%s" "%s"; for a in "$@"; do printf "\\t%%s" "$a"; done; echo; } >> "%s"\n%s\n'
    # FAKE_SSH_DOWN: nothing answers. FAKE_SSH_REFUSE_KEY: the board answers and
    # refuses a login made with -i, the way a card that has never seen the key does.
    (bin_ / "ssh").write_text(fake % ("ssh", log, """if [ -n "${FAKE_SSH_DOWN:-}" ]; then
    echo "ssh: connect to host 203.0.113.1 port 22: Operation timed out" >&2; exit 255
fi
if [ -n "${FAKE_SSH_REFUSE_KEY:-}" ]; then
    for a in "$@"; do
        [ "$a" != -i ] || { echo "root@203.0.113.1: Permission denied (publickey,password)." >&2; exit 255; }
    done
fi
exit "${FAKE_SSH_RC:-0}\""""))
    (bin_ / "ssh").chmod(0o755)
    if sshpass:
        # Like the real one: -p PASSWORD, then run the rest.
        (bin_ / "sshpass").write_text(fake % ("sshpass", log, 'shift 2; exec "$@"'))
        (bin_ / "sshpass").chmod(0o755)
    return str(bin_), log


def calls(log):
    try:
        return [l.split("\t") for l in pathlib.Path(log).read_text().splitlines()]
    except OSError:
        return []


def base_env(path, home, **more):
    e = {"PATH": path, "HOME": str(home), "BOARD": "203.0.113.1"}
    e.update(more)
    return e


# ---- a fake board -----------------------------------------------------------------
# What stands in for the board when a tool has to be run from end to end. Its
# `ssh` decides the login as a board does (is the offered key in
# /root/.ssh/authorized_keys? is the password right, and was one allowed?) and
# then runs the remote command locally with every board path moved under a fake
# root: a card (a directory), /proc/mounts kept by a fake mount and umount, and
# a reboot that empties /tmp, forgets /root on a RAM-disk root, and runs the
# line of the board's own boot script that restores keys from /mnt/jffs2.
#
# Files in the fake root steer it:
#   down, stay-down   nothing answers (now / after the next reboot)
#   fail              lines "TIMES<tab>EXIT<tab>TEXT<tab>STDERR": the next TIMES
#                     commands containing TEXT fail with EXIT instead of running.
#                     STDERR "PARTIAL": the command runs on the first 3 bytes of
#                     its input and then fails - a connection dropped mid-copy.
#   fail-bind         mount --bind fails
#   hostkey-changed   `ssh <alias>`, which goes through known_hosts, is refused
FAKE_BOARD = r'''
import hashlib, os, re, shutil, subprocess, sys
R = os.environ["FAKE_BOARD"]
MOUNTS = R + "/proc/mounts"


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return default


def write(path, text):
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def local(cmd):
    """A command written for the board, with its paths moved under the fake root."""
    cmd = re.sub(r"(?<![\w.$}/-])/(proc|tmp|opt|root|mnt|etc|boot)\b", lambda m: R + m.group(0), cmd)
    return re.sub(r"\bcd /(?=\s|;|$)", "cd " + R, cmd, flags=re.M)


def sh(cmd, shell="/bin/sh", **kw):
    env = dict(os.environ, PATH=R + "/bin" + os.pathsep + os.environ["PATH"])
    return subprocess.run([shell, "-c", local(cmd)], env=env, **kw).returncode


def table():
    return [l.split() for l in read(MOUNTS).splitlines() if l.strip()]


def save(rows):
    write(MOUNTS, "".join(" ".join(r) + "\n" for r in rows))


def ssh(args):
    with open(R + "/calls", "a") as f:
        f.write("\t".join(["ssh"] + args) + "\n")
    opts, ident, i = {}, None, 0
    while i < len(args):
        a = args[i]
        if a == "-o":
            k, _, v = args[i + 1].partition("=")
            opts[k.lower()] = v
            i += 2
        elif a == "-i":
            ident = args[i + 1]
            i += 2
        elif a == "-G":
            print("hostname 203.0.113.1")
            return 0
        elif a.startswith("-"):
            i += 1
        else:
            break
    target, cmd = args[i], " ".join(args[i + 1:])
    if os.path.exists(R + "/down") or os.path.exists(R + "/rebooting"):
        sys.stderr.write("ssh: connect to host %s port 22: Connection refused\n" % target)
        return 255
    if "@" not in target:                   # the Host alias: the one login that uses known_hosts
        if os.path.exists(R + "/hostkey-changed"):
            sys.stderr.write("@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n"
                             "Host key verification failed.\n")
            return 255
        return 0
    plan = [l.split("\t") for l in read(R + "/fail").splitlines() if l]
    for step in plan:
        if int(step[0]) > 0 and step[2] in cmd:
            step[0] = str(int(step[0]) - 1)
            write(R + "/fail", "".join("\t".join(x) + "\n" for x in plan))
            if step[3] == "PARTIAL":
                sh(cmd, input=sys.stdin.buffer.read(3))
            else:
                sys.stderr.write(step[3] + "\n")
            return int(step[1])
    # The login. Keys first, as ssh does: the one given with -i, and - unless
    # IdentitiesOnly forbids it - the one this user has anyway (FAKE_DEFAULT_KEY).
    offered = []
    if opts.get("pubkeyauthentication") != "no":
        offered = [ident] if ident else []
        if opts.get("identitiesonly") != "yes" and os.environ.get("FAKE_DEFAULT_KEY"):
            offered.append(os.environ["FAKE_DEFAULT_KEY"])
    known = read(R + "/root/.ssh/authorized_keys").splitlines()
    ok = any(read(k + ".pub").strip() in known for k in offered if read(k + ".pub").strip())
    password = os.environ.get("FAKE_SSHPASS")           # set by the fake sshpass
    if not ok and password is not None and opts.get("batchmode") != "yes":
        if password != read(R + "/password").strip():
            return 99                                   # the fake sshpass turns this into its exit 5
        ok = True
    if not ok:
        sys.stderr.write("%s: Permission denied (publickey,password).\n" % target)
        return 255
    # A card mounted read-only refuses a write, as the real one does.
    if "/tmp/sd/" in cmd and re.search(r"cat > |\bcp |\bmv |\brm -f ", cmd):
        row = [r for r in table() if r[1] == R + "/tmp/sd"]
        if row and row[0][3].split(",")[0] != "rw":
            sys.stderr.write("sh: Read-only file system\n")
            return 1
    return sh(cmd)


def link(mountpoint, on):
    """The card appears at a mountpoint, or goes away again."""
    if on:
        if os.path.isdir(mountpoint) and not os.path.islink(mountpoint):
            os.rmdir(mountpoint)
        os.symlink(R + "/card", mountpoint)
    else:
        os.unlink(mountpoint)
        os.mkdir(mountpoint)


def mount(args):
    rows = table()
    at = {r[1]: r for r in rows}
    if args[0] == "--bind":
        src, dst = args[1], args[2]
        if os.path.exists(R + "/fail-bind") or src not in at or dst in at:
            sys.stderr.write("mount: %s: bind mount failed\n" % dst.replace(R, ""))
            return 32
        rows.append([at[src][0], dst] + at[src][2:])
        link(dst, True)
    elif args[0] == "-o" and args[1].startswith("remount,"):
        mode, where = args[1].split(",")[1], args[2]
        if where not in at:
            sys.stderr.write("mount: %s: mount point not mounted\n" % where.replace(R, ""))
            return 32
        for r in rows:                      # a bind shares its read-only state with the original
            if r[0] == at[where][0]:
                r[3] = ",".join([mode] + r[3].split(",")[1:])
    elif args[0] == "-o" and len(args) == 4:
        mode, dev, where = args[1], args[2], args[3]
        if any(r[0] == dev for r in rows) or where in at:
            sys.stderr.write("mount: %s: %s already mounted\n" % (where.replace(R, ""), dev))
            return 32
        rows.append([dev, where, "vfat", mode + ",relatime", "0", "0"])
        link(where, True)
    else:
        sys.stderr.write("fake mount: what is %r?\n" % (args,))
        return 2
    save(rows)
    return 0


def umount(args):
    rows = table()
    if args[0] not in [r[1] for r in rows]:
        sys.stderr.write("umount: %s: not mounted\n" % args[0].replace(R, ""))
        return 32
    save([r for r in rows if r[1] != args[0]])
    if os.path.islink(args[0]):
        link(args[0], False)
    return 0


def reboot(args):
    open(R + "/rebooting", "w").close()
    for n in os.listdir(R + "/tmp"):        # /tmp is tmpfs
        p = os.path.join(R, "tmp", n)
        if os.path.islink(p) or os.path.isfile(p):
            os.unlink(p)
        else:
            shutil.rmtree(p)
    shutil.copy(MOUNTS + ".boot", MOUNTS)
    if os.path.exists(R + "/ramroot"):      # Buildroot: / is a RAM disk, rebuilt at every boot
        shutil.rmtree(R + "/root/.ssh", ignore_errors=True)
        sh(read(R + "/S21misc"), shell="bash", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if os.path.exists(R + "/stay-down"):
        open(R + "/down", "w").close()
    write(R + "/proc/uptime", "5.25 3.10\n")
    with open(R + "/boots", "a") as f:
        f.write("boot\n")
    os.unlink(R + "/rebooting")
    return 0


def md5sum(args):
    """Plain files, and busybox's `-s -c LIST`."""
    def digest(path):
        with open(path, "rb") as f:
            return hashlib.md5(f.read()).hexdigest()
    names = [a for a in args if not a.startswith("-")]
    if "-c" in args:
        try:
            return 0 if all(digest(l.split()[1]) == l.split()[0] for l in read(names[0]).splitlines() if l.strip()) \
                and read(names[0]).strip() else 1
        except OSError:
            return 1
    for n in names:
        try:
            print("%s  %s" % (digest(n), n))
        except OSError as exc:
            sys.stderr.write("md5sum: %s: %s\n" % (n, exc.strerror))
            return 1
    return 0


def fw_setenv(args):
    env = dict(l.split("=", 1) for l in read(R + "/uboot.env").splitlines() if "=" in l)
    env.pop(args[0], None)
    if len(args) > 1:
        env[args[0]] = " ".join(args[1:])
    write(R + "/uboot.env", "".join("%s=%s\n" % kv for kv in sorted(env.items())))
    return 0


def fw_printenv(args):
    env = dict(l.split("=", 1) for l in read(R + "/uboot.env").splitlines() if "=" in l)
    rc = 0
    for n in [a for a in args if not a.startswith("-")]:
        if n in env:
            print(env[n] if "-n" in args else "%s=%s" % (n, env[n]))
        else:
            sys.stderr.write("## Error: \"%s\" not defined\n" % n)
            rc = 1
    return rc


sys.exit({"ssh": ssh, "mount": mount, "umount": umount, "reboot": reboot, "md5sum": md5sum,
          "fw_setenv": fw_setenv, "fw_printenv": fw_printenv}[sys.argv[1]](sys.argv[2:]))
'''
# The line of the factory boot script (buildroot/board/pluto/S21misc) that puts
# authorised keys back after a reboot, taken from the patch that carries it as
# context: what ssh-key writes to /mnt/jffs2 is judged by the code that reads it.
S21_KEYS = next(l.strip() for l in (ROOT / "firmware" / "patches" / "0004-mute-tx-when-no-dma-stream.patch")
                .read_text().splitlines() if "/mnt/jffs2/root/.ssh" in l and "keys.md5" in l)
OLD = {"BOOT.bin": "old boot\n", "uImage": "old kernel\n"}
NEW = {"BOOT.bin": "NEW boot\n", "uImage": "NEW kernel\n"}


def board_path(d, sshpass):
    """fake_path, with the fake board's ssh (and sshpass), a sleep that does not,
    and an ssh-copy-id that only records that it was called."""
    d = pathlib.Path(d)
    d.mkdir()
    path, _ = fake_path(d, sshpass=False)
    bin_ = pathlib.Path(path)
    tool = d / "fakeboard.py"
    tool.write_text(FAKE_BOARD)
    (bin_ / "ssh").write_text('#!/bin/sh\nexec "%s" "%s" ssh "$@"\n' % (sys.executable, tool))
    scripts = {"sleep": "exit 0", "ssh-copy-id": 'echo "ssh-copy-id $*" >> "$FAKE_BOARD/calls"; exit 1'}
    if sshpass:
        # Like the real one: -p PASSWORD, run the rest, and exit 5 for a refused password.
        scripts["sshpass"] = ('printf "sshpass\\t%s\\t%s\\n" "$1" "$2" >> "$FAKE_BOARD/calls"\n'
                              'FAKE_SSHPASS="$2"; export FAKE_SSHPASS; shift 2\n"$@"; rc=$?\n'
                              '[ $rc -ne 99 ] || exit 5\nexit $rc')
    for name, body in scripts.items():
        f = bin_ / name
        if f.is_symlink() or f.exists():
            f.unlink()
        f.write_text("#!/bin/sh\n%s\n" % body)
        f.chmod(0o755)
    return path, tool


class Board:
    """A fake root. layout: "debian-rw", "debian-ro" (how /boot is mounted) or
    "buildroot" (the card not mounted, / a RAM disk, /mnt/jffs2 the only thing kept)."""

    def __init__(self, d, layout, tool):
        self.r = r = pathlib.Path(d)
        self.layout = layout
        for sub in ("bin", "proc", "tmp", "card", "opt", "root", "etc", "mnt/jffs2"):
            (r / sub).mkdir(parents=True)
        for name, text in OLD.items():
            (r / "card" / name).write_text(text)
        for name in ("mount", "umount", "reboot", "md5sum", "fw_setenv", "fw_printenv"):
            (r / "bin" / name).write_text('#!/bin/sh\nexec "%s" "%s" %s "$@"\n' % (sys.executable, tool, name))
        for name in ("sleep", "sync", "chown"):
            (r / "bin" / name).write_text("#!/bin/sh\nexit 0\n")
        for f in (r / "bin").iterdir():
            f.chmod(0o755)
        jffs2 = "/dev/mtdblock2 %s/mnt/jffs2 jffs2 rw,noatime 0 0\n" % r
        if layout == "buildroot":
            mounts = "rootfs %s/ rootfs rw 0 0\n" % r + jffs2
            (r / "etc" / "os-release").write_text("NAME=Buildroot\nID=buildroot\n")
            (r / "ramroot").write_text("")
            (r / "S21misc").write_text(S21_KEYS + "\n")
        else:
            os.symlink(str(r / "card"), str(r / "boot"))
            mounts = ("/dev/mmcblk0p2 %s/ ext4 rw,relatime 0 0\n" % r
                      + "/dev/mmcblk0p1 %s/boot vfat %s,relatime 0 0\n" % (r, layout[-2:]) + jffs2)
            (r / "etc" / "os-release").write_text('PRETTY_NAME="Debian GNU/Linux 13 (trixie)"\nID=debian\n')
        (r / "proc" / "mounts").write_text(mounts)
        (r / "proc" / "mounts.boot").write_text(mounts)
        (r / "proc" / "uptime").write_text("1000.50 900.00\n")
        (r / "password").write_text("analog\n")
        (r / "opt" / "VERSIONS").write_text("fake-board v0\n")
        self.start = self.mounts()

    def mounts(self):
        return (self.r / "proc" / "mounts").read_text().replace(str(self.r), "")

    def card(self):
        return {f.name: f.read_text() for f in (self.r / "card").iterdir()}

    def authorise(self, key):
        """Put a key in /root/.ssh by hand: on a RAM-disk root it lasts until the reboot."""
        (self.r / "root" / ".ssh").mkdir(exist_ok=True)
        with open(str(self.r / "root" / ".ssh" / "authorized_keys"), "a") as f:
            f.write(pathlib.Path(str(key) + ".pub").read_text())

    def fail(self, *steps):
        (self.r / "fail").write_text("".join("\t".join(str(x) for x in s) + "\n" for s in steps))

    def calls(self, clear=False):
        got = calls(self.r / "calls")
        if clear:
            (self.r / "calls").write_text("")
        return got

    def boots(self):
        return len((self.r / "boots").read_text().splitlines()) if (self.r / "boots").exists() else 0

    def left_alone(self):
        """Is the board's mount state exactly as the tool found it? Nothing at
        /tmp/sd (an empty directory may remain: it is the mount point), no note
        of a state still to be put back, and /proc/mounts as it was."""
        sd = self.r / "tmp" / "sd"
        problems = []
        if self.mounts() != self.start:
            problems.append("mounts are now %r" % self.mounts())
        if sd.is_symlink() or (sd.exists() and any(sd.iterdir())):
            problems.append("/tmp/sd is still the card, or has files in it")
        if (self.r / "tmp" / "sd.was").exists():
            problems.append("/tmp/sd.was is left behind")
        return "; ".join(problems)


def fake_key(path, text):
    """A key file and its public half. The fake board compares the public halves."""
    pathlib.Path(path).write_text("private half of %s\n" % text)
    pathlib.Path(str(path) + ".pub").write_text("ssh-ed25519 AAAA%s %s\n" % (text, text))
    return str(path)


# ---- 1. every host script parses under this bash, and avoids what 3.2 lacks -------
ver = run(["bash", "-c", "echo $BASH_VERSION"])[1].strip()
print("bash %s%s" % (ver, "  (macOS: /bin/bash is 3.2)" if MAC else ""))
if MAC:
    # Everything below is about bash 3.2. A newer bash earlier on PATH (Homebrew's)
    # would run it all and prove nothing, quietly.
    check("the bash these checks run is the 3.x macOS ships, not a newer one first on PATH",
          ver.startswith("3."), "%s is %s" % (shutil.which("bash"), ver))
for s in HOST_SCRIPTS:
    rc, out = run(["bash", "-n", s])
    check("%s parses" % s.relative_to(ROOT), rc == 0, out.strip()[:200])
# bash 4 only: mapfile/readarray, associative arrays, ${x,,} and ${x^^}, |&, coproc.
# GNU only: stat -c, paste -s with no "-" operand, readlink -f.
BASH4 = re.compile(r"^\s*(mapfile|readarray|coproc)\b|\bdeclare -A\b|\blocal -A\b|\$\{\w+(,,|\^\^)\}|\|&")
GNU = re.compile(r"\bstat -c|\bpaste -sd\S*\s*(\)|\||$)|\breadlink -f\b")
for s in HOST_SCRIPTS:
    hits = ["%d: %s" % (i, l.strip()) for i, l in enumerate(s.read_text().splitlines(), 1)
            if not l.lstrip().startswith("#") and (BASH4.search(l) or GNU.search(l))]
    check("%s uses nothing only bash 4 or GNU has" % s.relative_to(ROOT), not hits, "; ".join(hits)[:300])

# ---- 2. the one login helper: the key alone, then everything else, else say how ---
HELPER = TOOLS / "lib" / "board-ssh.sh"
SH_CALL = '. "%s"; board_ssh_require || exit 2; board_ssh 203.0.113.1 "echo hi"' % HELPER
PY_CALL = ('import subprocess, sys; sys.path.insert(0, %r); import board_ssh\n'
           'if not board_ssh.can_login(): print(board_ssh.hint(), file=sys.stderr); sys.exit(2)\n'
           'sys.exit(subprocess.run(board_ssh.ssh_argv("203.0.113.1") + ["echo hi"]).returncode)') % str(TOOLS)
INSTALL = "brew install sshpass" if MAC else "sudo apt install sshpass"
USUAL = ("StrictHostKeyChecking=no", "UserKnownHostsFile=/dev/null", "LogLevel=ERROR", "ConnectTimeout=10")
for label, argv in (("board-ssh.sh", ["bash", "-c", SH_CALL]), ("board_ssh.py", [sys.executable, "-c", PY_CALL])):
    for have_key in (True, False):
        for have_sshpass in (True, False):
            with tempfile.TemporaryDirectory() as d:
                path, log = fake_path(d, have_sshpass)
                key = pathlib.Path(d) / "key"
                if have_key:
                    key.write_text("not really a key\n")
                env = base_env(path, d, FISHBALL_SSH_KEY=str(key), BOARD_PASS="hunter2")
                what = "%s, %s key, %s sshpass" % (label, "a" if have_key else "no", "with" if have_sshpass else "no")

                def attempt(**more):
                    pathlib.Path(log).write_text("")
                    rc, out = run(argv, env=dict(env, **more))
                    got = calls(log)
                    return rc, out, got, [c for c in got if c[0] == "ssh"]

                rc, out, got, sshs = attempt()
                if not have_key and not have_sshpass:
                    check(what + ": stops before any ssh, naming both fixes",
                          rc == 2 and not got and "./devkit ssh-key" in out and INSTALL in out,
                          "exit=%s calls=%r out=%r" % (rc, got, out[:200]))
                    continue
                ssh = sshs[0] if sshs else []
                check(what + ": ssh root@board with the options these tools always used",
                      rc == 0 and len(sshs) == 1 and all(o in ssh for o in USUAL)
                      and ssh[-2:] == ["root@203.0.113.1", "echo hi"], "exit=%s calls=%r" % (rc, got))
                if not have_key:
                    check(what + ": no key to offer, and sshpass carries BOARD_PASS",
                          got[0][:3] == ["sshpass", "-p", "hunter2"] and "-i" not in ssh and "BatchMode=yes" not in ssh,
                          repr(got))
                    continue
                # With a key the first connection is the key ALONE and cannot ask
                # for anything - not a password, and not the passphrase of a key
                # that has one, which under sshpass nothing would ever answer.
                check(what + ": the first connection offers the key alone and cannot prompt",
                      got[0][0] == "ssh" and ssh[ssh.index("-i") + 1] == str(key)
                      and "IdentitiesOnly=yes" in ssh and "BatchMode=yes" in ssh, repr(got))
                rc, out, got, sshs = attempt(FAKE_SSH_REFUSE_KEY="1")
                second = sshs[1] if len(sshs) == 2 else []
                ok = (rc == 0 and len(sshs) == 2 and "-i" not in second and "IdentitiesOnly=yes" not in second
                      and all(o in second for o in USUAL) and second[-2:] == ["root@203.0.113.1", "echo hi"]
                      and "Permission denied" not in out)
                if have_sshpass:
                    check(what + ": a refused key costs one more connection, without it, the password typed by sshpass",
                          ok and got[1][:3] == ["sshpass", "-p", "hunter2"] and "BatchMode=yes" not in second,
                          "exit=%s calls=%r out=%r" % (rc, got, out[:200]))
                else:
                    check(what + ": a refused key costs one more connection, with the keys ssh has anyway and no prompt",
                          ok and "BatchMode=yes" in second and not [c for c in got if c[0] == "sshpass"],
                          "exit=%s calls=%r out=%r" % (rc, got, out[:200]))
                check(what + ": no connection ever carries the key without BatchMode",
                      all("BatchMode=yes" in c for c in sshs if "-i" in c), repr(sshs))
                rc, out, got, sshs = attempt(FAKE_SSH_DOWN="1")
                check(what + ": a board that does not answer is asked once, and ssh's own words come through",
                      rc == 255 and len(sshs) == 1 and "timed out" in out, "exit=%s calls=%r out=%r" % (rc, got, out[:200]))

# ---- 3. the tools that used to stop at "need sshpass" ----------------------------
with tempfile.TemporaryDirectory() as d:
    path, log = fake_path(d, sshpass=False)
    key = pathlib.Path(d) / "key"
    key.write_text("not really a key\n")
    env = base_env(path, d, FISHBALL_SSH_KEY=str(key))
    for name, argv in (("net show", ["bash", TOOLS / "net.sh", "show"]),
                       ("uboot-contract", ["bash", TOOLS / "uboot-contract.sh"]),
                       ("throughput-ab", ["bash", TOOLS / "throughput-ab.sh"]),
                       ("board-busy", ["bash", TOOLS / "board-busy.sh"]),
                       ("automation install", ["bash", TOOLS / "automation" / "automation.sh", "install"])):
        pathlib.Path(log).write_text("")
        rc, out = run(argv, env=env)
        got = [c for c in calls(log) if c[0] == "ssh"]
        check("%s without sshpass logs in with the key instead of stopping" % name,
              bool(got) and str(key) in got[0] and "BatchMode=yes" in got[0] and "need sshpass" not in out
              and "needs sshpass" not in out, "exit=%s calls=%r out=%r" % (rc, got[:1], out[:160]))
    # No key either: each says how to get one, and tries nothing.
    for name, argv in (("net show", ["bash", TOOLS / "net.sh", "show"]),
                       ("uboot-contract", ["bash", TOOLS / "uboot-contract.sh"]),
                       ("flash", ["bash", TOOLS / "flash.sh", "--help"])):
        pathlib.Path(log).write_text("")
        rc, out = run(argv, env=dict(env, FISHBALL_SSH_KEY=d + "/none"))
        if name == "flash":
            check("flash --help needs no login at all", rc == 0 and "Flash a built firmware" in out, out[:160])
            continue
        check("%s with neither a key nor sshpass names both fixes and contacts nothing" % name,
              rc == 2 and "./devkit ssh-key" in out and INSTALL in out and not calls(log),
              "exit=%s out=%r" % (rc, out[:200]))
    # find and --help never needed a login; they used to die on the sshpass check at the top.
    rc, out = run(["bash", TOOLS / "net.sh", "--help"], env=dict(env, FISHBALL_SSH_KEY=d + "/none"))
    check("net --help works with neither a key nor sshpass", rc == 0 and "./devkit net find" in out, out[:160])
    rc, out = run(["bash", "-c", 'eval "$(sed -n "/^resolve_name()/,/^}/p;/^bounded()/,/^}/p" "$1")"\n'
                   'resolve_name localhost 5 || exit 1\n'
                   'resolve_name host-that-does-not-exist.invalid 5 && exit 1\n'
                   'bounded 1 sleep 20; [ $? -eq 124 ] || exit 1\n'
                   'bounded 5 sh -c "exit 7"; [ $? -eq 7 ] || exit 1\necho DONE', "_", TOOLS / "net.sh"],
                  env=dict(env, PATH=path))
    check("net find resolves through the system resolver, and bounds a command without GNU timeout",
          rc == 0 and "127.0.0.1" in out and "DONE" in out, "exit=%s out=%r" % (rc, out[:200]))

    # ssh-key with no sshpass and no terminal cannot type a password: it says so
    # (after making the key), instead of the old "install sshpass" dead end.
    newkey = pathlib.Path(d) / "sub" / "fishball"
    pathlib.Path(log).write_text("")
    rc, out = run(["bash", TOOLS / "ssh-key.sh"], env=dict(env, FISHBALL_SSH_KEY=str(newkey), FAKE_SSH_RC="255"))
    check("ssh-key without sshpass or a terminal makes the key, then says to run it in a terminal",
          rc == 1 and newkey.exists() and "in a terminal" in out and "ssh-copy-id -i" in out,
          "exit=%s out=%r" % (rc, out[-240:]))

    # The Python callers.
    rc, out = run([sys.executable, TOOLS / "tx-gpio-bitmap-check.py"], env=dict(env, FISHBALL_SSH_KEY=d + "/none"))
    check("gpio-check with neither a key nor sshpass names both fixes",
          rc != 0 and "./devkit ssh-key" in out and INSTALL in out and "Traceback" not in out, out[:200])
    sys.path[:0] = [str(TOOLS), str(TOOLS / "selftest")]
    keep = dict(os.environ)
    os.environ.update(PATH=path, FISHBALL_SSH_KEY=str(key))
    try:
        import sdr_selftest
        base = sdr_selftest.Shell("203.0.113.1", "analog").base
    finally:
        os.environ.clear()
        os.environ.update(keep)
    pathlib.Path(log).write_text("")
    rc, out = run(base + ["echo hi"], env=env)
    got = [c for c in calls(log) if c[0] == "ssh"]
    check("selftest --ssh offers the key and cannot stop at a password prompt",
          rc == 0 and len(got) == 1 and str(key) in got[0] and "BatchMode=yes" in got[0]
          and "ConnectTimeout=8" in got[0] and got[0][-2:] == ["root@203.0.113.1", "echo hi"],
          "exit=%s base=%r calls=%r" % (rc, base, got))

# ---- 4. flash, ssh-key and net, end to end against the fake board -----------------
# These rewrite the files a board boots from, or reboot it, so each is run all
# the way through - the paths that go wrong as well: what is left on the card,
# how the card is left mounted, and what the user is told.
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    path, tool = board_path(d / "nopass", sshpass=False)
    path_pw, _ = board_path(d / "pass", sshpass=True)
    key = fake_key(d / "fishball", "devkit")
    out_dir = d / "output"
    out_dir.mkdir()
    for name, text in NEW.items():
        (out_dir / name).write_text(text)
    count = [0]

    def board(layout, authorised=True):
        count[0] += 1
        b = Board(d / ("board%d" % count[0]), layout, tool)
        if authorised:
            b.authorise(key)
        return b

    def tool_env(b, p=path, **more):
        e = base_env(p, d, FISHBALL_SSH_KEY=key, FAKE_BOARD=str(b.r), FW_OUTPUT=str(out_dir),
                     BACKUP_DIR=str(b.r / "backups"))
        e.update(more)
        return e

    def flash(b, *args, **kw):
        return run(["bash", TOOLS / "flash.sh"] + list(args), env=tool_env(b, **kw))

    def backups(b):
        return {f.name: f.read_text() for f in (b.r / "backups").glob("*/*")}

    # The whole flash, with its reboot, on each way a board can have the card.
    for layout, what in (("debian-rw", "Debian, /boot read-write"), ("debian-ro", "Debian, /boot read-only"),
                         ("buildroot", "Buildroot, card not mounted")):
        b = board(layout)
        if layout == "buildroot":            # the key has to be where a reboot does not lose it
            jk = b.r / "mnt" / "jffs2" / "root" / ".ssh"
            jk.mkdir(parents=True)
            shutil.copy(str(b.r / "root" / ".ssh" / "authorized_keys"), str(jk))
            (jk / "keys.md5").write_text("%s  authorized_keys\n" % hashlib.md5((jk / "authorized_keys").read_bytes()).hexdigest())
        rc, out = flash(b)
        card = b.card()
        check("flash on %s: both files swapped, the old ones kept as .prev and backed up, checked after the reboot" % what,
              rc == 0 and all(card.get(n) == NEW[n] and card.get(n + ".prev") == OLD[n] for n in NEW)
              and not [n for n in card if n.endswith(".new")] and backups(b) == OLD and b.boots() == 1
              and "BOOT.bin  ok" in out and "uImage  ok" in out and "Flashed and booted" in out,
              "exit=%s card=%r out=%r" % (rc, sorted(card), out[-300:]))
        check("flash on %s: the card ends mounted exactly as it began" % what, not b.left_alone(), b.left_alone())

    # The one a kernel change uses, on the layout the hardware test ran.
    for layout in ("debian-rw", "debian-ro"):
        b = board(layout)
        rc, out = flash(b, "--kernel-only", "--no-reboot")
        card = b.card()
        check("flash --kernel-only --no-reboot on %s: uImage alone is swapped, and nothing reboots" % layout,
              rc == 0 and card["uImage"] == NEW["uImage"] and card["uImage.prev"] == OLD["uImage"]
              and card["BOOT.bin"] == OLD["BOOT.bin"] and "BOOT.bin.prev" not in card and b.boots() == 0
              and "Not rebooting" in out and not b.left_alone(),
              "exit=%s card=%r state=%r out=%r" % (rc, sorted(card), b.left_alone(), out[-200:]))
    b = board("debian-ro")
    (b.r / "card" / "uImage").unlink()
    rc, out = flash(b, "--no-reboot")
    check("flash: a file the board says is not on the card is written, with nothing to back up",
          rc == 0 and "uImage not on the card yet" in out and b.card()["uImage"] == NEW["uImage"]
          and "uImage.prev" not in b.card() and backups(b) == {"BOOT.bin": OLD["BOOT.bin"]} and not b.left_alone(),
          "exit=%s out=%r" % (rc, out[-300:]))

    # A dropped connection on "is this file on the card?" used to be read as
    # "no": no backup, and on with the flash.
    for layout in ("debian-rw", "debian-ro", "buildroot"):
        b = board(layout)
        b.fail((1, 255, "test -r /tmp/sd/uImage", "ssh: connect to host 203.0.113.1 port 22: Connection reset by peer"))
        rc, out = flash(b)
        check("flash on %s: no answer to \"is uImage on the card?\" stops it with nothing written" % layout,
              rc == 1 and b.card() == OLD and "did not answer" in out and "Nothing has been written" in out
              and "not on the card yet" not in out and "== 2." not in out and b.boots() == 0 and not b.left_alone(),
              "exit=%s card=%r state=%r out=%r" % (rc, sorted(b.card()), b.left_alone(), out[-300:]))

    # A copy that dies part-way: connection dropped, or the card is full.
    for layout in ("debian-rw", "debian-ro", "buildroot"):
        for code, how in ((255, "the connection drops"), (1, "the board says the write failed")):
            b = board(layout)
            b.fail((1, code, "cat > '/tmp/sd/uImage.new'", "PARTIAL"))
            rc, out = flash(b)
            check("flash on %s, %s mid-copy: no .new left, the boot files untouched, and it says so" % (layout, how),
                  rc == 1 and b.card() == OLD and "copying uImage to the card failed" in out
                  and "Nothing was swapped" in out and "untouched" in out and b.boots() == 0 and not b.left_alone(),
                  "exit=%s card=%r state=%r out=%r" % (rc, sorted(b.card()), b.left_alone(), out[-300:]))
    b = board("debian-ro")
    b.fail((1, 0, "md5sum /tmp/sd/BOOT.bin.new", "garbled"))
    rc, out = flash(b)
    check("flash: a copy whose checksum does not come back right is removed, not swapped",
          rc == 1 and b.card() == OLD and "copied WRONG" in out and "Nothing was swapped" in out and not b.left_alone(),
          "exit=%s card=%r out=%r" % (rc, sorted(b.card()), out[-300:]))

    # A bind mount that fails used to go unnoticed: the flash then ran against
    # an empty directory in the board's RAM and reported success.
    b = board("debian-rw")
    (b.r / "fail-bind").write_text("")
    rc, out = flash(b)
    check("flash: a failed mount --bind stops it before anything is read or written",
          rc == 1 and b.card() == OLD and "could not mount the card" in out and "Nothing has been written" in out
          and "saved" not in out and "not on the card yet" not in out and not b.left_alone(),
          "exit=%s state=%r out=%r" % (rc, b.left_alone(), out[-300:]))

    # A swap the board refuses (no room for .prev), and one it never answers.
    b = board("debian-ro")
    b.fail((1, 1, "mv uImage.new uImage", "cp: write error: No space left on device"))
    rc, out = flash(b)
    card = b.card()
    check("flash: a refused swap of the second file says which file IS swapped, and not to reboot",
          rc == 1 and card["BOOT.bin"] == NEW["BOOT.bin"] and card["uImage"] == OLD["uImage"]
          and "uImage NOT swapped" in out and "Already swapped: BOOT.bin" in out and "do not reboot" in out
          and not [n for n in card if n.endswith(".new")] and b.boots() == 0 and not b.left_alone(),
          "exit=%s card=%r out=%r" % (rc, sorted(card), out[-400:]))
    b = board("debian-rw")
    b.fail((1, 255, "mv BOOT.bin.new BOOT.bin", "ssh: connection lost"))
    rc, out = flash(b)
    check("flash: no answer during a swap is not reported as \"card unchanged\"",
          rc == 1 and "stopped answering" in out and "may or may not" in out and "untouched" not in out
          and b.boots() == 0, "exit=%s out=%r" % (rc, out[-400:]))

    # After the reboot. On a RAM-disk root a key that lives only in /root/.ssh is
    # gone, and with no sshpass nothing else can log in: the board is up and says
    # "Permission denied". That used to be ninety discarded errors and then
    # "board has not come back ... restore it with a card reader".
    b = board("buildroot")
    rc, out = flash(b)
    check("flash: a board that comes back refusing the login is reported as that, with status 3",
          rc == 3 and b.boots() == 1 and all(b.card().get(n) == NEW[n] for n in NEW)
          and "refuses the login" in out and "./devkit ssh-key" in out and "NOT DONE: step 5" in out
          and "has not come back" not in out and "card reader" not in out,
          "exit=%s out=%r" % (rc, out[-500:]))
    b = board("buildroot")
    rc, out = flash(b, p=path_pw)
    check("flash: the same board with sshpass gets back in with the password, and finishes",
          rc == 0 and "Flashed and booted" in out and not b.left_alone(), "exit=%s out=%r" % (rc, out[-300:]))
    b = board("buildroot")
    (b.r / "password").write_text("changed\n")
    rc, out = flash(b, p=path_pw)
    check("flash: with sshpass and a password the board no longer takes, also status 3",
          rc == 3 and "refuses the login" in out and "has not come back" not in out, "exit=%s out=%r" % (rc, out[-300:]))
    b = board("debian-rw")
    (b.r / "stay-down").write_text("")
    rc, out = flash(b)
    check("flash: a board that really does not come back still gets the card-reader message, status 1",
          rc == 1 and "has not come back" in out and "card reader" in out and "refuses the login" not in out,
          "exit=%s out=%r" % (rc, out[-300:]))
    # Ninety turns of a loop whose sleep is faked: counted in turns that was "180s".
    m = re.search(r"has not come back after (\d+)s", out)
    check("flash: reports the seconds that passed, not turns of its loop", bool(m) and int(m.group(1)) < 120, out[-300:])

    # -- the helper against a board: stdin survives the second attempt, and the
    #    key you log in with every day is not shut out by a stale devkit key.
    PIPE = ('. "%s"; printf "sent through\\n" | board_ssh 203.0.113.1 "cat > /tmp/got" || exit 1\n'
            'board_ssh 203.0.113.1 "cat /tmp/got"') % HELPER
    PY_PIPE = ('import subprocess, sys; sys.path.insert(0, %r); import board_ssh\n'
               'a = board_ssh.ssh_argv("203.0.113.1")\n'
               'subprocess.run(a + ["cat > /tmp/got"], input=b"sent through\\n", check=True)\n'
               'sys.exit(subprocess.run(a + ["cat /tmp/got"]).returncode)') % str(TOOLS)
    for label, argv in (("board-ssh.sh", ["bash", "-c", PIPE]), ("board_ssh.py", [sys.executable, "-c", PY_PIPE])):
        b = board("debian-rw", authorised=False)
        rc, out = run(argv, env=tool_env(b, p=path_pw))
        sshs = [c for c in b.calls() if c[0] == "ssh"]
        check("%s: a key the board refuses, then the password - and what was piped in arrives whole" % label,
              rc == 0 and out == "sent through\n" and len(sshs) == 4, "exit=%s out=%r calls=%d" % (rc, out, len(sshs)))
        b = board("debian-rw", authorised=False)
        everyday = fake_key(d / "id_everyday", "everyday")
        b.authorise(everyday)
        rc, out = run(argv, env=tool_env(b, FAKE_DEFAULT_KEY=everyday))
        check("%s: a stale devkit key does not shut out the key you log in with every day" % label,
              rc == 0 and out == "sent through\n", "exit=%s out=%r" % (rc, out))
    b = board("debian-rw", authorised=False)
    b.authorise(everyday)
    for name, argv in (("board-busy", ["bash", TOOLS / "board-busy.sh"]),):
        rc, out = run(argv, env=tool_env(b, FAKE_DEFAULT_KEY=everyday))
        check("%s gets in with the everyday key when the devkit key is stale" % name,
              rc == 0 and "is free" in out, "exit=%s out=%r" % (rc, out[:200]))

    # -- "cannot log in" is not "nothing there", and neither is "not Debian".
    AUTO = ["bash", TOOLS / "automation" / "automation.sh", "install"]
    b = board("debian-rw", authorised=False)
    rc, out = run(AUTO, env=tool_env(b))
    check("automation install on a board that refuses the login says that, not \"runs something else\"",
          rc == 1 and "refuses the login" in out and "./devkit ssh-key" in out and "something else" not in out, out[:300])
    rc, out = run(["bash", TOOLS / "board-busy.sh"], env=tool_env(b))
    check("board-busy on a board that refuses the login says that, not \"no answer\"",
          rc == 2 and "refuses the login" in out and "no answer" not in out, "exit=%s out=%r" % (rc, out[:300]))
    (b.r / "down").write_text("")
    rc, out = run(AUTO, env=tool_env(b))
    check("automation install on a board that is not there says it cannot log in",
          rc == 1 and "cannot log in" in out and "Connection refused" in out and "something else" not in out, out[:300])
    rc, out = run(["bash", TOOLS / "board-busy.sh"], env=tool_env(b))
    check("board-busy on a board that is not there still says no answer",
          rc == 2 and "no answer" in out and "refuses" not in out, "exit=%s out=%r" % (rc, out[:300]))
    b = board("buildroot")
    rc, out = run(AUTO, env=tool_env(b))
    check("automation install on a Buildroot board still says it needs the Debian root",
          rc == 1 and "this board runs something else" in out, out[:300])

    # -- ssh-key. The password login is password ONLY (an agent full of keys used
    #    to use up the board's attempts first), nothing goes through known_hosts,
    #    ssh-copy-id is not involved, and on a RAM-disk root the key is saved
    #    where the board's own boot script restores it from.
    def ssh_key(b, home, p=path_pw, **more):
        home.mkdir(exist_ok=True)
        e = tool_env(b, p=p, FISHBALL_SSH_KEY=str(home / ".ssh" / "fishball"), **more)
        e["HOME"] = str(home)
        return run(["bash", TOOLS / "ssh-key.sh"], env=e), e

    b = board("buildroot", authorised=False)
    home = d / "home-buildroot"
    (rc, out), env = ssh_key(b, home)
    got = b.calls(clear=True)
    pw = [c for c in got if c[0] == "ssh" and "PubkeyAuthentication=no" in c]
    jk = b.r / "mnt" / "jffs2" / "root" / ".ssh"
    pub = (home / ".ssh" / "fishball.pub").read_text() if (home / ".ssh" / "fishball.pub").exists() else "?"
    check("ssh-key on a Buildroot board: installs the key and logs in with it",
          rc == 0 and "OK - key login works" in out and (b.r / "root" / ".ssh" / "authorized_keys").read_text() == pub,
          "exit=%s out=%r" % (rc, out[-300:]))
    check("ssh-key: the one password login offers no keys, and no login goes through known_hosts or ssh-copy-id",
          len(pw) == 1 and "-i" not in pw[0] and any(o.startswith("PreferredAuthentications=password") for o in pw[0])
          and all("UserKnownHostsFile=/dev/null" in c for c in got if c[0] == "ssh" and "root@203.0.113.1" in c)
          and not [c for c in got if c[0].startswith("ssh-copy-id")], repr(got)[:600])
    check("ssh-key on a Buildroot board: saves the key in /mnt/jffs2 with the keys.md5 the boot script checks, and says so",
          (jk / "authorized_keys").exists() and (jk / "authorized_keys").read_text() == pub
          and (jk / "keys.md5").exists() and "/mnt/jffs2/root/.ssh" in out, out[-400:])
    run([b.r / "bin" / "reboot"], env=env)
    rc, out = run(["bash", "-c", '. "%s"; board_ssh 203.0.113.1 "echo still in"' % HELPER], env=dict(env, PATH=path))
    check("ssh-key on a Buildroot board: the board's own boot script puts the key back after a reboot",
          rc == 0 and "still in" in out and (b.r / "root" / ".ssh" / "authorized_keys").read_text() == pub,
          "exit=%s out=%r" % (rc, out[:200]))
    (b.r / "proc" / "uptime").write_text("600.00 500.00\n")        # it has been up a while since
    rc, out = run(["bash", TOOLS / "flash.sh"], env=dict(env, PATH=path))
    check("flash on that board, key only: reboots it and is let back in",
          rc == 0 and "Flashed and booted" in out and b.boots() == 2, "exit=%s out=%r" % (rc, out[-300:]))
    (rc, out), _ = ssh_key(b, home, p=path)
    check("ssh-key again, where the key already works: no password needed, and the key is not added twice",
          rc == 0 and "already accepts this key" in out and (jk / "authorized_keys").read_text() == pub
          and (b.r / "root" / ".ssh" / "authorized_keys").read_text() == pub, "exit=%s out=%r" % (rc, out[-300:]))

    # A board set up before ssh-key knew about jffs2: the key works, in RAM only.
    b = board("buildroot", authorised=False)
    home = d / "home-old"
    (home / ".ssh").mkdir(parents=True)
    b.authorise(fake_key(home / ".ssh" / "fishball", "older"))
    (rc, out), env = ssh_key(b, home, p=path)
    run([b.r / "bin" / "reboot"], env=env)
    rc2, out2 = run(["bash", "-c", '. "%s"; board_ssh 203.0.113.1 "echo still in"' % HELPER], env=dict(env, PATH=path))
    check("ssh-key on a Buildroot board whose key was in RAM only: saves it, with the key as the login",
          rc == 0 and "/mnt/jffs2/root/.ssh" in out and rc2 == 0 and "still in" in out2,
          "exit=%s out=%r then %s %r" % (rc, out[-300:], rc2, out2[:120]))

    b = board("buildroot", authorised=False)
    for row in list(b.r.joinpath("proc").glob("mounts*")):
        row.write_text("".join(l for l in row.read_text().splitlines(True) if "jffs2" not in l))
    (rc, out), _ = ssh_key(b, d / "home-nojffs2")
    check("ssh-key on a RAM-disk root with nowhere to save the key: installs it and warns it will not last",
          rc == 0 and "FOR NOW" in out and "after a reboot" in out and not (b.r / "mnt" / "jffs2" / "root").exists(),
          "exit=%s out=%r" % (rc, out[-400:]))

    b = board("debian-rw", authorised=False)
    home = d / "home-debian"
    (rc, out), _ = ssh_key(b, home)
    cfg = (home / ".ssh" / "config").read_text() if (home / ".ssh" / "config").exists() else ""
    check("ssh-key on a Debian board: the key goes in /root/.ssh and nowhere else, and `Host fishball` is as it was",
          rc == 0 and "OK - key login works" in out and "jffs2" not in out and not (b.r / "mnt" / "jffs2" / "root").exists()
          and "Host fishball\n    HostName 203.0.113.1\n    User root\n" in cfg and "StrictHostKeyChecking accept-new" in cfg,
          "exit=%s out=%r cfg=%r" % (rc, out[-300:], cfg))
    # A re-imaged card: the board has a new host key, and a new authorized_keys.
    (b.r / "root" / ".ssh" / "authorized_keys").unlink()
    (b.r / "hostkey-changed").write_text("")
    (rc, out), _ = ssh_key(b, home)
    check("ssh-key after the card was re-imaged: still installs the key, and says how to make `ssh fishball` work again",
          rc == 0 and "OK - key login works" in out and "ssh-keygen -R 203.0.113.1" in out
          and "known_hosts remembers" in out, "exit=%s out=%r" % (rc, out[-600:]))

    b = board("debian-rw", authorised=False)
    (b.r / "password").write_text("changed\n")
    (rc, out), _ = ssh_key(b, d / "home-wrongpw")
    check("ssh-key with a password the board refuses says so, and names BOARD_PASS",
          rc == 1 and "could not install the key" in out and "BOARD_PASS" in out, "exit=%s out=%r" % (rc, out[-300:]))

    # -- net: the same reboot, the same RAM disk. `./devkit net name` writes the
    #    U-Boot environment, reboots, finds the board by name and shows it.
    net_path, _ = board_path(d / "net", sshpass=False)
    real = shutil.which("python3", path=net_path)
    shim = pathlib.Path(net_path) / "python3"
    shim.unlink()
    # The name lookup is the one thing here that would go to the network.
    shim.write_text('#!/bin/sh\ncase "$2" in *getaddrinfo*) echo 203.0.113.1; exit 0 ;; esac\nexec "%s" "$@"\n'
                    % os.path.realpath(real))
    shim.chmod(0o755)
    # net.sh sleeps 35 s while the board goes down; here that waits for the fake reboot.
    (pathlib.Path(net_path) / "sleep").write_text(
        '#!/bin/sh\ni=0\nwhile [ "$1" = 35 ] && [ ! -s "$FAKE_BOARD/boots" ] && [ $i -lt 200 ]; do\n'
        '    /bin/sleep 0.05; i=$((i + 1))\ndone\nexit 0\n')
    NET = ["bash", TOOLS / "net.sh", "name", "sdr2"]
    b = board("buildroot")
    rc, out = run(NET, env=tool_env(b, p=net_path))
    check("net name on a board that comes back refusing the login: says the setting IS written, and how to get back in",
          rc == 3 and b.boots() == 1 and (b.r / "uboot.env").read_text() == "hostname=sdr2\n"
          and "refuses the login" in out and "./devkit ssh-key" in out and "Permission denied" not in out,
          "exit=%s out=%r" % (rc, out[-500:]))
    b = board("buildroot", authorised=False)
    (rc, out), env = ssh_key(b, d / "home-net")
    rc, out = run(NET, env=dict(env, PATH=net_path))
    check("net name on a board whose key ssh-key saved: reboots, finds it, logs in and shows it",
          rc == 0 and b.boots() == 1 and "found it: sdr2.local is 203.0.113.1" in out and "== sdr2.local ==" in out
          and "eth0          DHCP" in out, "exit=%s out=%r" % (rc, out[-500:]))

# ---- 5. devkit: status, doctor --host, completion ---------------------------------
with tempfile.TemporaryDirectory() as d:
    f = pathlib.Path(d) / "f"
    f.write_bytes(b"x" * 1234)
    rc, out = run(["bash", "-c", 'eval "$(sed -n "/^fsize()/p;/^sha256()/,/^}/p" "$1")"; fsize "$2"; sha256 "$2"',
                   "_", DEVKIT, f])
    check("devkit's file size and sha256 need no GNU stat or sha256sum",
          out.split() == ["1234", hashlib.sha256(b"x" * 1234).hexdigest()], "exit=%s out=%r" % (rc, out[:200]))
    rc, out = run([DEVKIT, "status"], env=dict(os.environ, BOARD="203.0.113.1"))
    check("status runs clean: no usage error from stat or paste, and names what it tried",
          rc == 0 and "illegal option" not in out and "usage:" not in out.lower()
          and "not found (tried 203.0.113.1" in out, "exit=%s out=%r" % (rc, out[-240:]))

    path, log = fake_path(d, sshpass=False)
    rc, out = run([DEVKIT, "doctor", "--host"], env=base_env(path, d, FISHBALL_SSH_KEY=d + "/none"))
    check("doctor --host: python3 and ssh are enough to pass; no key and no sshpass is a warning with this OS's hint",
          rc == 0 and "ok     python3" in out and "ok     ssh" in out and "warn   no board key and no sshpass" in out
          and "./devkit ssh-key" in out and INSTALL in out and ("apt" not in out if MAC else "brew" not in out)
          and "== toolchain" not in out, "exit=%s out=%r" % (rc, out[:400]))
    key = pathlib.Path(d) / "key"
    key.write_text("k\n")
    rc, out = run([DEVKIT, "doctor", "--host"], env=base_env(path, d, FISHBALL_SSH_KEY=str(key)))
    check("doctor --host accepts the board key in place of sshpass",
          rc == 0 and "ok     board key" in out and "warn" not in out, "exit=%s out=%r" % (rc, out[:300]))

    rc, out = run(["bash", ROOT / "firmware" / "scripts" / "doctor.sh"], env=dict(os.environ, BOARD="203.0.113.1"))
    check("the factory doctor reaches its verdict under this bash (it used declare -A)",
          rc in (0, 1) and "unbound variable" not in out and "invalid option" not in out
          and ("Ready to build" in out or "would stop a build" in out) and "bison" in out,
          "exit=%s out=%r" % (rc, out[-200:]))

    # eval works in every bash; `source <(...)` reads nothing in 3.2, silently.
    rc, out = run(["bash", "-c", 'eval "$("$1" completion)"; complete -p devkit; '
                   'COMP_WORDS=(./devkit write-card ""); COMP_CWORD=2; _devkit_complete; echo "${COMPREPLY[@]}"',
                   "_", DEVKIT])
    check("eval \"$(./devkit completion)\" loads it, and write-card completes without /sys/block",
          rc == 0 and "_devkit_complete" in out and "--dry-run" in out and "No such file" not in out,
          "exit=%s out=%r" % (rc, out[:200]))
    if shutil.which("zsh"):
        rc, out = run(["zsh", "-f", "-c", 'eval "$("$1" completion)"; print -r -- $_comps[devkit]', "_", DEVKIT])
        check("the same line works in zsh, which is given bashcompinit by the script itself",
              rc == 0 and "_devkit_complete" in out, "exit=%s out=%r" % (rc, out[:200]))

    home = pathlib.Path(d) / "home"
    home.mkdir()
    dest = home / ".local" / "share" / "bash-completion" / "completions" / "devkit"
    env = dict(os.environ, HOME=str(home), SHELL="/bin/zsh")
    for k in ("BASH_COMPLETION_USER_DIR", "ZDOTDIR"):
        env.pop(k, None)
    rc, out = run([DEVKIT, "completion", "install"], env=env)
    check("completion install for zsh: prints the one line .zshrc needs, and edits nothing unasked",
          rc == 0 and dest.exists() and 'source "%s"' % dest in out and "--rc" in out
          and not (home / ".zshrc").exists(), "exit=%s out=%r" % (rc, out[:300]))
    run([DEVKIT, "completion", "install", "--rc"], env=env)
    rc, out = run([DEVKIT, "completion", "install", "--rc"], env=env)
    rcfile = (home / ".zshrc").read_text() if (home / ".zshrc").exists() else ""
    check("completion install --rc adds that line once, however often it runs",
          rc == 0 and rcfile.count(str(dest)) == 1 and "already reads it" in out, "exit=%s rc file=%r" % (rc, rcfile))
    rc, out = run([DEVKIT, "completion", "install"], env=dict(env, SHELL="/bin/bash"))
    if MAC:
        check("completion install for bash on macOS names .bash_profile",
              rc == 0 and ".bash_profile" in out and not (home / ".bash_profile").exists(), out[:300])
    else:
        check("completion install for bash on Linux is as it was: bash-completion loads the file",
              rc == 0 and "Every new shell will have it." in out and "To undo:  rm %s" % dest in out
              and not (home / ".bashrc").exists(), out[:300])

# ---- 6. what the board is running: a release on the modern target is not "factory" -
from board_info import describe                                            # noqa: E402
for attrs, want in (({"fw_version": "v2.3", "local,kernel": "6.12.0-g61ef303acadc"}, "modern, v2.3"),
                    ({"fw_version": "v2.0", "fw_build": "v2.0-9-g5ae29d94", "local,kernel": "6.12.0"},
                     "modern (Debian), v2.0-9-g5ae29d94"),
                    ({"fw_version": "debian-13", "local,kernel": "6.12.0"}, "modern (Debian), debian-13"),
                    ({"fw_version": "v1.6", "local,kernel": "5.15.0-175882-g1a2b3c"}, "factory (Buildroot), v1.6"),
                    ({"fw_version": "v0.38"}, "unknown, v0.38")):
    got = dict(describe(attrs))["firmware"]
    check("board_info: %r is %r" % (attrs, want), got == want, "got %r" % got)

# ---- 7. write_card.sh: CARD=/path is honoured, on a fake card ---------------------
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    fm = d / "repo" / "firmware-modern"
    (fm / "output").mkdir(parents=True)
    card = d / "card"
    card.mkdir()
    shutil.copy(str(ROOT / "firmware-modern" / "write_card.sh"), str(fm))
    for name, body in (("BOOT.bin", "boot"), ("uImage", "old kernel"), ("devicetree.dtb", "old dtb")):
        (card / name).write_text(body)
    (fm / "output" / "uImage").write_text("new kernel")
    (fm / "output" / "devicetree.dtb").write_text("new dtb")
    rc, out = run(["bash", fm / "write_card.sh"], env=dict(os.environ, CARD=str(card)))
    check("write_card.sh writes to CARD=/path, verifies, and keeps the old kernel as .prev",
          rc == 0 and (card / "uImage").read_text() == "new kernel" and (card / "uImage.prev").read_text() == "old kernel"
          and "4 bytes of BOOT.bin" in out and "written and verified" in out, "exit=%s out=%r" % (rc, out[-300:]))
    rc, out = run(["bash", fm / "write_card.sh"], env=dict(os.environ, CARD=str(d / "nowhere")))
    check("write_card.sh refuses a CARD that is not a boot partition", rc == 1 and "holds no BOOT.bin" in out, out[:200])
    src = (ROOT / "firmware-modern" / "write_card.sh").read_text()
    check("write_card.sh looks where macOS mounts a card", "/Volumes/*" in src, "")

print("\n%d/%d host-tool behaviours hold" % (CHECKS - len(FAILURES), CHECKS))
if FAILURES:
    print("\nFAILED:")
    for n in FAILURES:
        print("  - " + n)
sys.exit(1 if FAILURES else 0)
