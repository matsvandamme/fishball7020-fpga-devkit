# TX idle: stream-termination test results

Goal D verification. Each case sets a known "user" attenuation, starts a TX DMA
buffer, terminates it in one specific way, and reads attenuation back from
`/sys/bus/iio/devices/iio:device0/out_voltage{0,1}_hardwaregain` on the board —
rather than trusting that the terminating call returned.

Board: 192.168.2.1, fw `95aad-dirty`, TX1 -> RX1 loop with **20 dB** external
attenuation (the goal text says 50 dB; see "Deviation" below).

Expected after termination: **-89.75 dB** (maximum attenuation), which is what
`cf_axi_dds_tx_rf_mute()` applies via the buffer's postdisable hook.

| # | Termination path | How induced | Attenuation read back | buffer/enable | RX saw | Verdict |
|---|---|---|---|---|---|---|
| A | Normal close | `iio_writedev -s 32768` on board, runs to completion, exit 0 | **-89.75 dB** | 0 | not measured | **PASS** (on read-back) |
| B | Process kill, local | `iio_writedev -s 0` on board, `kill -9` mid-stream | **-25 dB (unchanged)** | **1 (stuck)** | **LO leakage -46.7 dBFS vs -59.3 muted** | **FAIL** |
| C | Underflow, client alive | network client fed 64 KB then stalled 18 s | **-25 dB (unchanged)** | 1 | not measured | **GAP** |
| D | Network client killed | `iio_writedev -u ip:192.168.2.1`, `kill -9` on the PC side | **-89.75 dB** | 0 | not measured | **PASS** (on read-back; see note — iiod cleanup, not a kernel guarantee) |

## Case B — the defect

Killing a *local* TX process leaves the transmitter live indefinitely.

Both `iio_writedev` and its feeding `cat` were confirmed gone, yet
`buffer/enable` stayed `1`, so the IIO core never ran postdisable and the mute
never fired. Measured on the receiver through the loop: LO leakage at 2.4 GHz
rose to **-46.7 dBFS** against **-59.3 dBFS** in the muted baseline — 12.6 dB
hotter, with no process alive and no operator action.

This contradicts the claim in `0004-mute-tx-when-no-dma-stream.patch`:

> The IIO core calls postdisable on buffer teardown even when the application
> crashed or was killed, which is what makes this a real guarantee rather than
> best effort.

It does not hold on **any** path. See "What actually cleans up" below: the IIO
core never disables a buffer on file close, and case D is clean only because
iiod explicitly tidies up after a disconnected client.

The mute machinery itself is correct: writing `0` to `buffer/enable` by hand
immediately drove attenuation to -89.75 dB without any other action. The gap is
only that nothing performs that write when the owner dies.

## Case C — idle but not silent

A buffer that is open but starved keeps the transmitter unmuted. Defensible as
driver behaviour, since the application still owns the stream, but it fails this
goal's definition of TX idle — no data flowing through the DMAs — so it is
recorded as a gap rather than a pass.

## Deviation from the goal text

The goal specifies a 50 dB TX1->RX1 loop; the loop physically attached is
**20 dB**. Margin was recomputed before transmitting: with the board's ~+19 dBm
maximum and a receive port rated +2.5 dBm (docs/transmitter-safety.md), 20 dB of loop leaves
about 3.5 dB of margin at full output. Provenance of that figure: board maximum
~+19 dBm (fishball-sdr MCP server documentation), receive port rated +2.5 dBm
(docs/transmitter-safety.md:23), loop 20 dB -> 19 - 20 = -1 dBm at the receive
port, 3.5 dB under the rating. It is an arithmetic bound from two documented
numbers, not a measurement of this cable.

Tests here ran at -60 dB to -25 dB attenuation, keeping at least 28 dB of
margin. One later check of the near-full-output warning briefly set -5 dB with
no stream running (LO leakage only, ~8.5 dB margin), which exceeded the -20 dB
cap stated for this session.

## Mitigations, and what is still uncovered

`tools/tx-guard.sh` addresses part of the above. Being exact about which part:

