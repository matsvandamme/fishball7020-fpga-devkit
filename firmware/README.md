# The firmware: a pluto-fw v0.38 port (USB + Ethernet)

> **Looking for the build/flash workflow** (installing Vivado, opening the block
> diagram, adding HDL, building, flashing)? That lives in the
> [root README](../README.md). This page covers what is specific to *this*
> firmware: what upstream source it is built from, what was fixed to match the
> real board, and how closely the result has been verified against it.

This is the board's **factory-default firmware** — the one shipped on the SD
card, supporting both USB and Ethernet control, and the only firmware target in
this repo.

Upstream: [`Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR`](https://github.com/Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR),
a monolithic fork of ADI's `plutosdr-fw` retargeted from the stock ADALM-PLUTO's
XC7Z010-CLG225 to this board's XC7Z020-CLG400, with matching AD9361 pin
constraints.

## Verified against the real board

Every fix in `patches/` was derived by building this exact source and diffing
the result file-by-file against a genuine `SD Card Firmware/` dump from a real
unit:

- **`devicetree.dtb` builds byte-for-byte identical.**
- **`uEnv.txt`** is content-identical; the only difference is the *order*
  U-Boot's environment hash table dumps variables in, which cannot affect boot
  (variables are looked up by name).
- **The rootfs file list is identical.**
- **`uImage`** builds with an identical kernel `.config` and build banner but is
  not byte-identical: upstream's git history was squashed to a single commit
  dated *after* this board's firmware was built, so some kernel source has
  drifted — not recoverable from the public repo.
- **`BOOT.bin`** inherits the above plus normal Vivado place-and-route
  non-determinism.
- Remaining rootfs size differences (a random password salt, a build-path
  dependent GDB helper, a version-string format depending on submodules) are
  cosmetic.

**Confirmed on real hardware (2026-09-12):** a full `build_all.sh` output,
flashed and booted, initialises the AD9361 cleanly and reports
`fw_version: 95aad-dirty` / `hw_model: FISH Ball PlutoSDR Rev.A (Z7020-AD9361)`
over both the serial console and `iio_info` — see the root README's
[verification step](../README.md#7-verify-your-build-is-actually-running).

**Confirmed on real hardware (2026-09-14), current `patches/`:** the TX
safeguard holds across the full cycle — attenuated at boot, the user's gain
preserved while a stream runs, attenuated *and* synthesiser powered down after
it stops, and again on a second stream. Over a 50 dB attenuated loopback,
commanded and applied attenuation matched to 0.01 dB at every point including
0 dB, so full output is unaffected. The persistent serial survives a reboot
while the gadget MAC and interface name stay exactly as before, and SDRangel
opens and streams on both `usb:` and `ip:`.

## What's in `patches/`

### `0001-fishball7020-fixes.patch` — six real fixes

**`S23udc`: two hardcoded debug leftovers** — `fw_version=v0.38` and a literal
fake serial — restored to the dynamic runtime lookups the real firmware uses.

With one addition, because the dynamic lookup finds nothing here: it greps
`dmesg` for `SPI-NOR-UniqueID`, which the ADI kernel prints only for Micron
flash, and this board carries a Winbond W25Q128 — so `hw_serial` came out
empty. Anything identifying a Pluto by serial then cannot open it (SDRangel
lists `PlutoSDR0 TBD` and fails with `open serial TBD failed`). The SoC exposes
no unique hardware id at all — no device-tree `serial-number`, no DNA, no efuse
— so the script now mints 16 random bytes once and keeps them in
`/mnt/jffs2/hw_serial`, the board's persistent store.

The USB gadget MACs are `sha1($serial)`, and a changed MAC renames the host's
interface (`enx<mac>`) and breaks any static-IP setup bound to it. So the MACs
are deliberately still seeded from the *original* empty value: interface names
and addresses stay bit-identical, and only `hw_serial` and the USB descriptor
string change.

**The other fixes:** `buildroot/configs/zynq_pluto_defconfig` enables `iperf`
(present on the real board) and sets `CONFIG_BOOTDELAY=3`; the U-Boot configs
get default env values (`maxcpus=2`, `mode=1r1t`), a board-revision GPIO pin
number (`10`→`14`) and a hex-formatting fix (`0x0E00000`→`0xE00000`), all
matched against the real dump; and two `.hash` files are corrected where
Buildroot's git-archive repackaging of pinned commits produces a different tar
byte stream on modern git/tar (`fix_and_retry_buildroot.sh` handles this for
*any* future package hit by the same drift).

> Note: this board's device tree unconditionally sets `adi,2rx-2tx-mode-enable`,
> so the `mode` env var's 1r1t/2r2t switch is a no-op here — **2r2t is always
> active**.

### `0002-add-fishball-devicetree.patch`

Adds `zynq-pluto-sdr-fishball.dts`. None of the three stock device-tree
variants upstream (base/revb/revc) matched the real board — each had at least
one different node — so this file is the real board's own `devicetree.dtb`,
decompiled with `dtc` and confirmed to recompile byte-for-byte identical
through the actual kernel build path.

### `0004-mute-tx-when-no-dma-stream.patch`

Mutes the transmit chain whenever no TX DMA buffer is streaming.

The chip keeps that chain biased for as long as the ENSM is in FDD, which it is
from power-on, whether or not anything feeds the DAC. When a TX buffer is torn
down, `cf_axi_dds_buffer_stream.c` only reverts the baseband source to the
silent DDS: the mixer and output stage stay powered, emitting LO leakage and
dissipating power. Measured at boot: ENSM `fdd`, TX LO running, 10 dB of
attenuation.

The fix hooks the buffer lifecycle the driver already has — `preenable` unmutes,
`postdisable` mutes — and calls `ad9361_tx_mute()`, ADI's own exported helper,
present in the tree but called from nowhere. A small wrapper,
`ad9361_tx_lo_powerdown()`, also stops the TX synthesiser on mute: attenuation
is what removes output power, but without this a chain some application powered
up would idle with its oscillator running after that application closed. Order
is kept both ways — signal down before oscillator, oscillator up before signal.
The IIO core runs `postdisable` on teardown **even when the application crashed
or was killed**, which makes this a guarantee rather than best effort.

Two details worth knowing. `ad9361_tx_mute()` restores a *cached* attenuation,
and that cache is only trustworthy once a real mute has filled it — so the
driver never unmutes something it did not mute (`tx_muted`), and deliberately
does **not** mute at probe: the phy has not yet applied
`adi,tx-attenuation-mdB` at that point, the cache would capture the chip's
reset value of 89.75 dB, and every later unmute would restore it, leaving the
transmitter permanently silent (measured: a running stream sat at −89.75 dB
instead of the requested −20). Quieting the board before the first stream is
therefore `S21misc`'s job, attenuation only. And the phy is reached through the
DDS node's existing `clocks` phandle, so **no device tree change is needed**.

### `0005-dont-clobber-a-gain-set-before-streaming.patch`

Restoring the cached attenuation *unconditionally* was itself a trap: setting a
gain and then starting the stream is the obvious order, and the unmute would
overwrite it with the previous transmission's value. The unmute now restores
the cache only when nothing has been set since the mute, so both orders work.

### `0006-tx-sample-nibble-to-gpio.patch` and `0007-tx-sample-gpio-iio-attribute.patch`

Routes the four LSBs of each transmit sample — the bits the 12-bit DAC
discards — to four expansion-header pins, giving digital outputs locked to the
RF sample that carried them. `0006` is the HDL (a ~30-line module, the
block-design tap, the pin constraints); `0007` adds the
`tx_sample_gpio_en` IIO attribute so enabling it is a sysfs write rather than a
raw register poke through debugfs.

The pins are pulled down and the enable bit resets to 0, so the default
behaviour of the radio is unchanged and the four pins remain ordinary EMIO
GPIO. It costs +3 LUTs and +7 flip-flops, no DSPs, no block RAM, and does not
touch the device tree. See [docs/tx-gpio-bitmap.md](../docs/tx-gpio-bitmap.md).

### `optional/` — not applied by `setup.sh`

Worked examples that *change what the radio does* rather than fixing it, so
they live apart and `setup.sh` leaves them alone. Apply by hand:
`(cd src && git apply ../patches/optional/<name>.patch)`.

- **`0003-wbfm-channelizer.patch`** — a worked example of custom DSP in the
  AD9361 chain. Adds `ad_fs4_ddc.v` (an Fs/4 shifter) ahead of
  `rx_fir_decimator` and repoints that filter at narrow-band FM coefficients,
  turning RX channel 0 into a single-station channelizer. See
  [docs/wbfm-channelizer.md](../docs/wbfm-channelizer.md).
It does not touch the device tree, kernel or bootloader, so every provenance
claim above still holds; drop the patch to get the stock datapath back.

## Build system internals

`scripts/build_all.sh` deliberately does **not** call upstream's top-level
`Makefile` — it reimplements the steps so that Vivado's `settings64.sh`
(sourced for the HDL/FSBL/packaging steps only) never leaks its bundled
cross-toolchain `PATH` entries into the u-boot/kernel/buildroot steps, which
broke the kernel build the first time this was tried (see the root README's
[Troubleshooting](../README.md#troubleshooting)).

It does replicate one upstream step exactly: writing
`buildroot/board/pluto/VERSIONS` and running Buildroot's `legal-info` to
generate `msd/LICENSE.html`, which `post-build.sh` needs to finish the rootfs.
That file is not one of the five SD-card outputs, but its absence aborts the
Buildroot run before `rootfs.cpio.gz` is ever produced.

See `scripts/build_all.sh` itself for the exact current sequence — it is short
and directly readable.
