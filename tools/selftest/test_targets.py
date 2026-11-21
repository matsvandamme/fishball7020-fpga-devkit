#!/usr/bin/env python3
"""Execute the two-target build plumbing (#9). No board, no sources, no toolchain.

    python3 tools/selftest/test_targets.py

Like test_safety.py, every check RUNS the thing and asserts on what it did - the
exit code AND the reason. Exit codes alone are not enough: twice while this was
written, a check "passed" because the script failed for an unrelated earlier
reason (an overlay-staleness refusal, a missing /sys) before ever reaching the
branch under test. Asserting the message is what tells those apart.

Runs on a hosted CI runner, which has none of firmware/src, firmware-modern/boot,
bootgen or an ARM cross-compiler; checks that need one are skipped, and say so.
Exit 0 if every behaviour holds, 1 otherwise. Python 3.8.
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEVKIT = str(ROOT / "devkit")
FAILURES = []
CHECKS = 0


def check(name, ok, detail=""):
    global CHECKS
    CHECKS += 1
    print(("  PASS  " if ok else "  FAIL  ") + name + ("" if ok or not detail else "\n        " + detail))
    if not ok:
        FAILURES.append(name)


def run(args, env=None, cwd=ROOT):
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(args, capture_output=True, text=True, timeout=120, cwd=str(cwd), env=e)
    return r.returncode, r.stdout + r.stderr


def expect(name, args, code, needle, env=None):
    rc, out = run(args, env=env)
    check(name, rc == code and needle.lower() in out.lower(),
          "exit=%s (want %s), wanted %r in: %r" % (rc, code, needle, out.strip()[:160]))


# ---- 1. --target is validated, and only a real target gets through ------------
expect("--target with an unknown value is refused",
       [DEVKIT, "build", "--target", "bogus"], 1, "unknown --target 'bogus'")
expect("--target with no value is refused",
       [DEVKIT, "build", "--target"], 1, "--target needs a value")
expect("--target=bogus (the = form) is refused too",
       [DEVKIT, "setup", "--target=bogus"], 1, "unknown --target")

# ---- 2. the modern build refuses what it must ----------------------------------
expect("modern build refuses to run without --xsa",
       [DEVKIT, "build", "--target", "modern"], 1, "needs --xsa")
expect("bare build is the modern target: without --xsa it says how to get one",
       [DEVKIT, "build"], 1, "fetch-pinned-xsa.sh")
expect("bare build without --xsa also names the factory target, for Vivado",
       [DEVKIT, "build"], 1, "./devkit build --target factory")
expect("bare build --hdl-only (an old factory guide) names --target factory",
       [DEVKIT, "build", "--hdl-only"], 1, "./devkit build --target factory --hdl-only")
expect("DEVKIT_TARGET with an unknown value is refused, and named",
       [DEVKIT, "build"], 1, "DEVKIT_TARGET=bogus", env={"DEVKIT_TARGET": "bogus"})
expect("modern build refuses the factory-only --hdl-only by name",
       [DEVKIT, "build", "--target", "modern", "--xsa", "x.xsa", "--hdl-only"], 1,
       "unknown option '--hdl-only'")
expect("modern build: --xsa with no path is refused",
       [str(ROOT / "firmware-modern" / "build_all.sh"), "--xsa"], 1, "--xsa needs a file path")
expect("modern build: --boot-only and --all together are refused",
       [DEVKIT, "build", "--target", "modern", "--xsa", "x.xsa", "--boot-only", "--all"], 1,
       "pick one of")
for flag in ("--rootfs-only", "--all"):
    expect("modern build %s inside a container is refused before building anything" % flag,
           [DEVKIT, "build", "--target", "modern", flag, "--xsa", "x.xsa"], 1,
           "build it on the", env={"container": "podman"})
# --rootfs-only needs no --xsa: it goes straight to debian/build.sh. A fake podman
# that can run nothing, first on PATH, makes that script stop at its emulation
# check - which is proof it got there, without building a root filesystem.
with tempfile.TemporaryDirectory() as d:
    fake = pathlib.Path(d) / "podman"
    fake.write_text("#!/bin/sh\nexit 1\n")
    fake.chmod(0o755)
    env = {"PATH": d + os.pathsep + os.environ["PATH"], "container": ""}
    expect("modern build --rootfs-only needs no --xsa and runs debian/build.sh",
           [DEVKIT, "build", "--target", "modern", "--rootfs-only"], 1,
           "cannot run armhf containers", env=env)

# ---- 3. flash and write-card: the modern target's root is not a file on /boot ---
for flag in ("--all", "--rootfs-only"):
    expect("flash --target modern %s is refused, and points at write-card" % flag,
           [DEVKIT, "flash", "--target", "modern", flag], 1, "sudo ./devkit write-card /dev/sdX")
    expect("flash --target modern %s names the command that builds the root" % flag,
           [DEVKIT, "flash", "--target", "modern", flag], 1, "./devkit build --rootfs-only")
    # The old default's commands, typed from an old guide, now reach the modern
    # target: each must be refused with the way back, never do something else.
    expect("bare flash %s (an old factory guide) names --target factory" % flag,
           [DEVKIT, "flash", flag], 1, "./devkit flash --target factory " + flag)
expect("write-card on the factory target is refused, and says why",
       [DEVKIT, "write-card", "--target", "factory", "/dev/sdz"], 1, "write-card is the modern target's")
expect("bare write-card is the modern target's: with no device it prints its usage",
       [DEVKIT, "write-card"], 1, "usage:")
expect("write-card --target modern with no device prints its usage",
       [DEVKIT, "write-card", "--target", "modern"], 1, "usage:")
expect("write-card refuses a device AND --image together",
       [DEVKIT, "write-card", "--target", "modern", "--image", "a.img", "/dev/sdz"], 1,
       "a device or --image, not both")

# Which output directory does flash read? A fake sshpass first on PATH means the
# board can never be contacted: it reports the FW_OUTPUT it inherited and fails.
# On a runner with no build output flash stops earlier, at "missing <path>", which
# names the directory just as well - so either answer is accepted, and both name it.
with tempfile.TemporaryDirectory() as d:
    fake = pathlib.Path(d) / "sshpass"
    fake.write_text('#!/bin/sh\necho "FAKE-SSHPASS FW_OUTPUT=[${FW_OUTPUT:-}]" >&2\nexit 255\n')
    fake.chmod(0o755)
    env = {"PATH": d + os.pathsep + os.environ["PATH"], "BOARD": "203.0.113.1"}
    modern_out = str(ROOT / "firmware-modern" / "output")
    rc, out = run([DEVKIT, "flash", "--target", "modern", "--boot-only"], env=env)
    check("flash --target modern reads firmware-modern/output, never contacting a board",
          rc != 0 and ("FW_OUTPUT=[%s]" % modern_out in out or "missing %s/BOOT.bin" % modern_out in out),
          "exit=%s out=%r" % (rc, out.strip()[:200]))
    rc, out = run([DEVKIT, "flash", "--boot-only"], env=env)
    check("flash with no --target is the modern target (firmware-modern/output)",
          rc != 0 and ("FW_OUTPUT=[%s]" % modern_out in out or "missing %s/BOOT.bin" % modern_out in out),
          "exit=%s out=%r" % (rc, out.strip()[:200]))
    rc, out = run([DEVKIT, "flash", "--target", "factory", "--boot-only"], env=env)
    check("flash --target factory reads firmware/output",
          rc != 0 and ("FW_OUTPUT=[]" in out or "missing %s/BOOT.bin" % (ROOT / "firmware" / "output") in out),
          "exit=%s out=%r" % (rc, out.strip()[:200]))
    rc, out = run([DEVKIT, "flash", "--boot-only"], env=dict(env, DEVKIT_TARGET="factory"))
    check("DEVKIT_TARGET=factory makes bare flash the factory target again",
          rc != 0 and ("FW_OUTPUT=[]" in out or "missing %s/BOOT.bin" % (ROOT / "firmware" / "output") in out),
          "exit=%s out=%r" % (rc, out.strip()[:200]))

# ---- 4. import_xsa.sh: each refusal, and a good import, on synthetic XSAs ------
IMPORT = str(ROOT / "firmware" / "scripts" / "import_xsa.sh")
with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    notzip = d / "not.xsa"
    notzip.write_bytes(b"this is not a zip")

    def xsa(name, part='xc7z020clg400-2', version='2022.2', bit=b"\x00" * 64):
        p = d / name
        with zipfile.ZipFile(p, "w") as z:
            if bit is not None:
                z.writestr("system_top.bit", bit)
            z.writestr("sysdef.xml", '<Project Version="%s"><Part PART="%s"/></Project>' % (version, part))
            z.writestr("system.hwh", '<M INSTANCE="axi_ad9361"/><M INSTANCE="sys_ps7"/>')
        return str(p)

    cases = [
        ("import_xsa refuses a file that is not a zip", str(notzip), "not a readable zip"),
        ("import_xsa refuses an XSA with no bitstream", xsa("nobit.xsa", bit=None), "contains no system_top.bit"),
        ("import_xsa refuses another board's part", xsa("part.xsa", part="xc7z010clg400-1"), "not for this board's part"),
        ("import_xsa refuses another tool version", xsa("ver.xsa", version="2023.1"), "different tool version"),
    ]
    for name, f, needle in cases:
        expect(name, [IMPORT, f, str(d / "pluto"), str(d / "out")], 1, needle)

    good = xsa("good.xsa", bit=b"BITSTREAM" * 100)
    rc, out = run([IMPORT, good, str(d / "pluto"), str(d / "out")])
    bitf = d / "pluto" / "pluto.runs" / "impl_1" / "system_top.bit"
    prov = d / "out" / "xsa-provenance.txt"
    ok = (rc == 0 and bitf.is_file() and bitf.read_bytes() == b"BITSTREAM" * 100
          and prov.is_file() and "Written by import_xsa.sh" in prov.read_text()
          and "ip: INSTANCE=\"axi_ad9361\"" in prov.read_text())
    check("import_xsa imports a good XSA: bitstream extracted byte-exact, provenance written", ok,
          "exit=%s out=%r" % (rc, out.strip()[:160]))

# ---- 5. the bootgen run-here probe must survive pipefail -----------------------
# The trap it exists to avoid: `bootgen | grep -q` under pipefail reports a WORKING
# bootgen as broken, because grep exits first and bootgen takes SIGPIPE.
COMMON = str(ROOT / "firmware" / "scripts" / "fetch_common.sh")
with tempfile.TemporaryDirectory() as d:
    good = pathlib.Path(d) / "good"
    good.write_text("#!/bin/sh\necho '****** Xilinx Bootgen v2022.2'\nyes padding | head -c 200000\nexit 1\n")
    bad = pathlib.Path(d) / "bad"
    bad.write_text("#!/bin/sh\necho 'libc.so.6: version GLIBC_2.38 not found' >&2\nexit 127\n")
    for f in (good, bad):
        f.chmod(0o755)
    probe = 'set -euo pipefail; source "%s"; _bootgen_runs_here "$1" && echo RUNS || echo DOES-NOT-RUN' % COMMON
    rc, out = run(["bash", "-c", probe, "_", str(good)])
    check("probe: a bootgen that runs (and exits non-zero, with lots of output) is seen as running, under pipefail",
          "RUNS" in out and "DOES-NOT" not in out, out.strip()[:120])
    rc, out = run(["bash", "-c", probe, "_", str(bad)])
    check("probe: a bootgen that cannot run here is seen as not running",
          "DOES-NOT-RUN" in out, out.strip()[:120])

    # devkit_ensure_bootgen must NOT rebuild a bootgen that runs and is up to date.
    bgdir = pathlib.Path(d) / "bootgen"
    bgdir.mkdir()
    shutil.copy(str(good), str(bgdir / "bootgen"))
    (bgdir / "bootgen").chmod(0o755)
    rc, out = run(["bash", "-c", 'set -euo pipefail; source "%s"; devkit_ensure_bootgen "$1"; echo DONE' % COMMON,
                   "_", str(bgdir)])
    check("devkit_ensure_bootgen leaves a working, current bootgen alone",
          rc == 0 and "DONE" in out and "Building" not in out and "Rebuilding" not in out,
          "exit=%s out=%r" % (rc, out.strip()[:160]))

# ---- 6. tab completion knows the targets and which flags belong to which --------
def complete(*words):
    script = ('source "%s"; COMP_WORDS=("$@"); COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 )); '
              '_devkit_complete; printf "%%s\\n" "${COMPREPLY[@]}"') % (ROOT / "tools" / "devkit-completion.bash")
    return run(["bash", "-c", script, "_"] + list(words))[1].split()

check("completion offers both targets after --target",
      set(complete("./devkit", "build", "--target", "")) == {"factory", "modern"})
m = complete("./devkit", "build", "--target", "modern", "--")
f = complete("./devkit", "build", "--target", "factory", "--")
b = complete("./devkit", "build", "--")
check("completion: bare build completes the modern target's flags",
      "--boot-only" in b and "--hdl-only" not in b, " ".join(b))
check("completion: modern build offers --boot-only and not the factory's --hdl-only",
      "--boot-only" in m and "--hdl-only" not in m, " ".join(m))
check("completion: factory build still offers --hdl-only",
      "--hdl-only" in f and "--boot-only" not in f, " ".join(f))
check("completion: modern build offers --rootfs-only and --all",
      "--rootfs-only" in m and "--all" in m, " ".join(m))
mf = complete("./devkit", "flash", "--target", "modern", "--")
check("completion: modern flash does not offer --all or --rootfs-only",
      "--all" not in mf and "--rootfs-only" not in mf and "--boot-only" in mf, " ".join(mf))
check("completion knows write-card", "write-card" in complete("./devkit", "wr"))

# ---- 6b. setup --kernel-only stops before the boot side ---------------------------
rc, out = run([str(ROOT / "firmware-modern" / "setup.sh"), "--help"])
check("modern setup --help documents --kernel-only", rc == 0 and "--kernel-only" in out, out.strip()[:160])

# ---- 6c. the release pin: well-formed, and the fetcher refuses a wrong hash ------
import re
pin = (ROOT / "firmware-modern" / "factory-xsa.pin").read_text()
tag = re.search(r"^tag=(v\d+\.\d+)$", pin, re.M)
sha = re.search(r"^sha256=([0-9a-f]{64})$", pin, re.M)
check("factory-xsa.pin names a factory (v1.x) tag and a 64-hex sha256",
      bool(tag and sha and tag.group(1).startswith("v1.")), pin[-200:])
rel = (ROOT / ".github" / "workflows" / "release.yml").read_text()
check("release.yml re-downloads the pinned XSA (never trusts the cache), needs real hashes, and gates the rootfs on the fail-closed iiod",
      'rm -f "$B/firmware-modern/boot/pinned/$tag/system_top.xsa"' in rel
      and '[ -n "$local_sum" ] && [ "$local_sum" = "$board_sum" ]' in rel
      and "^Requires=fishball-rf-quiesce.service" in rel, "")
dropin = (ROOT / "firmware-modern" / "debian" / "overlay" / "etc" / "systemd" / "system" / "iiod.service.d" / "fishball.conf").read_text()
check("iiod fails closed on the quiesce and rebinds USB on both start and stop",
      "\nRequires=fishball-rf-quiesce.service\n" in dropin
      and "ExecStartPost=-/usr/local/sbin/fishball-usb-bind\n" in dropin
      and "ExecStopPost=-/usr/local/sbin/fishball-usb-bind --no-wait" in dropin, "")
unit = (ROOT / "firmware-modern" / "debian" / "overlay" / "etc" / "systemd" / "system" / "iiod.service").read_text()
_active = "\n".join(l for l in unit.splitlines() if not l.startswith("#"))
check("the overlay's iiod.service replaces the package's without udev-settle or the malformed Environment=",
      "ExecStart=/usr/sbin/iiod" in _active and "udev-settle" not in _active
      and "Environment=$" not in _active and "Requires=\n" not in dropin, "")
check("release.yml gates a modern BOOT.bin on the pin, and a dry run publishes nothing",
      "factory-xsa.pin" in rel and "fetch-pinned-xsa.sh" in rel
      and rel.count("!inputs.dry_run") == 2, "")
with tempfile.TemporaryDirectory() as d:
    shutil.copy(str(ROOT / "firmware-modern" / "fetch-pinned-xsa.sh"), d)
    (pathlib.Path(d) / "factory-xsa.pin").write_text("tag=v1.7\nsha256=nothex\n")
    rc, out = run([str(pathlib.Path(d) / "fetch-pinned-xsa.sh")])
    check("fetch-pinned-xsa.sh refuses a malformed pin before downloading anything",
          rc == 1 and "64-hex sha256" in out and "fetching" not in out, out.strip()[:160])

# ---- 7. help --all documents the targets ---------------------------------------------
rc, out = run([DEVKIT, "help", "--all"])
check("help --all documents --target and names what each target needs",
      rc == 0 and "--target modern" in out and "Needs an ARM Linux cross-compiler" in out
      and "write-card" in out)

# ---- 8. with bootgen present (a developer machine, not CI): check_bootbin.py ------
bootgen = next((p for p in (ROOT / "firmware-modern" / "boot" / "bootgen" / "bootgen",
                            ROOT / "firmware" / "src" / "bootgen" / "bootgen") if p.is_file()), None)
images = [p for p in (ROOT / "firmware" / "output" / "BOOT.bin",
                      ROOT / "firmware-modern" / "output" / "BOOT.bin") if p.is_file()]
if bootgen and images:
    rc, out = run([str(ROOT / "firmware" / "scripts" / "check_bootbin.py"), str(images[0]), "--bootgen", str(bootgen)])
    check("check_bootbin: a real BOOT.bin has exactly its three partitions",
          rc == 0 and "exactly the three partitions" in out, out.strip()[:160])
    with tempfile.NamedTemporaryFile(suffix=".bin") as t:
        t.write(b"\x00" * 4096)
        t.flush()
        rc, out = run([str(ROOT / "firmware" / "scripts" / "check_bootbin.py"), t.name, "--bootgen", str(bootgen)])
        check("check_bootbin: an image that is not a BOOT.bin FAILS", rc == 1 and "FAIL" in out, out.strip()[:160])
    cb = str(ROOT / "firmware" / "scripts" / "check_bootbin.py")
    img = images[0]
    with tempfile.NamedTemporaryFile(suffix=".bin") as t:
        t.write(img.read_bytes()[: img.stat().st_size // 2])
        t.flush()
        rc, out = run([cb, t.name, "--bootgen", str(bootgen)])
        check("check_bootbin: a truncated BOOT.bin FAILS (partition runs past the end)",
              rc == 1 and "RUNS PAST THE END" in out, out.strip()[:200])
    rc, out = run([cb, str(img), "--ref", str(img), "--require-same", "system_top.bit", "--bootgen", str(bootgen)])
    check("check_bootbin --require-same: the same partition exits 0", rc == 0, out.strip()[:160])
    if len(images) == 2:
        rc, out = run([cb, str(images[0]), "--ref", str(images[1]), "--require-same", "u-boot.elf", "--bootgen", str(bootgen)])
        check("check_bootbin --require-same: a partition that differs exits 3", rc == 3 and "DIFF" in out, out.strip()[:160])
    rc, out = run([cb, str(img), "--ref", str(img), "--require-same", "nope.elf", "--bootgen", str(bootgen)])
    check("check_bootbin --require-same with no such partition FAILS, not 'same'",
          rc == 1 and "not a partition of both" in out, out.strip()[:160])
else:
    print("  SKIP  check_bootbin.py partition checks (no bootgen or no BOOT.bin here - normal on a CI runner)")
if not bootgen and not shutil.which("bootgen"):
    # A CI runner: "could not check" must be its own exit code, never the 1 that
    # means "checked, and this is not a bootable image" - write-card tells them apart.
    with tempfile.NamedTemporaryFile(suffix=".bin") as t:
        rc, out = run([str(ROOT / "firmware" / "scripts" / "check_bootbin.py"), t.name])
        check("check_bootbin with no bootgen anywhere exits 4, not 1", rc == 4 and "no bootgen" in out,
              "exit=%s out=%r" % (rc, out.strip()[:160]))

print("\n%d/%d target behaviours hold" % (CHECKS - len(FAILURES), CHECKS))
if FAILURES:
    print("\nFAILED:")
    for n in FAILURES:
        print("  - " + n)
sys.exit(1 if FAILURES else 0)
