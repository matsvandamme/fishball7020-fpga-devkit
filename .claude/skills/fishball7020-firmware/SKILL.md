---
name: fishball7020-firmware
description: Build, flash, measure and safely transmit with the Fishball7020 / PlutoSky SDR (Zynq XC7Z020 + AD9361, sold also as PlutoSky R1 and 7020-SDR). Use for FPGA and HDL changes, Vivado block-design work, kernel and device-tree patches, BOOT.bin and bitstreams, flashing, libiio/iiod and sysfs access, IQ capture, transmitting, RF loopback measurement, AD9361 gain tables and ENSM, TX muting, MATLAB/Simulink, and diagnosing a board that misbehaves. Encodes rules that are expensive to rediscover - never loop TX to RX without at least 20 dB of attenuation, set TX attenuation only after a buffer starts and mute before tearing it down, flash only via the SD partition and never DFU, delete the Vivado project before an HDL change, simulate before synthesising, and find out which of the two firmware targets (factory 5.15/Buildroot or modern 6.12/Debian) the board runs before believing anything about it.
license: GPL-2.0
compatibility: Board reached over its USB Ethernet gadget (default ip:192.168.2.1) or as fishball.local. U-Boot/kernel builds need an ARM Linux cross-compiler, `gcc-arm-linux-gnueabi` (preferred for the factory target; the only one that rebuilds the factory kernel byte for byte) or `arm-linux-gnueabihf-gcc` (both targets accept it; U-Boot is built with `-mfloat-abi=soft`); `./devkit container` provides gnueabi. Buildroot is needed only for the factory root filesystem. HDL builds need Vivado 2022.2 and nothing else from AMD (the FSBL builds from AMD's embeddedsw with gcc-arm-none-eabi, and setup builds bootgen from source), so a --xsa build needs no AMD tool at all; HDL simulation needs only iverilog; the host tools need Python 3.8+, plus sshpass for anything that reaches the board over ssh (flash, selftest --ssh, gpio-check, net, verify --board).
metadata:
  repository: fishball7020-fpga-devkit
  board: Fishball7020 / PlutoSky R1 (XC7Z020 + AD9361)
---

# Working on the Fishball7020 / PlutoSky

A reverse-engineered, buildable firmware for a board sold under several names:
Zynq XC7Z020 + AD9361, two transmit and two receive chains, and on the common
variant **a power amplifier (PA)**, which breaks the safety arithmetic most
Pluto advice assumes. `./devkit` is the one entry point (run from anywhere;
`./devkit --help` lists everything, `./devkit help <command>` one command,
`./devkit --version` which devkit and what is built); `./devkit doctor` comes first.

## First, find out what you are talking to

Two firmware targets share the bitstream, `BOOT.bin` and U-Boot, and differ in
everything above them. The userspaces turn a correct command into a silent
no-op, so check before trusting any rule below.

**Modern is the default target.** Add `--target factory` for Vivado, HDL or
bitstream work and for the factory flash's `--all`/`--rootfs-only`;
`DEVKIT_TARGET=factory` in the environment restores the old default.

```bash
# run on the board
grep ^ID= /etc/os-release   # ID=debian -> modern; Buildroot otherwise
uname -r                    # 6.12.0-... or 5.15.0
systemctl is-system-running 2>/dev/null || echo "no systemd - Buildroot"
```

```bash
# run from: the repo root
python3 tools/board_addr.py --check   # where the board is: 0 found, 3 ssh only (iiod down), 1 none. Never ping.
./devkit status                       # what is built, and what the board runs (read over IIOD)
```

On a Windows PC with nothing installed, `tools\board-info.cmd` prints the same
plus every IIO attribute value, read-only (`-DebugAttrs`, `-OutFile board.txt`);
ask a Windows user for its output rather than for `iio_info`.

All combinations occur: the 6.12 kernel boots the Buildroot ramdisk, Debian
boots on either kernel, and `fw_setenv rootfs_mode ramdisk` switches userspace
without a card reader. `board_addr.py --check` exits 3 (not 0) when only
the Debian ssh answers: the board is up and `iiod` is held back.

| | factory: `firmware/` (`--target factory`) | modern: `firmware-modern/` (the default) |
|---|---|---|
| Linux | 5.15.0, the vendor's fork | **6.12 LTS, Analog Devices' `main`** |
| root filesystem | Buildroot/busybox RAM disk | Debian 13 armhf with systemd, on ext4 (card p2) |
| set up by | `./devkit setup --target factory` | `./devkit setup` |
| device tree | flat; the factory board's, plus `0008` and `0011` | an overlay on ADI's `.dtsi` (`firmware-modern/dts/`) |
| defconfig | `zynq_pluto_defconfig` | `fishball_defconfig` |
| patches | `firmware/patches/`, 20 (+ `optional/0003`) | `firmware-modern/patches/`, 10, drivers only |
| FPGA input | Vivado, or `--xsa` | **always `--xsa`** |
| CI | `verify-patches.yml` | `verify-modern.yml`, `verify-rootfs.yml` |

Default to `firmware-modern/` for kernel and driver work; `firmware/` exists
because the byte-identical factory claim only means something against the
factory kernel. Debian has `pkill`, `apt`, OpenSSH and a writable root;
Buildroot has none of those. See
[`firmware-modern/debian/README.md`](../../../firmware-modern/debian/README.md),
[`docs/debian-root-reference.md`](../../../docs/debian-root-reference.md) and
[`docs/modern-kernel.md`](../../../docs/modern-kernel.md).

## References: load only what the task needs

| | |
|---|---|
| [`rf-safety.md`](references/rf-safety.md) | **Read before anything transmits.** Power budget, mute layers, the buffer-restore trap, stopping, the affirmation gate, board-side scripts |
| [`build-and-flash.md`](references/build-and-flash.md) | Command sequences for both targets, the Vivado trap, kernel-only builds, device trees, the patch catalogue, flashing, containers |
| [`talking-to-the-board.md`](references/talking-to-the-board.md) | libiio/IIOD, sysfs, debugfs, networking, refused attributes, the GPIO pins, MATLAB, what each shell lacks, the read-only Claude Code pane |
| [`measuring.md`](references/measuring.md) | The self-test, baselines, board versus cable, what a healthy board looks like |
| [`ad9361-gain-tables.md`](references/ad9361-gain-tables.md) | Why gain in dB is not gain in dB, and where the discontinuities are |
| [`debugging.md`](references/debugging.md) | Traps that are slow to diagnose: symptom, cause, fix |

## The rules, most dangerous first

### Transmitting

- **Never loop TX to RX without at least 20 dB of attenuation; measure through
  exactly 20 dB.** The RX input's absolute maximum is **+2.5 dBm**; plan for
  **about +19 dBm** flat out (an estimate, never metered). Bigger pads let the
  board's own TX->RX leak into the result.
- **Never transmit into an antenna without a licence, or at power into an
  unterminated port.** The board covers the FM broadcast band. If the MCP's
  safety gate refuses, stop and ask the operator; never reach for `force`.
- **Take the antenna off any port that must not radiate at power-on.** Every
  power-on emits a few ms at the TX LO on both ports, before any software runs.
- **Raise output only after `./devkit tx-guard affirm <0|1>`, and only after
  looking at that port.** Nothing on the board can detect what is attached.
  The affirmation is per channel and dies at reboot; muting is never gated.
- **Set TX attenuation AFTER the buffer starts, then read it back and rewrite
  until the chip agrees.** The kernel restores a cached gain when the hardware
  buffer actually starts, overwriting anything written before. (A one-shot
  buffer is the exception: set first, play out, mute.)
- **Mute (−89.75 dB) BEFORE tearing a buffer down, on every path.** The stop
  hook caches whatever it finds, so closing first hands your loud value to the
  next program: a bare enable on a muted board came up **28.25 dB** louder.
- **Check both attenuators right after every buffer enable**, failing on an
  unreadable value (`tools/tx_gate.py:assert_quiet_after_enable`). The four
  streaming tools (selftest, `sample_gpio_clock.py`,
  `modulation-gallery/board.py`, `tx-gpio-bitmap-check.py`) do; a new one must.
- **To stop: mute, kill the writer, wait until it has exited (`pgrep -x
  iio_writedev`), then read the hardware back**: both `hardwaregain`s, TX LO
  `powerdown`, and all eight DDS `scale`s. A killed writer's late exit mutes
  whatever the next one started.
- **Never assume a cyclic stream ends.** The 60 s `tx_cyclic_timeout_ms` bound
  is armed only on the modern Debian root; on factory Buildroot a killed
  cyclic stream runs until stopped. The starve watchdog (0015) fires once and
  exempts cyclic streams.
- **Never judge `hardwaregain` alone**: after a starve-mute the attenuator can
  read loud while only the powered-down TX LO keeps the port silent.
- **On the factory kernel, re-mute after any debugfs `initialize`** and read
  both attenuations back: it zeroes the cached attenuation, and 0 dB is full
  output (fixed only by `firmware-modern/patches/0019`). Never add a safety
  field to `ad9361_rf_phy_state`; `ad9361_clear_state()` memsets it.
- **Never engage the FPGA ÷8 TX interpolator.** On this 2R2T board TX1 then
  emits nothing. Use the AD9361's own FIR below 2.083 MSPS, as pyadi-iio does.
- **Board-side scripts trap `HUP` too, and every handler ends in `exit`.** A
  trapped signal resumes the script, which can open the next TX buffer with
  the operator gone. `QUIT` never fires under dash; `nohup` drops `HUP`.
- **A mute you did not read back is not a mute.** Never `2>/dev/null` a gain
  write; on disagreement say "TREAT THAT PORT AS LIVE" and act on it.

### Flashing and building

- **Never DFU. Flash with `./devkit flash`.** DFU has no `BOOT.bin` target and
  has bricked units here. The script backs up, md5-verifies before swapping,
  keeps `*.prev`, and waits for a real reboot. `--boot-only` (HDL),
  `--kernel-only` (driver), `--dtb-only` (device tree), `--all` (a factory
  release, `--target factory` only).
- **A bad `BOOT.bin` means a card reader.** Keep a known-good `output/`; it is
  the only recovery that does not need the board to boot.
- **Delete the Vivado project before any HDL or coefficient change.**
  `build_hdl.tcl` reuses `pluto.xpr`; `build_all.sh`'s mtime guard covers only
  the project's own sources, so other changes are silently ignored:
  `rm -rf firmware/src/hdl/projects/pluto/pluto.{xpr,cache,gen,hw,ip_user_files,runs,sim,srcs,sdk}`.
- **Simulate before you synthesise** (`./devkit sim`, about a second;
  `--mutate` proves the testbench can fail). Synthesis is 20-70 minutes and
  cannot tell you the logic is wrong.
- **Verify before you flash, and `--board` after.** `./devkit verify` reads
  BOOT.bin's partitions back out; `./devkit verify --target factory` checks
  five files, a compressed bitstream (an uncompressed one fails to boot
  silently) and timing. `verify --board` is the only proof the board runs your
  build and never changes `$?`: read the verdict, or (factory) `--require-board`.
- **Modern always takes `--xsa`; never substitute a release XSA silently.**
  Releases differ in FPGA design. Without Vivado use
  `firmware-modern/fetch-pinned-xsa.sh` and say which release's design it is.
- **Rebuild `firmware-modern/debian/rootfs.tar` after any `overlay/` change**;
  never `OVERLAY_OK=1` a card that transmits. The root is written with
  `write-card`, never flashed over the network.
- **Never build `zynq_pluto_defconfig` in `firmware-modern/`**: the result
  boots with no Ethernet, no SD card and no GPIO sysfs.
- **To fix an applied patch, add a new one; never edit it.** `setup.sh` cannot
  re-apply over an earlier version. Stacked files (`cf_axi_dds.c`) need a diff
  against a reconstructed pre-change copy.
- **Change the device tree only with a strong reason, and check it by building
  it**: `python3 firmware-modern/verify_dtb.py <built.dtb>` (16 checks,
  including the 89750 mdB TX default). Defaults belong in the driver or the
  rootfs init (`fishball-rf-quiesce.service` on Debian).
- **Do not edit a script a running build is executing**: bash reads it from a
  byte offset.

### Software that talks to the radio

- **Never accept MATLAB's offer to update the firmware**: that image is for a
  Zynq-7010 ADALM-Pluto. MATLAB sees one channel (`ChannelMapping` = 1 on
  `sdrrx` and `sdrtx`); RX2/TX2 go through `fishball.capture2` /
  `fishball.safeTransmit`. Simulink blocks need `Interpreted execution` and
  must not open the radio in `setupImpl`.
- **Resolve `iio:deviceN` and the GPIO base by name, never by index.** The
  numbers move between kernels; libgpiod tools are absent on Debian.
- **Check `iio_attr`'s exit status and never hide its errors.** `rf_port_select`
  (anything but `A_BALANCED`) and `filter_fir_en 1` without coefficients are
  refused with `EINVAL`, and a hidden refusal looks applied.
- **Rebuild the buffer after any configuration change.** A retune is not in the
  samples for ~35 frames, while the register already reads the new value.
- **Never hard-code the board's address**; use `tools/board_addr.py`.

### Diagnosing

- **Run `./devkit selftest --ssh` first.** It never transmits and reports
  rails, die temperatures, the interface eye, the digital loopback and the
  receiver. Add `--loopback --pad <dB>` only with a cable and pad fitted.
- **When the radio misbehaves, ask what else writes to it.** Buildroot:
  `/mnt/jffs2/autorun.sh`, which survives reflashing. Debian: systemd units
  (`systemctl list-units --failed`); `autorun.sh` is never run there.
- **No libiio but ssh works on Debian? `iiod` is held back by design**
  (`Requires=fishball-rf-quiesce`). Read the journal, fix, reboot, or
  `systemctl start iiod`; never start iiod by hand.
- **Ask "could this be the instrument?" before "is the board broken?"**
  Gain-table transitions, autoranging and an unaveraged FFT peak all mimic
  faults; see `ad9361-gain-tables.md` and `measuring.md`.
- **`pgrep -f` / `pkill -f` match the shell running them**; `pkill` does not
  exist on Buildroot. Wait on PIDs or `pgrep -x`.

## Where things are

| | |
|---|---|
| `devkit` | the entry point; `./devkit --help` |
| `firmware/` | factory target: `scripts/` (`setup.sh`, `build_all.sh`, `verify_output.sh`, `doctor.sh`, `check_bootbin.py`, `fetch_common.sh` with every pin), `patches/`, `sim/`, `output/`, `src/` (upstream, not committed) |
| `firmware-modern/` | modern target: `setup.sh`, `build_all.sh`, `patches/`, `dts/`, `config/`, `verify_dtb.py`, `baseline/`, `factory-xsa.pin`, `debian/` (overlay, `rootfs.tar`, `write-card.sh`) |
| `tools/flash.sh` | network flashing (`./devkit flash`) |
| `tools/make-sd-card.sh` | a bootable FACTORY card from scratch; refuses anything not a removable whole disk |
| `tools/board_addr.py` | the one address resolver every tool uses |
| `tools/tx-guard.sh`, `tools/tx_gate.py` | the transmit gate (`./devkit tx-guard`) and its host adapter |
| `tools/selftest/` | is the board damaged? (`./devkit selftest`) |
| `tools/tx-gpio-bitmap-check.py` | the sample-locked GPIO outputs (`./devkit gpio-check`) |
| `tools/net.sh`, `tools/clock-cal.py`, `tools/temps.py` | `./devkit net`, `clock`, `temps` |
| `tools/adsb/` | `./devkit adsb`: ADS-B aircraft from 1090 MHz, live (Qt window or `--text`), `--channel 1\|2`; receive only; `test_adsb.py` runs with no board |
| `tools/IDLE-CASES.md`, `IDLE-CASES.md` | the transmitter-idle cases behind the safety rules |
| `matlab/+fishball/`, `examples/matlab/` | MATLAB package and six examples; 03 transmits, 04 when given `TxChannel`, 06's QAM model transmits |
| `docs/` | user docs: [`transmitter-safety.md`](../../../docs/transmitter-safety.md), [`flashing.md`](../../../docs/flashing.md), [`building.md`](../../../docs/building.md), [`networking.md`](../../../docs/networking.md), [`tx-gpio-bitmap.md`](../../../docs/tx-gpio-bitmap.md), [`matlab.md`](../../../docs/matlab.md), [`block-design.md`](../../../docs/block-design.md), [`measured-performance.md`](../../../docs/measured-performance.md) |
