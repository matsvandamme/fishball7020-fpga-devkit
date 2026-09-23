# Building in a container

Vivado 2022.2 is pinned to this project. A toolchain bump changes the
bitstream, and the provenance claims in this repo rest on the current one — so
when the host OS eventually moves somewhere Vivado 2022.2 has never heard of,
the toolchain has to stop depending on the host.

```bash
# run from: the repo root
./devkit container build-image      # once, ~3 minutes
./devkit container doctor           # same checks, inside
./devkit container build --hdl-only # same build, inside
```

Verified on this repo: the container's `BOOT.bin` came out **byte-for-byte
identical** to the host's (`md5 3fb710d8…`), with routing utilisation matching
to five decimals — 6.54675 % vertical, 9.82488 % horizontal on both.

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

> **Verified this far:** the installer extracts inside the image, its bundled
> OpenJDK 11.0.11 starts, and `xsetup` runs and accepts its batch arguments.
> A full install was not run end-to-end here, because Vivado was already
> installed on this machine and the download is ~30 GB behind a login.

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
