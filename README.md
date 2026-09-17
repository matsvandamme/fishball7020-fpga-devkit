> **This is not the official Analog Devices / OpenSourceSDRLab repository.**
> The Fishball7020 is an ADALM-PLUTO-derivative board that ships with no
> published, editable firmware source. This is an independent,
> reverse-engineered reconstruction, verified as close to bit-perfect as public
> sources allow — see [How this repo came to exist](#how-this-repo-came-to-exist).

# Fishball7020 FPGA Devkit

<p align="center">
  <img src="https://img.shields.io/badge/board-Zynq%20XC7Z020%20%2B%20AD9361-blue" alt="Board: Zynq XC7Z020 + AD9361">
  <img src="https://img.shields.io/badge/toolchain-Vivado%2FVitis%202022.2-orange" alt="Toolchain: Vivado/Vitis 2022.2">
  <img src="https://img.shields.io/badge/host%20OS-Ubuntu%2022.04%20LTS-e95420" alt="Host OS: Ubuntu 22.04 LTS">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-GPL--2.0-lightgrey" alt="License: GPL-2.0"></a>
  <a href="../../actions/workflows/verify-patches.yml"><img src="https://github.com/matsvandamme/fishball7020-fpga-devkit/actions/workflows/verify-patches.yml/badge.svg" alt="Verify patches CI status"></a>
</p>

<p align="center"><img src="docs/img/board.jpg" alt="Fishball7020 / PlutoSky SDR board — Zynq XC7Z020 with AD9361, 4x SMA connectors, Ethernet and USB" width="480"></p>

Build your own FPGA/HDL firmware for the **"7020-SDR"** — a Zynq
XC7Z020-CLG400 + AD9361 software-defined radio with dual TX/RX, also sold as
**PlutoSky** by OpenSourceSDRLab. From a stock board to your own logic running
inside it: open the real block design, add HDL next to the AD9361 datapath,
rebuild every layer (bitstream → FSBL → U-Boot → kernel → rootfs), and flash it
back — no disassembly.

New to those terms — bitstream, FSBL, block design? **[How it
works](docs/how-it-works.md)** explains them from scratch, no prior knowledge
assumed.

> **This repo targets one exact board:** the one sold as
> [**"7020-SDR" (XC7Z020 + AD9361, dual TX/RX)**](https://nl.aliexpress.com/item/1005012055627197.html).
> Other Zynq/AD936x boards — including the original ADALM-PLUTO (XC7Z010) —
> use different pin constraints and will not work unchanged.
>
> The same hardware appears as **7020-SDR** (AliExpress), **PlutoSky / PlutoSky
> R1** ([vendor write-up](https://blog.opensourcesdrlab.com/archives/PlutoSky-R1)),
> **PlutoSky_7020_AD936X_SDR** ([vendor repo](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR)),
> **Fish-Wan** (the upstream fork) and **Fishball7020** (here). Listings drift;
> the board's own report does not. From any machine with `libiio-utils`:
>
> ```bash
> iio_attr -S
> #  1: 192.168.2.1 (FISH Ball PlutoSDR Rev.A (Z7020-AD9361)), serial=... [ip:pluto.local]
> ```
>
> `FISH Ball PlutoSDR Rev.A (Z7020-AD9361)` fits. `Z7010`, `AD9363` or another
> Rev does not.

| | |
|---|---|
| **Board** | Zynq-7020 (XC7Z020-CLG400) + AD9361, 2×2 MIMO RF front end |
| **Toolchain** | Xilinx Vivado/Vitis **2022.2** (free WebPACK — no purchase) |
| **Host OS** | **Ubuntu 22.04 LTS** — what Vivado 2022.2 officially supports |
| **Firmware base** | Linux 5.15, U-Boot, Buildroot — a Zynq-7020 port of ADI's `plutosdr-fw` |
| **Verified against real hardware** | device tree reproduces the factory one exactly (plus one named-GPIO addition); kernel config identical; kernel and bootloader within a few hundred bytes; rootfs file list identical — see [Provenance](#how-this-repo-came-to-exist) |

## What you get

- **A firmware build you can trust** — `devicetree.dtb` comes out byte-for-byte
  identical to a real unit's; rootfs and bootloader environment
  content-identical.
- **One command builds every layer** — bitstream → FSBL → U-Boot → Linux 5.15
  → Buildroot rootfs → `BOOT.bin`.
- **The real ADI block design, editable** — put your own HDL directly into the
  AD9361 datapath.
- **Four ways onto the board** — SD card, DFU over USB, over SSH from the
  running board (the only remote route that can update the bitstream), or JTAG
  for a seconds-long loop.
- **Four header pins that tick with the transmitted waveform** — the four
  bits of every transmit sample the 12-bit DAC throws away are routed to
  expansion-header pins, giving digital outputs locked to the RF sample that
  carried them. Off by default, costs nothing until enabled. See
  [Sample-locked GPIO outputs](#sample-locked-gpio-outputs).
- **The transmitter is off unless you are transmitting.** Stock firmware leaves
  the TX chain biased from power-on, radiating LO leakage with nothing in the
  DAC. This build mutes it and powers the synthesiser down whenever no TX
  buffer streams. See [Transmitter safety](#transmitter-safety).
- **Reproducible changes** — they live in `patches/`, so a clean clone rebuilds
  them anywhere.
- **The traps are handled** — Vivado `PATH` pollution breaking the kernel
  build, Buildroot mirror timeouts, host GCC drift. Each cost a debugging
  session; none will cost you one.
- **An Agent Skill** in [`.claude/skills/`](.claude/skills/fishball7020-firmware/SKILL.md),
  loaded automatically by Claude Code, carrying the expensive-to-rediscover
  parts: flashing rules, the PA power budget, AD9361 gain tables and their
  discontinuities, libiio and busybox gotchas. Harmless if you don't use an agent.

## Quick start

**Just want a working board?** Download the five prebuilt SD-card files from
the [latest release](../../releases/latest) (checksums included), copy them
onto a FAT32 microSD card, insert it, power on. If nothing happens, check the
`BOOT` DIP switch is in SD mode (`0 0`). That is the whole procedure — build
only when you want to *change* something.

> **Back up first.** Copy the five files already on your card somewhere safe —
> that is your way back. No backup? See
> [recovery](#if-things-go-wrong-recovering-the-factory-firmware).

**Want to change the firmware?** Assumes Vivado/Vitis 2022.2
([step 1](#1-install-vivadovitis-20222) if not — the only slow part):

```bash
# run from: wherever you want the devkit to live (e.g. ~)
git clone https://github.com/matsvandamme/fishball7020-fpga-devkit.git
cd fishball7020-fpga-devkit

./devkit doctor          # can this machine build? checks in a second, not at minute 40
./devkit setup           # clone upstream source + apply patches            (~5 min)
./devkit build           # build everything                              (45-90 min)
./devkit verify          # is the build sane?
./devkit flash --all     # copy it onto the running board over the network, reboot
./devkit verify --board  # is the board actually running it?
```

`./devkit` wraps the scripts so you never have to remember which lives where:
`doctor · setup · sim · build · verify · flash · selftest · gpio-check · status`,
all from the repo root, arguments passed through (`./devkit build --hdl-only`).
The underlying scripts in `firmware/scripts/` and `tools/` still work directly.
Then go to [step 4](#4-add-your-own-hdl) to start changing the FPGA logic.

> ### Before you ever transmit
>
> The receive port survives **+2.5 dBm**. This board is sold in a variant with
> a power amplifier that puts out about **+19 dBm** — roughly 16 dB more than
> its own receiver tolerates. So: **never loop TX to RX without at least 20 dB
> of attenuation**, never transmit at power into an open or unterminated port,
> and remember that most of this board's range is licensed spectrum. Details
> in [Transmitter safety](#transmitter-safety). This firmware mutes the
> transmitter whenever nothing is streaming, so an idle board is quiet.

## Table of contents

- [What you get](#what-you-get) · [Quick start](#quick-start)
- [Boot modes (DIP switch)](#boot-modes-boot-dip-switch) · [LEDs](#leds) · [Requirements](#requirements)
- **Walkthrough** — [1. Install Vivado](#1-install-vivadovitis-20222) ·
  [2. Get the source](#2-get-the-firmware-source) ·
  [3. Open the block diagram](#3-open-the-block-diagram) ·
  [4. Add your own HDL](#4-add-your-own-hdl) ·
  [4b. Change the kernel](#4b-change-the-kernel) ·
  [5. Build](#5-build-the-firmware) ·
  [6. Flash](#6-flash-the-board) ·
  [7. Verify](#7-verify-your-build-is-actually-running)
- [Repository layout](#repository-layout)
- [How it works](docs/how-it-works.md) — the boot chain explained from scratch
- [The stock block design: IPs, wiring, and what you can change](docs/block-design.md)
- [Worked example: an FM channelizer in the FPGA](docs/wbfm-channelizer.md)
- [Sample-locked GPIO outputs](#sample-locked-gpio-outputs) — four header pins that tick with the transmitted waveform
- [Transmitter safety](#transmitter-safety) — TX is muted when nothing is being sent
- [Measured performance](#measured-performance) — what one board actually does; [full tables](docs/measured-performance.md)
- [Simulating your HDL first](#simulating-your-hdl-first) — one second instead of twenty minutes
- [Is the board healthy?](#is-the-board-healthy) — a self-test that measures, cable optional
- [Controlling the USER LED](docs/user-led.md)
- [Troubleshooting](#troubleshooting)
- [How this repo came to exist](#how-this-repo-came-to-exist) ·
  [The end-to-end test](#the-end-to-end-test) ·
  [Vendor resources](#vendor-resources) · [License](#license)

## Boot modes (BOOT DIP switch)

A two-position switch marked **`BOOT`**, next to `RST` between the `USB2.0` and
`DEBUG` ports, picks where the board boots from. Boards ship in SD mode, which
is what the devkit needs. If a freshly flashed card seems to do nothing, check
this first.

<table>
<tr>
<td align="center"><img src="docs/img/boot-sd-00.jpg" alt="BOOT switch set to 0 0 for SD card boot" width="250"><br><b>SD card — <code>0 0</code></b><br><sub>factory default, used by the devkit</sub></td>
<td align="center"><img src="docs/img/boot-qspi-10.jpg" alt="BOOT switch set to 1 0 for QSPI flash boot" width="250"><br><b>QSPI flash — <code>1 0</code></b><br><sub>boots from the onboard flash</sub></td>
<td align="center"><img src="docs/img/boot-jtag-11.jpg" alt="BOOT switch set to 1 1 for JTAG mode" width="250"><br><b>JTAG — <code>1 1</code></b><br><sub>debugging and flashing</sub></td>
</tr>
</table>

<sub>Switch photographs from the distributor's
<a href="https://blog.opensourcesdrlab.com/archives/PlutoSky-R1">PlutoSky R1 write-up</a>.</sub>

| Mode | SW1 | SW2 | What it does |
|---|---|---|---|
| **SD card** | `0` (GND) | `0` (GND) | Boots `BOOT.bin` from the microSD card — **factory default, what the devkit needs** |
| **QSPI flash** | `1` (VCC3V3) | `0` (GND) | Boots from the onboard 16 MiB flash instead |
| **JTAG** | `1` (VCC3V3) | `1` (VCC3V3) | Debugging and flashing over JTAG |

`1` means the slider is pushed toward the **`ON`** marking. **Change it only
with the board powered off** — the mode is sampled at power-on.

SD-card boot never writes the QSPI flash, so whatever is on that chip is
unaffected. The distributor's write-up lists QSPI as default; boards observed
in practice ship in SD mode — check the switch, not the documentation.

### LEDs

| LED | Meaning |
|---|---|
| `PWR` | Power present |
| `DONE` | FPGA configured — the same DONE that Vivado reports as `End of startup status: HIGH` |
| `USER` | Driven by Linux (PS GPIO); blinks via the kernel heartbeat trigger — [how to control it](docs/user-led.md) |

## Requirements

**Hardware:** the board, a micro-USB cable, and a microSD card with a reader
(a board that still boots can be reflashed over the network instead — see
[Option C](#option-c--over-ssh-from-the-running-board-no-card-removal)). If you
will ever loop TX to RX, **an SMA attenuator of at least 20 dB**. A debug-port
cable only if you want the serial console or JTAG.

**Software** (Ubuntu 22.04 LTS):

```bash
# run on your HOST, from anywhere
sudo apt update
sudo apt install -y git build-essential bison flex libssl-dev \
    device-tree-compiler u-boot-tools screen python3 xvfb \
    libgmp-dev libmpc-dev libmpfr-dev sshpass iverilog libiio-utils
```

- **No extra GCC needed on 22.04.** Jammy's GCC 11 builds everything. Only on a
  much newer distro (GCC ≥ 14) does one legacy Buildroot host tool need
  `gcc-13` alongside; `build_all.sh` detects and picks automatically.
- **`libgmp-dev`/`libmpc-dev`/`libmpfr-dev`** are needed by the kernel's
  GCC-plugin build. Miss them and stage 4 fails with `fatal error: gmp.h`.
- **`xvfb` matters if you build headless.** Vitis (`xsct`) needs an X display
  for the FSBL; without `$DISPLAY` or Xvfb, stage 2 dies with `ERROR: Xvfb is
  not available`. `build_all.sh` checks up front rather than 40 minutes in.
- `sshpass` is what `./devkit flash`, `verify --board` and `gpio-check` use to
  reach the board; `iverilog` runs the HDL simulation; `libiio-utils` gives you
  `iio_attr`/`iio_info` for identifying and inspecting the board. `screen` is
  only for the serial console.

## 1. Install Vivado/Vitis 2022.2

The Zynq-7020 is covered by Xilinx's **free WebPACK license** — no purchase, no
license file.

1. Create an account at [xilinx.com](https://www.xilinx.com) and go to the
   [2022.2 downloads page](https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/vivado-design-tools/2022-2.html).
2. Download the **Vitis** unified installer for Linux — not just Vivado; the
   FSBL build needs Vitis.
3. `chmod +x Xilinx_Unified_2022.2_*.bin && ./Xilinx_Unified_2022.2_*.bin`
4. In the GUI: choose **Vitis**; under device families select only
   **Zynq-7000** (brings ~130 GB down to ~30 GB); **keep the default path
   `/tools/Xilinx`**, which `tools/env-vivado.sh` points at.

**Always `source tools/env-vivado.sh`, never Vivado's own `settings64.sh`.**
Vivado 2022.2 is linked against `libtinfo.so.5`, `libncurses.so.5` and
`libssl.so.1.1`, absent from a default 22.04. The script prepends vendored
copies to `LD_LIBRARY_PATH` before sourcing `settings64.sh`, touching nothing
system-wide.

## 2. Get the firmware source

```bash
# run from: wherever you want the devkit to live (e.g. ~)
git clone https://github.com/matsvandamme/fishball7020-fpga-devkit.git
cd fishball7020-fpga-devkit/firmware
./scripts/setup.sh
```

This clones the upstream source (a Zynq-7020 port of ADI's `plutosdr-fw`) into
`src/` and applies this repo's `patches/` — six fixes plus the board's device
tree (the [firmware README](firmware/README.md) details each). `src/` is
gitignored; re-run `setup.sh` any time for a clean slate.

> **Where to run things:** `./devkit …` runs from the **repo root**. The raw
> scripts run from **`firmware/`** unless the block says otherwise — each block
> states its directory on the first line. Commands that run *on the board* are
> marked as such.

## 3. Open the block diagram

> **[The stock block design](docs/block-design.md)** walks through every IP
> block, the wiring, clock domains, address map, and what is safe to change.

The project does not exist until the first build — only the `.tcl` that
generates it — so build once first (`./devkit build`; `--hdl-only` needs a
previous full build). Then:

```bash
# run from: firmware/
source ../tools/env-vivado.sh
cd src/hdl/projects/pluto
vivado pluto.xpr
```

In the GUI: **Sources → Design Sources → system_top → system_i**,
right-click **Open Block Design**.

## 4. Add your own HDL

This is not a bare "samples straight to DMA" design. Channel 0 runs through
ADI's programmable FIR decimator/interpolator; channel 1 bypasses filtering
entirely:

```
                            AD9361 (physical LVDS pins)
                                    │
                             ┌──────▼───────┐
                             │  axi_ad9361   │
                             └──┬────────▲───┘
      RX ch.0: adc_data_i0/q0 ──┤         ├── TX ch.0: dac_data_i0/q0
      RX ch.1: adc_data_i1/q1 ──┤         ├── TX ch.1: dac_data_i1/q1
                                │         │
                    ┌───────────▼──┐   ┌──┴────────────┐
        ch.0 only:  │rx_fir_       │   │tx_fir_        │  ch.0 only:
     (decimation,   │decimator     │   │interpolator   │  (interpolation,
      8x, 2x taps)  └──────┬───────┘   └───────▲───────┘   2x/8x taps)
                           │                     │
      ch.1 connects  ┌─────▼──────┐       ┌──────┴─────┐  ch.1 connects
      directly, no   │   cpack     │       │  tx_upack  │  directly, no
      filter ────────►(util_cpack2)│       │(util_upack2)◄──── filter
                     └─────┬──────┘       └──────▲─────┘
                           │                       │
                    ┌──────▼──────┐         ┌──────┴──────┐
                    │  adc_dma     │         │  dac_dma     │
                    │ (axi_dmac)   │         │ (axi_dmac)   │
                    └──────────────┘         └──────────────┘
                     ▲ YOU ARE HERE — insert custom logic between
                     axi_ad9361 and cpack/tx_upack (channel 1),
                     or before/after the FIR blocks (channel 0)
```

- **Channel 1 has no filter in the path** — wired straight from `axi_ad9361` to
  `cpack`/`tx_upack`. The cleanest insertion point: break the connection in the
  block design, insert your block (mirroring the `ad_connect
  axi_ad9361/adc_data_i1 …` calls in `system_bd.tcl`), reconnect to `cpack`'s
  `enable_2`/`fifo_wr_data_2` (and `_3` for Q).
- **Channel 0** routes through 129-tap FIRs that decimate/interpolate by 8,
  built by `ad_add_decimation_filter`/`ad_add_interpolation_filter` in
  `system_bd.tcl` from Xilinx's `fir_compiler` IP, with taps from
  `library/util_fir_int/coefile_int.coe`. Insert before them (raw, full rate)
  or after — or just swap the `.coe` to change the response without touching
  wiring.
- Both channel-0 groups run on `axi_ad9361/l_clk`; match that clock domain.
- Edit graphically (drag in IP, wire it, **Create HDL Wrapper**) or edit
  `system_bd.tcl` directly.

> **Don't be misled by `library/util_fir_int/` and `library/util_fir_dec/`.**
> Neither has a `component.xml`, so neither is ever packaged — the `.v` files
> are dead code. Only `coefile_int.coe` is used, and the RX decimator and TX
> interpolator are passed **the same** file, so editing it in place changes
> both.

> **A worked example does all of this for real.**
> **[Isolating one FM channel in the FPGA](docs/wbfm-channelizer.md)** inserts a
> custom Verilog block into the channel-0 RX path, designs and verifies new FIR
> coefficients from a script, and explains why the obvious approach — "just
> lowpass the channel" — cannot work.
>
> For a second, smaller reference design that ships **enabled in the base
> firmware**, see [Sample-locked GPIO outputs](#sample-locked-gpio-outputs) —
> `tx_gpio_bitmap.v` is about thirty lines and shows the whole pattern: a
> module, a block-design tap, a pin constraint and a driver attribute.

### Rebuilding after a GUI block-design edit

`build_hdl.tcl` opens the existing `pluto.xpr` and does a full `reset_run
synth_1`, so your edit flows through to `BOOT.bin` automatically. Three things
first: **save the block design** (`Ctrl-S` — an unsaved edit isn't in
`pluto.xpr` and the build silently omits it), **Validate Design (F6)**, and
**close Vivado** (the GUI holds a project lock).

```bash
# run from: firmware/
./scripts/build_all.sh
```

GUI edits live in `src/`, which is gitignored and regenerated by `setup.sh`.
To keep a change, port it into `system_bd.tcl` and add it to `patches/`.

## 4b. Change the kernel

The FPGA is half the board. The other half is a Linux kernel with ADI's
drivers in it, and much of the board's *behaviour* — what appears in `/sys`,
when the transmitter is muted, what the serial number is — lives there rather
than in fabric. **[Changing the kernel](docs/kernel.md)** covers what is
already patched and why, the three-minute kernel-only rebuild loop, the kernel
options that matter, debugging a driver on a busybox board, and making a change
stick as a patch. Flash a kernel change with `./devkit flash --kernel-only`.

## 5. Build the firmware

```bash
# run from: firmware/
./scripts/build_all.sh
```

**Iterating on HDL?** Use `--hdl-only`. Stages 3–5 produce byte-identical
output when only the FPGA design changed, and are most of the wall time —
about 20 minutes instead of 70. It reuses the existing kernel/U-Boot/rootfs and
refuses to run if no previous full build produced them.

| Stage | What it does |
|---|---|
| 1. HDL | Synthesizes and implements `pluto.xpr`, exports the hardware platform |
| 1b. Toolchain | Builds Buildroot's Linaro GCC 7.3 cross-compiler (once) |
| 2. FSBL | Scaffolds and compiles a fresh Vitis FSBL from the hardware platform |
| 3. U-Boot | Built from `zynq_pluto_defconfig`, patched to the real board's boot defaults |
| 4. Kernel | `uImage` + `zynq-pluto-sdr-fishball.dtb` |
| 5. Root filesystem | Buildroot; auto-retries a known git-archive hash-drift issue |
| 6. `uEnv.txt` | Generated from the just-built U-Boot's own defaults |
| 7. Packaging | `bootgen` combines FSBL + bitstream + U-Boot into `BOOT.bin` |

A full run is 45–90 minutes (HDL and Buildroot are the long stages). Every step
re-runs every time — no per-stage skip logic — but Vivado's incremental
synthesis means only what changed gets rebuilt.

## 6. Flash the board

### Option A — SD card (always works)

```bash
# run from: firmware/
cp output/{BOOT.bin,devicetree.dtb,uEnv.txt,uImage,uramdisk.image.gz} /path/to/sd-card/
```

FAT32, single partition. Eject, insert, power-cycle. This is the only option
that updates **everything** including the bitstream, so it's the one for any
HDL change. If the board comes up with old firmware or not at all, check the
`BOOT` switch is in SD mode — a board in QSPI mode ignores the card entirely,
which looks exactly like a failed build.

### Option B — DFU over USB (no disassembly)

Kept for reference — **prefer Option C**, which does everything DFU does, can
also update `BOOT.bin`, and backs up and verifies as it goes. U-Boot has USB DFU
built in and can push `uImage`, `devicetree.dtb` and `uramdisk.image.gz` onto
the card over the micro-USB cable, but it **cannot** update `BOOT.bin` — there
is no DFU target for the bitstream/FSBL/U-Boot — and DFU has bricked units on
this board.

1. Open a serial console (see [step 7](#7-verify-your-build-is-actually-running)),
   power-cycle, press any key within 3 s to stop at `Zynq>`.
2. `Zynq> run dfu_mmc` — the board now waits for transfers, printing nothing.
3. From your host:
   ```bash
   # run from: firmware/output/  (on your HOST, not the board)
   dfu-util -l   # confirms you can see the three targets
   dfu-util -D uImage             -a uImage
   dfu-util -D devicetree.dtb     -a devicetree.dtb
   dfu-util -D uramdisk.image.gz  -a uramdisk.image.gz
   ```
4. **Ctrl+C** on the console to exit the DFU loop, then `Zynq> reset`.

### Option C — over SSH, from the running board (no card removal)

If the board still boots, it can rewrite its own SD card. The FAT partition
`/dev/mmcblk0p1` is normally left unmounted, so you can mount it, replace
`BOOT.bin` and reboot over the network. **This is the only remote option that
can update the FPGA bitstream.**

**Use the script** — it does the backup, the checksum verification before the
swap, the clean unmount and the reboot, and keeps the previous firmware both on
the card and on your disk:

```bash
./devkit flash              # BOOT.bin + uImage
./devkit flash --all        # all five files
./devkit flash --boot-only  # just the bitstream
```

What it does, if you would rather do it by hand:

```bash
# run from: firmware/   (BOARD is the running board)
BOARD=root@192.168.2.1

# 1. Back up what is on the card RIGHT NOW - this is your way back.
ssh $BOARD 'mkdir -p /tmp/sd && mount -o ro /dev/mmcblk0p1 /tmp/sd && cat /tmp/sd/BOOT.bin' > BOOT.bin.rollback
ssh $BOARD 'md5sum /tmp/sd/BOOT.bin; umount /tmp/sd'
md5sum BOOT.bin.rollback                      # the two must match

# 2. Copy the new one in beside the old, then verify before swapping.
ssh $BOARD 'mount -o rw /dev/mmcblk0p1 /tmp/sd'
scp output/BOOT.bin $BOARD:/tmp/sd/BOOT.bin.new
ssh $BOARD 'md5sum /tmp/sd/BOOT.bin.new'      # must match md5sum output/BOOT.bin

# 3. Swap, flush, unmount cleanly, reboot.
ssh $BOARD 'cd /tmp/sd && cp BOOT.bin BOOT.bin.stockbak && mv BOOT.bin.new BOOT.bin && sync && cd / && umount /tmp/sd && reboot'
```

The board is back in about 40 seconds.

> **Do the backup step.** A bad `BOOT.bin` means the board does not boot, and
> then this option is gone — recovery needs a card reader. Verify the md5
> *before* the `mv`, unmount cleanly so FAT metadata is flushed, and keep the
> rollback until the new firmware has proved itself.

### Option D — JTAG (temporary, but the fastest HDL loop)

Push a bitstream straight into the FPGA over JTAG — seconds instead of a full
rebuild. It is **volatile** (gone on power-cycle) and does **not** update
`BOOT.bin`: for testing, not deployment. Use the **debug port** (JTAG is
interface 0), and keep the USB 2.0 port connected too.

**One-time setup.** Vivado ships udev rules for Digilent cables but doesn't
install them; without them libusb can't claim the device and Vivado reports
`ERROR: [Labtoolstcl 44-199] No matching targets found`. Run this **in a real
terminal on the machine the board is plugged into** — `sudo` needs a TTY, and
rules installed inside a VM don't affect the host:

```bash
# run on your HOST, from anywhere
sudo cp /tools/Xilinx/Vivado/2022.2/data/xicom/cable_drivers/lin64/install_script/install_drivers/*.rules \
        /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Unplug and replug the debug cable, then verify (no sudo needed): two `.rules`
files in `/etc/udev/rules.d/`, and permissions `crw-rw-rw-` on the USB node.
Confirm Vivado sees it with `open_hw_manager; connect_hw_server;
get_hw_targets; open_hw_target; get_hw_devices` — you want the Digilent cable,
then `arm_dap_0 xc7z020_1`.

**Keep BOTH cables connected throughout.** The debug port powers the board and
the USB 2.0 port carries the network; since the bitstream is volatile,
unplugging to "move over" would cut power and lose it.

**Never program while Linux is running.** Its drivers are bound to the *old*
PL; swapping underneath them hangs the system.

### D1. Quick method — Hardware Manager, halted at U-Boot

1. Open the debug UART, power-cycle, press a key within 3 s to stop at `Zynq>`.
   The FSBL has configured the PS and enabled the level shifters; Linux has
   claimed nothing.
2. Program — GUI: **Open Hardware Manager → Auto Connect → right-click
   `xc7z020_1` → Program Device**. Or scripted:

   ```tcl
   open_hw_manager
   connect_hw_server
   open_hw_target
   current_hw_device [get_hw_devices xc7z020_1]
   set_property PROGRAM.FILE \
     {<repo>/firmware/src/hdl/projects/pluto/pluto.runs/impl_1/system_top.bit} \
     [current_hw_device]
   program_hw_devices [current_hw_device]
   ```

3. Back at `Zynq>`, type `boot`.

Success prints `INFO: [Labtools 27-3164] End of startup status: HIGH`. `LOW`
means the bitstream didn't take.

**Caveat.** On Zynq the PS↔PL level shifters and PL resets are managed by
*software* (`ps7_post_config`), not by programming. Re-loading the PL under a
PS set up for the previous bitstream can leave AXI in an undefined state —
usually fine when the AXI topology hasn't changed, otherwise use D2.

### D2. Robust method — full JTAG bootstrap (ADI's own flow)

Brings the whole board up from JTAG so the PS is initialised *for the bitstream
you are loading*, in the right order:

```tcl
# xsdb run-jtag.tcl     (run from: firmware/src/hdl/projects/pluto)
connect
target 2
rst
source ps7_init.tcl
ps7_init
fpga -f pluto.runs/impl_1/system_top.bit
ps7_post_config
dow ../../../u-boot-xlnx/u-boot
con
```

Ordering is the point: `ps7_init` configures DDR/clocks/MIO, the bitstream goes
in next, and **`ps7_post_config` must come after it** — that's what enables the
level shifters and releases the PL resets. ADI's shipped script has the `fpga`
line commented out because their use case was flashing U-Boot without a new
bitstream. Everything needed comes from a normal build. When the design works,
rebuild and flash via Option A so it persists.

### If things go wrong: recovering the factory firmware

If you skipped the backup or lost it, the distributor publishes the board's
prebuilt factory firmware:
**[`OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR`](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR)**

This is a verified fallback, not a guess: those binaries were compared
byte-for-byte against a working unit's SD card during this project. Copy them
onto a FAT32 card as in [Option A](#option-a--sd-card-always-works). Keep a
local copy *before* experimenting — a rescue that needs the internet and a
third-party repo still being online is a weaker net than a folder on your disk.

## 7. Verify your build is actually running

**Before you flash**, check the build made sense — this costs a second, where
flashing and rebooting costs minutes:

```bash
./devkit verify            # is the build sane?
./devkit verify --board    # ...and is the board actually running it?
```

It asserts the five files are present and non-trivial, that the bitstream is
compressed (an uncompressed one overflows the FSBL's OCM and `BOOT.bin`
silently fails to boot), and that no setup endpoint fails timing — then prints
what is actually in the design, so you can see your change landed:

```
== FPGA design ==
  PASS  utilization report present
        DSP48s 72 / 220   Slice LUTs 11896 / 53200
        -> stock filter
        block design: stock RX path, no rx_ddc
== bitstream ==
  PASS  compressed (2367948 B < 3.9 MB uncompressed)
== timing ==
  PASS  no failing setup endpoints
        WNS 0.231 ns over 48263 endpoints
```

(With the optional channelizer applied you would see `96 / 220` DSPs and
`rx_ddc (Fs/4 shifter) is wired in` instead.)

It exits non-zero on failure, so it works in scripts.

`--board` answers a different question: it mounts the board's SD card and
compares every file against `output/` by checksum. Worth knowing because a
board whose card holds a *different* build of the same size looks entirely
normal, and every symptom of that is indistinguishable from "my change did not
work". A stale board is reported as such rather than as a bad build.

**Which USB port is which** — the two do completely different things:

| | **USB 2.0 (OTG) port** | **Debug port** |
|---|---|---|
| Enumerates as | `0456:b673` Analog Devices, typically `/dev/ttyACM*` (`-if03`) | `0403:6010` **Digilent Adept**, two `/dev/ttyUSB*` |
| Gives you | Network-over-USB (`192.168.2.1`), libiio, mass storage, a console | **JTAG** (`-if00`) and the board's **real UART console** (`-if01`) |
| Available | Only **after Linux boots** — a USB gadget created by the board's Linux | From **power-on** — real hardware, independent of software |

**For serial, use the debug port**: its UART is the actual console (`ttyPS0`),
so you see FSBL → U-Boot → kernel → login. The OTG console only appears once
Linux is up, so you miss the whole boot — and see nothing at all if the board
fails to boot, which is exactly when you need it.

Find the port by its stable name rather than assuming a number:

```bash
# run on your HOST, from anywhere
ls -l /dev/serial/by-id/
#  ...Digilent_Adept_USB_Device_<serial>-if00-port0 -> ttyUSB0   <- JTAG
#  ...Digilent_Adept_USB_Device_<serial>-if01-port0 -> ttyUSB1   <- console
screen /dev/serial/by-id/usb-Digilent_Digilent_Adept_USB_Device_<serial>-if01-port0 115200
```

Press Enter for a login prompt; credentials are **`root` / `analog`** (change
with `device_passwd` on the board). Exit `screen` with `Ctrl-A` then `k`, `y`.

**SSH works too** and is usually more convenient — the firmware runs dropbear,
reachable over the USB network or Ethernet at `ssh root@192.168.2.1`. That
needs the **USB 2.0 port**; the debug port carries no network.

Then confirm your build is running, **on the board**:

```
# on the BOARD (inside the screen session)
cat /opt/VERSIONS
```

It prints a `device-fw <git-hash>` line plus one per component, generated by
your `build_all.sh`. Upstream firmware hardcodes `fw_version=v0.38` — anything
else (a real git hash) proves you are running your own build. The same value
shows in `iio_info` as `fw_version`, where `hw_model` should read `FISH Ball
PlutoSDR Rev.A (Z7020-AD9361)`.

## Repository layout

```
fishball7020-fpga-devkit/
├── README.md                            ← you are here: the build/flash workflow
├── LICENSE                              multiple licenses apply — see below
│
├── .claude/skills/                      ← Agent Skill, loaded automatically by Claude Code
│   └── fishball7020-firmware/
│       ├── SKILL.md                     the rules, the map, what a healthy board measures
│       └── references/                  gain tables · measuring · board access · debugging
│
├── devkit                               ← one entry point: doctor · setup · sim · build
│                                          verify · flash · selftest · gpio-check · status
├── tools/
│   ├── env-vivado.sh                    ← source this before any vivado/xsct/bootgen command
│   ├── flash.sh                         ← flash the running board over the network, safely
│   ├── tx-gpio-bitmap-check.py          verifies the TX-nibble-to-GPIO feature on hardware
│   ├── flash.sh                         flash the running board over the network, safely
│   ├── setup-hardware-runner.sh         register this machine as the hardware-CI runner
│                                          (workflows stay inert until you do)
│   ├── selftest/                        ← is the board damaged? measures and says (see below)
│   │   ├── sdr_selftest.py              rails, BIST, receiver, and an RF loopback sweep
│   │   ├── iiod_min.py                  libiio's network protocol over a socket, stdlib only
│   │   └── test_dsp.py                  asserts the measurement maths, no board needed
│   └── legacy-libs/libs/                vendored libtinfo5/libncurses5/libssl1.1
│
└── firmware/       the only firmware target — factory-default USB+Ethernet build
    ├── README.md                       deep reference: exact patch list, provenance,
    │                                   byte-for-byte comparison against real hardware
    ├── patches/                        applied by setup.sh:
    │   │                               0001 fixes + hw_serial · 0002 device tree
    │   │                               0004 TX mute · 0005 keep a gain set before streaming
    │   │                               0006 sample-locked GPIO · 0007 its IIO attribute
    │   │                               0008 gpio-line-names for those four pins
    │   └── optional/                   NOT applied — worked examples
    │       └── 0003-wbfm-channelizer.patch         (docs/wbfm-channelizer.md)
    ├── scripts/
    │   ├── doctor.sh                   (run first) can this machine build? checks before the hour
    │   ├── setup.sh                    (run once) clones upstream into src/, applies patches
    │   ├── build_all.sh                (run every time) full build → output/
    │   ├── build_hdl.tcl               Vivado batch: synth → impl → export platform
    │   ├── gen_fsbl_*.tcl              Vitis/xsct: scaffold and compile the FSBL
    │   ├── fix_and_retry_buildroot.sh  auto-repairs a known Buildroot hash-drift issue
    │   ├── boot.bif                    bootgen recipe: FSBL + bitstream + U-Boot → BOOT.bin
    │   ├── gen_fir_coe.py/.m           designs + verifies FIR coefficients
    │   ├── verify_output.sh            checks output/ and reports what's in the bitstream
    │   └── coefile_*.coe               generated coefficients, copied into src/ by build_all
    ├── sim/                            ← simulate the custom HDL in a second, no Vivado
    │   ├── run_sim.sh                  runs it; --mutate proves the testbenches can fail
    │   ├── tb_ad_fs4_ddc.v             golden-model testbench for the channelizer
    │   └── tb_tx_gpio_bitmap.v         golden-model testbench for the GPIO bit-map
    ├── src/                            ← created by setup.sh, NOT committed (see .gitignore)
    │   ├── hdl/projects/pluto/         ← the Vivado project (system_bd.tcl, system_top.v,
    │   │                                 system_constr.xdc — what you edit in step 4)
    │   ├── linux/  u-boot-xlnx/  buildroot/
    └── output/                         ← the 5 final SD-card files
```

## Sample-locked GPIO outputs

Four pins on the expansion header that change state **in lockstep with the
samples you transmit**. Not "roughly when" — each edge is tied to one specific
sample, with a fixed offset you measure once and then trust. Useful as a master
clock, a frame marker or a sync line for external hardware that has to stay
aligned with the transmitted waveform: multi-channel radar, MIMO, anything with
a receiver that is not this board.

It is **built into the base firmware and off by default**, so it costs nothing
until you ask for it.

### Why it is free

You hand the AD9361 **16-bit** samples. Its transmit DAC is **12 bits** and
reads only the top 12 — ADI's own HDL does literally
`dac_data_out_int <= dma_data[15:4]`. The bottom four bits reach the FPGA and
stop there, changing nothing about the transmitted signal.

```
your sample:   b15 … b4 │ b3 b2 b1 b0
               └ the DAC │ └ discarded — this feature routes them to pins
```

So at normal sample rates the pins cost no analog performance — the DAC never
sees those bits — and no extra hardware: +3 LUTs and +7 flip-flops, no DSPs, no
block RAM. (Below 2.083 MSPS the FPGA interpolator is engaged and filters the
whole 16-bit word, so the nibble leaks into the DAC data at roughly −70 dBFS —
see [Limits](docs/tx-gpio-bitmap.md#limits).)

### How the nibble reaches the pin

The four bits branch off early — while the sample is still exactly the 16-bit
word you wrote — and travel to the pad on their own. Four things happen on the
way.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/nibble-path-dark.svg">
  <img src="docs/img/nibble-path-light.svg" alt="The transmit path from your DDR buffer to the antenna port, with the low four bits branching off at util_upack2 into tx_gpio_bitmap, an IO buffer and JP5 pins 7, 9, 11 and 13" width="760">
</picture>

**1 — The tap, taken before any filter.** DMA hands the FPGA one long stream of
bytes; `util_upack2` splits it back into per-channel samples. Its output
`fifo_rd_data_0[3:0]` is the low nibble of channel 0's **I** sample, still bit
for bit what you put in the buffer. (`fifo_rd_data_1[3:0]` is Q — the hook for
widening to eight pins later.) Tapping here and not further down matters: the
next block is a **FIR interpolator**, a filter that blends neighbouring samples
to raise the sample rate, and a nibble read after it would be filter output
rather than the bits you authored.

**2 — The capture, once per sample.** A small module, `tx_gpio_bitmap`, latches
the nibble into a register and holds it until the next sample. It fires on the
**strobe** — the signal that says "a new word is standing here now" — which in
this design is `fifo_rd_valid | fifo_rd_underflow`. Two traps live here, and
both are the kind that simulate fine and only show up on a scope:

- Not `fifo_rd_en`. That one is a *request* for a sample, and `util_upack2`
  registers its output, so the word appears a clock later. Capture on the
  request and every pin sits permanently one sample behind the DAC.
- Not every clock. With both channels running (**2R2T**) a new sample arrives
  only every *second* FPGA clock, so capturing on the clock would double the
  rate of every pattern you wrote — a half-rate clock would come out at full
  rate, a one-sample marker would arrive twice.

Including `underflow` means that when DMA starves and the DAC is fed zeros, the
pins carry those zeros too — so "the pins are the low nibble of what the DAC
got" holds with no exceptions.

**3 — The switch, one flag bit.** The same module chooses who owns the four
pads: with the flag clear they are ordinary Linux GPIO; with it set the fabric
drives them from the captured nibble. The flag is **bit 1 of the DAC core's
`GP_CONTROL` register** (AXI offset `0xBC`; bit 0 is already the interpolator
bypass, so software must read-modify-write it — the `tx_sample_gpio_en` file
below does that for you). Software writes it in one clock domain and the
datapath reads it in another, so it crosses two flip-flops on the way in and a
change takes effect two clocks later.

**4 — The pad.** An `ad_iobuf` per pin in `system_top.v` connects the module's
output and tristate control to the package ball, and the ball's input side goes
back to Linux so the GPIO can still be *read* either way.

**What comes out.** A pad changes one clock after the tap. The matching RF is
much further behind — it still has the interpolator, the AD9361's own digital
filters and the DAC ahead of it — so **the pins lead the RF by a fixed
offset**. Fixed is the useful part: it does not drift, and it repeats run to
run for a given configuration, so it can be calibrated out once. It is not
zero, and it has not yet been measured here — see
[what has actually been verified](docs/tx-gpio-bitmap.md#what-has-actually-been-verified).

### The pins

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/jp5-pinout-dark.svg">
  <img src="docs/img/jp5-pinout-light.svg" alt="JP5 pinout: a 2x10 header with pins 7, 9, 11, 13 carrying sample_gpio[0..3] and grounds on pins 2 and 20" width="700">
</picture>

| Signal | Header net | JP5 pin | FPGA ball |
|---|---|---|---|
| `sample_gpio[0]` | `3V3_IO1` | 7 | V10 |
| `sample_gpio[1]` | `3V3_IO2` | 9 | U9 |
| `sample_gpio[2]` | `3V3_IO3` | 11 | U10 |
| `sample_gpio[3]` | `3V3_IO4` | 13 | T9 |

Ground on **pin 2 or 20**. The even pins 4–18 are **1.8 V** differential
pairs and pins 1/3/5 are power rails (5 V, 3.3 V, 1.8 V) — do not drive them. The bit number matches the silkscreen, so
`sample_gpio[0]` is the pin labelled `3V3_IO1`. All four are 3.3 V LVCMOS in
bank 13, whose VCCO the schematic ties to VCC3V3, and each is pulled **down**
so an idle pin reads a defined low rather than floating.

Pin *numbering* is certain; which physical end of the connector is pin 1 is not
marked on the schematic — find the square pad or the silkscreen dot before you
clip anything on.

### Turning it on

```sh
# on the board - resolve the device by name; the iio:deviceN index is not stable
D=$(for d in /sys/bus/iio/devices/iio:device*; do
      [ "$(cat $d/name)" = cf-ad9361-dds-core-lpc ] && echo $d; done)
echo 1 > $D/tx_sample_gpio_en               # pins carry the sample nibble
echo 0 > $D/tx_sample_gpio_en               # pins are ordinary GPIO again
```

With it off, the four pins are plain Linux GPIO that you can drive and read as
usual — so enabling the feature in the bitstream takes nothing away. They are
named in the device tree, so no arithmetic is needed:

```sh
gpiofind sample_gpio0              # -> gpiochip0 72
gpioget $(gpiofind sample_gpio0)   # read it
gpioset $(gpiofind sample_gpio0)=1 # drive it (with the feature off)
```

The legacy numeric path still works if you prefer it: GPIO **978–981**, which
is `gpiochip base + 54 + 18` (54 MIO lines, then EMIO 18–21).

### Using it

There is no "clock mode" register. **The pattern is data**: whatever you put in
the low nibble of each transmit sample appears on the pins, one nibble per
sample. A pin is a clock because you made that bit alternate; it is a frame
marker because you made it pulse once per frame.

```python
n = np.arange(N)
bit0 = (n % 2  == 0)       # master clock at half the sample rate
bit1 = (n % 64 == 0)       # frame marker, one sample every 64
nibble = (bit0 | bit1 << 1).astype(np.int16)

i16 = (i16 & ~0x000F) | nibble      # OR it in LAST, after any scaling
sdr.tx_cyclic_buffer = True         # loop one period for a continuous clock
sdr.tx([i16, q16])
```

**OR the nibble in last.** Any gain or format step applied afterwards
overwrites the bottom bits, because to that code they are noise. This also
means GNU Radio's ordinary complex-float path cannot carry it — work at
`short` level or render the buffer with numpy.

The fastest a pin can toggle is **half the sample rate** (~30 MHz at
61.44 MSPS), and every pattern is a whole-number division of it.

### Checking it works

```bash
./devkit gpio-check
```

No scope, no antenna, no jumper: it transmits with attenuation pinned at
maximum — the nibble lives in bits the DAC discards, so the analog chain sees
zeros — and reads the pins back through sysfs. It verifies each bit reaches its
own pin, that the flag releases them, and that an authored square wave comes
out at the period the sample rate implies.

**Full reference:** [docs/tx-gpio-bitmap.md](docs/tx-gpio-bitmap.md) — the
datapath, why the capture strobe is what it is, the block-design wiring,
measured cost and timing, and what has and has not been verified on hardware.

## Transmitter safety

**Stock firmware leaves the transmitter running.** Measured at power-on: the
AD9361 comes up in ENSM `fdd` with the TX synthesiser going and only 10 dB of
attenuation, so the port emits LO leakage continuously — nothing in the DAC
DMA, no DDS tone, nobody having asked to transmit. When a transmission ends,
ADI's driver reverts to a silent DDS but leaves the chain biased.

Idling like that is not itself a damage risk — at maximum attenuation the
output is negligible (−89.75 dB below full scale). But there is no reason to
keep a transmitter energised that you are not using, it warms a die already
above 50 °C, and on the **PA variant this is not a trivial amount of power**.

**Do not transmit at power into an unterminated port.** An open or shorted
connector reflects everything back into the output stage. Neither the AD9361
datasheet (TX specified into a matched 100 Ω load, ~6.5 dBm max) nor the
PGA-102+ PA datasheet (~+17.5 dBm here) states any tolerance for an output
open, short or high VSWR — treat it as unspecified and always terminate. The
receiver has a hard number: **+2.5 dBm is the AD9361's absolute-maximum RF
input**, which is why every loopback here goes through an attenuator.

**This build fixes it in firmware.** `patches/0004` hooks the TX buffer
lifecycle the DAC driver already has:

| Event | What happens |
|---|---|
| boot (`S21misc`) | TX attenuated to maximum — quiet before anything streams |
| a TX buffer starts streaming | TX unmuted — your gain if you set one, else the last you used |
| the buffer stops | TX muted and the synthesiser powered down, automatically |

It calls `ad9361_tx_mute()`, ADI's own exported helper, which was present in
the tree but called from nowhere. `patches/0005` exists because restoring the
cached attenuation *unconditionally* was itself a trap: setting a gain then
starting the stream is the obvious order, and the unmute would overwrite it a
moment later with the previous transmission's value — asking for −10 dB could
put −60 dB on the wire. The unmute now restores the cache only when nothing has
been set since the mute, so both orders work:

| What you do | What you get |
|---|---|
| set a gain, then start the stream | the gain you set |
| start the stream having set nothing | the last gain you used |

If you have a watchdog script polling `buffer/enable` to re-apply a gain, you
no longer need it — check `/mnt/jffs2/autorun.sh`, since that partition is
persistent and survives reflashing. `tools/selftest/sdr_selftest.py --ssh`
lists what is there.

What makes this a guarantee rather than best effort: the IIO core runs the
buffer's `postdisable` hook on teardown **even when the application crashed or
was killed**, because teardown happens on file close. A userspace watchdog
could never promise that. The TX mute needed no device tree change of its
own — the driver reaches the phy through the DDS node's existing `clocks`
phandle.

Measured over a 50 dB attenuated loopback, **the mute costs no output power**:
commanded and applied attenuation matched to 0.01 dB at every point including
0 dB, and received level tracked commanded gain across 40 dB within 1.9 dB.

> ### A TX→RX loopback without an attenuator will destroy your receiver
>
> The receiver is the fragile end — rated to roughly **+2.5 dBm** — and **this
> board is sold in a variant with a power amplifier on transmit**, which most
> Pluto advice does not account for. The PA is a Mini-Circuits
> [**PGA-102+**](https://www.minicircuits.com/pdfs/PGA-102+.pdf):
>
> | GHz | 0.05 | 0.8 | 2.0 | 3.0 | 4.0 | 6.0 |
> |---|---|---|---|---|---|---|
> | **Gain (dB)** | **17.7** | 15.9 | 14.0 | 12.5 | 11.5 | 10.4 |
>
> with P1dB around **+17.5 dBm**. Measured flat out: **+18.5 dBm at 900 MHz**,
> and **+19 dBm** as the across-band figure, the six runs agreeing to 0.7 dB —
> roughly **16 dB above what its own receive port survives**.
>
> <sub>This table and these figures are the canonical copy; `tools/selftest/README.md`
> and the agent skill point here. Update them here first.</sub>
>
> **Fit at least 20 dB of attenuation** in any loopback; 40–50 dB is
> comfortable and still leaves 60 dB of SNR. Start at maximum attenuation and
> raise power in steps. `tools/selftest/` does all of this and never transmits
> with less than 35 dB of its own attenuation. The non-PA variant is 10–18 dB
> quieter — check which you have before relying on that.

## Simulating your HDL first

A Vivado build is 20 minutes with `--hdl-only` and 70 from cold, and then you
still have to flash. Synthesis also cannot tell you the logic is *wrong* — only
that it fits and meets timing. So check the logic first:

```bash
# run from: firmware/
./sim/run_sim.sh
```

Needs only `iverilog`, takes about a second, and checks the repo's custom HDL
against a golden model of what it should compute. It works whether or not you
applied the optional patches — if a module isn't in `src/`, the runner lifts it
straight out of its patch file.

```
== ad_fs4_ddc ==        PASS  473 checks, no mismatches against the golden model
== tx_gpio_bitmap ==    PASS  2092 checks
```

**The check that earns its keep** in both modules is gapped valid. A counter
must advance once per *sample*, not once per *clock*, and on this board `valid`
is genuinely intermittent — in 2R2T mode the AD9361 asserts `adc_valid` every
second clock. Getting it wrong looks correct in a back-to-back simulation,
synthesises cleanly, meets timing, and is wrong on hardware.

A green suite means nothing until you have watched it go red:

```bash
./sim/run_sim.sh --mutate
```

It breaks the modules ten ways — a phase counter moved out of its guard, sign
errors, I/Q swapped, an unregistered output; a nibble captured every clock,
pins left tristated, a reversed mux, one synchroniser stage instead of two, a
reset leaving a stale value — and reports any mutant the testbenches fail to
catch. CI runs both.

This is not decoration: writing that last mutant exposed a hole in the reset
test, where a sample was landing between the reset and the check and papering
over the stale value. If you add HDL, add a testbench beside these.

## Measured performance

One board, six runs — both channels, through 20 dB, 30 dB and 50 dB
attenuators. Measuring three ways separates a property of the *board* from a
property of the *cable*.

| | |
|---|---|
| **Gain accuracy** | 12 slope measurements, every one within **1.4% of unity** |
| **Image rejection** | **55–63 dBc** after calibration (41–48 dBc as found) |
| **Harmonic distortion** | **−67 to −79 dBc** |
| **Transmit power** | **+19 dBm** flat out, agreeing to 0.7 dB across six runs |
| **Transmit mute depth** | **63–70 dB**, into the noise floor |
| **FPGA headroom** | 72 of 220 DSP48s used, timing met with **+0.231 ns** to spare (v1.2 default; +0.214 without the GPIO feature) |

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/loop-gain-dark.svg">
  <img alt="TX to RX loop gain against frequency for both channels, 100 MHz to 5 GHz. Both peak near +20 dB around 300-700 MHz and roll off to +5 to +9 dB at 5 GHz. A shaded band shows the spread across three attenuator values: about 1-2 dB below 2 GHz, widening to 6-8 dB at 5 GHz." src="docs/img/loop-gain-light.svg">
</picture>

The gain figure is what matters in practice: **a link budget you compute is the
one you get.** Ask for 6 dB less and you get 6.0, not 5.2.

The **step at 4 GHz is not the hardware** — the AD9361 swaps RX gain table
there and the two tables label their steps differently, so a calibration made
below 4 GHz is wrong above it by about 5 dB on channel 0 and 7 dB on channel 1.

The spread is the second result. Repeated passes on the same cable agree to
0.06 dB; across three *different* attenuators the same frequencies scatter by
6–8 dB above 2 GHz. Same board, same instrument — the variable is the SMA
connectors. That is why the self-test compares against a baseline you record
with your own cable rather than absolute thresholds.

**Crossed** measurements — TX0 into RX1 and TX1 into RX0 — separate the
transmit chain from the receive chain, which a straight loopback cannot. The
transmitters match to 0.25 dB, the receivers differ by 1.5 dB, and the 4 GHz
step lives entirely in the receiver, exactly as an RX gain-table change must.
With both crosses the system is over-determined and closes to −0.05 dB.

Full tables, method and caveats in
**[docs/measured-performance.md](docs/measured-performance.md)**.

## Is the board healthy?

If you have overdriven an input, transmitted into an open port, or the board
has simply stopped behaving, `tools/selftest/` answers with measurements rather
than "well, it still enumerates". Most checks need nothing plugged in; the rest
need TX cabled to RX through an **attenuator**.

```bash
cd tools/selftest
./sdr_selftest.py --ssh                                     # no cable, never transmits
./sdr_selftest.py --ssh --loopback --pad 50                 # + the RF tests
./sdr_selftest.py --ssh --loopback --pad 50 --channel both  # both TX/RX pairs
```

Python 3.8 and nothing else — `numpy` for the FFT if you have it, a pure-Python
transform if you don't.

**Without a cable** it reads the six Zynq supply rails against ±5% limits and
both die temperatures, runs the AD9361's **digital-interface eye scan** (all
16×16 clock/data delay combinations with PRBS running — how you catch an LVDS
link gone marginal), pushes a tone through the chip's **internal digital
loopback** to prove both DMAs and the FPGA datapath, then exercises the
receiver: capture integrity, DC offset, gain-chain response over 70 dB, both
channels, synthesiser lock from 70 MHz to 6 GHz. The BIST checks live in
debugfs, hence `--ssh`; everything else is libiio alone.

**With a loopback** it adds the analogue path: TX attenuator linearity over
25 dB, RX gain linearity over 40 dB, image rejection, 2nd and 3rd harmonics,
and path loss at eight frequencies from 100 MHz to 5 GHz — which is what finds
a blown balun, showing up as a hole in one band and nowhere else.

**It cannot overdrive your receiver, even if you forget the attenuator.** The
PA can put about +18.5 dBm on a port rated to +2.5 dBm, so the script never
transmits with less than **35 dB** of its own attenuation — about −10 dBm even
at full-scale drive with a bare cable. Sweeps start at 50 dB and only work
downward. Nothing transmits without `--loopback`, and every setting is restored
on exit, including after Ctrl-C. It also **asks how much attenuation is in your
cable** and checks that answer against what it measures, because a pad that is
missing or not making contact is the failure that kills receivers.

Path loss depends on your cable, so record a baseline while the board is known
good and compare later:

```bash
./sdr_selftest.py --ssh --loopback --save-baseline ~/board-healthy.json
./sdr_selftest.py --ssh --loopback --baseline     ~/board-healthy.json
```

That turns *"is 41.6 dB at 2.4 GHz correct?"* into *"it was 41.5 dB in March"*.
Details in [`tools/selftest/README.md`](tools/selftest/README.md).

## Troubleshooting

- **SDRangel lists the board as `PlutoSDR0 TBD` and won't open it.** SDRangel
  identifies Plutos by serial number, and firmware built before patch 0001
  reported an empty one — this board's W25Q128 flash never emits the
  `SPI-NOR-UniqueID` line the boot script looks for. Rebuild with the current
  `patches/` and reflash; the board mints a persistent serial on first boot. If
  SDRangel is a snap, also `sudo snap connect sdrangel:raw-usb`.
- **`vivado`/`xsct`/`bootgen` fail to start, or complain about missing shared
  libraries** — you sourced Vivado's `settings64.sh` instead of
  `tools/env-vivado.sh`.
- **The kernel build fails with `GLIBC_2.xx not found` in a `gcc-plugins`
  step** — you sourced `env-vivado.sh` in the same shell you then built the
  kernel in; it injects Xilinx toolchain directories into `PATH` that conflict.
  `build_all.sh` isolates this correctly; by hand, use a fresh shell.
- **U-Boot/kernel builds fail with `unrecognized -march target: armv5`** —
  Buildroot's cross-compiler (stage 1b) isn't built yet. Re-run `build_all.sh`
  rather than invoking `make` directly.
- **Buildroot fails with `has wrong sha256 hash`** — known, harmless
  git-archive repackaging drift for a few pinned commits.
  `fix_and_retry_buildroot.sh` repairs it automatically; if it still fails,
  check `/tmp/buildroot_autoretry_*.log` for a different cause.
- **`dfu-util -l` shows nothing** — you didn't stop autoboot in time, or
  `run dfu_mmc` wasn't accepted.
- **You moved the checkout and Buildroot fails with `cp: cannot stat`** —
  Buildroot's `output/` is **not relocatable**; autotools bakes absolute paths
  into thousands of generated files. Discard the stale build state (the
  download cache is unaffected):
  ```bash
  # run from: firmware/
  rm -rf src/buildroot/output
  ./scripts/build_all.sh
  ```

Still stuck? [Open an issue](../../issues/new/choose) — the templates ask for
the details that actually speed up debugging. See also
[CONTRIBUTING.md](CONTRIBUTING.md).

## How this repo came to exist

The board ships with no published, editable firmware source. This firmware was
reverse-engineered and rebuilt from scratch, starting from the public upstream
fork
[`Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR`](https://github.com/Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR),
cross-referenced against:

- **The board's real schematic**, to verify the HDL project's pin constraints
  by hand — several other candidate projects turned out to target *different*,
  similarly-named boards despite compiling successfully.
- **A byte-for-byte comparison** against
  [`OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR`](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR),
  confirming it as the genuine source of the prebuilt binaries (though not of
  editable HDL/kernel source, which was never published).
- **An extracted `IKCONFIG` kernel `.config`** pulled out of the real
  firmware's compiled kernel image, proving this rebuild's configuration
  identical rather than merely close.

The result, verified file-by-file against a real unit: the device tree
recompiles byte-for-byte identical to the factory one (patch `0008` then adds
`gpio-line-names`, the single deliberate departure — see below); `uEnv.txt` and
the rootfs file list are
content-identical; kernel and bootloader are within a few hundred bytes (the
upstream history was squashed *after* this board's firmware was built, so some
source has drifted — not recoverable from public sources). The
[firmware README](firmware/README.md) has the exact patch list, including two
genuine upstream bugs found along the way.

### The end-to-end test

The claim this repo has to earn is narrow and testable: *a fresh clone, an
edit, and a rebuild produce firmware whose FPGA actually contains the edit.*
Re-run before every release, from a clean clone, flashed to a real board.

**A clean clone reproduces stock.**

| | |
|---|---|
| Patches applied | 0001, 0002, 0004, 0005, 0006, 0007, 0008 — `optional/0003` skipped, with a message saying so |
| `devicetree.dtb` | reproduces the factory one exactly, then patch `0008` adds `gpio-line-names` (+152 B) — verified by decompiling and diffing |
| RX path | no `rx_ddc`, stock `coefile_int.coe`, **72 / 220 DSP48s**, 11 896 LUTs |
| BOOT.bin | 2 888 788 B, bitstream compressed to 2 329 140 B |
| Timing | WNS +0.231 ns, 0 failing endpoints of 48 263 |
| HDL simulation | 2 565 checks against the golden models, all 10 mutants caught |
| On the board | correct `hw_model`, persistent serial, TX muted at boot, sample-locked GPIO passes its own check, 32 self-test checks passed |

**"Stock" now means two things more than factory.** The kernel config and
rootfs are still factory-identical, and the device tree still recompiles
byte-for-byte from the factory one — but the default *bitstream* contains the
sample-locked GPIO feature, and patch `0008` adds `gpio-line-names` to the
device tree so those four pins can be found by name. Both are deliberate and
both are listed above. That costs +3 LUTs and +7 flip-flops and changes no
radio behaviour, because its enable bit resets to 0 and the four header pins
stay ordinary GPIO until something sets it.

**An HDL change reaches the fabric** — `optional/0003-wbfm-channelizer.patch`
applied, Vivado project deleted, `build_all.sh --hdl-only` re-run.

| | |
|---|---|
| RX path | `rx_ddc` wired, `coefile_wbfm_102100.coe`, **96 / 220 DSP48s** |
| Timing | WNS +0.292 ns, 0 failing endpoints of 55 269 |
| On the board | LO spur moved from **+0 kHz** to **−1000 kHz** |

That last row is the whole test in one number. The AD9361's LO leakage and DC
offset land at exactly 0 Hz and cannot be moved by anything in software — so a
spur at −1 MHz can only have been moved by logic running in the FPGA. Engaging
the ÷8 filter confirms the rest: an out-of-band signal 37.8 dB over the floor
vanishes, and capture RMS drops from −49.2 to −78.6 dBFS.

**The sample-locked GPIO feature**, measured against a build without it.

| | |
|---|---|
| Timing | WNS **+0.231 ns** vs +0.214 without it — *better*, because the patch constrains a clock-domain crossing ADI's design leaves timed as if it were synchronous |
| Logic | **+3 LUTs, +7 flip-flops**, no DSPs, no block RAM |
| I/O | **+4 bonded IOBs** — V10, U9, U10, T9, bank 13, `LVCMOS33`, pulled down |
| Idle state | pins read **0** undriven, confirmed on hardware — they floated to 1 before the pull-down was added |
| Control | `tx_sample_gpio_en` reads back, and sets register `0xBC` bit 1, confirmed |
| On the board | all four one-hot nibbles appear on their own pin; authored square wave tracks `N/fs` to 0.1% |

**This is not ceremony.** The v1.1 run found three real defects in the build's
own self-repair path, each of which would have stopped the next person building
from a clean clone: it patched the alphabetically-first of 1120 packages
containing a `COPYING` rather than the one that failed; it recorded the hash of
a zero-byte download as valid, disabling the check that caught the corruption;
and it cleared `dl/` without clearing the stamps that stop Buildroot
re-fetching. None were visible by reading the code.

## Vendor resources

Published by the board's distributor — useful primary reference, but none of it
includes editable HDL sources, which is the gap this repo fills.

- [**PlutoSky R1 write-up**](https://blog.opensourcesdrlab.com/archives/PlutoSky-R1)
- [**Vendor file archive**](https://workupload.com/archive/kc2v7ryVZZ)
- [`OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR`](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR)
  — confirmed by checksum as the genuine source of the prebuilt factory binaries.

## License

Several kinds of content under different licenses — see [`LICENSE`](LICENSE)
for the breakdown. In short: this repo's own scripts, patches and documentation
are **GPL-2.0** (the `LICENSE` file); the cloned upstream source (Linux/U-Boot/Buildroot, fetched by
`setup.sh`, never committed here) remains GPL; Xilinx Vivado/Vitis and any AMD
IP are proprietary and licensed separately.
