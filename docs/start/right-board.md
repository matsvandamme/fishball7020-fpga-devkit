---
icon: material/help-circle-outline
description: One command tells you whether this firmware fits your board.
---

# Check you have the right board

The board is sold as **PlutoSky R1**, **7020-SDR**, **Fishball7020** and
**Fish-Wan**. The released firmware fits one variant: a Zynq XC7Z020 with an
AD9361, on the R1 board. The **PlutoSky R2** is supported too, with its own
build and no release yet.

![The bare board from above, labelled: four SMA connectors along the top edge, the AD9361 radio chip below them, the JP5 header on the left edge, the Zynq XC7Z020 in the middle, and the Ethernet jack, two USB-C sockets and the microSD card along the bottom edge.](../img/start-board.svg)

*The bare board. In its case it looks like the picture on
[gather what you need](what-you-need.md).*

Ask the board which it is (needs `libiio-utils` on your PC):

```bash
# run on your HOST, from anywhere
iio_attr -S
#  1: 192.168.2.1 (FISH Ball PlutoSDR Rev.A (Z7020-AD9361)), serial=... [ip:fishball.local]
```

| It says | |
|---|---|
| `FISH Ball PlutoSDR Rev.A (Z7020-AD9361)` | **fits** |
| a PlutoSky R2 on the vendor's firmware (`fw_version` `v0.38-5-g76414`; a `10M_IN` socket on the case) | needs the R2 build: [the PlutoSky R2](../plutosky-r2.md) |
| `FISH Ball PlutoSDR R2 (Z7020/AD9361)` | an R2 already running this firmware |
| a `Z7010`, an `AD9363` or another Rev | does not work unchanged |

Transmit power figures on this site assume the power amplifier is fitted
([variants](../hardware.md)), and were measured on an R1. The R2 is sold with
and without an amplifier; nothing here has measured its transmitter.

**Next:** [gather what you need](what-you-need.md).
