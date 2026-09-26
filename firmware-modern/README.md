# firmware-modern — a current Linux for this board

**Status: running on the board. Selftest green. Driver patches not yet rebased.**

| | |
|---|---|
| Linux 6.12.0 on the board | yes |
| `./devkit selftest` | **23 passed, 0 warnings, 0 failed** |
| cyclic transmit (`OPEN … CYCLIC`) | **works** — the loopback tone passes |
| Ethernet, SD card, GPIO sysfs | yes |
| transmitters at boot | **−89.75 dB**, from the device tree alone |
| `tools/flash.sh` over the network | works again |
| the eight driver patches | **not yet rebased** — their seven attributes are the only things missing from the IIO contract |

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
make ARCH=arm CROSS_COMPILE=$CROSS zynq_pluto_defconfig
make ARCH=arm CROSS_COMPILE=$CROSS uImage LOADADDR=0x8000 -j$(nproc)
make ARCH=arm CROSS_COMPILE=$CROSS DTC_FLAGS=-@ xilinx/zynq-pluto-sdr-fishball.dtb
```

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

## Next

Rebase the eight driver patches — 0004, 0005, 0007, 0012, 0015, 0016, 0017,
0018 — in dependency order, finishing with 0015 and 0017. Their seven
attributes are the only things now missing from the IIO contract, so
`dump_context.py` gives a precise definition of done. Then Debian, on a larger
card.
