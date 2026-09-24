---
name: fishball7020-firmware
description: Build, flash, measure and safely transmit with the Fishball7020 / PlutoSky SDR (Zynq XC7Z020 + AD9361, sold also as PlutoSky R1 and 7020-SDR). Use for FPGA and HDL changes, Vivado block-design work, kernel and device-tree patches, BOOT.bin and bitstreams, flashing, libiio/iiod and sysfs access, IQ capture, transmitting, RF loopback measurement, AD9361 gain tables and ENSM, TX muting, and diagnosing a board that misbehaves. Encodes rules that are expensive to rediscover - flash only via the SD partition and never DFU, delete the Vivado project before an HDL change or the build silently reuses the old one, simulate before synthesising, and check /mnt/jffs2 before believing anything about the firmware.
license: GPL-2.0
compatibility: Board reached over its USB Ethernet gadget (default ip:192.168.2.1). HDL builds need Vivado/Vitis 2022.2; HDL simulation needs only iverilog; the host tools need Python 3.8 and nothing else.
metadata:
  repository: fishball7020-fpga-devkit
  board: Fishball7020 / PlutoSky R1 (XC7Z020 + AD9361)
---

# Working on the Fishball7020 / PlutoSky

A reverse-engineered, buildable firmware for a board sold under several names.
Zynq XC7Z020 + AD9361, two transmit and two receive chains, and — on the common
variant — **a power amplifier**, which changes the safety arithmetic that most
Pluto advice assumes.

Depth lives in `references/`; load only what the task needs.

| | |
|---|---|
| [`rf-safety.md`](references/rf-safety.md) | **Read before anything transmits.** The PA, the power budget, TX muting |
| [`build-and-flash.md`](references/build-and-flash.md) | Exact command sequences for building, flashing, recovering |
| [`ad9361-gain-tables.md`](references/ad9361-gain-tables.md) | Why gain in dB is not gain in dB, and where the discontinuities are |
| [`measuring.md`](references/measuring.md) | The self-test, baselines, and what is a property of the board versus the cable |
| [`talking-to-the-board.md`](references/talking-to-the-board.md) | libiio/IIOD, sysfs, debugfs, and what busybox does not have |
| [`debugging.md`](references/debugging.md) | The traps that have actually cost hours here |

## The rules

**Flash with `./devkit flash`. Never DFU.** DFU has no `BOOT.bin` target, so it
can never deliver an HDL change, and on this board it has bricked units. The
script mounts `/dev/mmcblk0p1` on the running board, backs the card up to
`firmware/.flash-backups/<stamp>/` (gitignored), md5-verifies each copy BEFORE
swapping it in, keeps the old files on the card as `*.prev`, unmounts cleanly,
reboots, and only reports success once `/proc/uptime` has reset and the card
md5s match. `--boot-only` for HDL, `--kernel-only` for a driver change, `--all`
for a release. `BOARD` / `BOARD_PASS` override the address and password. A bad
`BOOT.bin` removes this route entirely - recovery is a card reader.

**Delete the Vivado project before any HDL or coefficient change.**
`build_hdl.tcl` reuses an existing `pluto.xpr` rather than re-running
`system_bd.tcl`, so a changed block design or `.coe` is *silently ignored* and
you flash the old bitstream:

```bash
rm -rf src/hdl/projects/pluto/pluto.{xpr,cache,gen,hw,ip_user_files,runs,sim,srcs,sdk}
```

**Four header pins carry the transmit sample's low nibble** (JP5 7/9/11/13, GPIO
978–981 when off). Enable: `echo 1 > /sys/bus/iio/devices/iio:deviceN/tx_sample_gpio_en`
on `cf-ad9361-dds-core-lpc` - resolve `N` by name, never assume the index. Verify
with `./devkit gpio-check` (no scope, no antenna). Pin-to-pin timing IS measured
(logic analyser: all four within 1.5 ns, every sample present up to 61.44 MSPS);
the pins LEAD the RF by a constant offset of roughly a microsecond that is still
designed-for, not measured - never write "the pin edge and its RF happen
together". **Never engage the FPGA ÷8 TX interpolator** (DAC core rate = AD
rate / 8): upstream's `tx_upack` read-enable ORs in channel 1's DAC valid, the
board runs 2R2T; measured, TX1 then emits nothing (spectrum = TX muted, within
1.2 dB). Always compare against a muted reference in absolute dBFS - a
normalised spectrum made that silence look like "a spray of components" once.
pyadi-iio and the MCP
use the AD9361's own FIR below 2.083 MSPS and never touch it. Three
ways to fool yourself: a pin read with `direction=out` returns what you *wrote*;
a pin's level alone never says who is driving it (stream two different nibbles);
and the nibble must be OR-ed into the samples **last**. Everything else -
balls, bank, pull-down, the capture strobe, measured cost - is in
[`docs/tx-gpio-bitmap.md`](../../../docs/tx-gpio-bitmap.md).

