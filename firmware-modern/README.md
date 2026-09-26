# firmware-modern — a current Linux for this board

**Status: running on the board. Selftest green. All eight driver patches rebased
and measured.**

| | |
|---|---|
| Linux 6.12.0 on the board | yes |
| `./devkit selftest` | **23 passed, 0 warnings, 0 failed** |
| cyclic transmit (`OPEN … CYCLIC`) | **works** — the loopback tone passes |
| Ethernet, SD card, GPIO sysfs | yes |
| transmitters at boot | **−89.75 dB**, from the device tree alone |
| `tools/flash.sh` over the network | works again |
| the eight driver patches | **rebased** — six add byte-identical code; see [`patches/`](patches/) |
| the seven transmitter-safety attributes | all present, all reading their 5.15 values |

This is the `modern` branch's firmware target, built for
[issue #4](https://github.com/matsvandamme/fishball7020-fpga-devkit/issues/4).
`main` stays as it is: a verified, byte-identical reconstruction of the factory
firmware. This is a different thing that does not pretend to be that.

| | `main` | here |
|---|---|---|
| kernel | 5.15.0, vendor fork of a fork | **6.12.0**, Analog Devices `main` |
| device tree | 1003-line flat file, decompiled from the factory `.dtb` | **175-line overlay** on ADI's `zynq-pluto-sdr.dtsi` |
| userspace | Buildroot, busybox, ramdisk | still Buildroot — Debian comes later |

## Why ADI 6.12 and not mainline 7.2

The issue proposed mainline. Mainline does not carry the AD9361 driver, and
that is the smaller half of the problem. `IIO_BUFFER_BLOCK_FLAG_CYCLIC` is
defined in `include/linux/iio/buffer_impl.h` — an ADI modification to **IIO
core** — and the board's libiio (pinned at `38483f31`, 0.25) probes
`BLOCK_FREE_IOCTL` to enable the high-speed path, where *"cyclic mode is only
supported"*. Without that ABI, libiio silently falls back to `read()/write()`
and **`OPEN … CYCLIC` stops working at the daemon**, which breaks
`./devkit gpio-check`, the selftest's loopback tone and the MCP's transmit
tools.

ADI's `main` is on 6.12 — a current LTS — and still ships `ad9361.c`,
`cf_axi_dds.c`, `cf_axi_adc_core.c` *and* that flag. So the eight
transmitter-safety patches rebase instead of being rewritten, and ~18,900 lines
stay someone else's job. Mainline remains a later stretch goal, not a
prerequisite.

## The device tree

`dts/zynq-pluto-sdr-fishball.dts` is an overlay, not a flat tree. The board's
AD9361 differs from a stock Pluto in exactly **nine properties**, established
by parsing both trees and diffing them rather than by eye: 2R2T, four LVDS
interface settings, two synthesiser start frequencies, a transmit feedback
clock delay, and the transmit attenuation.

That last one is safety-critical and is now a **default rather than a patch**.
ADI ships 10 dB; on a board with a power amplifier that is roughly +9 dBm out
of an SMA, applied by `ad9361_setup()` before any userspace runs. `main` fixes
it with patch 0011. Here it is simply the value in the tree, which is strictly
better — a patch can be forgotten.

Two bugs were caught by checking the built `.dtb` rather than trusting a clean
build, and both would have booted:

- a `memory@0` node became a **sibling** of the dtsi's `memory`, so the tree
  carried both 512 MB and 1 GB. `dtc` reported it only as an oblique
  "duplicate unit-address" warning against an unrelated node.
- `adi,channels` was missing. `dma-axi-dmac.c` configures from hardware only
  for cores `>= 4.3.a`; older ones take `axi_dmac_parse_dt()`, which returns
  `-ENODEV` without it. This board's bitstream is from ADI's 2018-era HDL, so
  a failed DMA probe — nothing streaming at all — was a real possibility.

## Building

```bash
# run from: firmware-modern/src/linux
CROSS=../../../firmware/src/buildroot/output/host/bin/arm-linux-gnueabihf-

# the board's device tree and the eight driver patches
cp ../../dts/zynq-pluto-sdr-fishball.dts arch/arm/boot/dts/xilinx/
for p in ../../patches/*.patch; do git apply "$p" || break; done

# the kernel configuration
cp ../../config/fishball_defconfig arch/arm/configs/
make ARCH=arm CROSS_COMPILE=$CROSS fishball_defconfig

make ARCH=arm CROSS_COMPILE=$CROSS uImage LOADADDR=0x8000 -j$(nproc)
make ARCH=arm CROSS_COMPILE=$CROSS DTC_FLAGS=-@ xilinx/zynq-pluto-sdr-fishball.dtb
```

**Do not build `zynq_pluto_defconfig` on its own.** It rebuilds boot 1 from the
table below: no Ethernet, no SD card, no GPIO sysfs. ADI's defconfig describes an
ADALM-Pluto, and a Pluto has none of that hardware.

Two config files, doing different jobs:

| | |
|---|---|
| [`config/fishball_defconfig`](config/fishball_defconfig) | what to **build**. 266 lines, `savedefconfig` output, verified to reproduce the `.config` that built the tested `uImage` byte-for-byte. Sixteen lines more than `zynq_pluto_defconfig`. |
| [`config/fishball.config`](config/fishball.config) | why each option is there — 26 entries, annotated with which part of this board needs it. Four of them (`ETHERNET`, `OF_MDIO`, `DEBUG_KERNEL`, `CRYPTO_ECB`) do not appear in the defconfig because they are implied; `savedefconfig` strips anything Kconfig will select anyway. |

Keeping both is deliberate: a `defconfig` is reproducible but says nothing, and
a commented delta explains itself but drifts. The defconfig is authoritative.

The `.dts` is built by name because nothing adds it to a Makefile; that is
deliberate, so the file stays a drop-in rather than a tree modification.

`zynq_pluto_defconfig` already enables `CONFIG_AD9361`, `CONFIG_CF_AXI_ADC` and
`CONFIG_CF_AXI_DDS`. The 2018-era Linaro GCC 7.3 from `main`'s Buildroot builds
6.12 without complaint.

## What the bring-up cost, and what it taught

Three boots, two card-reader trips. Every failure was the same shape: **ADI's
`zynq_pluto_defconfig` and `zynq-pluto-sdr.dtsi` describe an ADALM-Pluto**, and
this board is a Pluto-compatible with more hardware on it. Nothing was wrong
with the kernel; things were simply absent.

| boot | what was missing | why |
|---|---|---|
| 1 | Ethernet, SD, GPIO sysfs | `CONFIG_MACB`, `CONFIG_REALTEK_PHY`, `CONFIG_MMC`, `CONFIG_GPIO_SYSFS` — a Pluto has no Ethernet and boots from QSPI |
| 2 | SD only | driver built, but ADI's dtsi says `&sdhci0 { status = "disabled"; }` |
| 3 | nothing | — |

Two lessons worth keeping:

- **Losing `/dev/mmcblk0` costs a card-reader trip**, because `tools/flash.sh`
  works by mounting `/dev/mmcblk0p1` on the running board. It is the one
  capability whose absence you cannot fix remotely.
- **The USB gadget saved both rounds.** With Ethernet down the board was still
  reachable at `192.168.2.1`, which is how every measurement above was taken.
  Keep the USB cable connected while iterating on the kernel.

After boot 2 the guessing stopped: comparing the `status` of every node in the
built `.dtb` against the factory one found exactly one regression, and after
the fix, none. That audit is cheap and worth re-running on any DTS change.

## The driver patches

All eight are rebased, applied in filename order, and measured on the board
rather than declared to apply. [`patches/README.md`](patches/README.md) has the
per-patch detail; the short version:

- **six of the eight add byte-for-byte identical code.** Only `0004` and `0015`
  needed anything different, and both times because ADI's tree changed, not
  because the patch was fragile.
- the rebase **found an upstream bug**: ADI's 6.12 never wires up
  `indio_dev->setup_ops`, so the DDS buffer's pre-enable and post-disable hooks
  are dead. gcc warns about it. `0004` restores the line.
- the **buildroot halves of `0004` and `0012` are not carried here**, because
  `main`'s rootfs already has them. That becomes a live trap the moment the
  rootfs is replaced — see the README in `patches/`.

## Next

Throughput and signal parity against `docs/measured-performance.md`,
interleaved A/B, then Debian on a larger card.

Two loose ends worth writing down:

- `cf-ad9361-lpc` is missing four channel `label` attributes that 5.15 had.
  Metadata only — nothing reads them — but it is an unexplained difference and
  unexplained differences are how regressions hide.
- the `setup_ops` finding should go upstream to ADI.
