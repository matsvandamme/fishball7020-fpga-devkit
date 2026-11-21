# firmware: the factory firmware, rebuilt from source

> **PlutoSky R2:** a different board, built from
> [its own repository](https://github.com/matsvandamme/plutosky-r2-fpga-devkit). Nothing built here works on it.

A reconstruction of the firmware the Fishball7020 ships with on its SD card:
the vendor's Linux 5.15, a Buildroot root filesystem that runs from RAM, and
the FPGA design, which you build with Vivado or take ready-made from an XSA.
It supports control over both USB and Ethernet. This is the target that makes
the provenance claim: rebuilt from source, it matches a factory board file by
file ([below](#verified-against-the-real-board)).

| | here (factory) | [`firmware-modern/`](../firmware-modern/README.md) |
|---|---|---|
| kernel | 5.15, the vendor's fork | 6.12, Analog Devices `main` |
| device tree | a flat file decompiled from the factory `.dtb` | a short overlay on ADI's `zynq-pluto-sdr.dtsi` |
| userspace | Buildroot and busybox, in RAM | Debian 13 with systemd, on the SD card |
| FPGA | built with Vivado, or taken from an XSA | always taken from an XSA |
| claim | the same **bytes** as a factory board | the same **behaviour**, on a current kernel |

`firmware-modern/` is the recommended target unless you specifically want the
factory kernel. Both build `BOOT.bin` from the same FSBL and U-Boot source,
pinned in [`scripts/fetch_common.sh`](scripts/fetch_common.sh), and drive the
board with the same host tools. `./devkit` acts on `firmware-modern/` by default;
add `--target factory` to act on this one, or set `DEVKIT_TARGET=factory`.

Upstream source: [`Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR`](https://github.com/Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR),
a fork of ADI's `plutosdr-fw` (the ADALM-Pluto firmware) retargeted from the
Pluto's XC7Z010 to this board's XC7Z020, with matching AD9361 pin constraints.

## Quick start

```bash
# run from: the repo root
./devkit doctor --target factory   # can this machine build? about a second
./devkit setup --target factory    # clone upstream into firmware/src/ and apply patches/ (~6.8 GB)
./devkit sim                       # simulate the custom HDL first, if you changed any
./devkit build --target factory    # everything, with Vivado (45-90 min)
./devkit verify --target factory   # five files present, bitstream compressed, timing met
```

**Without Vivado**, give the build an **XSA**: the finished FPGA design in one
file, the bitstream plus a description of the hardware around it. The build then
skips the FPGA stage and needs nothing from AMD installed
([`docs/building-without-vivado.md`](../docs/building-without-vivado.md)):

```bash
# run from: the repo root
XSA="$(./firmware-modern/fetch-pinned-xsa.sh)"   # the XSA of a published factory release
./devkit build --target factory --xsa "$XSA"
```

A release's XSA is that release's FPGA design, not necessarily what the current
source would build. Your own previous build leaves one at
`firmware/src/hdl/projects/pluto/system_top.xsa`.

**Put it on the board** over the network, onto a board that is already running.
Each option takes a backup and checks md5 sums before swapping anything in:

```bash
# run from: the repo root
./devkit flash --target factory --all            # all five SD-card files
./devkit flash --target factory --boot-only      # BOOT.bin: an HDL or bitstream change
./devkit flash --target factory --kernel-only    # uImage: a driver or kernel change
./devkit flash --target factory --dtb-only       # devicetree.dtb: a device-tree patch
./devkit flash --target factory --rootfs-only    # uramdisk.image.gz
./devkit verify --target factory --board         # is the board running what you built?
```

Other ways to flash, including a card reader and recovery:
[`docs/flashing.md`](../docs/flashing.md). The full build walkthrough (Vivado,
the block diagram, adding HDL): [`docs/building.md`](../docs/building.md).

## What is in this directory

| | |
|---|---|
| [`patches/`](patches/README.md) | the changes applied to upstream, one section per patch; five are transmitter safety |
| `scripts/setup.sh`, `build_all.sh`, `verify_output.sh`, `doctor.sh` | what `./devkit setup`, `build`, `verify` and `doctor` run with `--target factory` |
| `scripts/fetch_common.sh` | the pinned upstream, U-Boot, FSBL and bootgen commits, shared with `firmware-modern/` |
| `scripts/build_hdl.tcl`, `import_xsa.sh`, `boot.bif`, `check_bootbin.py` | the FPGA build, the `--xsa` path, `BOOT.bin` packaging, and reading a `BOOT.bin` back apart |
| `scripts/fix_and_retry_buildroot.sh` | repairs Buildroot download-hash drift and retries |
| `scripts/gen_fir_coe.py`, `gen_fir_coe.m`, `*.coe` | receive-filter coefficient files |
| [`fsbl/`](fsbl/README.md) | builds the FSBL (first-stage boot loader) without Vitis |
| `sim/` | testbenches for the custom HDL; `./devkit sim` runs them |
| `src/` | the upstream source, cloned and patched by `setup`; not committed |
| `output/` | the five SD-card files: `BOOT.bin`, `uImage`, `devicetree.dtb`, `uEnv.txt`, `uramdisk.image.gz` |

## Rules that save you a card-reader trip or an hour

- **Never flash over DFU** on this board. Use `./devkit flash` or the SD card.
- **Nothing in `src/` is yours.** `setup` clones and patches it, and the surest
  fix for a confused tree is `rm -rf firmware/src && ./devkit setup --target factory`. Put your
  changes in a numbered patch.
- **Never edit a patch that is already applied.** `setup` cannot apply a changed
  patch over its earlier version; add a new, higher-numbered patch instead.
- **Keep `0011`.** It is what stops the transmitter probing at 10 dB of
  attenuation (about +9 dBm at the SMA) into whatever is on the TX port.
- **`CONFIG_BOOTDELAY=3` is your only way into U-Boot.** It is the one window in
  which boot can be interrupted from the serial console.
- **`source tools/env-vivado.sh`, never Vivado's own `settings64.sh`**
  ([`docs/building.md`](../docs/building.md#install-vivado-20222)).
- **`--hdl-only` needs a previous full build.** It reuses the existing kernel,
  U-Boot and root filesystem, and refuses to run without them.

## Verified against the real board

Built from this source and compared file by file with the SD-card contents of a
real factory unit:

- **`devicetree.dtb`**: patch `0002` recompiles byte for byte to the factory
  file. Two later patches change it on purpose, `0008` (GPIO line names) and
  `0011` (probe-time attenuation); without those two it is factory-identical.
- **`uEnv.txt`**: the same content. Only the order in which U-Boot dumps its
  variables differs, which cannot affect boot.
- **Root filesystem**: the same file list. Remaining size differences (a random
  password salt, a build-path dependent GDB helper, a version-string format)
  are cosmetic.
- **`uImage`**: the same kernel `.config` and build banner, but not the same
  bytes, and only when built with `gcc-arm-linux-gnueabi` (the build prints a
  note when it has to fall back to `gnueabihf`). Upstream's git history was squashed to one commit dated after the
  factory firmware was built, so some kernel source has drifted and cannot be
  recovered from the public repo.
- **`BOOT.bin`**: inherits all of the above, plus Vivado's normal
  place-and-route variation.

The optional channelizer and patch `0021` change only the FPGA design, so none
of the above depends on them.

To check your own build and board:

```bash
# run from: the repo root
./devkit verify --target factory --board   # is the card running what you built?
iio_info -u ip:fishball.local | grep -E 'fw_version|hw_model'
# expect fw_version 95aad-dirty (the pinned upstream commit)
# and    hw_model   FISH Ball PlutoSDR Rev.A (Z7020-AD9361)

# against a devicetree.dtb from a factory SD card: only gpio-line-names
# (0008) and adi,tx-attenuation-mdB (0011) should differ
diff <(dtc -I dtb -O dts FACTORY/devicetree.dtb) \
     <(dtc -I dtb -O dts firmware/output/devicetree.dtb)
```

More in [Verify your build is actually running](../docs/flashing.md#verify-your-build-is-actually-running)
and [`docs/provenance.md`](../docs/provenance.md).

## Build system internals

`scripts/build_all.sh` does not call upstream's top-level `Makefile`. It runs
the same steps itself so that Vivado's `settings64.sh`, which it sources only
for the FPGA and packaging steps, cannot put Xilinx's bundled
cross-toolchains on `PATH` for the U-Boot, kernel and Buildroot steps. Those
toolchains break the kernel build (the `GLIBC_2.xx not found` entry in
[`docs/troubleshooting.md`](../docs/troubleshooting.md)).

It does replicate one upstream step: writing `buildroot/board/pluto/VERSIONS`
and running Buildroot's `legal-info` to produce `msd/LICENSE.html`. That file is
not one of the five SD-card outputs, but Buildroot's `post-build.sh` needs it
and stops before `rootfs.cpio.gz` without it.

The seven build stages are listed in
[`docs/building.md`](../docs/building.md#build-the-firmware); `build_all.sh`
itself is short and readable. Its options are `--hdl-only`, `--xsa FILE` and
`--preflight-only` (run the checks that guard the build, then stop).

## Further reading

- [`patches/README.md`](patches/README.md): each patch, what it changes and why.
- [`docs/provenance.md`](../docs/provenance.md): how the reconstruction was made.
- [`docs/transmitter-safety.md`](../docs/transmitter-safety.md): the safety
  patches from the operator's side.
