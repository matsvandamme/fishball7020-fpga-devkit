---
icon: material/help-circle-outline
description: One command tells you whether this firmware fits your board.
---

# Check you have the right board

The board is sold as **PlutoSky R1**, **7020-SDR**, **Fishball7020** and
**Fish-Wan**. This firmware fits one variant: a Zynq XC7Z020 with an AD9361.

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
| a `Z7010`, an `AD9363` or another Rev | does not work unchanged |

Transmit power figures on this site assume the power amplifier is fitted
([variants](../hardware.md)).

**Next:** [gather what you need](what-you-need.md).
