# The factory target's patches

Each file here is a change to the pinned upstream source. `./devkit setup --target factory`
([`../scripts/setup.sh`](../scripts/setup.sh)) applies every top-level `*.patch`
in filename order and stamps each one it applied, as a `sha256  filename` line,
in `src/.devkit-patches-applied`; a re-run applies only unstamped patches. An
applied patch cannot be changed in place, so a fix is always a new,
higher-numbered patch. `optional/` is never applied automatically.

Every patch file starts with a prose header;
`head -40 firmware/patches/0015-*.patch` is often the fastest answer to "why is
this here". Two numbers are missing on purpose: `0003` is now
[`optional/0003`](#0003-wbfm-channelizer), because it changes what the radio
does rather than fixing it, and `0010` was withdrawn because it had no effect on
any reachable call path ([`tools/IDLE-CASES.md`](../../tools/IDLE-CASES.md)
records the reasoning). Neither number is reused.

| patch | what it does | |
|---|---|---|
| [`0001`](#0001-fishball7020-fixes) | init-script and bootloader fixes | a persistent serial number, `iperf`, a boot delay |
| [`0002`](#0002-add-fishball-devicetree) | the board's device tree | the reconstruction everything else is compared against |
| [`0004`](#0004-mute-tx-when-no-dma-stream) | mute TX with no stream | **safety** |
| [`0005`](#0005-dont-clobber-a-gain-set-before-streaming) | keep a gain set before streaming | |
| [`0006`](#0006-tx-sample-nibble-to-gpio) | sample nibble to GPIO | four header pins locked to the TX samples |
| [`0007`](#0007-tx-sample-gpio-iio-attribute) | the switch for `0006` | `tx_sample_gpio_en` |
| [`0008`](#0008-name-the-sample-gpio-lines) | name those GPIO lines | so `gpiofind sample_gpio0` works |
| [`0009`](#0009-bitmap-flag-cdc-constraint-needs-from) | a timing constraint Vivado dropped | build fix for `0006` |
| [`0011`](#0011-probe-the-transmitter-at-maximum-attenuation) | probe at full attenuation | **safety** |
| [`0012`](#0012-user-led-follows-the-transmitter) | the USER LED follows TX | lit means RF can leave the port |
| [`0013`](#0013-stable-mac-and-dhcp-hostname) | a stable MAC and a DHCP hostname | makes a DHCP reservation possible |
| [`0014`](#0014-default-hostname-fishball) | default hostname `fishball` | |
| [`0015`](#0015-mute-the-transmitter-when-the-dac-starves) | mute when the DAC starves | **safety** |
| [`0016`](#0016-a-transmit-disable-latch-that-debugfs-cannot-clear) | a TX-disable latch | **safety** |
| [`0017`](#0017-count-transmit-dma-underflows) | count DMA underflows | |
| [`0018`](#0018-refuse-to-transmit-louder-when-the-die-is-hot) | a die-temperature ceiling | **safety**, off by default |
| [`0020`](#0020-host-tools-must-use-u-boots-own-libfdt) | u-boot host tools use u-boot's libfdt | build fix |
| [`0021`](#0021-filter-both-receive-channels-by-default) | filter both receive channels | `STOCK_RX_FILTER=1` opts out |
| [`0022`](#0022-give-a-large-first-block-time-to-arrive) | a large first transmit block gets time to arrive | transmitter safety |
| [`0023`](#0023-persistent-transmit-watchdog-settings) | `fw_setenv tx_starve_ms` / `tx_cyclic_bound` | transmitter safety |
| [`0024`](#0024-resume-the-transmitter-when-data-returns) | data arriving after a starve mute unmutes | fixes "TX works once per connection" |
| [`optional/0003`](#0003-wbfm-channelizer) | FM broadcast channelizer | **not** applied |

The five **safety** patches work together: `0004` mutes on the clean path,
`0015` covers a killed or stalled writer, `0011` makes power-on and debugfs
`initialize` land on silence, `0016` is the latch to engage when the network
is not trusted, and `0018` is the thermal ceiling.
[`docs/transmitter-safety.md`](../../docs/transmitter-safety.md) describes the
same protections from the operator's side.

Some terms used below: **TX** and **RX** are transmit and receive; the
**ENSM** is the AD9361's state machine that powers its transmit and receive
chains up and down; **attenuation** is how far the transmit output is turned
down, from 0 dB (full power) to −89.75 dB (the floor, "muted"); a **DMA
buffer** is the block of samples a program hands the kernel to send;
**debugfs** and **sysfs** are the kernel's file interfaces under
`/sys/kernel/debug` and `/sys`.

## 0001: fishball7020 fixes

Small fixes that make the rebuilt firmware match the real board.

**`S23udc`** had two hardcoded debug values, `fw_version=v0.38` and a literal
fake serial number. Both are restored to the runtime lookups the real firmware
uses. `fw_version` is read from `/opt/VERSIONS`.

The serial lookup greps `dmesg` for `SPI-NOR-UniqueID`, which the ADI kernel
prints only for Micron flash. This board carries a Winbond W25Q128, so
`hw_serial` would be empty, and anything that identifies a Pluto by serial
cannot open it (SDRangel lists `PlutoSDR0 TBD` and fails with
`open serial TBD failed`). The SoC exposes no unique hardware id (no
device-tree `serial-number`, no DNA, no efuse), so when the lookup is empty the
script mints 16 random bytes once and keeps them in `/mnt/jffs2/hw_serial`, the
board's persistent store.

The USB gadget MAC addresses are `sha1($serial)`. A changed MAC renames the
host's network interface where it is named by MAC (`enx<mac>`) and breaks any static-IP setup bound to
it, so the MACs are still seeded from the *original*, empty value. Interface
names and addresses on the host stay the same; only `hw_serial` and the USB
descriptor string change.

**The other changes:**

- `buildroot/configs/zynq_pluto_defconfig` enables `iperf`, which the real
  board has.
- U-Boot's `configs/zynq_pluto_defconfig` sets `CONFIG_BOOTDELAY=3`. This is
  the only window in which boot can be interrupted from the serial console, so
  recovery depends on it.
- U-Boot's `include/configs/zynq-common.h` gets the real board's default
  environment: `maxcpus=2`, `mode=1r1t`, a board-revision GPIO pin number
  (`10` → `14`) and a hex-formatting change (`0x0E00000` → `0xE00000`).

Three of those four `zynq-common.h` edits have no effect on how the board runs.
`0x0E00000` and `0xE00000` are the same number; the edit exists so the dumped
`uEnv.txt` matches the factory one byte for byte. `mode` is overridden because
the device tree sets `adi,2rx-2tx-mode-enable` unconditionally, so 2R2T (two
receive and two transmit channels) is always active. The GPIO change is inside
`qspiboot`, which an SD-card boot never reaches. The functional U-Boot changes
are therefore two values, `CONFIG_BOOTDELAY=3` and `maxcpus=2`, which is worth
knowing before replacing U-Boot.

Buildroot source tarballs whose `.hash` no longer matches on a modern git/tar
are not patched here: [`../scripts/fix_and_retry_buildroot.sh`](../scripts/fix_and_retry_buildroot.sh)
repairs that at build time, for any package.

## 0002: add fishball devicetree

Adds `linux/arch/arm/boot/dts/zynq-pluto-sdr-fishball.dts`. None of upstream's
three device-tree variants (base, revb, revc) matches the real board; each
differs in at least one node. This file is the real board's own
`devicetree.dtb`, decompiled with `dtc`, and it recompiles byte for byte to the
factory `.dtb` through the kernel build.

Two later patches change the compiled `.dtb`: [`0008`](#0008-name-the-sample-gpio-lines)
and [`0011`](#0011-probe-the-transmitter-at-maximum-attenuation). They are kept
separate from `0002` so that without them the `.dtb` is factory-identical.

## 0004: mute TX when no DMA stream

Mutes the transmit chain whenever no transmit DMA buffer is streaming.

**Why.** The AD9361 keeps its transmit chain biased for as long as the ENSM is
in FDD (full duplex) mode, which it is from power-on, whether or not anything
feeds the DAC. When a transmit buffer is torn down, upstream's
`cf_axi_dds_buffer_stream.c` only switches the baseband source back to the
silent DDS (the internal tone generator). The mixer and output stage stay
powered, emitting LO (local oscillator) leakage and dissipating power. On
upstream's firmware, at boot the ENSM is in `fdd`, the TX LO is running and
attenuation is 10 dB.

**What it changes.** The buffer lifecycle hooks the driver already has call
`ad9361_tx_mute()`, ADI's own exported helper, which upstream never calls:
`preenable` unmutes and `postdisable` mutes. A small wrapper,
`ad9361_tx_lo_powerdown()`, also stops the TX synthesiser on mute. Attenuation
removes the output power; stopping the synthesiser stops a chain some
application powered up from idling with its oscillator running after that
application closes. The order holds both ways: signal down before oscillator,
oscillator up before signal.

`ad9361_tx_mute()` restores a *cached* attenuation on unmute, and that cache is
only valid once a real mute has filled it. So the driver never unmutes
something it did not mute (`tx_muted`), and it does **not** mute at probe: at
that point the phy has not yet applied `adi,tx-attenuation-mdB`, the cache
would capture the chip's reset value of 89.75 dB, and every later unmute would
restore it, leaving the transmitter permanently silent.

Quieting the board before the first stream is therefore the job of
`tx_quiesce` in the Buildroot init script `S21misc`, which sets both channels
to −89.75 dB at boot (attenuation only). To skip it:

```sh
# run from: the board
fw_setenv tx_quiesce 0
```

The phy is reached through the DDS node's existing `clocks` phandle, so this
patch needs no device-tree change.

`0004`'s `postdisable` mute does not fire when a local writer is killed with
`kill -9`; [`0015`](#0015-mute-the-transmitter-when-the-dac-starves) covers
that case.

## 0005: don't clobber a gain set before streaming

Setting a gain and then starting the stream is the obvious order. Restoring
the cached attenuation unconditionally on unmute would overwrite that gain
with the value cached at the end of the previous transmission. With this patch
the unmute restores the cache only when nothing has been set since the mute
(`ad9361_tx_is_muted()`: both channels still at full attenuation). Both orders
work: set a gain then stream, and it is kept; stream having set nothing, and
the last gain comes back.

## 0006: tx sample nibble to GPIO

Routes the four least significant bits of each transmit sample (the bits the
12-bit DAC discards) to four expansion-header pins. The result is four digital
outputs locked to the RF sample that carried them.

The patch is the HDL: a module of about 30 lines (`tx_gpio_bitmap.v`), the
block-design tap in `system_bd.tcl`, and the pin constraints. The pins are
pulled down and the enable bit resets to 0, so by default the radio behaves as
before and the four pins are ordinary EMIO GPIO (GPIO routed through the FPGA
fabric). Resource use: 3 LUTs and 7 flip-flops, no DSPs, no block RAM. It does
not touch the device tree.

Full reference, including timing and authoring patterns:
[`docs/tx-gpio-bitmap.md`](../../docs/tx-gpio-bitmap.md). `./devkit gpio-check`
checks the feature on hardware.

## 0007: tx sample gpio iio attribute

Adds the `tx_sample_gpio_en` IIO attribute to the DDS device, so switching
`0006` on is a sysfs write rather than a raw register write through debugfs.

```sh
# run from: the board. The iio:deviceN index is not stable, so find it by name.
D=$(for d in /sys/bus/iio/devices/iio:device*; do
      [ "$(cat $d/name)" = cf-ad9361-dds-core-lpc ] && echo $d; done)
cat   $D/tx_sample_gpio_en                # 0 = GPIO (default), 1 = sample nibble
echo 1 > $D/tx_sample_gpio_en             # on
echo 0 > $D/tx_sample_gpio_en             # off
```

## 0008: name the sample GPIO lines

Adds `gpio-line-names` to the Zynq GPIO controller, so the four sample-locked
pins appear as `sample_gpio0` to `sample_gpio3`:

```sh
# run from: the board
gpiofind sample_gpio0        # -> gpiochip0 72
gpioget $(gpiofind sample_gpio0)
```

Without the names, a user has to compute `gpiochip base + 54 + 18`. The
controller has 54 MIO lines followed by 64 EMIO lines, and the property is
positional from line 0, hence the 72 empty placeholders before the four names.
The numeric path (GPIO 978–981 on this 5.15 kernel) still works.

This patch adds 152 bytes to `devicetree.dtb`. It is one of the two patches
that change the `.dtb` (the other is [`0011`](#0011-probe-the-transmitter-at-maximum-attenuation));
without both, the `.dtb` is byte-identical to the factory one. Do not drop
`0011` to get there: it stops the chip probing at 10 dB of attenuation.

## 0009: bitmap flag CDC constraint needs from

`0006`'s enable flag crosses from the AXI clock into the AD9361's clock (a
clock-domain crossing, CDC). `0006` bounds that crossing with
`set_max_delay -datapath_only` instead of timing it as a single-clock path, but
names only the end point. `-datapath_only` without `-from` is an error
(`Constraints 18-540`), and in an `.xdc` file that error drops the line without
a word in the build log, so the crossing was timed as an ordinary 2 ns path.
`0009` names both ends.

To check the limit is applied, open the routed design in Vivado and run:

```tcl
# run from: the Vivado Tcl console, routed design open
report_timing -to [get_cells -hier *flag_m_reg]
```

The requirement must read `(MaxDelay Path 4.000ns)`, not two clock edges. The
`verify-patches` CI workflow checks that every datapath-only delay in the
constraints has a `-from`. This is a separate patch rather than an edit to
`0006` because an applied patch cannot be changed in place.

## 0011: probe the transmitter at maximum attenuation

`adi,tx-attenuation-mdB` is what the driver writes to **both** transmit
attenuators in `ad9361_setup()`. Upstream sets `10000` (10 dB), which on a
board that reaches about +19 dBm is roughly **+9 dBm at the SMA**, against a
receive port rated +2.5 dBm and whatever is or is not attached to TX. This
patch sets it to `89750`: maximum attenuation.

That value applies in two places:

- **Every boot.** The driver probes, applies the property, and the transmitter
  stays there until `tx_quiesce` (see `0004`) writes −89.75 dB over it. The
  window is short, but it is the one moment an unterminated TX port is hot
  without anyone having asked for anything. (Separately, the AD9361's transmit
  calibration emits a short burst at every power-on, before any attenuation is
  applied, which no patch prevents; see
  [Every power-on transmits](../../docs/transmitter-safety.md#every-power-on-transmits-and-no-software-here-can-stop-it).)
- **debugfs `initialize`.**
  `echo 1 > /sys/kernel/debug/iio/iio:device0/initialize` re-runs
  `ad9361_setup()`, which re-applies the property to both channels. From a
  muted −89.75 dB, upstream's value is a raise of about 79.75 dB with no
  unmute, no buffer enable and nothing in the log. `0005` does not apply: this
  is not an `ad9361_tx_mute()` unmute and never touches the cached attenuation.

The consequence is that a transmitter never given a gain stays silent instead
of emitting at 10 dB. Every tool in this repo sets an attenuation and reads it
back after enabling the transmit buffer. The `verify-patches` CI workflow
asserts the constant `<0x15E96>` (89750) in the device tree source, because a
careless device-tree edit can silently revert it.

## 0012: user LED follows the transmitter

The USER LED runs the kernel's heartbeat trigger by default, which only says
the CPU is alive. This patch registers a `tx-active` LED trigger driven from
`ad9361_set_tx_atten()`, the single function every attenuation change passes
through (the kernel's own mute on DMA teardown and a plain sysfs write alike).
The LED is **lit whenever either transmit chain is out of full attenuation**
and dark when both sit at the −89.75 dB floor. TX1 alone, TX2 alone, both, or
a running stream each light it; returning to the floor puts it out.

It hooks the attenuator rather than the DMA buffer because attenuation can be
raised with no buffer open at all, and a stream-only indicator would then sit
dark while LO leakage leaves the SMA.

The LED is on PS MIO pin 0, which the FPGA fabric cannot reach, so this has to
be software ([`docs/user-led.md`](../../docs/user-led.md)). The trigger is
selected in `S21misc` rather than the device tree, so the `.dtb` stays
factory-identical. To keep the heartbeat:

```sh
# run from: the board
fw_setenv tx_led 0
```

## 0013: stable MAC and DHCP hostname

Two things a router needs to show this board as anything but a hex string.

**A stable MAC.** The device tree has no `local-mac-address`, so the `macb`
Ethernet driver logs `invalid hw address, using random` and `eth0` comes up
with a different locally-administered address on every boot. The router sees
a new device each time and a DHCP reservation cannot be made. U-Boot already
holds a MAC in its `ethaddr` variable and uses it for its own networking;
`eth0` is now set to the same one, so the board keeps one identity from
bootloader to Linux. If `ethaddr` is unset, nothing changes.

**A hostname in DHCP.** `udhcpc` ran with no hostname, so DHCP option 12 was
absent. busybox `ifupdown` turns a `hostname` line in the interface stanza into
`udhcpc -x hostname:`, and a `hwaddress` line into `ip link set addr` before
the interface comes up, so both fixes are two lines in the file `S40network`
already generates.

On the Debian root filesystem of [`firmware-modern/`](../../firmware-modern/README.md)
neither patch has any effect: `/etc/network/interfaces` is a fixed file there
and `hostnamectl` sets the name. `firmware-modern/debian/` implements both
behaviours itself, and `./devkit net` detects which root filesystem it is
talking to.

## 0014: default hostname fishball

Sets the default hostname to **`fishball`** (`0013` set `Fishball7020`), so the
board answers to `fishball.local` (mDNS). It is a separate patch because `0013`
was already applied to existing trees. The name is per board and changes
without a rebuild:

```sh
# run from: the repo root
./devkit net name <host>      # sets it (fw_setenv hostname) and finds the board again
```

Setting it to `pluto` restores compatibility with tooling that expects
`pluto.local`.

## 0015: mute the transmitter when the DAC starves

`0004` mutes from the buffer's `postdisable` hook. That hook does not always
run: after `kill -9` on a **local** process feeding a transmit buffer,
`buffer/enable` still reads `1`, the mute never fires, and the transmitter
stays live indefinitely ([`tools/IDLE-CASES.md`](../../tools/IDLE-CASES.md),
case B). A client that stalls without dying (case C) is not covered by `0004`
either.

This patch keys off a state instead of an event: *no DMA block has arrived for
N milliseconds*. One watchdog covers both cases:

- `dds_buffer_submit_block()` re-arms it on every block.
- `preenable` arms it, so a buffer enabled and never fed is covered too.
- `postdisable` cancels it, so the clean path is unchanged.

It is a workqueue rather than a timer because muting talks to the AD9361 over
SPI, and that sleeps. With the default timeout the mute lands about 0.27 s
after the last block.

```sh
# run from: the board. Milliseconds; 0 disables; values under 20 are refused.
cat /sys/bus/iio/devices/iio:deviceN/tx_starve_timeout_ms    # default 250
```

Values under 20 ms are refused because the board's network path delivers in
bursts with gaps, and a timeout inside a gap would mute a healthy stream and
look like a random dropout.

**Cyclic streams are exempt.** In a cyclic transmit the hardware repeats one
submitted block forever, so silence on the submission path is normal. They
have a separate backstop, `tx_cyclic_timeout_ms` in the same directory, whose
driver default is `0` (off). This target's Buildroot root filesystem leaves it
at `0`; the Debian root of `firmware-modern/` sets it to 60000 ms at boot (see
[`docs/transmitter-safety.md`](../../docs/transmitter-safety.md)).

## 0016: a transmit-disable latch that debugfs cannot clear

`iiod` listens on TCP port 30431 with **no authentication**, so anyone who can
reach the board can tune, receive and transmit. Two routes raise the output
without looking like a transmission: debugfs `initialize` re-applies the device
tree's attenuation to both channels, and `bist_tone` injects a tone at the
*transmit* data port, so it reaches the DAC and the amplifier with nothing
muting it.

This adds one latch, off by default:

```sh
# run from: the board
echo 1 > /sys/bus/iio/devices/iio:device0/tx_disable    # 0 releases it
```

Enforcement is inside `ad9361_set_tx_atten()`, the same choke point `0012`
uses. It **clamps rather than refuses**, because several callers treat a
failure there as fatal and would leave the chain half-configured, and because
the safe outcome is silence rather than an error. `bist_tone` mode 1 is refused
separately, since a digital injection never touches the attenuator.

The flag lives in `struct ad9361_rf_phy`, not in `ad9361_rf_phy_state` next to
`tx1_atten_cached`. `ad9361_clear_state()` does `memset(st, 0, sizeof(*st))`
on the state struct, and debugfs `initialize` calls it on the way to
`ad9361_setup()`, so a flag stored there would be cleared by exactly the
surface it defends against (the transmitter would return at −10 dB while
`tx_disable` still read `1`). The `verify-patches` CI workflow asserts where
the flag lives.

With the latch on:

| asked for | attenuation after | |
|---|---|---|
| boot default | −89.75 dB | `0011`'s device tree |
| latch on | −89.75 dB | |
| sysfs write −20 dB | −89.75 dB | refused to rise |
| debugfs `initialize` | −89.75 dB | both channels, latch still `1` |
| `bist_tone` mode 1 | refused | |
| `bist_tone` mode 2 | accepted | receive side, unaffected |
| latch off, set −30 dB | −30 dB | releases cleanly |

## 0017: count transmit DMA underflows

The DAC core reports underflow and overflow in `ADI_REG_VDMA_STATUS`. Upstream
writes the bits back to clear them at `preenable` and otherwise ignores them,
so the only way to know whether a transmission was clean was to receive it and
inspect the spectrum (as
[`docs/modulation-and-throughput.md`](../../docs/modulation-and-throughput.md)
does).

The bits are sticky and read-to-clear, so they answer *did it happen*, not
*how often*. The driver samples them once per submitted block and accumulates
counts:

```sh
# run from: the board. Write anything to either to zero it.
cat /sys/bus/iio/devices/iio:deviceN/tx_dma_underflow_count
cat /sys/bus/iio/devices/iio:deviceN/tx_dma_overflow_count
```

A short stall at stream start, for example in a stream fed through a pipe,
shows up as a small non-zero underflow count.

## 0018: refuse to transmit louder when the die is hot

The AD9361 reports its die temperature, and the PGA-102+ amplifier sits next
to it. This patch adds a ceiling:

```sh
# run from: the board. Millidegrees C; 0 disables (the default).
echo 60000 > /sys/bus/iio/devices/iio:device0/tx_temp_limit
```

Above that die temperature the driver **refuses to lower the attenuation**. It
is off by default because the right threshold depends on the enclosure and the
duty cycle. `./devkit temps` prints the setting and suggests a value.

The check is in `ad9361_set_tx_atten()`, the same choke point as `0016`, and
runs **only** when something asks to be louder than fully muted, so it adds one
AuxADC read per gain change and nothing per sample. **Muting is never
blocked**: the failure direction is silence. A refusal is logged:

```
die at <T> C is over the <limit> C transmit limit - staying muted
```

This also gives a **safe way to test transmit code with an antenna fitted**:
set the limit *below* the current die temperature, and every request to get
louder is refused and logged while muting still works. Confirm the gate is
active with an explicit gain write first; an empty log alone proves nothing.

## 0020: host tools must use u-boot's own libfdt

A build fix; it changes nothing about the radio.

U-Boot's `tools/Makefile` rewrites its own `-Iinclude` into
`-idirafter include`, which puts `include/` **after** the system directories.
On a host with libfdt's headers installed (`libfdt-dev` on Debian; on Arch they
come with `dtc`, which this repo requires), `<libfdt.h>` and `<libfdt_env.h>`
then resolve to `/usr/include`, disagree with the `libfdt_env.h` U-Boot
force-includes about `fdt32_t`/`fdt64_t`, and build stage [3/7] fails at
`tools/aisimage.o` with conflicting types. Reported as
[#8](https://github.com/matsvandamme/fishball7020-fpga-devkit/issues/8).

The fix is three forwarding headers in `lib/libfdt/`, a directory searched
**before** the system ones and reached only from `tools/Makefile`, so it cannot
affect a target build. Adding `-I$(srctree)/include` instead does not work: gcc
treats it as a duplicate of the `-idirafter` entry for the same directory,
drops it and keeps the later position.

On a host without those headers the `u-boot` binary is byte-identical with and
without this patch.

## 0021: filter both receive channels by default

Upstream routes receive channel 0 through `rx_fir_decimator` and sends channel 1
straight to `cpack`. `cpack` captures every enabled channel on channel 0's
valid signal, so when decimation is on, **channel 1 is sampled at one eighth
rate with no anti-alias filter of its own**: everything outside ±Fs/16 folds
onto it, and it is offset from channel 0 by the filter's group delay. That is
harmless on the 1R1T boards this block design also targets, which have no
channel 1; on this 2R2T board it makes the second receiver unusable whenever
the fabric decimator is on.

This patch feeds both channels through the filter: four paths instead of two,
with `cpack`'s inputs 2 and 3 taken from the filter outputs. Both channels share
one enable bit and one coefficient set, and therefore one group delay, so they
stay aligned. It changes only `system_bd.tcl`.

```sh
# run from: the repo root
STOCK_RX_FILTER=1 ./devkit build --target factory   # upstream's wiring: channel 0 filtered only
```

An empty `STOCK_RX_FILTER=` is treated as unset, not as "yes". The choice is
printed during build stage 1, and `./devkit verify --target factory` names which build it sees:

| build | DSP48s | Slice LUTs | `verify` prints |
|---|---|---|---|
| default (this patch) | 94 / 220 | 12 521 / 53 200 | `decimator on BOTH RX channels (default)` |
| `STOCK_RX_FILTER=1` | 72 / 220 | 11 896 / 53 200 | `decimator on RX channel 0 only` |

Full description, with spectra: [`docs/both-receive-channels.md`](../../docs/both-receive-channels.md).
Resource figures for both builds: [`docs/block-design.md`](../../docs/block-design.md).

## 0022: give a large first block time to arrive

`0015` arms the starve watchdog when a transmit buffer is enabled, and exempts a
cyclic stream once its block arrives. But libiio enables the buffer before it
uploads the data, so a large cyclic buffer was muted before it landed: 4.4 MB for
two channels at 40 MS/s, reported by Akil0515 and measured as
`no transmit data for 250 ms - muting the transmitter` after `push()`. The mute
also switches the DAC to the DDS, so it looked like a DMA underflow and the
sample-locked markers vanished too.

The first wait is now 250 ms plus the time to upload one block at 1 MB/s, capped
at 10 s; after the first block, `0015` applies unchanged. Measured on 6.12 (same
code here): two channels at 40, 50 and 60 MS/s run unmuted; a killed streaming
transmitter still mutes at 280 ms; a buffer enabled and never fed mutes at 315 ms
for a 64 KB block. Not compiled for 5.15 on the machine that wrote it (its GCC 15
cannot build the 5.15 plugins); the code is identical to the 6.12 patch.

## 0023: persistent transmit-watchdog settings

`S21misc` applies two U-Boot settings at every boot, only when set:
`tx_starve_ms` (the starve mute's timeout, `0` = off) and `tx_cyclic_bound` (how
long an unattended cyclic transmit may run). Each is separate, each prints what
the kernel accepted, and a value that is not a number is ignored with a message.
The Debian root's `fishball-rf-quiesce` reads the same names.

## 0024: resume the transmitter when data returns

`0015`'s starve mute was one-way, and because it also switches the DAC to the
DDS, nothing drained the DMA afterwards: a program that keeps one transmit buffer
open and stops feeding it between transmissions (SDR Console) could transmit once
per connection. A block arriving after a starve mute now re-selects the DMA
source and unmutes through the call a buffer enable makes, and the watchdog is
armed again. The full account and the measurements are in
[`firmware-modern/patches/README.md`](../../firmware-modern/patches/README.md#0024-resume-the-transmitter-when-data-returns).

The same code as the 6.12 patch. **Compiled for 5.15, not run**: both boards on
the bench when it was written run the 6.12 kernel.

## Optional patches (not applied by setup.sh)

Worked examples that *change what the radio does* rather than fixing it.
`setup.sh` lists them but does not apply them. Apply one by hand:

```sh
# run from: firmware/
(cd src && git apply ../patches/optional/<name>.patch)
```

### 0003: wbfm channelizer

A worked example of custom DSP in the AD9361 receive chain. It adds
`ad_fs4_ddc.v` (an Fs/4 frequency shifter) ahead of `rx_fir_decimator` and
points that filter at narrow-band FM coefficients, turning RX channel 0 into a
single-station channelizer. `./devkit verify --target factory` reports `96 / 220` DSP48s and
`rx_ddc (Fs/4 shifter) is wired in` for this build. See
[`docs/wbfm-channelizer.md`](../../docs/wbfm-channelizer.md).

Neither `0003` nor `0021` touches the device tree, kernel or bootloader, so the
provenance claims in [`../README.md`](../README.md#verified-against-the-real-board)
hold with either. They are undone differently: `0003` by not applying it,
`0021` with `STOCK_RX_FILTER=1`, which builds upstream's datapath.
