# The modern target's kernel patches

Nine of the factory target's driver patches, rebased onto Analog Devices' Linux
6.12 instead of the vendor's 5.15, plus one patch that exists only here (`0019`).
The rationale for each carried patch is in the factory catalogue,
[`firmware/patches/README.md`](../../firmware/patches/README.md); this page
records what changed on 6.12 and how the series behaves on the board.

```bash
# run from: firmware-modern/src/linux
for p in ../../patches/*.patch; do git apply "$p" || break; done
```

Apply them in filename order. Three chains edit each other's added lines:
`0004 → 0005 → 0012` and `0004 → 0015 → 0017`, and `0016` and `0018` both touch
`ad9361_set_tx_atten()`. A patch applied out of turn fails with a reject, not a
wrong build.

| patch | what it does | on 6.12 |
|---|---|---|
| [`0004`](#0004-mute-tx-when-no-dma-stream) | mute TX when no DMA stream is running | **new code** |
| `0005` | don't clobber a gain set before streaming | context only |
| `0007` | `tx_sample_gpio_en` sysfs attribute | context only |
| `0012` | user LED follows the transmitter | context only |
| [`0015`](#0015-mute-the-transmitter-when-the-dac-starves) | mute when the DAC starves | **new code** |
| `0016` | a `tx_disable` latch debugfs cannot clear | context only |
| `0017` | count transmit DMA underflows | context only |
| `0018` | refuse to transmit louder when the die is hot | context only |
| [`0019`](#0019-never-restore-a-cached-attenuation-of-zero) | never restore a cached attenuation of zero | **new**, not on the factory target |
| [`0022`](../../firmware/patches/README.md#0022-give-a-large-first-block-time-to-arrive) | a large first transmit block gets time to arrive | same code as the factory patch |
| [`0024`](#0024-resume-the-transmitter-when-data-returns) | data arriving after a starve mute unmutes | same code as the factory patch; **measured here** |

"Context only" means the added lines are byte-for-byte identical to the 5.15
patch; only the surrounding context moved. To check, extract the added lines of
the 5.15 patch and of the 6.12 one and diff them. `0004`, `0015` and `0017` were
applied by hand because a hunk's context had moved, and of those only `0004` and
`0015` needed different code.

Some terms: **TX** is transmit; **attenuation** is how far the transmit output is
turned down, from 0 dB (full power) to −89.75 dB (the floor, "muted"); a **DMA
buffer** is the block of samples a program hands the kernel to send; **debugfs**
is the kernel's debug file interface under `/sys/kernel/debug`.

## 0004: mute TX when no DMA stream

Two code changes against 5.15:

- `of_find_spi_device_by_node()` is static in 6.12, so a local two-line
  equivalent replaces it.
- `cf_axi_dds_configure_buffer()` was rewritten upstream around
  `devm_iio_dmaengine_buffer_setup_with_ops()`, so the mute hooks attach
  differently.

**It also fixes an upstream bug.** ADI's 6.12 never assigns
`indio_dev->setup_ops` in `cf_axi_dds_configure_buffer()`. Up to 5.15 that
function built the buffer by hand and ended with the assignment. The helper it
now calls takes an `iio_dma_buffer_ops` (submit/abort), not an
`iio_buffer_setup_ops`, so it does not make the assignment either. gcc warns:

```
warning: 'dds_buffer_setup_ops' defined but not used
```

Without it, `dds_buffer_preenable()` and `dds_buffer_postdisable()` never run:
`cf_axi_dds_start_sync()` is skipped when a transmit stream starts, and
`cf_axi_dds_datasel(st, -1, DATA_SEL_DDS)` is skipped when it stops, which leaves
the DAC pointed at stale DMA data. `0004` restores the line, with a comment in
the source saying it is not part of the fishball changes. Status: **not yet
reported upstream.**

**Its root-filesystem half is not here.** The factory `0004` and `0012` also edit
`buildroot/board/pluto/S21misc` (`tx_quiesce` and `tx_led`). This target's
userspace is the Debian root in [`../debian/`](../debian/README.md), which has
no `S21misc`, so those halves are not carried here. The Debian root implements
both itself: `fishball-rf-quiesce` honours `tx_quiesce`, and `fishball-identity`
honours `tx_led`.

Any root filesystem used with this kernel has to reimplement `tx_quiesce` as
something that runs before anything can stream. The two layers split the boot:
this target's device tree ([`../dts/`](../dts/)) sets
`adi,tx-attenuation-mdB = <89750>`, which covers probe, and `tx_quiesce` covers
everything from then to the first stream. ADI's own device trees set `<10000>`
(10 dB of attenuation), which on a board with a power amplifier is roughly
**+9 dBm out of an SMA**
([`docs/debian-root-reference.md`](../../docs/debian-root-reference.md#transmitter-safety-at-boot)).

## 0015: mute the transmitter when the DAC starves

Which field carries the cyclic flag depends on `CONFIG_IIO_DMA_BUF_MMAP_LEGACY`.
The patch handles both.

## 0022: give a large first block time to arrive

The same code as [the factory `0022`](../../firmware/patches/README.md#0022-give-a-large-first-block-time-to-arrive),
measured here: two channels at 40, 50 and 60 MS/s unmuted; a killed streaming
transmitter muted at 280 ms; a buffer enabled and never fed muted at 315 ms.
The persistent switch, `fw_setenv tx_starve_ms`, is read by `fishball-rf-quiesce`.

## 0024: resume the transmitter when data returns

`0015`'s starve mute was one-way, and because it also switches the DAC to the
DDS, nothing drained the DMA afterwards: the next write timed out, a new buffer
on the same connection was refused as busy, and only reconnecting transmitted
again. Reported from SDR Console, which keeps one buffer open and stops feeding
it between transmissions ("TX only starts once after connecting").

A block arriving after a starve mute now schedules a work item that re-selects
the DMA source for the enabled channels and calls `cf_axi_dds_tx_rf_mute(false)`,
the order and the call a buffer enable uses, so `0005`, `0016`, `0018` and `0019`
decide what comes back exactly as they do there. The block has already re-armed
the watchdog, so every later stall mutes again.

Measured on an R1 (v2.4 + this kernel) and an R2 (v0.2 + this kernel) with
`tools/tx-idle-cases/resume-after-starve.py`: muted 1 s into a stall, back on the
next block, muted again on a second stall, back again; a new buffer on the same
connection works; a cyclic stream held 3 s stays unmuted.

## 0019: never restore a cached attenuation of zero

**The defect.** `0004` restores a cached attenuation when it unmutes. That cache
(`tx1_atten_cached` / `tx2_atten_cached`) lived in `struct ad9361_rf_phy_state`,
and `ad9361_clear_state()` does `memset(st, 0, sizeof(*st))` on it. debugfs
`initialize` calls `ad9361_clear_state()`. Zero is not a harmless default for an
attenuation: 0 mdB is full output. So this sequence keyed the transmitter flat
out with nothing having asked for it:

```sh
# run on the board. On a kernel without 0019, with an antenna fitted, do NOT.
echo 1 > /sys/kernel/debug/iio/iio:device0/initialize
# ...then anything that opens a transmit buffer...
```

On the board, `0016`'s test (set the latch, run debugfs `initialize`, check the
latch held) left **TX2 at 0.000000 dB with an antenna fitted**, and nothing had
written a gain at any point.

**The fix.** The cache moves to `struct ad9361_rf_phy`, which
`ad9361_clear_state()` does not touch, and is seeded at probe with
`MAX_TX_ATTENUATION_DB`, so "nothing cached yet" means muted rather than loud.

This is the third safety field moved out of that struct: `0016`'s `tx_disable`
latch and `0018`'s `tx_temp_limit` were moved for the same reason. The
`verify-modern` CI workflow asserts where all three live. Do not put a
safety-relevant field in `ad9361_rf_phy_state`.

It is not a 6.12 regression. The factory target's 5.15 kernel has the same code
and does not carry this patch, so there a debugfs `initialize` must be followed by
a re-mute and a read-back
([`docs/transmitter-safety.md`](../../docs/transmitter-safety.md)).

## On the board

Kernel 6.12.0, the same bitstream as the factory target:

| | |
|---|---|
| `./devkit selftest` | 23 passed, 0 warnings, 0 failed |
| TX0 / TX1 at probe | **−89.75 dB** both |
| `tx_starve_timeout_ms` | 250 |
| `tx_cyclic_timeout_ms` | 0 as the driver compiles it; a booted devkit Debian root reads **60000**, because `fishball-rf-quiesce` sets it before `iiod` starts. To see the driver's own value, `fw_setenv tx_cyclic_bound 0` and reboot. Stopping the unit does not reset it (the value it wrote stays), and stopping it also stops `iiod` |
| `tx_disable`, `tx_temp_limit`, `tx_sample_gpio_en`, `tx_dma_{under,over}flow_count` | present, 0 |
| `0016` behaviourally | latch set to 1, debugfs `initialize`, latch **still 1** and still −89.75 dB |
| `0015` starvation mute | **0.26–0.27 s** after `kill -9` on the feeder, with `buffer/enable` still 1; the same figure as on 5.15 |
| `0017` counters | 0 → 657 underflows during a starved stream, and a write zeroes them |
| `0018` thermal gate | limit 1 °C at a 40 °C die: an explicit −60 dB write refused and logged, muting still allowed |
| `0019` | `initialize` then a transmit stream: both channels stay at −89.75 dB |
| RF loopback, TX0→RX0 through 20 dB | **32 passed, 0 failed**. TX attenuator 1.007 dB/dB, image rejection below the noise floor, mute depth 73.1 dB to the floor |
| digital loopback error | 0.0 dB, `dig_eye_passes` 157 |

Re-run the `0016` and `0019` checks by hand after any change to `ad9361.c`. Both
patches exist to survive another code path's reset, and a passing selftest
exercises neither.

## Testing pitfalls

- **`pkill` is not in the board's busybox.** A starvation test that calls it never
  kills the writer, the watchdog keeps being re-armed, and the test reports the
  watchdog as broken. Kill by PID from `ps`.
- **Feed the stream from something endless.** A 1 MB file at 61.44 MS/s lasts
  4 ms, so the buffer closes normally before the kill and the test measures the
  ordinary close path. `cat /dev/urandom |` keeps it live.
- **Do not `sleep` straight after `kill -9` on a background job in busybox `sh`.**
  It returns on SIGCHLD, so the reading lands about 10 ms after the kill. Poll
  `/proc/uptime` instead.

More on all three: [`tools/IDLE-CASES.md`](../../tools/IDLE-CASES.md).
