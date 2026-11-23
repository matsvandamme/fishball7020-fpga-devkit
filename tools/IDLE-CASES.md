# TX idle: stream-termination test results (factory userspace)

The record of how a transmit stream can end on the factory target's Buildroot
userspace, and what the transmitter did next: before and after patch `0015`, plus
the kernel attenuation cache, the debugfs routes to a live transmitter, and the
source argument behind the withdrawn patch `0010`. These are the cases the
factory patch catalogue cites by letter
([`firmware/patches/README.md`](../firmware/patches/README.md)).

> **A second record exists: [`../IDLE-CASES.md`](../IDLE-CASES.md) at the repo
> root.** It covers the modern target (Debian, Linux 6.12): six termination paths
> each with a read taken *during* the stream, a black-holed network drop
> distinguished from a killed client, the affirmation gate, and a post-enable check
> on all four tools that open a transmit buffer. It does not repeat what is here:
> cyclic cases E and F on this userspace, the debugfs routes, and the kernel source
> argument. Where the two differ on a number, the root file is the later
> measurement.

**Method.** Each case sets a known "user" attenuation, starts a TX DMA buffer,
terminates it in one specific way, and reads the attenuation back from
`/sys/bus/iio/devices/iio:device0/out_voltage{0,1}_hardwaregain` on the board,
rather than trusting that the terminating call returned. Expected after
termination: **−89.75 dB** (maximum attenuation), which
`cf_axi_dds_tx_rf_mute()` applies from the buffer's `postdisable` hook.

