# Exact command sequences

Run `./devkit doctor` first - it checks everything a build needs in a second.

## Build

```bash
source tools/env-vivado.sh          # always, before any vivado/xsct/bootgen
cd firmware
./scripts/setup.sh                  # once: clones upstream into src/, applies patches/*.patch
./scripts/build_all.sh              # full: ~70 min
./scripts/build_all.sh --hdl-only   # reuses kernel/u-boot/rootfs: ~20 min
```

`setup.sh` applies `patches/*.patch` in sorted order and deliberately skips
`patches/optional/`. To use a worked example:

```bash
(cd src && git apply ../patches/optional/0003-wbfm-channelizer.patch)
```

**Then delete the Vivado project**, or the change is silently ignored:

```bash
rm -rf src/hdl/projects/pluto/pluto.{xpr,cache,gen,hw,ip_user_files,runs,sim,srcs,sdk}
```

## Kernel only

Much faster than `build_all.sh` when only the driver changed:

```bash
cd firmware
SRC=$PWD/src
PATH="$SRC/buildroot/output/host/bin:$SRC/buildroot/output/host/sbin:$PATH" \
  make -C "$SRC/linux" -j"$(nproc)" ARCH=arm \
  CROSS_COMPILE=arm-linux-gnueabihf- uImage UIMAGE_LOADADDR=0x8000
cp src/linux/arch/arm/boot/uImage output/uImage
```

Device tree only: same, with target `zynq-pluto-sdr-fishball.dtb` and
`DTC_FLAGS=-@`, then copy to `output/devicetree.dtb`.

## Check before flashing

Use the script. It does the backup, the checksum verification before the
swap, the clean unmount, the reboot, and confirms the card afterwards:

```bash
./devkit flash               # BOOT.bin + uImage - the usual case
./devkit flash --boot-only   # an HDL change
./devkit flash --kernel-only # a driver change
./devkit flash --all         # everything, e.g. a release
BOARD=192.168.1.50 BOARD_PASS=analog ./devkit flash   # a board elsewhere
```

It reports success only once `/proc/uptime` has reset (a board shutting down
still answers ssh for a few seconds) and the card's md5s match `output/`. The
previous files stay on the card as `*.prev` and in
`firmware/.flash-backups/<stamp>/`. Never DFU for `BOOT.bin` - it has no target
for it - and never pull power mid-write. Afterwards, `./devkit verify --board`.

## After flashing

```bash
python3 ../tools/selftest/sdr_selftest.py --ssh                        # never transmits
python3 ../tools/selftest/sdr_selftest.py --ssh --loopback --pad 30    # + RF, needs a cable
```

Denser frequency data, or a crossed loop that separates the transmit chain from
the receive chain — see `measuring.md`:

```bash
--sweep-points 60 --sweep-start 70e6 --sweep-stop 6e9
--tx-channel 0 --rx-channel 1
```

## Recovering

Keep a copy of a known-good `output/` before experimenting. The distributor's
prebuilt factory firmware is at `OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR`,
confirmed by checksum against a real unit; copying those files onto the SD card
returns the board to its shipped state.

## Building in a container

**This is now the recommended build route.** `./devkit container build
--hdl-only` runs the build inside a pinned Ubuntu 22.04 image with
`$XILINX_DIR` (default `/tools/Xilinx`) bind-mounted read-only. Verified end
to end: Vivado installed by `./devkit container install` into a directory the
host had never used produced a **byte-for-byte identical `BOOT.bin`**.
`./devkit doctor` now points at it when the host OS is too new.

All five SD-card files are reproducible. `uramdisk.image.gz` was not until
`mkimage` was pinned with `SOURCE_DATE_EPOCH`: it re-wraps the rootfs every
build, including `--hdl-only`, and stamped the current time into u-boot's
header. The payload never changed - only the header.

Two failures cost an afternoon and neither error names its cause:

**Vivado dies mid-synthesis** with `tcmalloc: large alloc 115875935977472
bytes` or `realloc(): invalid pointer`. Its licence manager `dlopen`s
`libudev.so.1` and enumerates every device to fingerprint the host, by which
point Vivado's tcmalloc has replaced malloc process-wide while libudev still
frees through glibc. `tools/container/udev-stub.c` answers with an empty list
and never allocates. Do **not** reach for `MALLOC_CHECK_` - that hides real
heap corruption in the tool that builds your bitstream. Mounting `/run/udev`,
`config_webtalk -user off` and using 20.04 all fail to fix it.

**The FSBL stage reports a bare `Channel closed`** from `xsct`. Vitis is
Eclipse-based and needs GTK3 plus the SWT dependencies; Vivado's own GUI needs
GTK2. The image carries both.

Also: mount the repo at **its own absolute path**, because `pluto.xpr` stores
absolute paths; and `tools/env-vivado.sh` now engages the `legacy-libs` shim
only where the distro lacks `libtinfo.so.5`, since those copies link
`GLIBC_2.33` and cannot load on anything older than jammy.

Full write-up: [`docs/building-in-a-container.md`](../../../../docs/building-in-a-container.md)
