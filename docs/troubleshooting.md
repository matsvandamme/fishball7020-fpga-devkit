# Troubleshooting

Known problems, by symptom, with the cause and the fix. If the radio itself
misbehaves rather than the build, run the [self-test](../tools/selftest/README.md)
first. On a Windows PC with no tools installed, double-click `tools\board-info.cmd`: it
prints what the board is, what it runs and every setting it reports, read-only.
`board-info.cmd -OutFile board.txt` saves the report for a bug report.

| You see | Section |
|---|---|
| ssh, libiio and ping stop after a while; `Calibration TIMEOUT` in the log | [The board stops responding after a while](#the-board-stops-responding-after-a-while) |
| ssh works, SDR software finds no device | [ssh works, but nothing can open the radio](#ssh-works-but-nothing-can-open-the-radio-debian-root) |
| SDRangel shows `PlutoSDR0 TBD` | [SDRangel](#sdrangel-lists-the-board-as-plutosdr0-tbd-and-will-not-open-it) |
| a build error | [Building](#building) |
| a fresh card does nothing, or the old firmware still runs | [Flashing](#a-freshly-flashed-card-seems-to-do-nothing-or-the-old-firmware-still-runs) |

## The board

### The board stops responding after a while

**Symptom.** ssh, libiio and ping stop, but the board is still enumerated on USB.
Before that, the kernel log repeats `ad9361 spi0.0: Calibration TIMEOUT`, then
`Failed to find suitable dividers: ADC clock below limit`, and a write to
`in_voltage_sampling_frequency` blocks forever. Only a physical replug clears it.

**Cause.** Not enough power: on laptop USB bus power alone, a board with a power
amplifier browns out under sustained use. In the host's kernel log, devices on a
**different root port** drop and re-enumerate with it, which no board fault can
cause; `device descriptor read/64, error -71` and `error -110` are the same
signature.

**Fix.** Put the board's second USB cable on a **mains charger**, not another
port on the same laptop. To confirm, run `./devkit selftest`: on mains it reports
`24 passed, 0 failed, HEALTHY` with no Calibration TIMEOUTs.

### ssh works, but nothing can open the radio (Debian root)

**Symptom.** `iio_info -u ip:192.168.2.1` fails and SDR++ finds no device, but
ssh and the console work.

**Cause.** `iiod` (the daemon that serves the radio) `Requires=`
`fishball-rf-quiesce`, so it is held back when the boot-time transmitter mute
could not be confirmed.

**Fix.** Ask why, fix what it names (usually `ad9361-phy` missing: the FPGA or
device tree), then `systemctl start iiod` (which re-runs the quiesce first) or
reboot.

!!! danger "Never run `/usr/sbin/iiod` directly"
    That bypasses the check that the transmitter is quiet.

```bash
# run from: the board
journalctl -b -u fishball-rf-quiesce -u iiod
```

### SDRangel lists the board as `PlutoSDR0 TBD` and will not open it

**Cause.** SDRangel identifies Plutos by serial number, and firmware built
without patch `0001` reports an empty one.

**Fix.** Rebuild with the current `patches/` and reflash; the board mints a
persistent serial on first boot. If SDRangel is a snap, also run
`sudo snap connect sdrangel:raw-usb`.

## Building

### `setup --target modern` stops with `the sparse checkout is not sparse`

**Symptom.** `./devkit setup --target modern` fetches the kernel and applies the
patches, then stops with `ERROR: .../firmware-modern/boot/fw/linux exists - the
sparse checkout is not sparse.` Running it again stops at the same line.

**Cause.** git older than 2.37, such as Ubuntu 22.04's 2.34, defaults to the old
non-cone sparse mode, where the pattern `scripts` matches every directory of
that name, `linux/scripts` among them. The vendor monorepo's `linux/`,
`buildroot/` and `hdl/` were checked out, gigabytes the modern target never uses.

**Fix.** Update the repository (`git pull`): setup now asks for cone mode
explicitly and narrows an existing checkout that is too wide, so running
`./devkit setup --target modern` again repairs it in place. On an older clone,
`rm -rf firmware-modern/boot/fw` and use git 2.37 or newer.

### U-Boot fails with `unrecognized -march target: armv5`

**Cause.** You ran U-Boot's `make` with a hard-float compiler, which refuses
`-march=armv7-a`, so U-Boot falls back to `armv5`.

**Fix.** Pass `CC="arm-linux-gnueabihf-gcc -mfloat-abi=soft"` to U-Boot's `make`
(U-Boot is soft-float anyway). `./devkit build` does this for you.

### `vivado` fails to start, or reports missing shared libraries

**Cause.** You sourced Vivado's `settings64.sh` instead of `tools/env-vivado.sh`,
which supplies the old libraries Vivado 2022.2 needs.

**Fix.** `source tools/env-vivado.sh`. See
[Install Vivado 2022.2](building.md#install-vivado-20222).

### Vivado dies mid-synthesis with `tcmalloc: large alloc 115875935977472 bytes`

**Symptom.** `tcmalloc: large alloc …` or `realloc(): invalid pointer`, in a
container.

**Cause.** Vivado's licence manager loads `libudev.so.1` to fingerprint the host,
and libudev frees memory through glibc after Vivado's tcmalloc has replaced
`malloc`.

**Fix.** `./devkit container` loads a stub libudev; see
[Building in a container](building-in-a-container.md#vivado-dies-in-synthesis-with-a-heap-error).

!!! warning "Do not silence it with `MALLOC_CHECK_`"
    That hides real heap corruption.

### The FSBL stage fails with a bare `Channel closed` from `xsct`

**Cause.** An older checkout that builds the FSBL (first-stage boot loader) with
Vitis's `xsct`, which needs GTK3 and the SWT libraries.

**Fix.** Update: the FSBL now builds from AMD's embeddedsw with
`gcc-arm-none-eabi`. On an old checkout, install GTK3 and SWT.

### The kernel build fails with `GLIBC_2.xx not found` in a `gcc-plugins` step

**Cause.** `env-vivado.sh` was sourced in the same shell; its Xilinx toolchain
directories on `PATH` conflict.

**Fix.** Build the kernel in a fresh shell. `build_all.sh` keeps the two apart.

### U-Boot stage [3/7] fails at `tools/aisimage.o` with `conflicting types for 'fdt64_t'`

**Cause.** Your host has libfdt's headers installed (`libfdt-dev` on
Debian/Ubuntu; on Arch they come with `dtc`), and U-Boot picks them up ahead of
its own.

**Fix.** Patch `0020` fixes it; `./devkit setup` applies it. Do **not** uninstall
the package: on Arch that would take `dtc` with it.

### Buildroot fails with `has wrong sha256 hash`

**Cause.** Known, harmless git-archive repackaging drift for a few pinned commits.

**Fix.** `fix_and_retry_buildroot.sh` repairs it automatically. If it still
fails, check `/tmp/buildroot_autoretry_*.log` for a different cause.

### Buildroot fails with `cp: cannot stat` after you moved the checkout

**Cause.** Buildroot's `output/` is **not relocatable**.

**Fix.** Discard the stale build state (the download cache is unaffected):

```bash
# run from: firmware/
rm -rf src/buildroot/output
./scripts/build_all.sh
```

## Flashing

### `dfu-util -l` shows nothing

!!! danger "Do not use DFU on this board"
    Flash [over SSH](flashing.md#option-c--over-ssh-from-the-running-board-no-card-removal) instead.

### A freshly flashed card seems to do nothing, or the old firmware still runs

**Cause.** The `BOOT` DIP switch is not in SD mode, or the card holds a different
build from the one you think.

**Fix.** Check the switch ([boot modes](flashing.md#boot-modes-boot-dip-switch)),
then `./devkit verify --board` to compare the card with your build.

## Still stuck?

[Open an issue](https://github.com/matsvandamme/fishball7020-fpga-devkit/issues/new/choose);
the templates ask for the details needed. See also
[CONTRIBUTING.md](../CONTRIBUTING.md).
