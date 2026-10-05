# Transmitting with this board without destroying it

The user-facing version is
[`docs/transmitter-safety.md`](../../../../docs/transmitter-safety.md); this file
is the agent's working copy, with the mechanisms spelled out.

## The power budget

**The receiver is the fragile end.** The AD9361's RX input is rated to
**+2.5 dBm** peak (AD9361 data sheet Rev. G, Table 11, Absolute Maximum
Ratings: "RF Inputs (Peak Power) 2.5 dBm"). Every decision here is sized
against that number.

The same table gives the thermal limits `./devkit temps` reports: maximum
junction temperature **110 °C**, operating range −40 to +85 °C. The −65 to
+150 °C row is *storage*, not an operating range.

The board is sold "with PA" and "without PA", and the vendor does not publish
the difference. The PA (power amplifier) is a Mini-Circuits **PGA-102+**, whose
gain falls with frequency:

| GHz | 0.05 | 0.8 | 2.0 | 3.0 | 4.0 | 6.0 |
|---|---|---|---|---|---|---|
| **Gain (dB)** | **17.7** | 15.9 | 14.0 | 12.5 | 11.5 | 10.4 |

P1dB is about +17.5 dBm. Plan for **about +19 dBm** flat out, roughly **16 dB
above what its own receive port survives**. That figure is the self-test's
estimate (scaled up from a quiet measurement, capped at the PA's compression
point), not a power-meter reading: never write "+19 dBm measured".

<sub>Canonical copy of this table: `docs/transmitter-safety.md`. Change it
there first, then mirror it here.</sub>

Sizing a loopback for a bare AD9361 (+7 dBm), as most Pluto advice does, is
wrong by 10-18 dB on this board. `./devkit selftest --loopback` reports which
variant a board is, by comparing measured loop gain against both models.

## Rules

- **Never loop TX to RX without an attenuator.** Fit at least 20 dB. More is
  equally safe, but for *measurement* use exactly 20 dB: the board's own
  TX->RX leak equals a 33-60 dB pad on channel 0 above 1 GHz, so a 50 dB loop
  there measures the leak as much as the cable (see `measuring.md`).
- **Do not transmit at power into an unterminated port.** Neither data sheet
  states a tolerance for an open, a short or high VSWR.
