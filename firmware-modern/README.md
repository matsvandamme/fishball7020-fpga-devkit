# firmware-modern — a current Linux for this board

**Status: kernel and device tree build. Nothing has been flashed yet.**

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

## Next, and read this before the first boot

**Remove the TX antennas, or fit 50 Ω loads.** The whole point of the
attenuation default above is that the transmitter comes up muted — but that is
the thing being changed, and this kernel has never run. The first check after
it boots is that `hardwaregain` reads −89.75 dB.

Then: `./devkit flash --kernel-only` and `--dtb-only` replace exactly those two
files, so `main` is one flash away. The bitstream is **not** touched — the HDL
patches are unaffected by a kernel swap, `BOOT.bin` stays as it is, and that
keeps the iteration loop at minutes rather than a 45–90 minute Vivado build.

Still to do: rebase the eight driver patches (0004, 0005, 0007, 0012, 0015,
0016, 0017, 0018), then Debian on a larger card.