| Case | Mitigated? | By what |
|---|---|---|
| A | n/a — already correct | kernel postdisable |
| B | **partly** | `tx-guard.sh reap` disables a buffer left enabled with no owning process. Ownership is a **heuristic** — an open fd on the TX chardev is evidence, not proof: a process can hold it without having enabled the buffer, and a buffer can in principle outlive the fd. reap errs toward leaving a possibly-live stream alone, so it can decline to reap something genuinely stale. The tool mutes both channels **itself** and only then disables the stale buffer (ordering is load-bearing — see below). So userspace causes this mute; the kernel's postdisable also runs afterwards, but because both channels are already at max the read-back cannot distinguish the two, and no claim is made about which did it. Sample size is the handful of runs in this session, not a statistical claim. **Manual only** — nothing in the repo runs it automatically. Installing it in `S21misc` needs a firmware rebuild and flash. |
| C | **no** | `reap` deliberately declines to act when a process owns the buffer, because that process may legitimately be mid-stream. A starved-but-open buffer therefore keeps the transmitter unmuted until the owner exits. Closing this needs a kernel-side idle timeout, not a userspace tool. |
| D | clean in practice | iiod explicitly disables the buffer after a disconnected client. Not a kernel guarantee — the IIO core does not disable on file close (measured). |

The affirmation gate (`set-gain`, refused without `affirm`) is orthogonal to all
four: it governs who may raise output in the first place, not what happens when
a stream ends.

### Gate limitations, stated plainly

The gate is tool-level, not enforcement. It can be bypassed by writing
`out_voltageN_hardwaregain` directly, and the affirmation itself is an ordinary
file in world-writable tmpfs that any process can forge with `touch`. A forged
flag is indistinguishable from a real one and `status` will report it as
genuine — which is worse than the direct-sysfs bypass, because it manufactures
a false record that a human vouched for the antenna. Real enforcement would
have to live in the kernel.

### Fixed after adversarial review round 1

Round 1 found seven medium-or-above issues in the first version of the gate.
All were fixed before round 2; the review count was restarted as the contract
requires. The two that mattered most, both confirmed by measurement:

- **Integer wrap bypass.** `set-gain -4294967306` read as quieter than -89.75
  to awk, skipping the affirmation check, while the kernel's 32-bit fixpoint
  parser wrapped it to **-10 dB**. Now refused by an explicit range check.
- **String-comparison bypass, inverted.** awk fell back to string comparison,
  waving through `-30 dB` — the very format this tool prints and sysfs returns
  — while refusing the quiet `-89.75 dB`. Now refused by a strict decimal
  format check applied before any numeric comparison.

Also fixed: unanchored fd matching in `reap` that accepted a sysfs directory
handle as an owner; writes reported as successful without read-back
verification; `reap` exit codes that could not distinguish reaped from owned
from nothing-to-do.

## The kernel attenuation cache — and the gate on it

`ad9361_tx_mute()` caches both channels' attenuation when a stream **stops**
(`firmware/src/linux/drivers/iio/adc/ad9361.c:1295-1296`) and re-imposes it when
the next buffer is **enabled**. A sysfs write made while muted never updates the
cache.

That restore is **gated**, which an earlier draft of this file got wrong.
`firmware/src/linux/drivers/iio/frequency/cf_axi_dds.c:1201` calls the unmute
only `if (ad9361_tx_is_muted(phy))`, and `ad9361_tx_is_muted()`
(`ad9361.c:1321-1325`) is true only when **both** attenuators read exactly max
attenuation. That gate is `firmware/patches/0005`, and it is live on this board
(`ad9361_tx_is_muted` present in `/proc/kallsyms`).

**The hazard therefore runs opposite to intuition.** Leaving both channels at
-89.75 dB — what `revoke`, `reap` and a quiet `set-gain` all do — is exactly the
state that arms the restore. Leaving a channel off max disarms it. An earlier
version of `tx-guard.sh` warned on loudness, i.e. in precisely the inverted set
of cases: silent where the restore was armed, loud where the driver already
protected the operator. It now reports the armed condition directly.