- **Never transmit into an antenna** without a licence for the frequency. This
  board covers the FM broadcast band, and with the PA it is not a trivial
  transmitter. The MCP server
  ([Fishball7020-mcp](https://github.com/matsvandamme/Fishball7020-mcp)) has a
  safety gate: its tone, IQ and waveform tools refuse anything outside the EU
  licence-free bands (433, 868, 2400, 5800 MHz) or over their power limit,
  unless the call gives an `override_reason` (checked by TypeSafe when
  `TYPESAFE_API_KEY` is set) or `force=true`. The gate is advice and `force`
  exists because the operator decides, so a refusal is a reason to stop and
  ask the operator, never one to reach for `force` yourself.
- **Every power-on transmits.** About a second after power is applied both
  TX1A and TX2A emit a ~4 ms burst at the TX LO: `ad9361_tx_quad_calib()` runs
  at `ad9361.c:5308`, before the device-tree attenuation is applied at
  `:5326`. No software here can stop it; take the antenna off any port that
  must not radiate when the board powers up.
- Start at maximum attenuation and work down, measuring as you go. Never start
  loud and back off.
- The self-test never transmits with less than **35 dB** of its own
  attenuation (`MIN_TX_ATTEN_DB`): worst case (full-scale drive, 18 dB of PA
  gain, no external pad) that is -10 dBm, 12.5 dB under the RX rating.
- **Never engage the FPGA ÷8 TX interpolator** (DAC core rate = AD rate / 8).
  Upstream's `tx_upack` read-enable ORs in channel 1's DAC valid on this 2R2T
  board, and TX1 then emits nothing (spectrum = TX muted, within 1.2 dB).
  pyadi-iio and the MCP use the AD9361's own FIR below 2.083 MSPS and never
  touch it.

## What protects the transmitter, layer by layer

| | covers | mechanism |
|---|---|---|
| the device tree | from `ad9361_setup()`'s attenuation write at `ad9361.c:5326` onward, **not** the power-on calibration before it | `adi,tx-attenuation-mdB = 89750` |
| the boot quiesce | from then until a DMA buffer starts | `S21misc`'s `tx_quiesce` (Buildroot) or `fishball-rf-quiesce.service` (Debian). On Debian **iiod `Requires=` it**: no proven mute, no SDR service (usb0 still comes up, without USB libiio) |
| `0004` / `0005` | while streaming, and when a buffer is torn down | mute on buffer close, unmute (restoring a cached gain) on buffer start |
| `0015` starve watchdog | a killed or stalled writer | mute after `tx_starve_timeout_ms` (250 ms) with no DMA block; the first block gets 250 ms + 1 ms per kB, capped at 10 s (`0022`) |
| `tx_cyclic_timeout_ms` | a cyclic stream that outlived its writer | **60 s on the modern Debian root only**; 0 (off) on Buildroot |
| `0016` `tx_disable` | debugfs `initialize` and `bist_tone` mode 1 | a latch debugfs cannot clear; off unless set |
| `0018` `tx_temp_limit` | getting louder when hot | off unless set |
| `firmware-modern/patches/0019` | a cached attenuation of zero | **modern only** |

The quiesce exists because the AD9361 comes up in ENSM `fdd` (the chip's state
machine, in full-duplex mode) with the TX chain biased and only 10 dB of
attenuation, so the port emits LO leakage from power-on with nothing in the
DMA. It sets **attenuation only, not the TX LO**: powering the synthesiser down
at boot would leave a later stream transmitting into a dead LO, silently.

Verify the quiesce on a running board. **The command differs by userspace**:

```bash
# run on the board - Buildroot
grep -c tx_quiesce /etc/init.d/S21misc
# run on the board - Debian (there is no /etc/init.d/S21misc)
systemctl is-active fishball-rf-quiesce     # -> active
journalctl -b -u fishball-rf-quiesce        # -> "both transmitters at -89.75 dB"
```

The knobs, all on the board (resolve `iio:deviceN` by its `name` file; these
are the usual indices, `device0` = `ad9361-phy`, `device2` =
`cf-ad9361-dds-core-lpc`):

```bash
# run on the board
cat /sys/bus/iio/devices/iio:device2/tx_starve_timeout_ms   # 250; 0 disables
cat /sys/bus/iio/devices/iio:device2/tx_cyclic_timeout_ms   # 60000 on Debian, 0 on Buildroot; 0 = off
# tools/chirp-view raises it to 3600000 while it runs and restores it on exit; after a
# kill -9 it stays raised until reboot (the board still mutes TX when the client drops):
echo 60000 > /sys/bus/iio/devices/iio:device2/tx_cyclic_timeout_ms
cat /sys/bus/iio/devices/iio:device0/tx_disable             # latch, 0 = off
cat /sys/bus/iio/devices/iio:device0/tx_temp_limit          # millidegC, 0 = off
```

> **On systemd, a unit with a dependency cycle does not fail: it disappears.**
> `DefaultDependencies=no` with `Before=sysinit.target` *and*
> `WantedBy=sysinit.target` is a cycle, and systemd breaks it by deleting the
> job (`Job fishball-rf-quiesce.service/start deleted to break ordering
> cycle`). The board then boots without the safety unit and reports no
> failure; `systemctl is-active` says `inactive`, not `failed`. Order a safety
> unit with ordinary dependencies (`After=sysinit.target`,
> `Before=iiod.service`, `WantedBy=multi-user.target`), and check
> `journalctl -b -u` for its read-back line rather than trusting that it ran.

### `postdisable` is not a guarantee; `0015` mutes on state

Kill a transmitting process *on the board* and `buffer/enable` stays `1`, the
buffer-close hook never runs, and the transmitter stays live: through a 20 dB
loop the port read 12.6 dB hotter than muted with the process gone. Do not
repeat the old claim (once in `patches/0004`) that teardown on file close
always mutes. Cases: [`tools/IDLE-CASES.md`](../../../../tools/IDLE-CASES.md).

`patches/0015` mutes on **state** rather than on an event: no DMA block for
`tx_starve_timeout_ms` and the transmitter is attenuated, about 0.26-0.27 s
from the kill on both kernels. Events can be missed; "the DAC is not being fed"
cannot.

**Cyclic transmits are exempt from 0015**: the hardware repeats one buffer
forever, and outliving the caller is what `CYCLIC 1` is for, so a kill looks
exactly like a normal return. `tx_cyclic_timeout_ms` bounds that instead. The
**driver** default is `0` (off). **The modern target's Debian root arms it at
60 s on every boot** from `fishball-rf-quiesce`, ordered before `iiod`. **The
factory Buildroot ramdisk does not**, so a killed cyclic stream there runs
until something stops it. Change it with
`fw_setenv tx_cyclic_bound <ms>`, or `0` for no bound, on both roots (Buildroot
since `0023`); it is separate from `tx_quiesce` so that turning off the boot
mute does not also unbound every cyclic transmit. The starve timeout persists
the same way: `fw_setenv tx_starve_ms <ms>` (20 ms minimum, `0` = off). Every streaming tool in the devkit transmits cyclically, so a
killed cyclic stream is the ordinary abnormal ending on this board.

**The starve watchdog fires once and does not re-arm.** Once `0015` has fired,
the driver believes the transmitter is muted; data resuming does not change
that, only a fresh buffer enable does. So after a starve-mute a gain write
raises the attenuator and *nothing* re-mutes it:

```
atten0=-30.000000  LO_pd=1  buf=1     (gain written AFTER the watchdog fired)
```

What keeps the port silent there is the powered-down TX LO. Never read
`hardwaregain` alone and conclude anything: read
`out_altvoltage1_TX_LO_powerdown` with it.

**Both mute mechanisms are needed.** At 900 MHz, with the receive LO offset by
1 MHz so leakage is distinguishable from the receiver's own DC offset: muting
the attenuators alone leaves residual LO **26 dB above the noise floor**;
powering the synthesiser down as well takes it a further **19.9 dB**, to
within 6 dB of the floor. These are ratios and are board properties; do not
convert them to dBm at the port (no receive gain recorded, no positive
control). Measuring at DC will not show this, because RX LO = TX LO puts the
leakage exactly where the receiver's own offset lives.

## Opening a buffer is not a neutral act

`patches/0004` mutes the transmitter whenever no DMA buffer is streaming and
unmutes when one starts. `patches/0005` makes that unmute restore a *cached*
attenuation when the chip looks muted, and the stop hook snapshots whatever
attenuation it finds into that cache *before* applying maximum.

| What you do | What you get |
|---|---|
| set a gain, then start the stream | the gain you set, unless the restore lands after your write (rule 2) |
| start the stream having set nothing | the last gain any stream used |
| stop the stream | maximum attenuation, TX synthesiser down |

On a board that reads fully muted, with no debugfs involved:

```
before anything                 atten0=-89.750000  LO_pd=1  buf=0
after a bare buffer enable      atten0=-61.500000  LO_pd=0  buf=1
```

A **28.25 dB raise by the kernel**, with nothing having asked for gain and no
affirmation on record, bounded only by the loudest gain used since boot. Hence
four rules:

1. **Set TX attenuation AFTER a buffer starts, then read it back.** Writing
   −89.75 dB before opening a buffer guarantees nothing during it. The one
   exception is a one-shot buffer, which has finished by then: set first, play
   out, then mute.
2. **Write, read back, and rewrite until the chip agrees.** Writing once right
   after the first frame is still too early: the restore happens when the
   hardware buffer actually starts, not when you hand the frame to the FIFO
   (`iio_writedev` may not have consumed it). Asked for −20.00 dB, a reused
   transmitter can report −30.00, the PREVIOUS stream's value.
3. **Mute BEFORE you tear the buffer down, never after, on every path
   including the error paths.** Closing first hands the cache your loud value
   for the next program, which gets it on a bare enable with no affirmation.
   Happy paths usually get this right; abort paths are where it is missed.
   `tools/tx-guard.sh reap` follows the same ordering.
4. **Check both attenuators immediately after every buffer enable**, and fail
   on an unreadable value rather than assuming quiet, because the enable
   itself can raise one. `tools/tx_gate.py:assert_quiet_after_enable` does it.

**Five tools in the devkit stream**, and all five follow these rules: the
selftest (the one CI runs), `tools/sample_gpio_clock.py`,
`tools/modulation-gallery/board.py`, `tools/tx-gpio-bitmap-check.py` (which
only ever writes −89.75 and still opens a buffer, so it IS a transmit path) and
the automation server's `Transmit`/`TransmitCapture` (which presets both
attenuators to −89.5, never the floor, so the enable has nothing to restore).
Any new streaming tool, including the MCP's `tx_disable` path, must do the
same. A grep for loud attenuation writes will not find a tool that raises TX
this way.

A script polling `buffer/enable` to re-apply a gain is a workaround for the
pre-0005 behaviour: delete it, it silently overrides the application. Look in
`/mnt/jffs2/autorun.sh` (Buildroot only; Debian does not run it).

### debugfs `initialize` and the cache (factory kernel)

On `firmware/` (and on `firmware-modern/` before `0019`) the cache lives in
`ad9361_rf_phy_state`, which `ad9361_clear_state()` memsets, and zero mdB is
full output:

```bash
# run on the board - DO NOT do this with an antenna fitted on an
# unpatched kernel. Result: TX2 at 0.000000 dB.
echo 1 > /sys/kernel/debug/iio/iio:device0/initialize
# ...then anything that opens a transmit buffer...
```

`firmware-modern/patches/0019` moves the cache out of that struct and seeds it
at probe with maximum attenuation, so "nothing cached yet" means muted. **The
same code is still on `firmware/`**: there, treat a debugfs `initialize` as
requiring a re-mute afterwards, and read both attenuations back. The cache is
the third safety field moved out of `ad9361_rf_phy_state`, after `0016`'s
latch and `0018`'s limit: **never add a safety field to that struct**.

## Stopping a transmission

A one-shot buffer finishes by itself. A **cyclic** one does not: the DMA keeps
feeding the DAC from the same buffer with no further help from the writer.

1. **Mute first, then kill the writer** (`pkill -x iio_writedev` on the host
   or on Debian; `ps` + `kill <pid>` on Buildroot). Killing first leaves a
   window where the DMA is still running and nothing is holding the
   attenuation.
2. **Wait for the killed writer to be gone before muting again or starting
   another.** When `iio_writedev` finally exits, the kernel's close hook mutes
   the transmitter; if a NEW writer has meanwhile set its gain, the radio sits
   at −89.75 dB with the gain read-back already passed, so every second
   transmitter in a sweep comes up dead. A trap that mutes on SIGTERM can also
   read back −89.750000 dB while `iio_writedev` is still running. Wait with
   `pgrep -x iio_writedev` (the process NAME, so unlike `pgrep -f` it cannot
   match the shell running it). On Buildroot there is no `pkill`/`pgrep`; see
   `talking-to-the-board.md`.
3. **Read the hardware back, not the log.** A script printing "muting" proves
   only that the line executed:

```bash
# run on your HOST
U=ip:192.168.2.1
for c in 0 1; do iio_attr -u $U -c -o ad9361-phy voltage$c hardwaregain; done
iio_attr -u $U -c -o ad9361-phy altvoltage1 powerdown
pgrep -x iio_writedev
for t in 0 1 2 3 4 5 6 7; do
  iio_attr -u $U -c -o cf-ad9361-dds-core-lpc altvoltage$t scale
done
```

Never skip the DDS sweep: a leftover DDS (the FPGA's built-in tone generator)
transmits **independently of the DMA path**, so a muted attenuator and a dead
writer say nothing about it. All eight scales must read `0.000000`.

## Board-side shell scripts that touch TX

**A mute that swallows its errors is worse than no mute.** Write, read back,
compare, and say so when the read-back disagrees:

```sh
# run on: the board
mute_both() {
  _bad=0
  for _c in 0 1; do
    echo -89.75 > "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null || { _bad=1; continue; }
    case "$(cat "$PHY/out_voltage${_c}_hardwaregain")" in
      -89.7*) : ;;
      *) echo "MUTE DID NOT LAND on ch$_c - TREAT THAT PORT AS LIVE" >&2; _bad=1 ;;
    esac
  done
  return $_bad
}
```

Then **act on the return value**: a helper that reports failure to callers
that discard it is the same silent failure one level up.

**Trap `HUP` as well as `EXIT INT TERM`.** A board-side script is almost always
run over ssh, and a dropped session delivers `SIGHUP`; a shell that traps only
the other three dies untrapped and whatever it held up stays up. For a DDS
tone (as in `tools/tx-idle-cases/dds-tone.sh`) that means a tone the firmware
cannot stop: it opens no DMA buffer, so neither 0004 nor 0015 can reach it.
Install **one** handler per signal: `trap` replaces, it does not append.

**A trapped signal does NOT terminate the shell: the handler must `exit`.**
This matters most; adding `HUP` without it is worse than not trapping at all.
The handler runs and execution **resumes at the next statement**; in a
multi-case script the next case then opens a TX buffer, and the cache restore
(which a revoke *arms* by leaving both attenuators at exactly −89.75) puts the
port back at the previous stream's gain with the operator gone. Shape it like
this:

```sh
# run on: the board
trap '_quiet_on_exit' EXIT
trap '_quiet_on_exit; trap - EXIT; exit 130' INT
trap '_quiet_on_exit; trap - EXIT; exit 143' TERM HUP PIPE QUIT
```

and mask the signals as the handler's first statement (`trap '' INT TERM HUP
PIPE QUIT`), because with `PIPE` trapped on a dead stdout every remaining
`echo` re-enters the handler.

- **`QUIT` does not fire under dash** (Debian's `/bin/sh`): dash accepts and
  lists the trap, then dies without running it. `INT` does fire, but over a
  plain `ssh host "sh script"` with no pty, Ctrl-C never reaches the board:
  the session drops and the script gets `HUP` and `PIPE` instead.
- **`nohup` silently drops the `HUP` arm.** POSIX shells do not install a trap
  for a signal ignored on entry, so a script launched `nohup … &` has no HUP
  handler however it was written. Run it in the foreground, or follow it with
  an explicit `off`.
- Killing processes by pattern: see `debugging.md` (`pkill -f` matches the
  shell issuing it).

## The affirmation gate, and what it is not

Antenna presence on TX cannot be measured on this board (no coupler, no
detector, on either port). `tools/tx-guard.sh` records what a person says is on
a port, per channel (0 is TX1A, 1 is TX2A, two separate SMAs), and refuses to
raise that channel without it; the record lives in the board's `/tmp`, so a
reboot withdraws it. `tools/tx_gate.py` is the host-side adapter and shells out
to `./devkit tx-guard`, so there is one rule and one store.

```bash
# run from: the repo root
./devkit tx-guard affirm 0        # only after LOOKING at TX1A
./devkit tx-guard check 0         # exit 0 affirmed, 3 not - for your own tools
./devkit tx-guard status          # affirmations, attenuation, buffer state
./devkit tx-guard revoke both     # withdraw, and force maximum attenuation
./devkit tx-guard reap            # disable a TX buffer left enabled with no owner
```

Without bash (Windows), `python tools/tx_gate.py <same command>` pushes the same
`tx-guard.sh` over ssh with paramiko and returns the same exit codes; any tool
importing `tx_gate` takes that route by itself there (`FISHBALL_TX_GATE=python`
forces it elsewhere). An unreachable board is exit 4, never permission.

Three host tools ask it before commanding output: `./devkit selftest
--loopback` (exit 1 when refused, having raised nothing),
`tools/sample_gpio_clock.py` and `tools/modulation-gallery/board.py`.
`./devkit selftest` without `--loopback` is untouched, and
`tools/tx-gpio-bitmap-check.py` never commands output, so it is checked rather
than gated. **Quiet is never gated**: muting has to work when ssh is down.
`--pad` on the command line is not an affirmation: it says what you believed
was in the path; the affirmation says you looked.

Do not say a refused run "raised nothing" without checking: an unaffirmed
`--loopback` run still enables a TX buffer for the *internal digital* loopback
test, by design, which is why every enable is followed by an attenuator read.
The defensible claim is that **no path commands output without an affirmation,
and the paths that enable a buffer without one are verified not to have raised
the attenuators**.

The gate raises the floor; it is not a lock. A direct write to
`out_voltageN_hardwaregain` bypasses it, and the affirmation is an ordinary
file in world-writable tmpfs that any process can forge. `0016`'s `tx_disable`
latch inside `ad9361_set_tx_atten()` is the one thing *debugfs* cannot clear
(it blocks `initialize`, which re-applies the device-tree attenuation, and
`bist_tone` mode 1, which injects at the transmit port and goes out through
the PA; both reachable over port 30431 with no authentication). It reads **0**
unless someone sets it, and root can clear it. The latch lives in
`struct ad9361_rf_phy`, not `ad9361_rf_phy_state`, because `initialize` calls
`ad9361_clear_state()`. Set it when the board should not transmit at all:

```bash
# run on the board
echo 1 > /sys/bus/iio/devices/iio:device0/tx_disable
```

To test this class of bug safely with an antenna connected, first arm the
thermal gate below the die temperature:

```bash
# run on the board
echo 1000 > /sys/bus/iio/devices/iio:device0/tx_temp_limit    # 1 C
```

Every request to get *louder* is then refused and logged, while muting still
works, so the question becomes "did the driver ask?" rather than "what came out
of the port?". `dmesg` answers it:

    ad9361 spi0.0: die at 40.351 C is over the 1.000 C transmit limit - staying muted

No line means nothing asked to get louder. Confirm the gate is live first by
making an explicit `-60 dB` write and seeing it refused, or a silent log proves
nothing.

## Levels and gain, briefly

Received levels are dBFS against a **12-bit** converter (full scale ±2047).
Transmit is **16-bit**: scaling transmit samples to ±2047 emits 24 dB low.
RX gain is an index with a dB-shaped name: only 38-51 dB is free of gain-table
transitions in every band, and the legal range moves with frequency (`[-1, 73]`
below 1.3 GHz, `[-3, 71]` to 4 GHz, `[-10, 62]` above; outside it, `-22
EINVAL`). See `ad9361-gain-tables.md`.

## Cyclic buffers and triggers (docs/cyclic-buffers.md)

- **No trigger IN exists in the shipped FPGA design.** axi_ad9361's `dac_sync_in`
  is unconnected in system_bd.tcl and the DDS core reports no external sync, so
  `sync_start_enable_available` is just `arm`, and writing `arm` only re-syncs
  the DDS internally (cf_axi_dds.c, ext_sync_avail false). Never promise a
  hardware-triggered TX/RX start; it needs an HDL change.
- **Trigger OUT is exact:** a marker bit in the low nibble of the cyclic buffer
  pulses a JP5 pin once per repetition (measured 0 errors, 2R2T, 4.46 MB, 40 and
  60 MS/s). The pin-to-RF offset (~1 us) is still unmeasured.
- `iio_writedev -c -b <file samples>` holds a cyclic buffer until killed; set
  the attenuation after it starts, mute before killing it.
- **One-shot on a trigger: `tools/tx-burst`** (runs on the board, C, libiio
  local). Non-cyclic buffer prepared once; each UDP datagram or GPIO rising edge
  = memcpy + iio_buffer_push = the burst plays once, then the DAC outputs zeros.
  Measured: exactly one burst per trigger at exact length (Saleae on markers),
  one DMA underflow per burst, queued 90-200 us after the trigger. It turns the
  starve watchdog OFF while running (the DAC starves between bursts by design)
  and restores it. A GPIO trigger (-g 72..75) and markers (-m) cannot be used
  together: the four free pins are the marker pins.
