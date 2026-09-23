# Building in a container

**This is the recommended way to build this firmware.**

Vivado 2022.2 is pinned to this project. A toolchain bump changes the
bitstream, and the provenance claims in this repo rest on the current one — so
the host OS should not be load-bearing, and here it is not. Vivado 2022.2
supports Ubuntu 18.04, 20.04 and 22.04 and nothing newer; the container makes
that irrelevant, and can install Vivado for you as well, since the installer
will not run on a newer host either.

```bash
# run from: the repo root
./devkit container build-image      # once, ~3 minutes
./devkit container doctor           # same checks, inside
./devkit container build --hdl-only # same build, inside
```

Verified on this repo: the container's `BOOT.bin` came out **byte-for-byte
identical** to the host's (`md5 3fb710d8…`), with routing utilisation matching
to five decimals — 6.54675 % vertical, 9.82488 % horizontal on both.

**All five SD-card files are reproducible.** `uramdisk.image.gz` was not, until
this work found out why: `mkimage` re-wraps the root filesystem on every build,
including `--hdl-only` which does not rebuild it, and stamped the current time
into u-boot's 64-byte header. The payload was always byte-identical; only the
header moved. `build_all.sh` now pins `SOURCE_DATE_EPOCH` to the rootfs's own
mtime, so the image is as old as its contents.

## Installing Vivado in the first place

There is a chicken-and-egg problem here, and it is the whole reason this
matters. The container exists because your host is too new to run Vivado
2022.2 — but the Xilinx installer is the *same* Java/GTK application with the
same requirements. On a host that cannot run Vivado, it generally cannot run
the installer either.

So the installer runs in the container too, writing out to the host:

```bash
# run from: the repo root
# AMD put the installer behind an account login, so download it yourself first:
#   https://www.xilinx.com/support/download.html  ->  Vivado 2022.2  ->  Linux Self Extracting Web Installer

# Rootless podman maps the container's root to YOUR user, so the target must be
# yours - a root-owned /tools/Xilinx cannot be written even from "root" inside.
sudo mkdir -p /tools/Xilinx && sudo chown "$USER" /tools/Xilinx

./devkit container install ~/Downloads/Xilinx_Unified_2022.2_1014_8888_Lin64.bin
```

