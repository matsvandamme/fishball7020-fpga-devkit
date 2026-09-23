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
