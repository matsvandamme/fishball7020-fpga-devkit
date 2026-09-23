# Building your own firmware

Everything between a fresh Ubuntu machine and five SD-card files that contain
your change. For the short version, see the [Quick start](../README.md#quick-start);
for what the build actually produces and why, [How it works](how-it-works.md).

This page describes building on the host, which needs Ubuntu 18.04, 20.04 or
22.04 — the releases Vivado 2022.2 supports. **On anything newer, build in a
container instead:** [Building in a container](building-in-a-container.md).
Same commands, same output, none of it dependent on your distribution.

**Contents**

- [Requirements](#requirements) · [Install Vivado/Vitis 2022.2](#install-vivadovitis-20222) · [Get the firmware source](#get-the-firmware-source)
- [Open the block diagram](#open-the-block-diagram) · [Add your own HDL](#add-your-own-hdl) · [Change the kernel](#change-the-kernel)
- [Simulate before you build](#simulating-your-hdl-first) · [Build the firmware](#build-the-firmware)
- [Repository layout](#repository-layout) · [Building in a container](building-in-a-container.md)

Then flash it: [Flashing the board](flashing.md).

## Requirements

**Hardware:** the board, a USB-C cable, and a microSD card with a reader
(a board that still boots can be reflashed over the network instead — see
[Option C](flashing.md#option-c--over-ssh-from-the-running-board-no-card-removal)). If you
will ever loop TX to RX, **an SMA attenuator of at least 20 dB**. A debug-port
cable only if you want the serial console or JTAG.

**Software** (Ubuntu 22.04 LTS):

> On anything else, don't fight it — build in a container instead. Vivado
> 2022.2 supports 18.04, 20.04 and 22.04 and nothing newer, and it is pinned
> here because a toolchain bump changes the bitstream. `./devkit container`
> runs the whole build inside a pinned image with `/tools/Xilinx` mounted from
> the host, and produces a byte-for-byte identical `BOOT.bin`. See
> [Building in a container](building-in-a-container.md).


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

## Install Vivado/Vitis 2022.2

> If your distribution is newer than 22.04, the installer will most likely not
> run either - it is the same Java/GTK application as Vivado. Install it from
> inside the container instead:
> [Installing Vivado in the first place](building-in-a-container.md#installing-vivado-in-the-first-place).


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
system-wide — but only where the distribution has no `libtinfo.so.5` of its
own. Those copies were extracted on 22.04 and link `GLIBC_2.33`, so forcing
them onto an older release breaks Vivado with
`librdi_commontasks.so: GLIBC_2.33 not found`, an error naming a library that
is not the problem.

## Get the firmware source

```bash
# run from: wherever you want the devkit to live (e.g. ~)
git clone https://github.com/matsvandamme/fishball7020-fpga-devkit.git
cd fishball7020-fpga-devkit/firmware
./scripts/setup.sh
```

`./devkit setup` from the repo root does the same thing. This clones the
upstream source (a Zynq-7020 port of ADI's `plutosdr-fw`) into `src/` and
applies this repo's `patches/` — six fixes plus the board's device
tree (the [firmware README](../firmware/README.md) details each). `src/` is
gitignored; re-run `setup.sh` any time for a clean slate.

> **Where to run things:** `./devkit …` runs from the **repo root**. The raw
> scripts run from **`firmware/`** unless the block says otherwise — each block
> states its directory on the first line. Commands that run *on the board* are
> marked as such.

## Open the block diagram

> **[The stock block design](block-design.md)** walks through every IP
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

## Add your own HDL

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
> **[Isolating one FM channel in the FPGA](wbfm-channelizer.md)** inserts a
> custom Verilog block into the channel-0 RX path, designs and verifies new FIR
> coefficients from a script, and explains why the obvious approach — "just
> lowpass the channel" — cannot work.
>
> For a second, smaller reference design that ships **enabled in the base
> firmware**, see [the sample-locked GPIO outputs](tx-gpio-bitmap.md) —
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

## Change the kernel

The FPGA is half the board. The other half is a Linux kernel with ADI's
drivers in it, and much of the board's *behaviour* — what appears in `/sys`,
when the transmitter is muted, what the serial number is — lives there rather
than in fabric. **[Changing the kernel](kernel.md)** covers what is
already patched and why, the three-minute kernel-only rebuild loop, the kernel
options that matter, debugging a driver on a busybox board, and making a change
stick as a patch. Flash a kernel change with `./devkit flash --kernel-only`.

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
# run from: firmware/
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

## Build the firmware

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

## Repository layout

```
fishball7020-fpga-devkit/
├── README.md                            ← start here: getting going with the devkit
├── LICENSE                              multiple licenses apply — read it for the breakdown
│
├── .claude/skills/                      ← Agent Skill, loaded automatically by Claude Code
│   └── fishball7020-firmware/
│       ├── SKILL.md                     the rules, the map, what a healthy board measures
│       └── references/                  gain tables · measuring · board access · debugging
│
├── docs/                                ← everything the README links to: building, flashing,
│   │                                      safety, the GPIO feature, measurements, hardware
│   ├── img/                             figures, and the scripts + data that draw them
│   └── vendor/                          the vendor schematic this board matches
│
├── devkit                               ← one entry point: doctor · setup · sim · build
│                                          verify · flash · selftest · gpio-check · status
├── tools/
│   ├── env-vivado.sh                    ← source this before any vivado/xsct/bootgen command
│   ├── flash.sh                         ← flash the running board over the network, safely
│   ├── tx-gpio-bitmap-check.py          verifies the TX-nibble-to-GPIO feature on hardware
│   ├── sample_gpio_clock.py             drive the sample-locked pins as clocks from your host
│   ├── setup-hardware-runner.sh         register this machine as the hardware-CI runner
│                                          (workflows stay inert until you do)
│   ├── selftest/                        ← is the board damaged? measures and says
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
    │   │                               0009 the bit-map flag's CDC constraint, fixed
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
    │   │                                 system_constr.xdc — what you edit to add HDL)
    │   ├── linux/  u-boot-xlnx/  buildroot/
    └── output/                         ← the 5 final SD-card files
```
