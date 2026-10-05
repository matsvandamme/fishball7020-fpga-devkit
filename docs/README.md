# Documentation map

Every page in `docs/`, grouped by what you want to do. New to SDR and FPGAs?
Start with [How it works](how-it-works.md), or take the
[Fabric School course](course/index.html). The [top-level README](../README.md)
covers getting a board running.

## Getting started

| Page | Read it when you want to |
|---|---|
| [How it works](how-it-works.md) | understand what the build produces and why, assuming nothing |
| [Transmitter safety](transmitter-safety.md) | transmit anything at all. **Read before the first transmit** |
| [Reaching the board and changing its IP address](networking.md) | log in, fix the address, put the board on your router |
| [Flashing the board](flashing.md) | get a build onto the board, check what it runs, or recover it |
| [Troubleshooting](troubleshooting.md) | fix a build or a board that misbehaves |

## Using the radio

| Page | Read it when you want to |
|---|---|
| [Using this board in your own project](your-own-project.md) | choose where your code lives: your PC, the board, the kernel or the FPGA |
| [Capturing IQ](capturing-iq.md) | record samples with metadata and a dropped-sample check |
| [Using SDR++ with this board](sdrpp.md) | listen and watch a band in SDR++: settings, the rates USB carries, the patched build |
| [Faster streaming](streaming-paths.md) | stream one receiver at 20 MS/s over the network with 8-bit samples; what each path sustains, and why |
| [Aircraft overhead: ADS-B](adsb.md) | `./devkit adsb`: aircraft decoded live from 1090 MHz, in a window or the terminal; receive only |
| [Other SDR tools](other-sdr-tools.md) | use SDR++, inspectrum, URH, Maia SDR or pyadi-iio instead of GNU Radio |
| [MATLAB](matlab.md) | use MATLAB or Simulink. Read it before MATLAB offers to update the firmware |
| [Both receive channels](both-receive-channels.md) | use RX1 and RX2 with the FPGA decimator on |
| [Modulation gallery](modulation-gallery.md) | see ten modulations this board transmitted, with the code |
| [Cyclic buffers and triggers](cyclic-buffers.md) | replay a waveform from the board's memory at full rate, or play it once per trigger |
| [Watching a sweep live: chirp-view](chirp-view.md) | sweep TX1 and watch RX1 receive it: waterfall, response, eight sweep modes, mirror cancelling |
| [Measured performance](measured-performance.md) | know the loopback numbers: gain accuracy, harmonics, isolation |
| [Throughput and modulation quality](modulation-and-throughput.md) | know how fast you can stream, and what limits it |
| [The board in a Claude Code pane](claude-code-pane.md) | watch the board's links, temperatures, radio settings, CI and build from Claude Code (`./devkit claude-pane start`), and how the plugin works; reads only |
| [Claude and the radio: the MCP server](mcp-server.md) | let Claude tune, scan, capture and transmit through the sibling Fishball7020-mcp server: install, connect, the transmit gate |

## Hardware and I/O

| Page | Read it when you want to |
|---|---|
| [What is on the board](hardware.md) | know every chip, connector, clock and supply rail |
| [GPIO](gpio.md) | drive the header pins from your PC, the board or the fabric |
| [Sample-locked GPIO outputs](tx-gpio-bitmap.md) | use four pins that tick with the transmitted samples |
| [The USER LED](user-led.md) | read or control the LED that shows when RF can leave the board |

## Building and changing the firmware

| Page | Read it when you want to |
|---|---|
| [Building your own firmware](building.md) | install the tools and build every layer, or add your own HDL |
| [Building in a container](building-in-a-container.md) | build with Vivado on a host newer than Ubuntu 22.04 |
| [Building without Vivado](building-without-vivado.md) | change the kernel, drivers or root filesystem without installing Vivado |
| [The stock block design](block-design.md) | know what is in the FPGA design and what you can change |
| [An FM channelizer in the FPGA](wbfm-channelizer.md) | follow a complete worked HDL example |
| [Changing the kernel](kernel.md) | patch a driver or the kernel configuration |
| [The modern kernel](modern-kernel.md) | know why Linux 6.12 from Analog Devices, and what changed from 5.15 |
| [Why the modern target runs Debian](debian-rootfs.md) | know why the board left Buildroot, and what it had to keep |
| [The Debian root reference](debian-root-reference.md) | know what each boot unit and overlay setting on the board does |
| [Provenance](provenance.md) | check how close the rebuild is to the factory firmware |

## Elsewhere in the repository

- [`examples/`](../examples/README.md): GNU Radio and MATLAB examples.
- [`firmware-modern/`](../firmware-modern/README.md) and [`firmware/`](../firmware/README.md): the two firmware targets.
- [`tools/selftest/`](../tools/selftest/README.md): what the self-test checks.
- [`vendor/`](vendor/README.md): the vendor schematic, and which revision describes this board.

These pages are also published, searchable, at
<https://matsvandamme.github.io/fishball7020-fpga-devkit/> (built by
[`mkdocs.yml`](../mkdocs.yml)). CI checks every link with
`python3 docs/check_links.py` and builds the site with `mkdocs build --strict`.
