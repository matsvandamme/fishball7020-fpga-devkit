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