**`./devkit` is the entry point; `doctor` comes first.** `doctor · setup · sim ·
build · verify · flash · selftest · gpio-check · net · status`, all from the repo root
with arguments passed through. `./devkit doctor` checks Vivado/Vitis, host
packages, `gmp.h`, disk (~25 GB), the patch stamp and the board in a second -
every check is a failure that once cost an hour. `./devkit verify` before
flashing; `./devkit verify --board` after: it md5-compares the card against
`output/` and is the only thing that proves the board runs what you built. A
STALE verdict means the board is behind, not that the build is bad. `setup.sh`
is idempotent (it stamps `src/.devkit-patches-applied` with a digest of the
patch set), and `build_all.sh` refuses an unpatched tree and a Vivado project
older than its sources.

**Set TX attenuation AFTER a buffer starts, then read it back.** With patch
0005, starting a stream restores a *cached* attenuation when the chip looks
muted - so writing −89.75 dB before opening a buffer guarantees nothing during
it. The selftest, the GPIO checker and the MCP all write after
`write_samples()` and assert the read-back. The one exception is a one-shot
buffer, which has finished by then: set first, play out, then mute.

**Simulate before you synthesise.** `./sim/run_sim.sh` checks the custom HDL
against a golden model in about a second; a Vivado build is 20 minutes with
`--hdl-only` and 70 from cold, and synthesis cannot tell you the logic computes
the wrong thing. `--mutate` proves the testbench can still fail.

**Verify before you flash.** `./scripts/verify_output.sh` checks the five files,
that the bitstream is compressed (an uncompressed one overflows the FSBL's OCM
and BOOT.bin fails to boot with no message), and that timing is met. It prints
the DSP count and which coefficients are in use, so you can see your change
landed.

**When the radio misbehaves, check `/mnt/jffs2` first.** It is the one writable,
persistent partition, and `/mnt/jffs2/autorun.sh` runs at every boot. Scripts
there survive reflashing the kernel, device tree and bitstream, appear nowhere
in the firmware source, and can rewrite IIO attributes underneath an
application. Three kernel rebuilds were once spent chasing a "firmware bug" that
was a script on this partition. `sdr_selftest.py --ssh` lists what is there.

**Do not change the device tree without a strong reason.** It recompiles
byte-for-byte identical to the factory board's, which is a load-bearing
provenance claim; patch `0008` (`gpio-line-names`, so the sample-locked pins
resolve via `gpiofind sample_gpio0`) is the single deliberate exception, kept
as its own patch so dropping it restores the factory `.dtb`. Most things people
reach for the device tree for belong in `S21misc` or in the driver instead.

**A loopback without an attenuator destroys the receiver.** The RX input is
rated to about +2.5 dBm; plan for **about +19 dBm** flat out (an estimate, not
a meter reading). Fit at least 20 dB, and measure through exactly 20 dB: bigger
pads let the board's own TX->RX leak into the result. Details in `rf-safety.md`.

## Where things are

| | |
|---|---|
| `devkit` | the entry point - doctor, setup, sim, build, verify, flash, selftest, gpio-check, net, status |
| `firmware/scripts/doctor.sh` | can this machine build? run before the hour, not during |
| `tools/flash.sh` | flash the running board over the network, safely (`./devkit flash`) |
| `tools/net.sh` | DHCP or a static address, permanently; finds the board again afterwards (`./devkit net`) |
| `docs/networking.md` | where the address lives, the two names, and why the SD card's uEnv.txt is a decoy |
| `tools/tx-gpio-bitmap-check.py` | verify the sample-locked GPIO outputs on hardware (`./devkit gpio-check`) |
| `docs/tx-gpio-bitmap.md` | the sample-locked GPIO feature, end to end |
| `firmware/patches/` | what makes this board's firmware; `setup.sh` applies these |
| `firmware/patches/optional/` | worked examples, **not** applied by default (just the FM channelizer) |
| `firmware/src/` | upstream source, created by `setup.sh`, not committed |
| `firmware/output/` | the five SD-card files |
| `firmware/sim/` | Icarus Verilog testbenches for the custom HDL |
| `firmware/scripts/verify_output.sh` | pre-flash sanity check |
| `tools/selftest/` | is the board damaged? measures and says |
| `docs/block-design.md` | the stock Vivado project, IP by IP |
| `docs/measured-performance.md` | what one board actually does |

