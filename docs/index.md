# Fishball7020 FPGA Devkit

Buildable firmware for a two-channel software-defined radio that ships without
any: a Zynq XC7Z020 and an AD9361, sold as PlutoSky R1, 7020-SDR, Fishball7020
and Fish-Wan. Every file on the SD card rebuilds from source, and you can put
your own logic in the radio's datapath. This site is the documentation; the
[repository](https://github.com/matsvandamme/fishball7020-fpga-devkit) has the
code and the [README](../README.md) gets a board running.

<div class="grid cards" markdown>

- **[Fabric School](course/index.html)**

    A ground-up course in SDR and the FPGA inside this board: 54 lessons, from
    what a radio is to your own logic in the AD9361 datapath, with 23 live
    calculators. Assumes no Verilog, no Vivado and no signal processing.

- **[Using this board in your own project](your-own-project.md)**

    Your code can live on your PC, in the board's Linux, in the kernel or in the
    FPGA. What each costs, and how to choose. Start here if the board works.

- **[Transmitter safety](transmitter-safety.md)**

    Read before anything radiates: this board has a power amplifier, and its
    receiver survives only +2.5 dBm.

- **[Prebuilt firmware](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases)**

    Ready-to-write SD-card files. Every release was booted on a board before it
    was published.

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
- `./devkit ssh-key` first saves typing the published root password.

!!! danger "Never use DFU"
    It has bricked units of this board. Flash with `./devkit flash` ([flashing](flashing.md)).

!!! warning "Before anything transmits"
    The board reaches about +19 dBm and its receiver survives only +2.5 dBm: fit at
    least 20 dB in any TX→RX loop ([transmitter safety](transmitter-safety.md)).

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
