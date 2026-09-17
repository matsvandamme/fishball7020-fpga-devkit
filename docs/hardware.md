# What is on the board

Everything below is read off the vendor schematic in
[`docs/vendor/`](vendor/7020_936x_SDR-schematic.pdf), with the sheet number so
you can check it, and cross-checked against what a running board reports
wherever that was possible.

Where a row says *inferred*, the schematic shows the pins and the connections
but not a part number, and I have said what the inference rests on. Where
something could not be determined at all, it is in
[What this page cannot tell you](#what-this-page-cannot-tell-you) rather than
guessed at.

<img src="img/board-map.png" alt="The board photographed from above, with EXT_CLK, the JP5 expansion header, the Zynq, the RJ45 jack, the four SMA ports, the TX_LO and RX_LO U.FL connectors, the AD9361, the two DDR3 chips, the BOOT switch, the microSD slot and the two USB-C sockets each labelled" width="900">

## The main devices

| Ref | Part | What it does | Sheet | Corroborated by |
|---|---|---|---|---|
| `U1` | Xilinx **XC7Z020-CLG400** | Zynq-7000: two Cortex-A9 cores plus Artix-7 fabric | 1, 2, 3, 5, 6 | legible on the package |
| `U2` `U3` | Micron **MT41K256M16TW-107IT:P** | DDR3L, 4 Gbit ×16 each, so **1 GB** across a 32-bit bus | 3 | board reports `MemTotal: 1027848 kB` |
| `U11` | Analog Devices **AD9361** | the radio: 2×2 transceiver, 70 MHz – 6 GHz | 10, 11, 12 | `ad9361-phy` in IIO |
| `U12` `U13` | Mini-Circuits **PGA-102+** | transmit power amplifier, one per channel | 12 | self-test measures ~15.7 dB of gain at 900 MHz |
| `U8` | FTDI **FT2232HL** | USB to JTAG *and* serial console, on one socket | 8 | two `ttyUSB` ports enumerate together |
| `U9` | Microchip **USB3320C-EZK** | USB 2.0 OTG PHY | 9 | the `usb0` network interface |
| `IC2` | Realtek **RTL8211F-CG** | gigabit Ethernet PHY | 4 | `eth0` |
| `RJ1` | HanRun **HR911130A** | RJ45 with integrated magnetics | 4 | legible on the part |
| — | Winbond **W25Q128JVSIQ** | 16 MB QSPI flash: FSBL, U-Boot, its environment, a small Linux image | 2 | four MTD partitions totalling 16 MB |
| `IC1` | **MAX809TTRG** | reset supervisor | 2 | |
| `IC7` | TI **TXS02612RTWR** | SD-card level shifter and 2-port expander | 7 | |
| `IC4` | serial EEPROM *(inferred)* | holds the FT2232's USB descriptors; the schematic shows `EEDAT`, `DI`, `DO` against the FT2232 | 8 | |
| `K1` `Q3` | **AQY-221N2VW** solid-state relay + **AO3400A** MOSFET | the PTT switch, brought out on JP5 pin 17 | 13 | |

## Clocks

The 40 MHz reference is the one that matters for radio work: everything the
AD9361 does is derived from it, so its accuracy is the radio's accuracy.

| Ref | Frequency | Feeds | Sheet |
|---|---|---|---|
| `Y3` | **40 MHz** | the AD9361 reference. Its tuning voltage, `XTAL_VTC`, is brought out on **JP5 pin 15**, so the oscillator can be disciplined from outside — a GPSDO, for instance | 10 |
| `Y2` | 33.333 MHz | `PS_CLK`, the Zynq processing system | 6 |
| `Y1` | 50 MHz | the PL fabric, at 1.8 V | 5 |
| `OS1` | 25 MHz | the Ethernet PHY | 4 |
| `OS2` | 24 MHz | the USB PHY | 9 |
| `X1` | crystal, with 18 pF loading caps | the FT2232HL | 8 |

## Connectors

| Ref | What it is |
|---|---|
| 4 × SMA | `TX1A`, `RX1A`, `TX2A`, `RX2A`. **Read the silkscreen** rather than counting positions |
| `RF1` | `EXT_CLK`, U.FL — feed the board an external reference instead of `Y3` |
| `RF2` `RF3` | `TX_LO` and `RX_LO`, U.FL — the AD9361's local oscillators, brought out |
| `JP5` | the 2×10 expansion header. Pins 7/9/11/13 are `sample_gpio[3:0]`; see [the pinout](../README.md#the-pins) |
| `JP1`–`JP4` | further headers |
| `BOOT1` | the 2-position boot switch: SD `0 0`, QSPI `1 0`, JTAG `1 1` |
| `RJ1`, 2 × USB-C, microSD, `FAN1` | network, host connections, boot media, fan |
| `RED1` `BLUE1` | the two LEDs, each through 240 Ω |

`RF1`, `RF2` and `RF3` are worth knowing about. An external reference and
brought-out LOs are what you would use to run two of these boards coherently,
which is the same problem the [sample-locked GPIO
outputs](../README.md#sample-locked-gpio-outputs) address from the digital
side.

## Supply rails

From sheet 1: **VCC5V**, **VCC3V3**, **VCC1V8**, **VCC1V35** (the DDR3L bank)
and **1V3_A** (the AD9361's analogue supply). Which rail feeds which FPGA bank
matters when you constrain a pin, and that is set out with the evidence under
[the pins](../README.md#the-pins) — bank 13, where the sample-locked GPIO pins
live, runs from VCC3V3.

## What this page cannot tell you

- **Which physical SMA is which.** The schematic gives the net names and the
  photo shows four identical connectors. The mapping between them lives in the
  PCB layout, which this repo does not have. The board is silkscreened; read it.
- **Which USB-C socket is which.** Same reason. Both are labelled on the board.
- **Whether `RF1`/`RF2`/`RF3` are fitted on your board.** The schematic shows
  them, and `RF1` has a `33R/NC` option on its feed, which is the kind of thing
  that differs between production runs. Look before you plan around them.
- **Component values for most passives.** They are in the schematic; this page
  covers the devices you would want to look up a datasheet for.

Regenerate the picture with
[`docs/img/make_board_map_svg.py`](img/make_board_map_svg.py).
