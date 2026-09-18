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

<img src="img/board-map.png" alt="The board photographed from above, with 22 labels: the four SMA ports, EXT_CLK, TX_LO and RX_LO, the AD9361, the Zynq XC7Z020, two MT41K256M16 DDR3L chips, the RTL8211F Ethernet PHY, the HR911130A RJ45 jack, the JP5 header, the BOOT DIP switch, the reset button, the microSD card and both USB-C sockets. Parts inferred from package and position rather than a legible marking have dashed rings and say likely: the four RF baluns, the two PGA-102+ amplifiers, the 40 MHz VCTCXO, the USB3320C, the FT2232H, the W25Q128 flash and the FAN1 header." width="900">

## The main devices

On the picture above, a solid ring means the part was identified from the part
itself: a legible marking, a logo, or silkscreen. A dashed ring and the word
"likely" mean the marking is not legible in the photo, but the package and
position fit exactly one part in the schematic. The two SOT-89 parts beside the
outer SMA ports are one example: they are the only SOT-89s on the RF side, and
the PGA-102+ is a SOT-89.

| Ref | Part | What it does | Sheet | Corroborated by | Datasheet |
|---|---|---|---|---|---|
| `U1` | Xilinx **XC7Z020-CLG400** | Zynq-7000: two Cortex-A9 cores plus Artix-7 fabric | 1, 2, 3, 5, 6 | legible on the package | [DS187](https://docs.amd.com/v/u/en-US/ds187-XC7Z010-XC7Z020-Data-Sheet) · [DS190 overview](https://docs.amd.com/v/u/en-US/ds190-Zynq-7000-Overview) |
| `U2` `U3` | Micron **MT41K256M16TW-107IT:P** | DDR3L, 4 Gbit ×16 each, so **1 GB** across a 32-bit bus | 3 | Micron logo and FBGA code `D9SHD` legible; board reports `MemTotal: 1027848 kB` | [Micron part page](https://www.micron.com/products/memory/dram-components/ddr3-sdram/part-catalog/part-detail/mt41k256m16tw-107-it-p) |
| `U11` | Analog Devices **AD9361** | the radio: 2×2 transceiver, 70 MHz – 6 GHz | 10, 11, 12 | ADI logo legible; `ad9361-phy` in IIO | [AD9361](https://www.analog.com/media/en/technical-documentation/data-sheets/ad9361.pdf) |
| `U12` `U13` | Mini-Circuits **PGA-102+** | transmit power amplifier, one per channel | 12 | SOT-89 packages beside the outer SMA ports; self-test measures ~15.7 dB of gain at 900 MHz | [PGA-102+](https://www.minicircuits.com/pdfs/PGA-102+.pdf) |
| `T1`–`T4` | RF baluns (the schematic gives no part number) | single-ended SMA ↔ the AD9361's differential RF pins | 12 | four square 6-pad parts around the AD9361 | — |
| `U8` | FTDI **FT2232HL** | USB to JTAG *and* serial console, on one socket | 8 | two `ttyUSB` ports enumerate together | [FT2232H](https://ftdichip.com/wp-content/uploads/2024/09/DS_FT2232H.pdf) |
| `U9` | Microchip **USB3320C-EZK** | USB 2.0 OTG PHY | 9 | the `usb0` network interface | [USB3320](https://ww1.microchip.com/downloads/en/DeviceDoc/00001792E.pdf) |
| `IC2` | Realtek **RTL8211F-CG** | gigabit Ethernet PHY | 4 | Realtek logo legible; `eth0` | [Realtek product page](https://www.realtek.com/Product/Index?id=3975&cate_id=786) |
| `RJ1` | HanRun **HR911130A** | RJ45 with integrated magnetics | 4 | legible on the part | [LCSC page, with datasheet](https://lcsc.com/product-detail/Ethernet-Connectors-Modular-Connectors-RJ45-RJ11_HANRUN-Zhongshan-HanRun-Elec-HR911130A_C54408.html) |
| — | Winbond **W25Q128JVSIQ** | 16 MB QSPI flash: FSBL, U-Boot, its environment, a small Linux image | 2 | four MTD partitions totalling 16 MB | [W25Q128JV](https://www.winbond.com/resource-files/w25q128jv%20revf%2003272018%20plus.pdf) |
| `IC1` | onsemi **MAX809TTRG** | reset supervisor, behind the `RST` button (`SW1`) | 2 | | [MAX809](https://www.onsemi.com/pdf/datasheet/max809s-d.pdf) |
| `IC7` | TI **TXS02612RTWR** | SD-card level shifter and 2-port expander | 7 | | [TXS02612](https://www.ti.com/lit/ds/symlink/txs02612.pdf) |
| `IC4` | serial EEPROM *(inferred)* | holds the FT2232's USB descriptors; the schematic shows `EEDAT`, `DI`, `DO` against the FT2232 | 8 | | — |
| `K1` `Q3` | Panasonic **AQY221N2VW** solid-state relay + AOS **AO3400A** MOSFET | the PTT switch, brought out on JP5 pin 17 | 13 | | [AQY221N2VW](https://industry.panasonic.com/global/en/products/control/relay/photomos/number/aqy221n2vw) · [AO3400A](https://www.aosmd.com/res/datasheets/AO3400A.pdf) |

Not on the picture: the MAX809, the TXS02612, the EEPROM, the relay and the
LEDs are too small to find reliably in an 800-pixel photo. The power
regulators are not in the published schematic at all, so this page cannot name
them. For the RTL8211F the link is Realtek's product page, the official source.

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
| `JP5` | the 2×10 expansion header. Pins 7/9/11/13 are `sample_gpio[3:0]`; see [the pinout](tx-gpio-bitmap.md#the-pins) |
| `JP1`–`JP4` | further headers |
| `BOOT1` | the 2-position boot switch: SD `0 0`, QSPI `1 0`, JTAG `1 1` |
| `RJ1`, 2 × USB-C, microSD, `FAN1` | network, host connections, boot media, fan |
| `RED1` `BLUE1` | the two LEDs, each through 240 Ω |

`RF1`, `RF2` and `RF3` are worth knowing about. An external reference and
brought-out LOs are what you would use to run two of these boards coherently,
which is the same problem the [sample-locked GPIO
outputs](tx-gpio-bitmap.md) address from the digital
side.

## Supply rails

From sheet 1: **VCC5V**, **VCC3V3**, **VCC1V8**, **VCC1V35** (the DDR3L bank)
and **1V3_A** (the AD9361's analogue supply). Which rail feeds which FPGA bank
matters when you constrain a pin, and that is set out with the evidence under
[the pins](tx-gpio-bitmap.md#the-pins) — bank 13, where the sample-locked GPIO pins
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
