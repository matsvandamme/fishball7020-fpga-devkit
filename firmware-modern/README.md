# firmware-modern: a current Linux for this board

> **PlutoSky R2:** a different board, built from
> [its own repository](https://github.com/matsvandamme/plutosky-r2-fpga-devkit). Nothing built here works on it.

Linux 6.12 LTS from Analog Devices, with a Debian 13 root filesystem, for the
Fishball7020. This is the **recommended** firmware target: use it unless you
specifically need the factory kernel.

| | [`firmware/`](../firmware/README.md) (factory) | here (modern) |
|---|---|---|
| kernel | 5.15, the vendor's fork | **6.12**, Analog Devices `main` |
| device tree | a flat file decompiled from the factory `.dtb` | a short overlay on ADI's `zynq-pluto-sdr.dtsi` |
| userspace | Buildroot and busybox, in RAM | **Debian 13 armhf with systemd**, on the SD card ([`debian/`](debian/README.md)) |
| FPGA | built with Vivado, or taken from an XSA | always taken from an XSA |

Both targets drive the same board with the same host tools. The `./devkit`
commands act on this target by default (`--target modern` below only says so
explicitly); add `--target factory`, or set `DEVKIT_TARGET=factory`, to act on
the factory one.

## Quick start

You need an **XSA**: the FPGA design in one file, the bitstream plus a
description of the hardware around it. This target never runs Vivado, so it
cannot make one. The pinned one is the XSA of a published factory release,
downloaded and checked against the sha256 in [`factory-xsa.pin`](factory-xsa.pin):

```bash
# run from: the repo root
./devkit setup --target modern                  # fetch the sources, apply the patches (~0.6 GB)
XSA="$(./firmware-modern/fetch-pinned-xsa.sh)"  # download the pinned XSA
./devkit build --target modern --xsa "$XSA"     # BOOT.bin, uImage, devicetree.dtb, uEnv.txt
./devkit verify --target modern                 # read the parts back out of BOOT.bin and check them
```

The build needs an ARM Linux cross-compiler (a compiler that runs on your PC and
produces code for the board's ARM cores). Either `gcc-arm-linux-gnueabi` or
`gcc-arm-linux-gnueabihf` works. With neither installed, put `container` in
front and the build runs in a container that has one:
`./devkit container build --target modern --xsa "$XSA"`.

If you built the factory target with Vivado, its XSA is at
`firmware/src/hdl/projects/pluto/system_top.xsa`. A release's XSA is that
release's FPGA design, which is why `--xsa` has no default.

Then put it on the board. **Over the network**, onto a board that is already
running, with a backup and an md5 check before anything is swapped:

```bash
# run from: the repo root
./devkit flash --target modern --boot-only      # BOOT.bin
./devkit flash --target modern --kernel-only    # uImage
./devkit flash --target modern --dtb-only       # devicetree.dtb
```

**A whole new card**, from a card reader, including the Debian root:

```bash
# run from: the repo root
./devkit build --target modern --rootfs-only              # debian/rootfs.tar, ~10 min
./devkit write-card --target modern --dry-run /dev/sdX    # checks the device, writes nothing
sudo ./devkit write-card --target modern /dev/sdX         # refuses any non-removable disk
```

`./devkit build --target modern --all --xsa "$XSA"` builds the boot files and
the root in one go. The root is built in its own container, so run that on your
PC rather than inside `./devkit container`.

## What is in this directory

| | |
|---|---|
| `setup.sh`, `build_all.sh`, `verify_output.sh` | what `./devkit setup`, `build` and `verify` run for this target |
| [`patches/`](patches/README.md) | the ten driver patches, most of them transmitter safety |
| `dts/zynq-pluto-sdr-fishball.dts` | the board's device tree, as an overlay on ADI's |
| `config/fishball_defconfig` | the kernel configuration; `config/fishball.config` explains each option |
| [`debian/`](debian/README.md) | the Debian root filesystem, and `write-card.sh` |
| `verify_dtb.py` | checks a built device tree; CI runs it |
| `dump_context.py` | lists every IIO attribute, to compare two kernels with `diff` |
| `write_card.sh` | puts a kernel on a card from a card reader (see below) |
| `factory-xsa.pin`, `fetch-pinned-xsa.sh` | which release's XSA to build from, and its checksum |
| `baseline/` | the self-test results the modern target is compared against |

## Building the kernel by hand

`build_all.sh` does this for you. By hand:

```bash
# run from: firmware-modern/src/linux
CROSS=arm-linux-gnueabihf-      # or arm-linux-gnueabi-
make ARCH=arm CROSS_COMPILE=$CROSS fishball_defconfig
make ARCH=arm CROSS_COMPILE=$CROSS uImage LOADADDR=0x8000 -j$(nproc)
make ARCH=arm CROSS_COMPILE=$CROSS DTC_FLAGS=-@ xilinx/zynq-pluto-sdr-fishball.dtb
```

Use `fishball_defconfig`, **never `zynq_pluto_defconfig` on its own**: that is
ADI's configuration for an ADALM-Pluto, which has no Ethernet and no SD card,
and a kernel built from it boots without either. U-Boot, built by hand with a
hard-float compiler, needs `CC="${CROSS}gcc -mfloat-abi=soft"`;
[`docs/troubleshooting.md`](../docs/troubleshooting.md) explains why.

## Rules for changing the kernel

- **Keep the USB cable connected.** The USB link answers at `192.168.2.1` even
  when Ethernet does not come up, and it is often the only way back in.
- **Never ship a kernel without the SD card driver.** Flashing over the network
  works by mounting the SD card on the running board; without it, the only
  fix is a card reader. `verify_dtb.py` checks for it.
- **Check the built `.dtb`**, not just the build log. Device-tree mistakes
  usually build cleanly and boot:
  `python3 firmware-modern/verify_dtb.py firmware-modern/src/linux/arch/arm/boot/dts/xilinx/zynq-pluto-sdr-fishball.dtb`
- **Rebuild `debian/rootfs.tar` after changing `debian/overlay/`.** `write-card`
  refuses a tarball older than the overlay.

## When a kernel does not boot

A kernel that does not boot cannot be replaced over the network, because
flashing needs the board's own kernel running. Take the card out, let your
desktop mount it, and use `write_card.sh`:

```bash
# run from: the repo root, card in a reader
./firmware-modern/write_card.sh             # put the new uImage and devicetree.dtb on the card
./firmware-modern/write_card.sh --restore   # put the *.prev copies back
```

It keeps the first copy of each file it replaces as `*.prev` and never
overwrites it, so the file kept is the last one known to boot.

## Further reading

- [`docs/modern-kernel.md`](../docs/modern-kernel.md): why ADI 6.12 and not
  mainline, the device tree, the IIO comparison with 5.15, throughput and
  reproducible builds.
- [`patches/README.md`](patches/README.md): each driver patch.
- [`debian/README.md`](debian/README.md) and
  [`docs/debian-rootfs.md`](../docs/debian-rootfs.md): the root filesystem.
- [`docs/measured-performance.md`](../docs/measured-performance.md): RF
  measurements on both kernels.
