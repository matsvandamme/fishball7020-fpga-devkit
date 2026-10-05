---
icon: material/connection
description: The four SMAs, the U.FL sockets and the two USB-C sockets. Trust the silkscreen, not the case.
---

# Which port is which

**Read the board, not the box.** On some PlutoSky R1 units the case's SMA
labels are in the wrong order. Each SMA has its name on the silkscreen beside
it: `TX1A`, `RX1A`, `TX2A` or `RX2A`.

| Connector | What it is |
|---|---|
| 4 × SMA | `TX1A`, `RX1A`, `TX2A`, `RX2A`: the AD9361's `A` ports (its `RX1B`/`RX2B` pairs are not wired) |
| `RF1` (U.FL) | `EXT_CLK`: **connected to nothing as shipped** ([external reference](external-reference-clock.md)) |
| `RF2`, `RF3` (U.FL) | `TX_LO` and `RX_LO`: the AD9361's local oscillators, brought out |
| 2 × USB-C, **USB** and **DEBUG** | use **both**, one on a mains charger: on laptop bus power alone the board browns out under sustained use |
| `JP5` | the 2×10 expansion header ([wire to JP5](wire-to-jp5.md)) |
| `BOOT1` | the boot switch: SD `0 0`, QSPI `1 0`, JTAG `1 1` |
| `RED1`, `BLUE1` | the two LEDs, each through 240 Ω |

![The board photographed from above, with 22 labels: the four SMA ports, EXT_CLK, TX_LO and RX_LO, the AD9361, the Zynq XC7Z020, two MT41K256M16 DDR3L chips, the RTL8211F Ethernet PHY, the HR911130A RJ45 jack, the JP5 header, the BOOT DIP switch, the reset button, the microSD card and both USB-C sockets.](../img/board-map.png)

## Check a receive port without opening the case

Put an antenna on one port and watch the FM band in [SDR++](../sdrpp.md),
with nothing transmitting, switching **RX Port** between RX1 and RX2.

**You should see:** stations only when the antenna is on that receiver. A
transmit port shows nothing on either.

!!! danger "It matters most in a loopback"
    The attenuator has to sit between a real TX and a real RX
    ([before you transmit](../start/before-you-transmit.md)).

**Reference:** [what is on the board](../hardware.md#connectors).