**Conditions.** Board at 192.168.2.1, firmware `95aad-dirty`, TX1 → RX1 loop with
**20 dB** of external attenuation (the goal text says 50 dB; see
[Loop attenuation](#loop-attenuation-against-the-goal-text)).

**Source citations name functions, not line numbers**, because patches `0016` and
`0018` insert code above earlier cited lines and a line number then points
somewhere unrelated. The exceptions are `ad9361_conv.c:98`, `:120`, `:604` and
`:641`: no patch in this repo touches that file, and the four call sites are what
the argument is about.

## Before the fix: cases A to D

| # | termination path | how induced | attenuation read back | `buffer/enable` | RX saw | verdict |
|---|---|---|---|---|---|---|
| A | normal close | `iio_writedev -s 32768` on board, runs to completion, exit 0 | **−89.75 dB** | 0 | not measured | **PASS** (on read-back) |
| B | process kill, local | `iio_writedev -s 0` on board, `kill -9` mid-stream | **−25 dB (unchanged)** | **1 (stuck)** | **LO leakage −46.7 dBFS vs −59.3 muted** | **FAIL** |
| C | underflow, client alive | network client fed 64 KB then stalled 18 s | **−25 dB (unchanged)** | 1 | not measured | **GAP** |
| D | network client killed | `iio_writedev -u ip:192.168.2.1`, `kill -9` on the PC side | **−89.75 dB** | 0 | not measured | **PASS** (on read-back; iiod's cleanup, not a kernel guarantee) |

### Case B: a killed local process leaves the transmitter live

Killing a *local* TX process left the transmitter live indefinitely. Both
`iio_writedev` and its feeding `cat` were confirmed gone, yet `buffer/enable`
stayed `1`, so the IIO core never ran `postdisable` and the mute never fired. On
the receiver through the loop, LO leakage at 2.4 GHz rose to **−46.7 dBFS**
against **−59.3 dBFS** in the muted baseline: 12.6 dB hotter, with no process
alive and no operator action.

This contradicts the source comment `0004-mute-tx-when-no-dma-stream.patch` adds:

> The IIO core calls postdisable on buffer teardown even when the application
> crashed or was killed, which is what makes this a real guarantee rather than
> best effort.

It does not hold on **any** path: the IIO core never disables a buffer on file
close, and case D is clean only because iiod explicitly tidies up after a
disconnected client. `0015` replaces that comment with a corrected one.

The mute machinery itself is correct: writing `0` to `buffer/enable` by hand
immediately drove attenuation to −89.75 dB. The gap is only that nothing performs
that write when the owner dies.

### Case C: idle but not silent

A buffer that is open but starved keeps the transmitter unmuted. That is
defensible as driver behaviour, since the application still owns the stream, but
it fails the goal's definition of TX idle (no data flowing through the DMAs), so
it is recorded as a gap rather than a pass.

## Loop attenuation against the goal text

The goal specifies a 50 dB TX1 → RX1 loop; the loop attached was **20 dB**. The
margin was recomputed before transmitting: with the board's ~+19 dBm maximum and a
receive port rated +2.5 dBm ([`docs/transmitter-safety.md`](../docs/transmitter-safety.md)),
20 dB of loop gives 19 − 20 = −1 dBm at the receive port, about 3.5 dB under the
rating at full output. That is an arithmetic bound from two documented numbers
(the +19 dBm also appears in the fishball-sdr MCP server's documentation), not a
measurement of this cable.

Tests here ran at −60 dB to −25 dB attenuation, keeping at least 28 dB of margin.
One later check of the near-full-output warning set −5 dB briefly with no stream
running (LO leakage only, ~8.5 dB margin), which exceeded the −20 dB cap stated
for that session.

## Userspace mitigations, and what they do not cover

`tools/tx-guard.sh` addresses part of the above:

| case | mitigated? | by what |
|---|---|---|
| A | n/a, already correct | kernel `postdisable` |
| B | **partly** | `tx-guard.sh reap` disables a buffer left enabled with no owning process. Ownership is a **heuristic**: an open fd on the TX chardev is evidence, not proof. A process can hold it without having enabled the buffer, and a buffer can in principle outlive the fd. `reap` errs toward leaving a possibly-live stream alone, so it can decline to reap something genuinely stale. It mutes both channels **itself** and only then disables the stale buffer (the order matters; see [reap mutes before it disables](#reap-mutes-before-it-disables)). The kernel's `postdisable` also runs afterwards, but with both channels already at maximum the read-back cannot tell which muted them, and no claim is made about which did. Tested over a handful of runs, not a statistical sample. **Manual only**: nothing in the repo runs it automatically. Running it at boot needs a firmware rebuild and flash; on the Debian root that means a systemd unit beside `fishball-rf-quiesce.service`, not `S21misc`, which belongs to the Buildroot userspace |
| C | **no** | `reap` declines to act when a process owns the buffer, because that process may be mid-stream. A starved-but-open buffer keeps the transmitter unmuted until the owner exits. Closing this needs a kernel-side idle timeout, not a userspace tool (now `0015`, [below](#after-the-fix-patch-0015)) |
| D | clean in practice | iiod explicitly disables the buffer after a disconnected client. Not a kernel guarantee: the IIO core does not disable on file close |

The affirmation gate (`set-gain`, refused without `affirm`) is orthogonal to all
four: it governs who may raise output in the first place, not what happens when a
stream ends.

### Gate limitations

The gate is tool-level, not enforcement. A direct write to
`out_voltageN_hardwaregain` bypasses it, and the affirmation is an ordinary file in
world-writable tmpfs that any process can forge with `touch`. A forged flag is
indistinguishable from a real one and `status` reports it as genuine, which is
worse than the direct-sysfs bypass because it manufactures a false record that a
person vouched for the antenna. Real enforcement would have to live in the kernel.

### Gate defects fixed after the first review

The first adversarial review of the gate found seven medium-or-above issues, all
fixed. The two most serious, both reproduced on the board:

- **Integer wrap bypass.** `set-gain -4294967306` compared as quieter than −89.75
  in awk, skipping the affirmation check, while the kernel's 32-bit fixpoint parser
  wrapped it to **−10 dB**. Now refused by an explicit range check.
- **String-comparison bypass, inverted.** awk fell back to string comparison,
  waving through `-30 dB` (the format this tool prints and sysfs returns) while
  refusing the quiet `-89.75 dB`. Now refused by a strict decimal format check
  applied before any numeric comparison.

Also fixed: unanchored fd matching in `reap` that accepted a sysfs directory
handle as an owner; writes reported as successful without read-back; `reap` exit
codes that could not distinguish reaped from owned from nothing-to-do.

### set-gain raises one channel at a time

Channel 0 is TX1A and channel 1 is TX2A, two separate SMA ports. Affirmations are
per channel and `set-gain` requires the channel explicitly, because one
affirmation covering both would let an operator affirming the TX1 loop put TX2A
(open at the time, and flagged suspect in `GOALS.md`) on air. Muting (`revoke`,
and the failure path) still acts on both, which is the safe direction.

## The kernel attenuation cache, and the gate on it

`ad9361_tx_mute()` (`drivers/iio/adc/ad9361.c`) caches both channels' attenuation
when a stream **stops** and re-imposes it when the next buffer is **enabled**. A
sysfs write made while muted never updates the cache.

The restore is **gated**. `cf_axi_dds_buffer_preenable()` in
`drivers/iio/frequency/cf_axi_dds.c` calls the unmute only
`if (ad9361_tx_is_muted(phy))`, and `ad9361_tx_is_muted()` is true only when
**both** attenuators read exactly maximum attenuation. That gate is
`firmware/patches/0005`, and it is live on this board (`ad9361_tx_is_muted`
present in `/proc/kallsyms`).

**So the hazard runs opposite to intuition.** Leaving both channels at −89.75 dB,
which is what `revoke`, `reap` and a quiet `set-gain` all do, is exactly the state
that arms the restore. Leaving a channel off maximum disarms it. `tx-guard.sh`
reports the armed condition directly (a warning keyed on loudness would fire in
exactly the inverted set of cases).

A userspace mitigation exists but **is not applied**: because the gate requires
*both* channels at exactly maximum, holding one channel one 0.25 dB step off
maximum (still ~89.5 dB down) keeps `is_muted()` false and blocks the restore. It
is not applied because it changes the kernel's documented mute-on-stream-stop
behaviour, which this work is required to preserve.

**Patch `0010` was withdrawn.** It made a sysfs attenuation write update the
cache. Review established that every caller of `ad9361_tx_mute(phy, 0)` is already
covered: the DDS path by `0004`'s `tx_muted` state and `0005`'s `is_muted()` gate,
and both `ad9361_conv.c` callers by being balanced pairs that re-cache from
hardware first ([below](#ungated-callers-of-the-cache-restore)). The patch had no
demonstrable effect on any reachable path, and its commit message justified it
with a mechanism those call sites cannot produce. The number is not reused.

### The 2026-09-20 18:30 fault: undiagnosed

The cache does not explain this fault. Patch `0005` was in the tree from
2026-09-14, six days before it, and it means setting a gain before starting a
stream escapes the restore, so "the cache restores −89.75 forever" does not fit
the running kernel.

What stands: the TX1A RF path is intact. A tone at −60 dB attenuation returned at
2.402001 GHz, −11.5 dBFS, 70.7 dB above the noise floor, in two identical
captures. Whatever the fault was, it was not a dead TX1A cable. Status:
**undiagnosed**.

### reap mutes before it disables

`reap` forces both attenuators to maximum **before** writing `0` to
`buffer/enable`. The kernel's `postdisable` hook snapshots whatever attenuation it
finds into the cache (in `ad9361_tx_mute()`) and only then sets maximum. Disabling
first would cache the dead stream's **loud** value and leave the board in the armed
state carrying it, so `reap`, the mitigation for case B, would itself supply the
loud cache entry that a later buffer enable restores with no affirmation on
record. Case B holds the attenuator at the killed stream's gain, so the sequence
the tool documents reaches this: affirm, `set-gain`, stream, SIGKILL, reap,
revoke, and then any client's next buffer enable lifts that channel back.

Muting first makes the snapshotted value maximum, so the later restore is a no-op.
The kernel's mute-on-stream-stop behaviour is unchanged: both channels are still
driven to maximum on stream stop. Only the value the kernel snapshots differs.

Source: `ad9361_tx_mute()` and `ad9361_tx_is_muted()` in `ad9361.c`, the buffer
hooks in `cf_axi_dds.c`, and `dds_buffer_state_set()` in
`cf_axi_dds_buffer_stream.c`.

**Confirmed on hardware.** On a board reading `-89.750000` on both channels, a bare
`iio_writedev` buffer enable came up at **`-61.500000`**, the gain the previous
stream had used, with nothing having asked for gain and no affirmation on record:
a 28.25 dB raise, with the value chosen by the kernel. Enabling a TX buffer on an
unaffirmed board is itself a TX-enabling action, and this one raised output by
28.25 dB. See the root [`IDLE-CASES.md`](../IDLE-CASES.md).

### Ungated callers of the cache restore

The restore in `cf_axi_dds_buffer_preenable()` is gated by `ad9361_tx_is_muted()`.
`ad9361_tx_mute(phy, 0)`, the call that re-imposes the cached gain, has two more
callers, in `firmware/src/linux/drivers/iio/adc/ad9361_conv.c`, and neither
consults the gate (`ad9361_conv.c` contains **zero** references to
`ad9361_tx_is_muted`) nor is a buffer enable:

- `:98` / `:120` `ad9361_dig_interface_timing_analysis()`: mutes, then restores
  **unconditionally**
- `:604` / `:641` `ad9361_dig_tune()`: the same, under `if (ret_mute == 0)`

Both are reachable on this board:

- `/sys/kernel/debug/iio/iio:device0/bist_timing_analysis` and `digital_tune` are
  present.
- The `CAL_SWITCH` case of `ad9361_phy_write_raw()` calls `ad9361_dig_tune()` from
  an ordinary **sampling-frequency change** whenever a FIR is enabled, and the
  device tree sets `adi,digital-interface-tune-skip-mode = <0x00>` (TUNE_RX_TX), so
  the skip branch that would suppress the restore is not taken.

**The consequence is small.** Status: not a hazard to operator intent.

- **They are balanced pairs.** Both callers first call `ad9361_tx_mute(phy, 1)`
  (`:98` and `:604`), which re-caches the *current* attenuation from hardware
  immediately before the matching `ad9361_tx_mute(phy, 0)` at `:120` and `:641`
  restores it. What comes back is the value in force at that moment, not a stale
  earlier gain.
- **The sample-rate route is mutex-protected.** `ad9361_phy_write_raw()` holds
  `phy->lock` across its whole body, including `dig_tune`, and
  `ad9361_phy_read_raw()` takes the same lock, so a userspace read blocks for the
  duration and only ever observes the post-restore value. A `revoke`, `reap` or
  `status` cannot read maximum, print "verified quiet" and be wrong milliseconds
  later on this path. `ad9361_conv.c` has no locking of its own.
- **One caller runs unlocked:** the debugfs **read** of `bist_timing_analysis`
  (its debugfs read handler in `ad9361.c`), the source of the ~12 ms
  mute-and-restore window. That is a deliberate debugfs action, not routine
  operation.

### debugfs `initialize`

`echo 1 > /sys/kernel/debug/iio/iio:device0/initialize` reaches the `DBGFS_INIT`
case in `ad9361.c`, which re-runs `ad9361_setup()`, which applies `pd->tx_atten`
(`adi,tx-attenuation-mdB`) via `ad9361_set_tx_atten()` to **both** channels under
`adi,2rx-2tx-mode-enable`, with no unmute, no buffer enable and no affirmation on
record. `0010` would not have closed it: it is not an `ad9361_tx_mute()` unmute
and never reads the cache. It was not executed here, because running it would
raise TX output.

**The size of the raise depends on the device tree.** On the factory tree the
constant is `0x2710` (10000 mdB), and there `initialize` is a ~79.75 dB raise from
muted to −10 dB, about +9 dBm at the SMA against a receive port rated +2.5 dBm. On
this board `adi,tx-attenuation-mdB` reads **89750**, so `initialize` lands on
silence. Check which tree you are on before sizing the hazard.

**`firmware/patches/0011-probe-the-transmitter-at-maximum-attenuation.patch`
closes it** by changing the constant from `0x2710` (10 dB) to `0x15E96`
(89750 mdB = 89.75 dB, maximum). The driver probes with the same constant at every
boot, so it also shrinks the boot-window exposure: the driver comes up silent
instead of at 10 dB, and `tx_quiesce` becomes a backstop rather than the only
thing between a fresh boot and roughly +9 dBm. It changes nothing else: the TX LO
still comes up powered (`0004` leaves it so), `tx_quiesce` and its `fw_setenv`
switch are untouched, the mute cache behaves as before, and receive is unaffected.

Status: **built, flashed and tested on both kernels.** `out_voltage0_hardwaregain`
reads **−89.750000 dB** at power-on with no init script having run, on 5.15 and
on 6.12. `verify-patches.yml` asserts the `<0x15E96>` constant so a device-tree
edit cannot quietly put 10 dB back.

Two later patches narrow the same path:

- **`0016`** adds `tx_disable`, a latch enforced inside `ad9361_set_tx_atten()`, so
  `initialize` cannot raise the transmitter at all while it is engaged. The latch
  lives in `struct ad9361_rf_phy` rather than `ad9361_rf_phy_state`, because
  `ad9361_clear_state()` memsets the latter and `initialize` calls it; with the
  latch in the state struct the transmitter came back at −10 dB while `tx_disable`
  still read `1`.
- **`firmware-modern/patches/0019`** closes a third instance of the same memset:
  the unmute restored `tx1_atten_cached` / `tx2_atten_cached` from
  `ad9361_rf_phy_state`, which `clear_state()` zeroes, and **0 mdB is full
  output**. So `initialize` followed by any transmit stream keyed the transmitter
  flat out: `0.000000 dB` with an antenna fitted and no gain ever written. Status:
  fixed on the 6.12 target, **still live on `firmware/`'s 5.15**, where an
  `initialize` needs re-muting afterwards. Do not put a safety-relevant field in
  `ad9361_rf_phy_state`.

### The transmitter-safety page's former claim: resolved

[`docs/transmitter-safety.md`](../docs/transmitter-safety.md) used to say:

> The reason this holds even when things go wrong is that the IIO core runs the
> buffer's `postdisable` hook on teardown **even if the application crashed or
> was killed**, since teardown happens on file close. No userspace watchdog can
> promise that.

Case B shows that to be **false**: both the writing process and its feeder were
gone, `buffer/enable` stayed `1`, `postdisable` never ran, and the attenuator held
the user's −25 dB with LO leakage 12.6 dB above the muted baseline. Case D is
clean in practice, but through iiod's own cleanup, not the
`postdisable`-on-file-close mechanism the page named. So the page was wrong about
the mechanism on every path and wrong about the outcome on the local one. Status:
**resolved**; the page now describes the starve watchdog, its cyclic exception and
its no-re-arm limit (which `0024` has since removed).

---

# After the fix (patch 0015)

Re-measured on the same board after flashing
`0015-mute-the-transmitter-when-the-dac-starves.patch`. The results above are the
before state and stay as they are. The defect was reproduced first on the
unpatched firmware: `kill -9`, then `buffer/enable` still `1` and both channels
still at −40 dB.

| # | termination path | before | after |
|---|---|---|---|
| A | normal close | −89.75 dB | **−89.75 dB**, buffer 0, unchanged |
| B | process kill, local | −25 dB, live indefinitely | **−89.75 dB after 0.26–0.27 s** |
| C | underflow, client alive | −25 dB, never covered | **−89.75 dB** |
| D | network client killed | −89.75 dB (iiod cleanup) | **−89.75 dB** |
| E | cyclic, running | n/a | **−40 dB**, correctly left alone |
| F | cyclic, killed | n/a | still live by design; bounded only if `tx_cyclic_timeout_ms` is set (2.10 s with a 2000 ms limit) |

`dmesg` names it when it fires:

```
iio iio:device2: no transmit data for 250 ms - muting the transmitter
```

**On Linux 6.12** after the rebase for
[`firmware-modern/`](../firmware-modern/README.md): case B mutes after **0.26–0.27 s**,
the same figure, with `buffer/enable` still reading `1`, which shows it is the
watchdog rather than the close hook. The underflow counter went 0 → 657 over the
starved stream and zeroed on write.

## Why cyclic is exempt

A cyclic transmit hands the hardware one buffer that repeats forever with no
software involvement (the DMA's `CYCLIC 1`; see `docs/block-design.md`). Outliving
the program that started it is the feature, so "no data arriving" describes a
*healthy* cyclic stream, and muting on it would break every one. Case E shows a
running cyclic transmit is untouched.

The consequence is that a `kill -9` on a cyclic transmit is indistinguishable
from a normal return, so it keeps transmitting. `tx_cyclic_timeout_ms` bounds it
and is off by default in the driver (case F). The modern target's Debian root arms
it at 60 s at boot; this userspace does not.

## Test pitfalls

Each of these produces a confident wrong answer.

**`pkill` does not exist on the board.** A case-B test using
`pkill -9 iio_writedev 2>/dev/null` never kills the writer; with `2>/dev/null` a
missing `pkill` looks like a successful one. The watchdog keeps being re-armed,
the attenuation stays where it was put, and the test reports the watchdog as
broken. Use `ps`, `kill -9 <pid>`, then `ps` again.

**Feed the stream from something endless.** `iio_writedev -s 0` fed from a 1 MB
file lasts **4 ms** at 61.44 MS/s, so the buffer closes normally before the kill
and the test measures case A while appearing to measure case B.
`cat /dev/urandom |` keeps it live; the DAC starves between blocks, which is
fine, because blocks are still being submitted.

**Do not use `sleep` immediately after `kill -9`** on a background job in busybox
`sh`. It returns instantly on `SIGCHLD`, so the script reads the attenuation about
10 ms after the kill and sees the value from before the mute (which reads as
"mutes after 3 to 6 seconds" when the real figure is 0.27 s). Poll
`/proc/uptime` instead:

```sh
# run on the board
S=$(cut -d' ' -f1 /proc/uptime); kill -9 $PID
while :; do case "$(cat $PHY/out_voltage0_hardwaregain)" in
  -89*) echo "muted after $(awk "BEGIN{printf \"%.2f\", $(cut -d' ' -f1 /proc/uptime)-$S}") s"; break;;
esac; done
```

# Related: two debugfs routes to a live transmitter

`0016-a-transmit-disable-latch-that-debugfs-cannot-clear.patch` closes both, but
only while its latch is engaged, and `tx_disable` reads **0** unless somebody sets
it. By default neither route is closed.

| route | what it does without the latch | with `tx_disable` set |
|---|---|---|
| `echo 1 > debugfs/initialize` | re-applies the device-tree attenuation to both channels: a ~79.75 dB raise from muted on the factory device tree, over an unauthenticated port | refused |
| `echo "1 ... " > debugfs/bist_tone` | injects a tone at the **transmit** port, out through the PA, with nothing muting it | refused |

The latch has to live outside `ad9361_rf_phy_state`: `ad9361_clear_state()`
memsets that struct and `initialize` calls it, so a latch kept there was cleared
by the thing it defends against (the transmitter came back at −10 dB with
`tx_disable` still reading 1).
