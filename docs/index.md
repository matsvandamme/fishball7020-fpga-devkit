---
hide:
  - navigation
  - toc
---

# Fishball7020 FPGA Devkit

<p class="lead">Buildable firmware for a two-channel software-defined radio that ships
without any: a Zynq XC7Z020 and an AD9361, sold as PlutoSky R1, 7020-SDR,
Fishball7020 and Fish-Wan. Every file on the SD card rebuilds from source, and
you can put your own logic in the radio's datapath.</p>

## What do you want to do?

<div class="grid cards" markdown>

-   :material-flag-checkered:{ .lg .middle } **Get a board running**

    ---

    Six short steps from the box to a working radio.

    [:octicons-arrow-right-24: Start here](start/index.md)

-   :material-radio-tower:{ .lg .middle } **Use the radio**

    ---

    Capture IQ, SDR++, aircraft, a live sweep, MATLAB, your own code.

    [:octicons-arrow-right-24: Your own project](your-own-project.md)

-   :material-alert-octagon-outline:{ .lg .middle } **Transmit safely**

    ---

    This board has a power amplifier, and its receiver survives only +2.5 dBm.

    [:octicons-arrow-right-24: Before you transmit](start/before-you-transmit.md)

-   :material-hammer-wrench:{ .lg .middle } **Build your own firmware**

    ---

    Kernel, drivers and Debian with no Vivado; the FPGA with it.

    [:octicons-arrow-right-24: Building](building.md)

-   :material-school-outline:{ .lg .middle } **Learn SDR and the FPGA**

    ---

    Fabric School: 54 lessons, from what a radio is to your own logic in the
    AD9361 datapath, with 23 live calculators. Assumes no Verilog, no Vivado
    and no signal processing.

    [:octicons-arrow-right-24: The course](course/index.html)

-   :material-download-outline:{ .lg .middle } **Prebuilt firmware**

    ---

    Ready-to-write SD-card files. Every release was booted on a board before it
    was published.

    [:octicons-arrow-right-24: Releases](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases)

</div>

## Four commands

```bash
# run from: the repo root
./devkit doctor     # can this machine build? answers in a second
./devkit setup      # fetch the sources and apply the patches
./devkit build --xsa "$(./firmware-modern/fetch-pinned-xsa.sh)"   # the first build takes the kernel
./devkit flash      # onto the running board, backed up and md5-verified
```

- `./devkit verify --board` proves the board runs what you built.
- Flashing goes over the network through the SD card's boot partition.
  **Never use DFU**: it has bricked units of this board.
- `./devkit ssh-key` first saves typing the published root password.
- Transmitting? Read [before you transmit](start/before-you-transmit.md):
  about +19 dBm out, a receiver that survives +2.5 dBm, at least 20 dB in any
  TX→RX loop.

## Two firmware targets

| | modern (the default) | factory (`--target factory`) |
|---|---|---|
| kernel | Linux 6.12 LTS, Analog Devices | 5.15, the vendor's fork |
| userspace | Debian 13 + systemd, on ext4 | Buildroot, in RAM |
| FPGA | taken from a built design (`.xsa`) | built with Vivado: the bitstream source |
| release | v2.3 | v1.7 |

Rebuilding needs nothing from AMD: the boot loader compiles from AMD's public
embeddedsw with an ordinary `gcc-arm-none-eabi`, and `bootgen` builds from
AMD's Apache-2.0 source. Vivado is needed only to synthesise a new bitstream.

## What one board measures

| | |
|---|---|
| Transmit power, flat out | about +19 dBm (estimated, never metered) |
| Image rejection, after TX quadrature calibration | 44–60 dBc |
| TX mute depth | at least 75 dB (every reading hit the noise floor) |
| Gain slopes, 56 of them | within 1.7% of 1.000 dB/dB |
| FPGA, default build | 94/220 DSP48s, 12 521 LUTs, WNS +0.215 ns |

Measured on one unit, with conditions attached: indicative, not a
specification. Details: [measured performance](measured-performance.md).

The [repository](https://github.com/matsvandamme/fishball7020-fpga-devkit) has
the code; its [README](../README.md) gets a board running.