That mounts `/tools/Xilinx` **read-write** — the one time it is not read-only —
passes your display through, and runs the installer's own GUI. Answer it the
same way [building.md](building.md#install-vivadovitis-20222) describes: choose
**Vitis**, select only **Zynq-7000** under device families (~130 GB down to
~30 GB), and keep the path `/tools/Xilinx`.

It is the web installer, so it needs your AMD account during the run and
downloads the content itself. Budget an hour and the disk.

Once that finishes, everything else mounts `/tools/Xilinx` read-only and the
host never needs to run a Xilinx binary again.

### If you see "Extraction failed."

You probably haven't, because `./devkit container install` works around it —
but it is worth knowing, because the message is a lie. The installer is a
self-extracting archive that trips its own signal trap on the way out:

```
Uncompressing Xilinx Installer.........Extraction failed.
Signal caught, cleaning up
```

It exits 143 having extracted all 720 MB perfectly correctly. A script with
`set -e` stops there and never launches the installer. So the install step
checks that an executable `xsetup` was produced rather than trusting the exit
status.

Two other ways the extraction genuinely does fail, both reported with the same
useless message: unpacking relative to a read-only directory (the one holding
the installer is mounted read-only), and unpacking onto the container's own
overlay filesystem, which rootless podman mounts with `userxattr`. The work
directory is a bind mount for both reasons.

> **Verified end to end.** Vivado 2022.2 was installed from the installer,
> inside the container, into a throwaway directory the host had never used,
> and a build run against it with the host's own `/tools/Xilinx` not mounted at
> all. `BOOT.bin` came out `3fb710d8f990cec8f14d5ca61ca2ddb7` — identical to
> the host build — with DSP48s 94/220, Slice LUTs 12521 and WNS 0.215 ns.

## What is and is not in the image

Vivado is **not** in the image. `/tools/Xilinx` is bind-mounted read-only, so
the image is about 1 GB rather than 45, and the toolchain you test is the one
you already have. The image pins the *userspace around it*: glibc, the X
libraries, and the packages `doctor.sh` checks for.

The repo is mounted at **its own absolute path**, not at `/work`. Vivado stores
absolute paths inside `pluto.xpr`, so a project created on the host and one
created in the container are only interchangeable if the path matches.

Rootless podman maps the container's root to the invoking user, so output files
land owned by you. Docker has no such mapping and is passed `--user`.

## The two traps, because neither error names its cause

### Vivado dies in synthesis with a heap error

```
tcmalloc: large alloc 115875935977472 bytes == (nil)
realloc(): invalid pointer
Abnormal program termination (6)
```

A 115 TB allocation is an integer underflow, and the stack names neither
culprit near the top. What is actually happening: Vivado's licence manager
(`libXil_lmgr11.so`) `dlopen`s `libudev.so.1` and enumerates **every device on
the machine** to fingerprint the host for WebTalk registration. By then
Vivado's bundled **tcmalloc has replaced malloc process-wide**, while libudev
still frees through glibc. The two allocators disagree and glibc's heap checker
— correctly — kills the process.

`tools/container/udev-stub.c` answers that enumeration with an empty list. It
allocates nothing and frees nothing, so the allocators never meet, and the
licence manager falls back to its other host-id sources. Only the fingerprint
changes; synthesis, implementation and the bitstream are untouched, and the
XC7Z020 is a WebPACK part that needs no licence anyway.

Switching glibc's heap checker off would also silence it, and is the wrong
trade: that hides real heap corruption inside the tool that produces your
bitstream.

Things that did **not** fix it, in case you try them: mounting `/run/udev`,
`config_webtalk -user off`, and dropping to Ubuntu 20.04. On 20.04 the same
crash appears as a `SIGSEGV` in `malloc_usable_size` instead of a `SIGABRT` in
`realloc` — same cause, different allocator victim.

### The FSBL stage fails with "Channel closed"

```
The Eclipse executable launcher no longer supports running with GTK + 2.x.
Channel closed
    while executing "error [dict get $msg err]"
```

Vivado's GUI wants GTK2; Vitis is Eclipse-based, refuses GTK2, falls back to
GTK3 — and then dies if GTK3 and the SWT dependencies are absent. `xsct`
reports it as a bare "Channel closed" from three layers up. The image installs
both toolkits.

## Why 22.04 and not 20.04

[UG973](https://docs.amd.com/r/2022.2-English/ug973-vivado-release-notes-install-license/Supported-Operating-Systems)
lists 18.04, 20.04 **and** 22.04 for Vivado 2022.2. 20.04 looks tidier — it is
the newest Ubuntu still shipping `libtinfo5`, `libncurses5` and `libssl1.1`, so
Vivado's runtime dependencies would come from the archive instead of
`tools/legacy-libs/`.

It was tried, and the udev crash appears there too. 22.04 is equally supported,
matches the host where this Vivado demonstrably works, and is what
`tools/legacy-libs/` was extracted on — those copies link `GLIBC_2.33` and
cannot load on focal at all.

That last point bit once: `env-vivado.sh` used to prepend them unconditionally,
which on an older distribution produced
`librdi_commontasks.so: GLIBC_2.33 not found` — an error naming a library that
is not the problem. It now engages the shim only where the distro has no
`libtinfo.so.5` of its own.

## What this does not cover

Flashing. `./devkit flash` talks to the board over the network and belongs on
the host — the container has no reason to reach your radio.

## Other operating systems

Untested, and honest about it.

| | |
|---|---|
| **Any Linux** | Yes. The container supplies the userspace, your kernel runs it natively. This is the tested case. |
| **Windows** | Very likely, through WSL2 — a real Linux kernel on x86-64. But the simpler route is to skip containers and run the devkit directly in WSL2 Ubuntu, with WSLg for the block-design GUI. Keep the checkout inside the WSL2 filesystem, never on `/mnt/c/`: build performance across that boundary is dire, and case sensitivity and POSIX permissions do not survive it, which Vivado's project files care about. Reaching the board over WSL2's default NAT may need mirrored networking. |
| **macOS, Intel** | Plausible. The Linux VM is x86-64, so the container runs natively in it. You would need XQuartz for the GUI and room for 44 GB inside the VM. |
| **macOS, Apple Silicon** | Realistically no. The VM is ARM64 and Vivado is x86-64 only. Rosetta can translate x86-64 Linux binaries, but Vivado is a large threaded application with its own JVM and tcmalloc — exactly the kind of software that breaks under translation, as the udev crash above already shows for something much milder. |

Flashing is unaffected either way: `./devkit flash` talks to the board over the
network from the host, and never needs the container.
