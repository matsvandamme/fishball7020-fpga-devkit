<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/img/vmat-logo-dark.png">
    <img src="docs/img/vmat-logo.png" alt="VMAT" width="110">
  </picture>
</p>

> **This is not the official Analog Devices / OpenSourceSDRLab repository.**
> The Fishball7020 is an ADALM-PLUTO-derivative board that ships with no
> published, editable firmware source. This is an independent,
> reverse-engineered reconstruction, verified as close to bit-perfect as public
> sources allow — see [how this repo came to exist](docs/provenance.md).

# Fishball7020 FPGA Devkit

<p align="center">
  <a href="https://matsvandamme.github.io/fishball7020-fpga-devkit/course/"><img src="https://img.shields.io/badge/course-Fabric%20School%20%C2%B7%2053%20lessons-8A3FFC" alt="Fabric School: a 53-lesson SDR and FPGA course for this board"></a>
  <img src="https://img.shields.io/badge/board-Zynq%20XC7Z020%20%2B%20AD9361-blue" alt="Board: Zynq XC7Z020 + AD9361">
  <img src="https://img.shields.io/badge/toolchain-Vivado%2FVitis%202022.2-orange" alt="Toolchain: Vivado/Vitis 2022.2">
  <img src="https://img.shields.io/badge/host%20OS-Ubuntu%2022.04%20LTS-e95420" alt="Host OS: Ubuntu 22.04 LTS">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--2.0-lightgrey" alt="License: GPL-2.0"></a>
  <a href="../../actions/workflows/verify-patches.yml"><img src="https://github.com/matsvandamme/fishball7020-fpga-devkit/actions/workflows/verify-patches.yml/badge.svg" alt="Verify patches CI status"></a>
</p>

<p align="center"><img src="docs/img/board.jpg" alt="Fishball7020 / PlutoSky SDR board — Zynq XC7Z020 with AD9361, 4x SMA connectors, Ethernet and USB" width="480"></p>

Build your own FPGA/HDL firmware for the **"7020-SDR"**, a Zynq XC7Z020-CLG400
+ AD9361 software-defined radio with two transmit and two receive channels,
also sold as **PlutoSky** by OpenSourceSDRLab. You open the real block design,
add your own HDL next to the AD9361 datapath, rebuild every layer (bitstream →
FSBL → U-Boot → kernel → rootfs), and flash it back over the network without
opening the case.

If bitstream, FSBL and block design are new terms, **[How it
works](docs/how-it-works.md)** starts from the beginning and assumes nothing.

