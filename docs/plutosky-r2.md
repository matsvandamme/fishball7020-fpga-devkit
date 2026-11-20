---
icon: material/chip
description: The PlutoSky R2 is a different board from the R1. What differs, how to build for it with --rev r2, and what has and has not been tested.
---

# The PlutoSky R2

The PlutoSky R2 needs its own firmware build. **An R1 image does not work on
it**: the board boots Linux and has no radio, no Ethernet and no USB.

!!! note "Booted on one R2, 2026-11-20"
    Built with Vivado 2022.2 (timing met, WNS +0.100 ns) and booted from a card
    on one PlutoSky R2: the radio is found and receives, Ethernet gets a DHCP
    address at 1 Gbit/s, and USB enumerates. Transmit, the `JP5` outputs and
    the 10 MHz input are not tested yet.

## Which board do you have

| | PlutoSky R1 / 7020-SDR | PlutoSky R2 |
|---|---|---|
| Zynq package | XC7Z020-**CLG400** | XC7Z020-**CLG484** |
| Vendor v0.38 firmware version | `v0.38-4-g95aad` | `v0.38-5-g76414` |
| QSPI flash | 16 MB (W25Q128) | 32 MB (W25Q256) |
| Extra socket | none | `10M_IN`, a 10 MHz reference input |
| `--rev` | `r1` (the default) | `r2` |

`iio_attr -C -u ip:192.168.2.1 fw_version` prints the version on the vendor's
firmware. The package is printed on the Zynq itself.

## What differs