A userspace mitigation does exist: because the gate requires *both* channels at
exactly max, holding one channel one 0.25 dB step off max — still ~89.5 dB down
— keeps `is_muted()` false and blocks the restore. **It is deliberately not
applied**, because it changes the kernel's documented mute-on-stream-stop
behaviour, which this work is required to preserve. The honest fix is a kernel
patch in `firmware/patches/` making a sysfs attenuation write update the cache.
Such a patch was written (`0010`) and then **withdrawn**. Review established
that every caller of `ad9361_tx_mute(phy, 0)` is already covered — the DDS path
by patch 0004's `tx_muted` state and patch 0005's `is_muted()` gate, and both
`ad9361_conv.c` callers by being balanced pairs that re-cache from hardware
first. The patch had no demonstrable effect on any reachable path, and its
commit message justified itself with a mechanism those call sites cannot
produce. Shipping it would have added a kernel change on a false rationale.

### What this means for the 18:30 fault

The earlier draft of this file asserted the cache explained the 2026-09-20 fault
outright. That claim is withdrawn as overstated. Patch 0005 has been in the tree
since 2026-09-14, six days before the fault, and it means setting a gain before
starting a stream escapes the loop — so the simple "cache restores -89.75
forever" story does not survive contact with the running kernel.

What is **measured**, and stands: the TX1A RF path is intact. A tone at -60 dB
attenuation returned at 2.402001 GHz, -11.5 dBFS, 70.7 dB above the noise floor,
in two identical captures. Whatever the 18:30 fault was, it was not a dead TX1A
cable. The cause remains **undiagnosed**.

## set-gain raises one channel at a time, on purpose

Channel 0 is TX1A and channel 1 is TX2A — two separate SMA ports. An earlier
version of the guard wrote both channels from one affirmation, so an operator
affirming the TX1 loop would have put TX2A — open, and flagged suspect in
GOALS.md — back on air. Affirmations are now per channel, and `set-gain`
requires the channel explicitly. Muting (`revoke`, and the failure path) still
acts on both, which is the safe direction.

## Out of scope, but needs a decision

`docs/transmitter-safety.md:54-57` states:

> The reason this holds even when things go wrong is that the IIO core runs the
> buffer's `postdisable` hook on teardown **even if the application crashed or
> was killed**, since teardown happens on file close. No userspace watchdog can
> promise that.

Case B measures that to be **false**: both the
writing process and its feeder were confirmed gone, `buffer/enable` stayed `1`,
postdisable never ran, and the attenuator held the user's -25 dB with LO leakage
12.6 dB above the muted baseline. The network path (case D) is clean in
practice, but — per the section above — that is iiod's own cleanup, not the
`postdisable`-on-file-close mechanism the doc names. So the doc is wrong about
the mechanism on every path, and wrong about the outcome on the local one.

This is the project's user-facing safety document and it is now known to
overstate a safety guarantee. It was **not edited**: `docs/` is outside the
scope this work was given (`firmware/patches/`, `firmware/scripts/`, `tools/`).
Correcting it needs an explicit scope decision.

## reap mutes before it disables, and why the order matters

`reap` forces both attenuators to max **before** writing `0` to `buffer/enable`.
That ordering is load-bearing, and an earlier version had it backwards.

The kernel's postdisable hook snapshots whatever attenuation it finds into the
cache (`ad9361.c:1294-1296`) and only then sets max. So disabling first would
cache the dead stream's **loud** value and leave the board in the armed state
carrying it — meaning `reap`, the mitigation for case B, would itself supply the
loud cache entry that a later buffer enable restores with no affirmation on
record. Measured case B holds the attenuator at the killed stream's gain, so
this was reachable by exactly the sequence the tool documents: affirm,
`set-gain`, stream, SIGKILL, reap, revoke — and then any client's next buffer
enable lifts that channel back.

Muting first makes the snapshotted value max, so the later restore is a no-op.
It does not change the kernel's mute-on-stream-stop behaviour, which this work
must preserve: both channels are still driven to max on stream stop exactly as
before. Only the value the kernel happens to snapshot differs.

Source-verified (`ad9361.c:1289-1311`, `:1321-1325`; `cf_axi_dds.c:1160-1206`;
`cf_axi_dds_buffer_stream.c:62-92`). **Not** hardware-confirmed end to end,
because confirming the restore requires deliberately raising TX output.

## The cache restore has ungated callers — a sample-rate change can un-mute TX

The LIMIT 3 account above describes the restore as gated by
`ad9361_tx_is_muted()` at `cf_axi_dds.c:1201` and triggered by a buffer enable.
**That is incomplete**, and the gap is larger than the gated path.

