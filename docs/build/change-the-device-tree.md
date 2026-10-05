---
icon: material/file-tree-outline
description: Build the device tree, audit the built .dtb, and flash it with --dtb-only.
---

# Change the device tree

The modern tree, `firmware-modern/dts/zynq-pluto-sdr-fishball.dts`, is an
**overlay** on ADI's `zynq-pluto-sdr.dtsi`: it states only where this board
differs from an ADALM-Pluto.

```bash
# run from: firmware-modern/src/linux
CROSS=arm-linux-gnueabi-      # or arm-linux-gnueabihf-
make ARCH=arm CROSS_COMPILE=$CROSS DTC_FLAGS=-@ xilinx/zynq-pluto-sdr-fishball.dtb
# The rename is yours to do: tools/flash.sh looks for the literal name
# devicetree.dtb and aborts if it is missing.
cp arch/arm/boot/dts/xilinx/zynq-pluto-sdr-fishball.dtb ../../output/devicetree.dtb
```

```bash
# run from: the repo root
python3 firmware-modern/verify_dtb.py firmware-modern/output/devicetree.dtb   # stdlib only
./devkit flash --dtb-only
```

**Check the built `.dtb`, not the `.dts`.** Most of what lands in it comes from
the dtsi, and two mistakes found here built and booted fine:

| Mistake | Effect |
|---|---|
| a `memory@0` node beside the dtsi's `memory` node | the kernel gets two memory sizes; `dtc` only warns "duplicate unit-address" |
| no `adi,channels` | the DMA driver fails to probe on this board's 2018-era FPGA cores, and nothing streams |

`verify_dtb.py` runs 16 checks, including that every node the factory tree
enables is still enabled; CI runs it on every push. Keep
`adi,tx-attenuation-mdB = 89750` in the AD9361 node: it is the safety setting
that makes the transmitter come up at −89.75 dB.

!!! warning "The device tree must match the bitstream"
    Change what the FPGA contains and the description may need to change too.

More: [the modern kernel](../modern-kernel.md#the-device-tree).