The patches, in order: `0001` fixes and a persistent serial; `0002` the device
tree; `0004` mute TX when no DMA stream; `0005` stop the unmute overwriting a
gain set before the stream. `optional/0003` is the FM channelizer.
`0006` routes each TX sample's low nibble - the bits the 12-bit DAC discards - to
JP5 pins 7/9/11/13 (balls V10/U9/U10/T9, bank 13, 3.3 V, pulled down);
`0007` adds the `tx_sample_gpio_en` sysfs attribute that enables it. Both edit
files 0004/0005 also touch (`cf_axi_dds.c`), so a new patch there must be
generated against a reconstructed pre-change file, never a plain `git diff`.
`0008` names those GPIO lines in the device tree. `0009` gives the bit-map
flag's clock-crossing constraint the `-from` it lacked. Without it, Vivado
dropped the line silently: `set_max_delay -datapath_only` needs both ends.
`0012` makes the USER LED follow the transmitter, so the board shows when it is
keyed. `0013` pins eth0 to the MAC U-Boot already uses and sends a hostname in
the DHCP request - without it the macb driver logs "invalid hw address, using
random" and picks a new MAC every boot, so a router sees a new device each time
and a DHCP reservation is impossible. It also makes the default hostname
`Fishball7020`, so the board answers to `Fishball7020.local` rather than
`pluto.local`.
To fix an applied patch, add a new one on top. Editing it would break every
existing tree: `setup.sh` cannot re-apply a patch over its earlier version.

## Typical work

**An HDL change** — edit, `./sim/run_sim.sh`, delete the Vivado project,
`./scripts/build_all.sh --hdl-only`, `./scripts/verify_output.sh`, flash
`BOOT.bin`, then `sdr_selftest.py --ssh`.

**A kernel change** — edit `src/linux/`, rebuild `uImage` alone (a few minutes;
the full `build_all.sh` is not needed), flash `uImage`, reboot. Then fold the
change into a numbered patch in `firmware/patches/` so a fresh clone gets it,
and add an assertion to `.github/workflows/verify-patches.yml`.

**Diagnosing the radio** — `sdr_selftest.py --ssh` first: read-only, never
transmits, and it reports supply rails, die temperatures, the AD9361 interface
eye, the internal digital loopback and the receiver. Add `--loopback --pad <dB>`
only with a cable and attenuator fitted.

**Before a release** — a clean-clone end-to-end build. This is not ceremony: the
v1.1 run found three defects in the build's own self-repair path, every one of
which would have stopped the next person building from a fresh clone.

## What a healthy board looks like

Measured on one unit, so treat as indicative rather than specification. Useful
for judging whether something is actually wrong.

| | |
|---|---|
| Gain slopes (TX attenuator, RX gain) | within **1.7% of 1.000 dB/dB** (56 slopes) |
| Image rejection, after a fresh TX quad calibration | **44–60 dBc** (31–54 as found), 5–7 dB worse into RX2, varies up to 10 dB run to run |
| Harmonics | 2nd **−64 to −80 dBc**, 3rd **−71 to −85 dBc** |
| Transmit power flat out | about **+19 dBm** - the self-test's capped estimate, never metered |
| TX mute depth | **at least 75 dB** - every reading hit the noise floor |
| Loop gain, 200 MHz – 1 GHz | ~**+20 dB** (flat to 2 dB), pad added back |
| Board's own TX->RX leak, as an equivalent pad | channel 0: 58–77 dB below 1 GHz, **33–51 dB** at 3–6 GHz; channel 1 ~10 dB weaker; crossed paths 10–35 dB weaker still |
| Supply rails | all six within **1.6%** of nominal |
| Digital interface eye | **157–181** of 256 delay positions pass |
| FPGA, stock build | 72/220 DSP48s, 11 896 LUTs, WNS **+0.205 ns** (with 0009; builds vary by a few hundredths - the worst path is in ADI's DMA) |

Two channels on one board differed by 1.5 dB in receive and 0.1–0.25 dB in
transmit, so some asymmetry is normal. Full data:
`docs/img/data/measured-performance.json`.