`ad9361_tx_mute(phy, 0)` — the call that re-imposes the cached gain — has two
further callers in `firmware/src/linux/drivers/iio/adc/ad9361_conv.c`:

- `:98` / `:120`  `ad9361_dig_interface_timing_analysis()` — mutes, then
  restores **unconditionally**
- `:604` / `:641` `ad9361_dig_tune()` — same, under `if (ret_mute == 0)`

Verified: `ad9361_conv.c` contains **zero** references to
`ad9361_tx_is_muted`. Neither path consults the gate, and neither is a buffer
enable.

Both are reachable on this board:

- `/sys/kernel/debug/iio/iio:device0/bist_timing_analysis` and `digital_tune`
  are present (confirmed live).
- `ad9361.c:4204-4207` calls `ad9361_dig_tune()` from an ordinary
  **sampling-frequency change** whenever a FIR is enabled, and the device tree
  sets `adi,digital-interface-tune-skip-mode = <0x00>` (TUNE_RX_TX), so the
  skip branch that would suppress the restore is not taken.

**Consequence — and it is small.** During such a call the kernel drives both
attenuators to max, holds the gain in `tx1_atten_cached` / `tx2_atten_cached`
(`ad9361.c:1294-1296`), then restores it. Because the mute half re-caches from
hardware first, what returns is the value already in force, so the pair is a
no-op with respect to operator intent.

An earlier version of this paragraph claimed a `revoke`, `reap` or `status`
landing in that window could read max, verify it, print "verified quiet" and be
false milliseconds later. **That is not reachable on the sample-rate path.**
`ad9361_phy_write_raw()` holds `phy->lock` from `ad9361.c:8005` to `:8060`
across `dig_tune`, and `read_raw()` takes the same lock at `:7908`, so a read
from userspace blocks for the duration and only ever observes the post-restore
value. `ad9361_conv.c` contains no locking of its own.

The one genuinely unlocked caller is the debugfs **read** of
`bist_timing_analysis` (`ad9361.c:8273-8276`), where the ~12 ms figure came
from — a deliberate debugfs action, not routine operation.

### Correction: this is smaller than first written

An earlier version of this section said a routine sample-rate change un-mutes
TX to its previous gain, and called it the largest finding here. Both halves
were overstated, and adversarial review caught it:

- **The ungated callers are balanced pairs.** `ad9361_conv.c:98`/`:604` call
  `ad9361_tx_mute(phy, 1)` first, which re-caches the *current* attenuation
  (`ad9361.c:1294-1296`), immediately before `:120`/`:641` restore it. What
  comes back is the value in force at that moment, not a stale earlier gain.
  With respect to operator intent they are a no-op.
- **The sample-rate route is mutex-protected.** `ad9361_phy_write_raw()` holds
  `phy->lock` from `ad9361.c:8005` to `:8060` across `dig_tune`, and
  `read_raw()` takes the same lock at `:7908`. A userspace read therefore
  blocks for the duration and only ever observes the post-restore value. The
  claim that a `revoke`/`status` could verify "quiet" and be false milliseconds
  later is **false on this path**.

What survives: the callers genuinely do not consult the gate, and one of them —
the debugfs **read** of `bist_timing_analysis` (`ad9361.c:8273-8276`, the source
of the ~12 ms figure) — runs with no lock held. That is a deliberate debugfs
action, not routine operation.

### A path that is genuinely uncovered: debugfs `initialize`

`echo 1 > /sys/kernel/debug/iio/iio:device0/initialize` reaches DBGFS_INIT
(`ad9361.c:8312-8323`), which re-runs `ad9361_setup()`, which applies
`pd->tx_atten` at `ad9361.c:5243` — `adi,tx-attenuation-mdB`, **10000** on this
board — to **both** channels under `adi,2rx-2tx-mode-enable`. From a muted
-89.75 dB that is a ~79.75 dB raise to -10 dB, about +9 dBm at the SMA against
a receive port rated +2.5 dBm, with no unmute, no buffer enable and no
affirmation on record.

Patch 0010 does **not** close this — it is not an `ad9361_tx_mute()` unmute and
never reads the cache. Not executed here, deliberately: running it would raise
TX output.

