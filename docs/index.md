---
hide:
  - navigation
  - toc
---

<div class="hero" markdown>

# What do you want to do?

Firmware, guides and measurements for the Fishball7020 / PlutoSky R1: a Zynq
XC7Z020 and an AD9361 radio, rebuilt from source.

<label class="hero-search" for="__search">:material-magnify: Search: write the card, SDR++, transmit, GPIO, reference clock…</label>

</div>

<p class="banner">New to the board? <a href="start/">Start here</a>: six short steps from the box to a working radio.</p>

<div class="grid cards" markdown>

-   :material-flag-checkered:{ .lg }

    **[Getting started](start/index.md)**

    First-time setup: the card, the cables, finding the board, the safety rules.

    <span class="count">9 articles</span>

-   :material-radio-tower:{ .lg }

    **[Use the radio](radio/index.md)**

    Capture IQ, SDR++, aircraft, a live sweep, MATLAB, your own code.

    <span class="count">12 articles</span>

-   :material-alert-octagon-outline:{ .lg }

    **[Transmit safely](start/before-you-transmit.md)**

    This board has a power amplifier, and its receiver survives only +2.5 dBm.

    <span class="count">4 rules</span>

-   :material-chip:{ .lg }

    **[Hardware and I/O](hw/index.md)**

    Ports, the JP5 header, GPIO, the USER LED, an external reference clock.

    <span class="count">8 articles</span>

-   :material-hammer-wrench:{ .lg }

    **[Build your own firmware](build/index.md)**

    Kernel, drivers and Debian with no Vivado; the FPGA with it.

    <span class="count">10 articles</span>

-   :material-wrench-outline:{ .lg }

    **[Troubleshooting](troubleshooting.md)**

    Known problems by symptom, each with its cause and fix.

    <span class="count">14 problems</span>

-   :material-school-outline:{ .lg }

    **[Fabric School](course/index.html)**

    A course from what a radio is to your own logic in the AD9361 datapath.
    Assumes no Verilog, no Vivado and no signal processing.

    <span class="count">54 lessons, 23 live calculators</span>

-   :material-chart-bell-curve:{ .lg }

    **[Measured performance](measured-performance.md)**

    What one board measures, with the conditions attached.

    <span class="count">Reference</span>

-   :material-download-outline:{ .lg }

    **[Prebuilt firmware](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases)**

    Ready-to-write SD-card files. Every release was booted on a board before it
    was published.

    <span class="count">Releases on GitHub</span>

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