Measured on one R2 on 2026-11-18, by reading the processor's pin-mux, clock and
GPIO registers and the device tree under its factory firmware and under an R1
v2.3 image, and checked against the vendor's
[schematic and source](https://github.com/OpenSourceSDRLab/PlutoSky-R2).

| | R1 | R2 |
|---|---|---|
| FPGA pins | CLG400 balls | CLG484 balls: every constraint differs |
| Ethernet PHY | on processor pins MIO 16–27, MDIO on MIO 52/53, address 0 | on FPGA pins, behind a GMII-to-RGMII core; PHY at address 1, core at address 8 |
| MIO bank 501 (MIO 16–53) | 1.8 V | 3.3 V |
| USB PHY reset | MIO 52 | MIO 46 |
| LED | MIO 0 | MIO 7 |
| `JP5` header | 2×10, `3V3_IO1`–`4` at **3.3 V** | 2×12, `EXT_IO` pairs at **1.8 V**, pin 1 is **5 V** |
| Reference | free-running 40 MHz | 40 MHz locked to `10M_IN` by an ADF4001 the FPGA programs |

With an R1 image on an R2 the kernel log shows all three failures:

```text
ad9361 spi0.0: ad9361_spi_check : Unsupported PRODUCT_ID 0xFF
mdio_bus e000b000.ethernet-ffffffff: MDIO device at address 0 is missing.
macb e000b000.ethernet eth0: Could not attach PHY (-19)
```

## Build for the R2

Every command that takes `--target` also takes `--rev`. `DEVKIT_REV=r2` in your
environment makes it the default.

```bash
# run from: the repo root

# 1. The FPGA design (Vivado 2022.2, 45-90 min). Fetches hdl/ only, ~0.2 GB.
./devkit setup --target factory --rev r2
./devkit build --target factory --rev r2

# 2. The boot files and the kernel, around that design.
./devkit setup --rev r2
./devkit build --rev r2 --xsa firmware/src-r2/hdl/projects/pluto/system_top.xsa

# 3. A card. The Debian root is the same for both boards.
./devkit build --rootfs-only
sudo ./devkit write-card --rev r2 /dev/sdX
```

| Step | Writes |
|---|---|
| 1 | `firmware/src-r2/hdl/projects/pluto/system_top.xsa` |
| 2 | `firmware-modern/output-r2/`: `BOOT.bin`, `uImage`, `devicetree.dtb`, `uEnv.txt` |

The R1's files stay where they were, in `firmware-modern/output/`. An XSA for
the other board is refused by its part number, so the two cannot be mixed by
passing the wrong file.

!!! danger "`./devkit flash --rev r2` does not check which board answers"
    It copies `output-r2/` to whatever board it finds. Flashing an R2 image to
    an R1, or the reverse, gives a board that boots without a network. The way
    back is a card reader.

## What `--rev r2` changes

| Part | R2 source |
|---|---|
| FPGA design | [`firmware/revs/r2/patches/`](https://github.com/matsvandamme/fishball7020-fpga-devkit/tree/main/firmware/revs/r2/patches): the vendor's R2 design, then this repo's FPGA patches with R2 pin constraints |
| First-stage boot loader | generated from the R2 XSA, which sets the pin-mux and the 3.3 V bank |
| U-Boot | the R1's source, unchanged |
| Kernel | the R1's, plus `CONFIG_XILINX_GMII2RGMII` ([`config/r2.config`](https://github.com/matsvandamme/fishball7020-fpga-devkit/blob/main/firmware-modern/config/r2.config)) |
| Device tree | [`zynq-pluto-sdr-fishball-r2.dts`](https://github.com/matsvandamme/fishball7020-fpga-devkit/blob/main/firmware-modern/dts/zynq-pluto-sdr-fishball-r2.dts): includes the R1's and overrides Ethernet, the USB reset pin, the LED pin and the model |
| Debian root | the same |

On the R2 the factory target builds **only** the FPGA design. There is no R2
build of the 5.15 kernel or the Buildroot root.

## The sample-locked GPIO pins on the R2

The four [sample-locked outputs](tx-gpio-bitmap.md) keep their `JP5` pin
numbers, 7, 9, 11 and 13, so the same cable fits. **The level does not carry
over: 1.8 V on the R2, 3.3 V on the R1.**

| Signal | `JP5` pin | R2 net | R2 ball |
|---|---|---|---|
| `sample_gpio0` | 7 | `EXT_IO3_P` | M19 |
| `sample_gpio1` | 9 | `EXT_IO3_N` | M20 |
| `sample_gpio2` | 11 | `EXT_IO5_P` | M21 |
| `sample_gpio3` | 13 | `EXT_IO5_N` | M22 |

Pin 1 of the R2's `JP5` is `VCC5V`, and pins 2, 22 and 24 are ground. Do not
plug an R1 wiring harness in without checking it against the R2 schematic.

## What is tested and what is not

| | State |
|---|---|
| A Vivado build of the R2 design | run once, 2026-11-19: timing met, WNS +0.100 ns, 12,717 LUTs. Two warnings come with the vendor's design: a pin constraint for a `gpio_sync` port that does not exist, and the reference PLL's slow SPI clock, which has no timing constraint |
| The boot loader's generated headers (`firmware/fsbl/generated/`) | made from an R1 design; the build's check accepts them for the R2 XSA, and the pin and memory setup is taken from the XSA itself |
| Booting the result on an R2 | done on one board: boots to Debian, radio receives, USB enumerates |
| Ethernet on Linux 6.12 through the converter core | works at 1 Gbit/s. The device tree says `rgmii-id`, not the vendor tree's `rgmii-rxid`: with the vendor's value the board receives and cannot send |
| Transmit, the sample-locked `JP5` outputs | not tested on the R2 |
| `./devkit flash --rev r2` and `./devkit write-card --rev r2` | not run on an R2; the test board's card was written from a card reader by hand |
| `./devkit selftest` baselines, the docs' port and header drawings | all R1 |
| A pinned, released R2 XSA | none; `fetch-pinned-xsa.sh` refuses `--rev r2` |
| The 10 MHz reference input | the FPGA programs the PLL as the vendor's design does; nothing here reads its lock state |

## Power, USB and the vendor's manual

The vendor's [PlutoSky R2 user manual](https://blog.opensourcesdrlab.com/archives/plutosky-R2)
says a board that is not detected may be short of power, and to connect both
USB-C sockets. On the test board, one freeze and one restart were seen with
only `DEBUG` connected and none after `USB2.0` was connected as well; that
fits the manual, and is not proven to be the cause.

The USB network is RNDIS, as on the R1. macOS has no driver for it, so from a
Mac use Ethernet or the serial console on `DEBUG` (115200 baud).

## Going back to the factory firmware

The R2's factory firmware is in its QSPI flash and a card does not overwrite
it. Power off, set the `BOOT` switch to QSPI (`1 0`), power on.