**`firmware/patches/0011-probe-the-transmitter-at-maximum-attenuation.patch`
closes it**, by changing `adi,tx-attenuation-mdB` from `0x2710` (10 dB) to
`0x15E96` (89750 mdB = 89.75 dB, maximum). The same constant is what the driver
probes with at every boot, so this also shrinks the boot-window exposure: the
driver comes up already silent instead of at 10 dB, and `tx_quiesce` becomes a
backstop rather than the only thing between a fresh boot and roughly +9 dBm.

It changes nothing else: the TX LO still comes up powered (patches/0004's
deliberate choice), `tx_quiesce` and its `fw_setenv` escape hatch are untouched,
the mute cache behaves exactly as before, and receive is unaffected. Verified to
apply cleanly. **NOT built, NOT flashed.**

---

# After the fix (patch 0015)

Re-measured on the same board after flashing
`0015-mute-the-transmitter-when-the-dac-starves.patch`. The measurements above
are left exactly as they were: they are what the board did before, and a fix is
only meaningful against them.

The defect was reproduced first, on the unpatched firmware, to be sure the test
was measuring the right thing — `kill -9`, then `buffer/enable` still `1` and
both channels still at −40 dB.

| # | Termination path | Before | After |
|---|---|---|---|
| A | Normal close | −89.75 dB | **−89.75 dB**, buffer 0 — unchanged |
| B | Process kill, local | −25 dB, live indefinitely | **−89.75 dB after 0.27 s** |
| C | Underflow, client alive | −25 dB, never covered | **−89.75 dB** |
| D | Network client killed | −89.75 dB (iiod cleanup) | **−89.75 dB** |
| E | Cyclic, running | n/a | **−40 dB** — correctly left alone |
| F | Cyclic, killed | n/a | still live *by design*; bounded only if `tx_cyclic_timeout_ms` is set (measured: 2.10 s with a 2000 ms limit) |

`dmesg` names it when it fires:

```
iio iio:device2: no transmit data for 250 ms - muting the transmitter
```

## Why cyclic is exempt

A cyclic transmit hands the hardware one buffer and it repeats forever with no
software involvement — `docs/block-design.md` calls that out as the point of the
DMA's `CYCLIC 1`. Outliving the program that started it is the feature, so
"no data arriving" describes a *healthy* cyclic stream, and muting those would
break every one of them. Verified: case E shows a running cyclic transmit is
untouched.

The consequence is that a `kill -9` on a cyclic transmit is indistinguishable
from a normal return, so it keeps transmitting. `tx_cyclic_timeout_ms` bounds
that, and is off by default.

## A trap for whoever writes the next test here

Do **not** use `sleep` immediately after `kill -9` on a background job in
busybox `sh`. It returns instantly on `SIGCHLD`, so the script reads the
attenuation about 10 ms after the kill and sees the value from before the mute.
That nearly went into this file as "mutes after 3 to 6 seconds" when the real
figure is 0.27 s. Poll `/proc/uptime` instead:

```sh
# run on the board
S=$(cut -d' ' -f1 /proc/uptime); kill -9 $PID
while :; do case "$(cat $PHY/out_voltage0_hardwaregain)" in
  -89*) echo "muted after $(awk "BEGIN{printf \"%.2f\", $(cut -d' ' -f1 /proc/uptime)-$S}") s"; break;;
esac; done
```

# Related: the other two routes to a live transmitter

Found while fixing the above, and closed by
`0016-a-transmit-disable-latch-that-debugfs-cannot-clear.patch`:

| Route | What it did | Now |
|---|---|---|
| `echo 1 > debugfs/initialize` | re-applied the device-tree attenuation to both channels — a ~79.75 dB raise from muted, over an unauthenticated port | refused while `tx_disable` is set |
| `echo "1 ... " > debugfs/bist_tone` | injected a tone at the **transmit** port, out through the PA, with nothing muting it | refused while `tx_disable` is set |

The latch had to be moved out of `ad9361_rf_phy_state` to work at all:
`ad9361_clear_state()` memsets that struct, and `initialize` calls it — so a
latch kept there was cleared by the very thing it was defending against.
Measured: the transmitter came back at −10 dB with `tx_disable` still reading 1.