> ### 📚 [Fabric School](https://matsvandamme.github.io/fishball7020-fpga-devkit/course/) — learn all of this from nothing
>
> A 53-lesson course written against **this** board: its block design, its
> clocks, its measured numbers. From what a radio *is* and what a decibel means,
> through Verilog and Vivado, to packaging your own logic as an IP and splicing
> it into the AD9361 datapath — then filters, modulation, OFDM, coding, routing,
> security, antennas, two coherent receivers, and the theory underneath all of
> it.
>
> It assumes no Verilog, no Vivado, no FPGA experience and no signal processing.
> Twenty-two live calculators, day/night, one self-contained page.
> **[Read it online](https://matsvandamme.github.io/fishball7020-fpga-devkit/course/)**
> · **[176-page PDF](https://matsvandamme.github.io/fishball7020-fpga-devkit/course/Fabric-School.pdf)**
> · [source](docs/course/)

## Is this your board?

This repo targets one exact board: the one sold as
[**"7020-SDR" (XC7Z020 + AD9361, dual TX/RX)**](https://nl.aliexpress.com/item/1005012055627197.html),
also listed as PlutoSky, PlutoSky R1, PlutoSky_7020_AD936X_SDR and Fish-Wan.
Listings drift, but the board's own report does not. With the board plugged
in over USB:

```bash
# run on your HOST, from anywhere (needs libiio-utils)
iio_attr -S
#  1: 192.168.2.1 (FISH Ball PlutoSDR Rev.A (Z7020-AD9361)), serial=... [ip:pluto.local]
```

`FISH Ball PlutoSDR Rev.A (Z7020-AD9361)` means it fits. `Z7010`, `AD9363` or
another Rev means it does not: the original ADALM-PLUTO and other AD936x boards
use different pins and will not work with this firmware unchanged.

## What you get

- **Firmware that matches a factory unit**, rebuilt from source with one
  command: the device tree is byte-for-byte identical, the rootfs and
  bootloader match by content. ([How it was verified](docs/provenance.md))
- **ADI's real block design**, open in Vivado, so your HDL sits in the AD9361
  datapath rather than beside it. ([The block design, IP by IP](docs/block-design.md))
- **A transmitter that is off unless you are transmitting.** Stock firmware
  leaves it energised from power-on. ([Transmitter safety](docs/transmitter-safety.md))
- **A USER LED that means something.** Lit whenever RF can leave either port,
  dark when both chains are muted — instead of blinking a heartbeat.
  ([Controlling the USER LED](docs/user-led.md))
- **Two receivers that both survive decimation.** Stock ADI wiring filters only
  channel 0, so engaging the FPGA decimator leaves channel 1 aliased by 70 dB.
  One optional patch fixes it for 22 DSP slices.
  ([Two receivers that both survive decimation](docs/both-receive-channels.md))
- **Four header pins that tick with the transmitted waveform**, carrying bits
  the DAC throws away. ([Sample-locked GPIO outputs](#sample-locked-gpio-outputs))
- **A self-test** that tells you whether the radio is damaged, with measurements.
  ([Is the board healthy?](#is-the-board-healthy))
- **Ten modulations measured on a second radio**, from a CW tone to 64-QAM,
  OFDM and a LoRa-style chirp — spectra, constellations and eye diagrams, every
  one received on a **HackRF One** rather than simulated.
  ([The modulation gallery](docs/modulation-gallery.md))
- **An agent skill** in [`.claude/skills/`](.claude/skills/fishball7020-firmware/SKILL.md)
  that Claude Code loads on its own, carrying the rules that were expensive to
  work out. Ignore it if you do not use an agent.

<br>

> ### 📡 [What it puts on the air](docs/modulation-gallery.md) — measured, not simulated
>
> Ten modulations transmitted by one Fishball7020 and received on a **HackRF
> One**: CW, OOK, 2-FSK, BPSK, QPSK, GMSK, 16-QAM, 64-QAM, OFDM and a LoRa-style
> chirp. Spectra with ~85 dB of clean dynamic range, constellations recovered
> over the air, eye diagrams, and a spur traced back to whichever radio made it.
>
> [![Ten modulations transmitted by a Fishball7020 and received on a HackRF One: ten spectrum panels showing CW, OOK, 2-FSK, BPSK, QPSK, GMSK, 16-QAM, 64-QAM, OFDM and a LoRa-style chirp, each about 85 dB above the muted noise floor.](docs/img/modulation/01-signal-set.png)](docs/modulation-gallery.md)
>
> The receiver is deliberately a *separate* radio — a board that receives its own
> transmission shares one clock with itself and hides every oscillator problem
> there is. All 128 chirp symbols decoded; the 64-QAM grid resolves fully; and
> the EVM floor turns out to belong to the link rather than the board.
> **[See how it was measured, and checked](docs/modulation-gallery.md)**

## Quick start

### Just want a working board?

1. **Back up your card first.** Copy the five files on the board's microSD card
   somewhere safe. That is your way back if anything goes wrong.
2. Download the five SD-card files from the
   [latest release](../../releases/latest), and copy them onto the FAT32 card.
3. Check the **`BOOT`** DIP switch, next to `RST`, is in SD mode: both
   sliders pushed away from `ON` (`0 0`). Boards ship like that.
4. Insert the card and power on. After about 40 seconds the board appears over
   USB at `192.168.2.1`.

If nothing happens, see [boot modes](docs/flashing.md#boot-modes-boot-dip-switch)
and [recovering the factory firmware](docs/flashing.md#if-things-go-wrong-recovering-the-factory-firmware).

### Want to change the firmware?

You need **Vivado/Vitis 2022.2**, which is free for this chip but a large
download. Installing it is by far the slowest step.

**Build in a container — this is the recommended route.** Vivado 2022.2
supports Ubuntu 18.04, 20.04 and 22.04 and nothing newer, so on anything else
neither Vivado nor its installer will run. `./devkit container` sidesteps that
entirely: it runs the build inside a pinned image, and it can install Vivado
for you as well. Verified to produce a **byte-for-byte identical `BOOT.bin`**
to a host build — with Vivado installed by the container, into a directory the
host had never used. Your distribution stops mattering.

```bash
# run from: the repo root
./devkit container build-image      # once, ~3 min
./devkit container install ~/Downloads/Xilinx_Unified_2022.2_*.bin   # once, ~1 h
./devkit container doctor           # can this build? asks before the hour, not during
./devkit container setup            # clone upstream source + apply patches   (~5 min)
./devkit container build            # everything                           (45-90 min)
./devkit verify                     # is the build sane?
```

Full details: [Building in a container](docs/building-in-a-container.md).

If you are already on Ubuntu 18.04, 20.04 or 22.04 you can build directly on
the host instead — [install instructions](docs/building.md#install-vivadovitis-20222).
Either way `./devkit doctor` tells you where you stand, and everything that
talks to the radio (`flash`, `selftest`, `gpio-check`) always runs on the host.

Then:

```bash
# run from: wherever you want the devkit to live (e.g. ~)
git clone https://github.com/matsvandamme/fishball7020-fpga-devkit.git
cd fishball7020-fpga-devkit

./devkit doctor          # can this machine build? finds out now, not at minute 40
./devkit setup           # clone upstream source + apply patches            (~5 min)
./devkit build           # build everything                              (45-90 min)
./devkit verify          # is the build sane?
./devkit flash --all     # copy it onto the running board over the network, reboot
./devkit verify --board  # is the board actually running it?
```

`./devkit` runs from the repo root and wraps everything:
`doctor · setup · sim · build · verify · flash · selftest · gpio-check · status`.
Arguments pass straight through, so `./devkit build --hdl-only` works.

> ### Before you ever transmit
>
> The receive port survives **+2.5 dBm**. This board is sold in a variant with
> a power amplifier that puts out about **+19 dBm**, some 16 dB more than its
> own receiver tolerates. So **never loop TX back to RX without at least 20 dB
> of attenuation in between**, and never transmit at power into an open or
> unterminated port. Most of this board's range is licensed spectrum. More in
> [Transmitter safety](docs/transmitter-safety.md).

## Your first hour with the board

**Connect.** Plug a cable into the board's **USB 2.0** socket (not `DEBUG`).
It shows up as a network interface, and the board is at `192.168.2.1`:

```bash
# run on your HOST, from anywhere
ssh root@192.168.2.1        # password: analog
```

The `DEBUG` socket is the serial console and JTAG, which you only need when the
board will not boot. [Which USB port is which](docs/flashing.md#verify-your-build-is-actually-running).

**Check it is healthy.** Nothing needs to be plugged into the RF ports for
this, and it never transmits:

```bash
# run from: the repo root
./devkit selftest --ssh
```

**See where you are.** `./devkit status` shows whether the source is set up,
what you last built, and whether the board is reachable. Once you have built
something, `./devkit verify --board` checks the board is really running it.

**Talk to it.** To software it is a Pluto at `ip:192.168.2.1`, so libiio,
pyadi-iio, GNU Radio and SDRangel work with it as they would with a Pluto.

**Put it on your network.** The Ethernet socket asks your router for an address
by default, and `iio_info -s` finds the board without you knowing it. To give it
a fixed address instead — or to understand why the obvious file on the SD card is
not the one that does it — see [changing the board's IP
address](docs/networking.md).

## Making changes

| I want to… | Start here |
|---|---|
| learn this from nothing — SDR, Verilog and Vivado | **[Fabric School](https://matsvandamme.github.io/fishball7020-fpga-devkit/course/)** — a 53-lesson course written against this board ([PDF](https://matsvandamme.github.io/fishball7020-fpga-devkit/course/Fabric-School.pdf)) |
| understand what the build produces and why | [How it works](docs/how-it-works.md) |
| install the tools and build on the host | [Building your own firmware](docs/building.md) — needs Ubuntu 18.04/20.04/22.04 |
| add my own HDL to the radio's datapath | [Add your own HDL](docs/building.md#add-your-own-hdl) · [the block design](docs/block-design.md) |
| see a complete worked example | [An FM channelizer in the FPGA](docs/wbfm-channelizer.md) |
| use both receivers with the FPGA decimator on | [Two receivers that both survive decimation](docs/both-receive-channels.md) |
| check my HDL in a second, before a 20-minute build | [Simulating your HDL first](docs/building.md#simulating-your-hdl-first) |
| change a driver or the kernel | [Changing the kernel](docs/kernel.md) |
| capture IQ that is still useful in a year | [Capturing IQ](docs/capturing-iq.md) — SigMF sidecars, and a check for dropped samples |
| get my build onto the board | [Flashing the board](docs/flashing.md) |
| iterate on the FPGA in seconds over JTAG | [Option D — JTAG](docs/flashing.md#option-d--jtag-temporary-but-the-fastest-hdl-loop) |
| drive the GPIO pins, from the host, the board or the fabric | [GPIO](docs/gpio.md) — the three routes, and which pins are actually free |
| blink the USER LED | [Controlling the USER LED](docs/user-led.md) |
| build without caring what Linux I run | **[Building in a container](docs/building-in-a-container.md)** — the recommended route; installs Vivado too, byte-identical output |
| drive the radio from an AI assistant | the sibling **[Fishball7020-mcp](https://github.com/matsvandamme/Fishball7020-mcp)** — 21 MCP tools: tune, sweep, capture, transmit |
| put the board on my router, or give it a fixed IP | [Changing the board's IP address](docs/networking.md) — the four routes, and the SD-card file that looks like it works |
| see what this board actually transmits | **[The modulation gallery](docs/modulation-gallery.md)** — ten modulations measured on a HackRF One, with the code to repeat it |
| fix a build that fails | [Troubleshooting](docs/troubleshooting.md) |

## What is on the board

<img src="docs/img/board-map.png" alt="The board photographed from above, with 22 labels: the four SMA ports, EXT_CLK, TX_LO and RX_LO, the AD9361, the Zynq XC7Z020, two MT41K256M16 DDR3L chips, the RTL8211F Ethernet PHY, the HR911130A RJ45 jack, the JP5 header, the BOOT DIP switch, the reset button, the microSD card and both USB-C sockets. Parts inferred from package and position rather than a legible marking have dashed rings and say likely: the four RF baluns, the two PGA-102+ amplifiers, the 40 MHz VCTCXO, the USB3320C, the FT2232H, the W25Q128 flash and the FAN1 header." width="860">

An **AD9361** transceiver (70 MHz – 6 GHz, two channels), a **Zynq
XC7Z020** (two ARM cores plus FPGA fabric), 1 GB of DDR3L, a power amplifier
on each transmit port, gigabit Ethernet and USB. Every chip with its
datasheet, plus the clocks, connectors and supply rails, read off the vendor
schematic: **[What is on the board](docs/hardware.md)**.

## Sample-locked GPIO outputs

The AD9361's DAC is 12 bits wide and ignores the bottom four bits of every
16-bit sample you send it. This firmware routes those four bits to pins 7, 9,
11 and 13 of the `JP5` header instead. Every pin edge then belongs to one
specific transmitted sample, at a fixed offset from its RF. That makes the pins
usable as a clock, frame marker or trigger for external hardware that must
stay in step with the transmitter, such as radar or MIMO receivers. It costs
nothing: the DAC never sees those bits.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/saleae-timing-dark.svg">
  <img src="docs/img/saleae-timing-light.svg" alt="Logic-analyser capture of the four sample-locked GPIO pins carrying a 4-bit counter at 5 MSPS, with the decoded value D, E, F, 0, 1 and so on under each 200 ns sample" width="760">
</picture>

It is off by default. To try it with the transmitter silent:

```bash
# run from: the repo root
python3 tools/sample_gpio_clock.py --help    # needs: pip install pyadi-iio numpy
./devkit gpio-check                          # check the pins work, no scope needed
```

**The full story** — how the nibble reaches the pin, the pinout, a complete
Python example, measured timing and limits:
**[docs/tx-gpio-bitmap.md](docs/tx-gpio-bitmap.md)**.

## Is the board healthy?

If you have overdriven an input, transmitted into an open port, or the board
has simply stopped behaving, the self-test answers with measurements. Most
checks need nothing plugged in. The RF checks need TX cabled to RX through a
**20 dB attenuator**:

```bash
# run from: the repo root
./devkit selftest --ssh                          # no cable, never transmits
./devkit selftest --ssh --loopback --pad 20      # + the RF tests
```

It cannot overdrive your receiver even if you forget the attenuator: it never
transmits with less than 35 dB of its own attenuation. What it checks and how
to read the result: [`tools/selftest/README.md`](tools/selftest/README.md).

## Measured performance

One board, 28 runs. Gain settings do what they say to within 1.7%, harmonics
sit at least 63 dB below the carrier, the two transmitters match to 0.2 dB, and
the transmitter goes at least 75 dB quiet when it stops.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/loop-gain-dark.svg">
  <img alt="TX to RX loop gain for both channels from 70 MHz to 6 GHz, through the same 20 dB attenuator. Both rise from 12-14 dB at 70 MHz to a plateau near +20 dB between 200 MHz and 1 GHz, then fall to about +2 dB at 6 GHz. Channel 1 runs about 1.5 dB hotter. A step up at 4 GHz is marked as the AD9361 changing RX gain table. The region above 3 GHz is shaded where the board's own TX-to-RX leak can add up to 2 dB." src="docs/img/loop-gain-light.svg">
</picture>

Two things are worth knowing before you measure your own board. A gain
calibration made below 4 GHz is wrong above it, because the AD9361 changes
receive gain table there. And the board leaks some of its own transmit signal
into its receiver, which spoils loopback measurements through large
attenuators: use 20 dB. The full tables, the leak, and how the numbers were
checked: **[docs/measured-performance.md](docs/measured-performance.md)**.

How it behaves with real modulated signals — QPSK and 16-QAM at the full
61.44 MSPS, where the streaming ceiling actually comes from, and why it is not
the radio: **[docs/modulation-and-throughput.md](docs/modulation-and-throughput.md)**.

## Repository layout

```
fishball7020-fpga-devkit/
├── devkit              ← the one entry point: ./devkit doctor, setup, build, flash, ...
├── docs/               ← everything this page links to
├── firmware/
│   ├── patches/        what makes this board's firmware; applied by setup
│   ├── scripts/        the build
│   ├── sim/            one-second HDL simulation, no Vivado
│   ├── src/            upstream source, created by setup (not committed)
│   └── output/         the five SD-card files a build produces
└── tools/              flashing, the self-test, the GPIO tools
```

The full tree, file by file, is in
[Building your own firmware](docs/building.md#repository-layout).

## Getting help

Build failed, or the board is acting up? Check
[Troubleshooting](docs/troubleshooting.md) and run the
[self-test](#is-the-board-healthy). Still stuck?
[Open an issue](../../issues/new/choose): the templates ask for the details
that speed things up. Contributions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Vendor resources

- [**Hardware schematic**](docs/vendor/7020_936x_SDR-schematic.pdf), kept here
  because the vendor's own GitHub copy is a **different revision** that does
  not describe this board. [Which is which](docs/vendor/README.md).
- [PlutoSky R1 write-up](https://blog.opensourcesdrlab.com/archives/PlutoSky-R1) ·
  [vendor file archive](https://workupload.com/archive/kc2v7ryVZZ) ·
  [factory binaries](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR)

None of it includes editable HDL sources, which is the gap this repo fills.

## License

This repo's own scripts, patches and documentation are **GPL-2.0**. The
upstream source that `setup` downloads (Linux, U-Boot, Buildroot) stays GPL,
and Xilinx Vivado/Vitis and AMD IP are proprietary and licensed separately.
The breakdown is in [`LICENSE`](LICENSE).

One directory in the tree is not ours:
[`.claude/skills/goal-creator/`](.claude/skills/goal-creator/) is a third-party
agent skill vendored under **MIT**, with its own `LICENSE` and a
[`VENDORED.md`](.claude/skills/goal-creator/VENDORED.md) recording where it came
from and at which commit. Nothing in the firmware or the build depends on it.
