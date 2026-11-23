# TX idle cases: how a stream can end, and what the transmitter does next

The test record behind [`docs/transmitter-safety.md`](docs/transmitter-safety.md)
for the modern target (Debian 13, Linux 6.12). One row per way a transmit stream
can stop, with the attenuation read back from sysfs on the board and, in every
measured row, a read taken while the stream was running, so that "muted
afterwards" is a change of state. It also records the affirmation gate, the boot
window, the power-on emission and the idle emission between streams, with each
result's status.

> **A second record exists: [`tools/IDLE-CASES.md`](tools/IDLE-CASES.md)**, for
> the factory userspace (Buildroot, busybox). It records the original defect (a
> killed local client left the transmitter live), cases A to F including the cyclic
> cases on that userspace, and the debugfs routes, none of which this file repeats.
> Where the two differ on a number, this file is the later measurement.

Terms: **attenuation** runs from 0 dB (full output) to −89.75 dB (the floor,
"muted"). `LO_pd` is `out_altvoltage1_TX_LO_powerdown` (1 = the transmit
synthesiser is off) and `buf` is the TX DMA buffer's `enable`. A **cyclic** buffer
is one block the hardware repeats forever. **dBFS** is decibels relative to the
receiver's full scale; **dBm** is absolute power at the connector.

## Conditions

- **Board:** Debian 13, Linux 6.12.0-g70fa2c6d3bdd-dirty, 3.071997 MSPS, TX LO
  900 MHz.
- **Bench for the termination cases:** TX1 → **20 dB** → RX1, checked with
  `./devkit selftest --loopback --pad 20`: *"declared 20 dB, measured 20 dB"*, and
  21 dB on a second run of the same cable (the selftest's declared-pad cross-check
  passes within ±8 dB and warns to 15, and 1 dB is inside its `%.0f`-rounded
  readout).
- **TX2 was keyed**, with its antenna removed and a pad moved onto it.
- **Levels:** the termination cases (rows 1–5) ran at **−30 dB on channel 0
  only**; the boot-window calibration ladder ran at **−55 to −20 dB**; the TX2
  ladder ran on channel 1. All are inside the contract's −10 dB cap:
  +19 dBm flat out − 30 − 20 ≈ −31 dBm at a port rated +2.5 dBm.
- **Cabling now:** TX1 → 20 dB → RX1 and TX2 → 30 dB → RX2, both checked by the
  selftest (declared 20 measured 20; declared 30 measured 30). The cabling changed
  several times during this work; measure it before relying on it.
- **Harnesses:** [`tools/tx-idle-cases/`](tools/tx-idle-cases/), with a README
  saying what each measures and how to run it. The one exception is the
  **withdrawn** idle-emission capture, whose script is lost; its
  [replacement](#idle-emission-measured-with-a-positive-control) is reproducible
  with `tools/tx-idle-cases/avg-level.py`, and its receiver gain is stated with the
  result.

Read back on the board with:

```bash
# run from: the board (ssh fishball)
cat /sys/bus/iio/devices/iio:device0/out_voltage{0,1}_hardwaregain
cat /sys/bus/iio/devices/iio:device0/out_altvoltage1_TX_LO_powerdown
cat /sys/bus/iio/devices/iio:device2/buffer/enable
```

## Stream-termination paths

**`buf` at the moment of the mute** says what did the muting: `1` means nothing
tore the stream down and the kernel's own watchdog muted it; `0` means the buffer
was disabled and the mute came with the teardown.

| # | how it was induced | during the stream | after | `buf` at mute | what muted it |
|---|---|---|---|---|---|
| 0 | baseline, nothing ever streamed | — | `-89.75` / `-89.75` | — | never unmuted |
| 1 | **normal close**: local `iio_writedev -s 9216000`, exits 0 by itself | `-30.000000` `LO_pd=0` `buf=1` | `-89.75` / `-89.75` `LO_pd=1` | **0** | buffer teardown |
| 2 | **network client killed**: `SIGKILL`, socket closes, FIN delivered | `-30.000000` `LO_pd=0` `buf=1` | `-89.75` / `-89.75` `LO_pd=1` | **0** | iiod's own cleanup |
| 3 | **starvation, client alive**: buffer open, fed 24 MB, then nothing, writer still running | `-30.000000` `LO_pd=0` `buf=1` | `-89.75` / `-89.75` `LO_pd=1` | **1** | kernel starve watchdog |
| 4 | **network drop**: TCP client of iiod, connection black-holed, **no FIN, no RST**, socket left ESTABLISHED | `-30.000000` `LO_pd=0` `buf=1` | `-89.75` / `-89.75` `LO_pd=1` | **1** | kernel starve watchdog |
| 5 | **local process killed**: `SIGKILL`, local backend, no iiod and no socket | `-30.000000` `LO_pd=0` `buf=1` | `-89.75` / `-89.75` `LO_pd=1` | **1** | kernel starve watchdog |
| 6 | **cyclic stream killed**: `SIGKILL` on a cyclic transmit | −30 dB, on the air at **+72.9 dB over floor** | **stays live with the bound off; muted 60 s after SUBMISSION with it armed** | 1 | the cyclic backstop, **armed at boot** |

Paths 1 to 5 end with **both** channels at maximum attenuation and the TX LO
powered down. Path 6 does not.

Time to mute, and the conditions:

| # | time to mute | `tx_starve_timeout_ms` | note |
|---|---|---|---|
| 1 | 2.65 s | 250 (default) | dominated by the remaining bounded samples playing out, not by any latency |
| 2 | 0.07 s | 250 (default) | iiod saw the disconnect and disabled the buffer |
| 3 | 1.95 s | 250 (default) | 250 ms after the 24 MB feed ran out; the rest is the feed |
| 4 | **0.24 s** | 250 (default) | uptime-to-uptime; see [the clock note](#case-4-timing-and-the-acceptance-criterion) |
| 5 | **0.26–0.27 s** (three runs on 6.12: 0.27, 0.27, 0.26) | 250 (default) | `kill -9` to mute, both processes confirmed gone with `ps` |

### Path 6: a killed cyclic stream

A cyclic transmit repeats one buffer in hardware with no software involvement, so
"no data arriving" describes a *healthy* cyclic stream, and the starve watchdog
exempts it. A `SIGKILL` on a cyclic transmit is therefore indistinguishable from a
normal return. `tx_cyclic_timeout_ms` bounds it, and reads **60000** on this
board: `fishball-rf-quiesce` sets it at boot, before `iiod` starts. The driver's
own default is `0`.

**On 6.12, in RF as well as sysfs.** A cyclic `iio_writedev` on TX2A carrying a
400 kHz tone at half scale, raised to −30 dB through the gate, then `kill -9` on
the client; run twice, identical but for the bound. Receiver: a HackRF on TX2A
through the bench's 30 dB pad, fixed at LNA 24 / VGA 20.

| after `kill -9` | bound **off** | bound **armed at 60 s** |
|---|---|---|
| transmitting, client alive | +72.98 dB over floor | +72.71 dB |
| 20 s | +72.94 | +72.75 |
| 50 s | +72.98 | +72.65 |
| 70 s | — | **+0.16**, at the noise floor |
| 90 s | **+72.94, still on the air** | +0.15 |

With the bound off the carrier is **unchanged to 0.04 dB ninety seconds after the
process died**. With it armed the carrier is gone by 70 s, down 72.5 dB. The sysfs
trace agrees: −30.000000 dB at 50 s, −89.750000 dB and the LO down at 60 s. The
buffer stays `enable=1` either way: the backstop mutes, it does not tear the
buffer down.

What this run does and does not establish:

- **The 60 s deadline runs from buffer submission, not from the kill.**
  `cf_axi_dds_tx_starve_arm()` does `mod_delayed_work(..., msecs_to_jiffies(ms))`
  on each *submitted block*, and a cyclic stream submits exactly one, so the timer
  is armed once, at submission. This run killed the client ~8 s in, so the two
  references are ~8 s apart and it **cannot distinguish them**. Status: open; a run
  that kills at t = 40 s would separate them.
- **It also mutes a healthy, unattended cyclic transmit at 60 s.** The timer does
  not care whether anyone is still there. That is a functional change as well as a
  safety one, and every streaming tool in this repo uses cyclic buffers.
  `sample_gpio_clock.py`, the one that holds a cyclic stream open indefinitely,
  says so when it starts.
- **The level is −17.4 dBm.** From the published floor (−88.2 dBFS) and `K`:
  `−88.2 + 72.98 = −15.22 dBFS → −17.39 dBm`. It inherits the calibration origin's
  error ([below](#the-calibration-and-its-origin)).
- **It is not an independent check on the absolute calibration.** Comparing the
  prediction `+19 − 6 (half scale) − 30` with the reading, the +19 and 30 dB terms
  cancel, leaving what doubling the digital amplitude gave: **5.6 dB** (−15.22
  against −20.83 dBFS), which closes on the amplitude convention (6.02 dB) and not
  the power one (3.01 dB). That is a relative check on the same instrument, gain
  and day. It establishes that `scale` is an **amplitude** factor, and that the DDS
  and DMA datapaths share a full-scale reference (the ladder is a DDS tone, path 6
  a DMA waveform). Only a power meter checks the absolute.
- **Run-to-run repeatability is 0.28 dB** (+72.96 mean against +72.70), seven times
  the within-run spread.

The older cases E and F in `tools/IDLE-CASES.md` ran on the *other* userspace
(`fw 95aad-dirty`, busybox); on this kernel they are superseded by the pair above.

**All four of this repo's streaming tools use cyclic buffers**:
`board.py transmit(cyclic=True)`, `sample_gpio_clock.py`, the selftest's `tx_tone`,
and `tx-gpio-bitmap-check.py`. So on this bench the cyclic kill is the ordinary
abnormal ending. Each tool mutes in its own cleanup, which a `SIGKILL` skips, and
that is why the backstop is armed at boot rather than left opt-in.

### Cases 2 and 4 differ in exactly one variable

A genuine drop delivers no FIN and no RST: the peer simply stops hearing anything.
Killing the writer closes the socket, so the FIN arrives and iiod tidies up; that
is case 2, not a drop. [`tools/tcp-blackhole.py`](tools/tcp-blackhole.py) produces
a real drop in userspace: it relays the connection and, on a sentinel, stops
copying bytes while **holding every socket open**, so from the board's side the
client vanishes mid-stream with the connection still up.

The two runs differ only in whether the FIN arrives, and take different paths to
the same place:

```
case 2, FIN delivered      kill -9 -> socket closes -> iiod disables the buffer
                           muted 0.07 s later, buf=0, socket gone from `ss`

case 4, no FIN             black-holed -> iiod notices NOTHING
                           both iiod sockets still ESTAB at and after the mute:
                             ESTAB 127.0.0.1:30431  users:(("iiod",pid=306,fd=12))
                             ESTAB 127.0.0.1:30431  users:(("iiod",pid=306,fd=13))
                           muted by the KERNEL, buf still 1
                           buf went 1 -> 0 only when the sockets were finally closed
```

**This closes the caveat on case D** in `tools/IDLE-CASES.md` ("clean in practice;
iiod explicitly disables the buffer after a disconnected client; not a kernel
guarantee"). With iiod still holding two ESTABLISHED sockets and the buffer still
enabled, the transmitter muted anyway.

The relay counts what it forwarded, which shows the stream was live when dropped:

```
[…] BLACKHOLED 2 flow(s) - no FIN, no RST; sockets held open;
    forwarded flow1 board->client 0.03 MB, flow2 client->board 2.95 MB
```

### Case 4 runs over loopback, not Ethernet

Case 4's client is a TCP client of iiod on the board's own loopback, not on the
host across Ethernet. Same rate, same 256 K-sample buffers, same 10 s, no relay in
either path:

```
direct over Ethernet from the host    underflows=5  starve_mutes=1
on the board over loopback            underflows=2  starve_mutes=0
```

The **host↔board Ethernet link cannot keep this DAC fed at 3.072 MSPS**, so over
Ethernet the watchdog fires within seconds with nothing wrong and there is never a
healthy stream to drop. Loopback sustains it. The mechanism under test is iiod's
socket lifecycle and the driver's response to it, which loopback exercises
identically; the transport is the one part of this case that is not the
real-world path.

The relay must copy in 1 MB chunks (`--chunk 1048576`). At 64 KB per
`recv`/`sendall`, the per-syscall overhead on this board's Cortex-A9 starves the
DAC through the relay, which looks exactly like the board being unable to keep up.
With 1 MB chunks the test runs at the default 250 ms timeout. The relay prints the
bytes it forwarded so that this failure is visible.

### Case 4 timing, and the acceptance criterion

The accepted run:

```
drop at /proc/uptime 13793.18 ; poller saw -89.75 at 13793.42   ->  0.24 s
[13793.338563] iio iio:device2: no transmit data for 250 ms - muting the transmitter
```

**The clock.** The 0.24 s is uptime against uptime, from the poller. The kernel
line is shown only as corroboration that the watchdog fired, because printk and
`/proc/uptime` are different clocks: bracketing a marker written to `/dev/kmsg`
with `/proc/uptime` reads, printk runs **0.075 to 0.080 s behind**:

```
uptime 14589.190..14589.200   printk 14589.120   offset -0.075 s
uptime 14589.240..14589.250   printk 14589.168   offset -0.077 s
uptime 14589.290..14589.300   printk 14589.215   offset -0.080 s
```

**The criterion.** The watchdog is re-armed on every submitted DMA block, so it
fires `timeout` after the **last block**, not after the drop, and the last block
precedes the drop:

```
0 < (mute - drop) <= timeout,   and   (mute - drop) = timeout - (drop - last block)
```

A delta *below* the timeout is therefore expected: 0.24 s against 250 ms says the
last block went in about 10 ms before the drop. What disqualifies a run is a delta
at or near **zero**, meaning the mute was already pending when the trigger was
pulled. One rejected run had the kernel log the mute at 12572.776818 against a drop
at 12572.83 (−0.053 s across clocks); corrected for the clock offset it is
+0.014 s, meaning the stream had stalled ~236 ms before the drop, and it stays
rejected.

**The delta does not carry this case.** Its residual uncertainty is tens of
milliseconds. What carries it is the state at the mute: `buffer/enable` still `1`,
all four sockets still `ESTAB`, the harness's ABORT guard having confirmed
`LO_pd=0` and no prior starve message, and `buf` dropping to `0` only when the
sockets were finally closed.

## Three mechanisms, and which cases each covers

Only one of the three survives a client that neither exits nor closes its socket.

| mechanism | fires when | cases | evidence |
|---|---|---|---|
| buffer teardown (`0004`'s postdisable mute) | the buffer is disabled: a normal close, or iiod cleaning up after a disconnect | 1, 2 | `buf=0` at the mute |
| iiod's client cleanup | iiod sees the socket close | 2 | socket gone from `ss`; `buf` 0 |
| kernel starve watchdog (`0015`) | no DMA data for `tx_starve_timeout_ms` | 3, 4, 5 | `buf=1` at the mute, `dmesg` names it |

```
iio iio:device2: no transmit data for 250 ms - muting the transmitter
```

## Two further findings

### A bare buffer enable raises TX output, with nothing affirmed

The kernel caches both channels' attenuation when a stream stops and re-imposes it
when the next buffer is enabled (`0004`, gated by `0005`'s `ad9361_tx_is_muted()`):

```
before anything                 atten0=-89.750000  LO_pd=1  buf=0
after a bare buffer enable      atten0=-61.500000  LO_pd=0  buf=1
```

A **28.25 dB raise**, performed by the kernel, on a board that read fully muted,
with no affirmation on record and nothing having asked for gain. The −61.5 dB was
the last value a previous stream had used (the loopback selftest's). Had that
stream been at −10 dB, opening a buffer would have put roughly +9 dBm at the SMA.

Two things bound it, and neither is the affirmation gate:

- **It can only restore a value some earlier stream used**, so it is bounded by the
  loudest gain used since boot. From a fresh boot the cache is seeded at probe
  (`firmware-modern/patches/0019`, which fixed a memset that made it restore 0 mdB,
  full output).
- **Ordering.** The mute hook snapshots whatever attenuation it finds and *then*
  sets maximum, so a tool that tears its buffer down before muting hands the cache
  its own loud value. `tools/tx-guard.sh reap` mutes first;
  `tools/sample_gpio_clock.py` did the opposite in its cleanup and is corrected.
  During a later real stream the cache restored silence:

  ```
  DURING a stream: atten0=-89.750000 atten1=-89.750000 LO_pd=0 buf=1
  ```

Status: **not fixed in the kernel**; mitigated by tool ordering and by the
post-enable check below.

### A large first block was muted before it arrived (fixed, `0022`)

The watchdog is armed when a buffer is enabled, and libiio enables the buffer
before it uploads the data. A 4.4 MB cyclic buffer (two channels at 40 MS/s,
Akil0515's signal generator, 2026-10-02) took longer than 250 ms to arrive:

```
iio iio:device2: no transmit data for 250 ms - muting the transmitter
```

then silence, the sample-locked markers gone, and the DAC underflow flag set,
because the mute also hands the DAC to the DDS - which reads exactly like a DMA
throughput ceiling. `0022` gives the first block 250 ms plus 1 ms per kB (capped
at 10 s); on 6.12 two channels then ran at 40, 50 and 60 MS/s, while a killed
streaming writer still muted at 280 ms and a never-fed buffer (64 KB) at 315 ms.

### After a starve mute, data arriving again unmutes (`0024`)

Until `0024` the starve mute was one-way. It also hands the DAC to the DDS, so
nothing drained the DMA afterwards: on an R1 (v2.4) and an R2 (v0.2), over libiio
USB, with zero samples at -89.5 dB (`tools/tx-idle-cases/resume-after-starve.py`):

```
feeding                      -89.50 / -89.50  LO_pd=0  source=DMA
paused 1.0 s                 -89.75 / -89.75  LO_pd=1  source=DDS
pushing into the same buffer FAILED: [Errno 110]
feeding again, same buffer   -89.75 / -89.75  LO_pd=1  source=DDS
a new buffer was REFUSED for 10.0 s: [Errno 16] Resource busy
```

Only a new connection transmitted again. That is what SDR Console showed its
user: one transmission per connection, the user LED lit (`0012` follows the
attenuator the program had just written) and nothing at the port.

With `0024` a block arriving after a starve mute re-selects the DMA source and
unmutes through the same call a buffer enable makes, and the block has already
re-armed the watchdog:

```
feeding                      -89.50 / -89.50  LO_pd=0  source=DMA
paused 1.0 s                 -89.75 / -89.75  LO_pd=1  source=DDS
feeding again, same buffer   -89.50 / -89.50  LO_pd=0  source=DMA
paused again                 -89.75 / -89.75  LO_pd=1  source=DDS
feeding a third time         -89.50 / -89.50  LO_pd=0  source=DMA
```

```
no transmit data for 250 ms - muting the transmitter
transmit data is back - unmuting the transmitter
```

A cyclic stream held for 3 s stayed unmuted on both boards, as before.

What is left of the old limit: while the transmitter is starve-muted and no data
is arriving, the driver considers it muted, so

```
atten0=-30.000000  LO_pd=1  buf=1     (gain written AFTER the watchdog fired)
```

a userspace attenuation write raises the attenuator and the driver does not
re-mute until data arrives and stops again, or the buffer closes.
**What stands in the way is the powered-down LO**: `LO_pd=1` means the oscillator
is off, so a raised attenuator with no stream is still a dead transmitter. This is
the one measurement where that second, independent layer carries the load on its
own.

## Raising attenuation does not by itself enable transmission

```
idle                        LO_powerdown=1   atten=-89.750000
after set-gain 0 -20        LO_powerdown=1   atten=-20.000000
```

`0004` powers the TX LO down when it mutes and brings it back on a DMA buffer
start, not on an attenuation write. So a leakage measurement taken after only an
attenuation write has nothing to find.

## The affirmation gate: which paths go through it

There is no antenna detector on this board: no coupler and no detector on either
transmit port. `tools/tx-guard.sh` records what a person says is on a port, **per
channel** (channel 0 is TX1A and channel 1 is TX2A, two separate SMAs; during this
work one had a pad on it and the other an antenna), and refuses to raise that
channel without it. The record lives in the board's `/tmp`, which is tmpfs, so a
reboot withdraws it.

`tools/tx_gate.py` is the host-side adapter, not a second gate: it shells out to
`./devkit tx-guard`, so there is one implementation of the rule, one store, and one
set of exit codes. A parallel gate keyed on `sys.stdin.isatty()` was deleted,
because `script -qec` walks straight through it.

Every demonstration below ran without a pipe, because a pipe makes `$?` report the
last command in it (which turns a refusal into `0`).

| invocation | exit | result |
|---|---|---|
| `tx-guard set-gain 0 -30`, unaffirmed | **3** | refused; attenuator still `-89.750000` |
| `tx-guard affirm 0` | 0 | recorded |
| `tx-guard set-gain 0 -30`, affirmed | 0 | written **and read back** at `-30.000000` |
| `tx-guard set-gain 1 -30`, unaffirmed | **3** | refused; ch1 is the antenna port |
| `tx-guard set-gain 0 5` | 1 | outside `[-89.75, 0]` |
| `tx-guard check 0` unaffirmed / affirmed / revoked | **3** / 0 / **3** | a query for tools that write their own attenuation |
| `tx-guard revoke both` | 0 | both forced to `-89.75`, verified |

**Four tools open a TX DMA buffer.** Three command output and are gated (below).
The fourth, `tools/tx-gpio-bitmap-check.py` (`./devkit gpio-check`), only ever
*writes* maximum attenuation, but it enables cyclic TX buffers, and a buffer enable
is a raise. It is not gated; it runs the same post-enable check as the others, on
**both** channels, and mutes before closing on its abort paths.

**The check runs on every enable, not only when a raise is requested.** Every
buffer enable in all four tools is followed by a read of **both** attenuators,
which fails on an unreadable value rather than assuming quiet. (Previously
`sample_gpio_clock.py`'s default invocation asked the gate nothing, opened a cyclic
buffer, and its docstring called that "safe: transmitter muted"; this file measures
that operation as a 28.25 dB raise.)

The three tools that command output, each refusing and accepting:

| tool | unaffirmed | affirmed |
|---|---|---|
| `./devkit selftest --loopback --pad 20` | **exit 1**, refused before the RF loopback's buffer (see the note on the internal one) | 32 passed, 0 failed, exit 0, unchanged |
| `./devkit selftest` (no `--loopback`) | 23 passed, exit 0, **untouched**; this is what CI runs | same |
| `tools/sample_gpio_clock.py --tx-gain -30` | **exit 1**, refused before any buffer was opened | mid-run sysfs read: `atten0=-30.000000 LO_pd=0 buf=1`; after exit `-89.75`, `buf=0` |
| `tools/modulation-gallery/board.py` `transmit(..., -30)` | raises `TxGateRefused` before any buffer was opened; `stop()` runs, both channels `-89.75`, `buf=0` | returns `-30.0`, verified over its own IIOD connection |

**The gate is asked before the buffer is created**, in all three. Asking after
would leave the buffer enable's raise in place for as long as the gate takes to
answer (`time ./devkit tx-guard check 0` → `real 0m0.836s`). Polling the board flat
out during each refusal, with `watch.sh` reading both channels and reporting
`unreadable` separately:

```
# run from: the board, while the tool runs on the host
selftest             buffer_ever_enabled=1  LO_ever_powered=YES  loudest_atten_either_channel=-89.750000  unreadable=0
sample_gpio_clock.py buffer_ever_enabled=0  LO_ever_powered=no   loudest_atten_either_channel=-89.750000  unreadable=0
board.py             buffer_ever_enabled=0  LO_ever_powered=YES  loudest_atten_either_channel=-89.750000  unreadable=0
```

`./devkit gpio-check` is not in this block: it never consults the gate, so it has
no refusal to poll. Its protection is the post-enable check.

**In the selftest row a buffer *was* enabled, by design.** `./devkit selftest` has
an *internal digital loopback* test that closes the loop inside the AD9361 and
sends a tone through both DMAs without it reaching the port. It opens a TX buffer.
Gating it would need an affirmation for `./devkit selftest`, which never transmits
and is what CI runs, so it is **checked, not gated**: immediately after the enable
both attenuators are read, and if the cache restore lifted either one, or either
cannot be read, the run mutes both channels and aborts. The check raises
`SystemExit`, which the surrounding `try/except Exception` cannot downgrade to a
WARN (a WARN exits 0), and it treats an unreadable attenuator as a failure. The
`loudest_atten_either_channel=-89.750000` above shows it did not raise, on this
board, with the cache holding maximum. The RF loopback section, which commands real
output, is gated, and is what the `exit 1` came from.

`board.py` powers the TX LO up in `configure_tx()` before it reaches the gate,
which is why its row reads `LO_ever_powered=YES`. That raises no output on its own
(the attenuators never left maximum, as the same line shows), but it differs from
`sample_gpio_clock.py`, and is left as it is.

**The supported claim:** no code path commands output without an affirmation, and
the one path that enables a buffer without one is verified not to have raised the
attenuators. That is weaker than "nothing was raised".

Gate details:

- **Quiet is never gated.** Muting must work when ssh is down, when no affirmation
  exists, and in a `finally:` after something has already gone wrong, so callers
  write maximum attenuation over their own connection.
- **Each tool re-reads the value over its own connection.** The gate reaches the
  board over ssh and the tools over libiio; if those resolved to different boards,
  the read-back catches it.
- **The gate reports the value it compared.** `tx_gate.py` refuses any read-back
  more than one 0.25 dB step from the request. (Before this, the gate printed a
  second, uncompared `cat` as "verified at" and the adapter returned it unchecked,
  so the starve watchdog firing between compare and report could hand a caller
  `-89.750000` as a success.)
- **The gate has a deadline.** A timeout is reported as a failure to reach the
  gate, never as permission. Without one a stalled ssh blocks the caller
  indefinitely, and the caller may already hold a DMA buffer, which is itself a
  raise.
- **The selftest is gated once per channel per run, not per write.** A loopback run
  raises attenuation dozens of times across the ramp and the linearity sweep. The
  check sits inside `set_tx_atten`, not beside the `--pad` prompt, so no caller can
  reach the attenuator by another route. `--pad 20` is not an affirmation: a number
  on a command line says what its author believed was in the path, not that
  somebody has just looked at the port.

## The boot window

This board runs Debian 13 with systemd, not Buildroot, so the `S21misc` *script*
that patch `0004` adds does not exist here. **Its `tx_quiesce` switch does.** On the
running board at the time, `/usr/local/sbin/fishball-rf-quiesce` line 26 read:

```sh
# on the running board (the overlay's current version sets QUIESCE=0 instead of exiting)
[ "$(fw_printenv -n tx_quiesce 2>/dev/null)" = "0" ] && exit 0
```

So `fw_setenv tx_quiesce 0` disables layer 2 on this root exactly as on Buildroot.
It is unset here, so the unit runs. The overlay's current script skips only the
mute on `tx_quiesce=0` and still sets the cyclic bound, which has its own switch
(`tx_cyclic_bound`). There are three layers:

| layer | covers | status |
|---|---|---|
| 1 device tree `adi,tx-attenuation-mdB` | from `ad9361.c:5326` on; **not** the TX calibration at `:5308`, which has already transmitted ([power-on emission](#the-capture-was-taken-and-the-boot-window-is-not-quiet)) | **live: `89750`** (89.75 dB), read from `/proc/device-tree/axi/spi@e0006000/ad9361-phy@0` |
| 2 `fishball-rf-quiesce.service` | from then until a DMA buffer starts | `Result=success`, journal: *"both transmitters at −89.75 dB"* |
| 3 kernel `0004` / `0015` | unmute on stream start; on stop or starve, re-mute **and power the TX LO down** | the termination cases above; `out_altvoltage1_TX_LO_powerdown` reads **1** while idle |

Timing on that boot, from systemd and the kernel log:

```
ad9361 probe complete            1.688 s   (chip live, device tree already applied)
fishball-rf-quiesce ran         14.664 s -> 14.897 s   Result=success
```

Layer 2 does not begin for **≈13 s** after the chip is alive, and across that gap
the transmitter is held at 89.75 dB by **layer 1**. The figure is given to one
significant figure because the two numbers come from different clocks (systemd's
`CLOCK_MONOTONIC` and printk, ~77 ms apart here and more across the early-boot
`sched_clock` switchover); layer 1 covers the gap whatever its exact length.
`adi,tx-attenuation-mdB` is `0x2710` (10 dB, ADI's default) in the factory tree at
`patches/0002:287`; `firmware-modern/dts` raises it to `89750`, and the board runs
the latter.

The unit's result, from systemd rather than the kernel ring buffer, so it does not
depend on anything that can be cleared:

```
# run on the board
$ systemctl show fishball-rf-quiesce.service -p Result       -p ExecMainStartTimestampMonotonic -p ExecMainExitTimestampMonotonic
Result=success
ExecMainStartTimestampMonotonic=14663959
ExecMainExitTimestampMonotonic=14897439
$ journalctl -b -u fishball-rf-quiesce
fishball-rf-quiesce: both transmitters at -89.75 dB
```

**No ordering cycle on that boot.** systemd can delete a unit to break a dependency
cycle, and the unit's own comment records a boot where it deleted this one. Checked:
`journalctl -b | grep -ci "ordering cycle"` → `0`, and nothing matching "deleting
job" or "breaking ordering cycle".

**Re-checking the 1.688 s probe time.** `dmesg -C` between the termination cases
discarded the line from the kernel's ring buffer, but journald had captured it, and
it keeps the kernel's own timestamp separately from its receipt time:

```
# run on the board
$ journalctl -k -b 0 -o export | grep -B40 "successfully initialized" \
      | grep -E "^_SOURCE_MONOTONIC_TIMESTAMP|^__MONOTONIC_TIMESTAMP"
__MONOTONIC_TIMESTAMP=9021648          <- journald's receipt time
_SOURCE_MONOTONIC_TIMESTAMP=1688130    <- the kernel's printk timestamp: 1.688130 s
```

Pitfall: `-o short-monotonic` prints `__MONOTONIC_TIMESTAMP`, journald's arrival
time, which is `9.021648` here because journald started at 8.003 s and restamped
everything it read from the ring buffer, so a casual check finds `9.02` and
disagrees with this file by 7.3 s. Read `_SOURCE_MONOTONIC_TIMESTAMP`.

**Stale comment on the board.** The comment inside the deployed
`fishball-rf-quiesce` on the board described layer 1 as covering "the instant
`ad9361_setup()` runs" (`grep -c "covers the instant"
/usr/local/sbin/fishball-rf-quiesce` → `1`). The overlay in
`firmware-modern/debian/overlay/` is corrected; the board keeps its copy until the
root filesystem is rewritten.

### The capture was taken, and the boot window is NOT quiet

A HackRF One was cabled to TX1 through the same 20 dB pad and recorded
continuously across power cycles. It takes a second receiver, because the board's
own receiver powers up with the board.

**Every power-on produces a short, strong, narrowband burst at the transmitter's LO
frequency, about 1 second after power is applied:**

| power cycle | when | duration | peak | above both control bands |
|---|---|---|---|---|
| first | t = 107.026 s | 8 blocks ≈ **4.1 ms** | ≥ ceiling | **+50.5 dB** |
| second | t = 155.054 s | 7 blocks ≈ **3.6 ms** | ≥ ceiling | **+50.9 dB** |

Durations are whole multiples of the analyser's 0.512 ms block, so they carry
±0.5 ms. The second burst is 1.05 s after that boot (power-on at t = 154 s, from the
board's own `/proc/uptime` read afterwards). Nothing else in 210 s of recording
exceeds either control band by more than a few dB, and the board-unpowered
stretches of the same recording are the zero reference.

**It is the transmitter, not a power-on click.** A broadband switching transient
would lift every band together. In 5 ms steps with the DC offset removed, against
two control bands 1.0 and 3.0 MHz below the TX LO:

```
     t(s)       TX 2400.00   ctl 2397.00   ctl 2399.00
  106.389         -83.2         -82.6         -83.0      quiet
  106.394         -19.1         -70.3         -70.6      NARROWBAND at the TX LO
  106.398         -13.1         -63.9         -62.9      NARROWBAND at the TX LO
  106.403         -83.1         -82.1         -82.6      quiet
```

Both control bands are on the same side, because at 4 MSPS centred 1.5 MHz under
the LO there is no room above it. The test rejects a click across the whole span,
but would not reject an event confined to the half-band above the LO.

**How strong.** Calibrated against deliberate transmissions through the same cable
and pad, with the identical method, so the pad's value cancels:

```
  atten -55 dB -> -48.0 dBFS      atten -25 dB -> -18.1 dBFS
  atten -45 dB -> -38.2 dBFS      atten -20 dB -> -13.0 dBFS   (max|sample| 88, no clipping)
  atten -35 dB -> -28.1 dBFS
  fit: dBFS = 1.0007 x atten + 6.95, worst residual 0.11 dB over 35 dB
```

The burst saturated the receiver: its −4.1 / −4.4 dBFS readings are the analyser's
clip ceiling, not a level. So the supported result is **at or above the loudest
calibrated point, an equivalent commanded attenuation of −20 dB**, with no upper
bound until the capture is re-run at lower receiver gain. That equivalence also
rests on an unrecorded receive gain (the boot capture's LNA/VGA were not written
down); the separation from the control bands is within one capture and does not
depend on it. The qualitative result, a strong narrowband burst at the TX LO on
both ports at every power-on, ~50 dB above two control bands, depends on none of
this.

**The mechanism is normal AD9361 behaviour, not a bug:**

```
ad9361.c:5308   ret = ad9361_tx_quad_calib(phy, real_rx_bandwidth, real_tx_bandwidth, -1);
ad9361.c:5326   ret = ad9361_set_tx_atten(phy, pd->tx_atten, ...);
```

The TX **quadrature calibration** generates an NCO tone and loops it through the
receiver to measure and correct transmit I/Q imbalance. Transmitting is the
mechanism, not a side effect: the function aborts if the TX LO is in powerdown
(*"Tx QUAD Cal abort due to TX LO in powerdown"*). It is ADI's reference code and
every AD9361 design runs it at init. There is no software fix: muting first would
leave nothing to calibrate. `calib_mode = manual_tx_quad` gates only the
*re*-calibration at `ad9361.c:5425`; the boot call at `:5308` is unconditional.

`adi,tx-attenuation-mdB` covers everything after `:5326` and nothing before it.
`firmware/patches/0011` and the modern device tree set that constant to maximum,
which is why the board is silent *once booted*, but not during the calibration.

**Why it matters on this board.** A calibration tone is unremarkable on a bare
AD9361. This board has a **PGA-102+ power amplifier** on transmit, so the tone
leaves the SMA amplified, loud enough to saturate a receiver through 20 dB of pad.

> **The PA gain to use here is ≈14.0 dB at 2.0 GHz and less above it**, from the
> PGA-102+ datasheet table in `docs/transmitter-safety.md`. It is not the 15.7 dB
> the selftest prints for 900 MHz, which is `pa_gain_db()` interpolating that
> table (not a measurement) and is roughly 2 dB optimistic at the burst's
> frequency, in the opposite direction from the clipping bound. `sdr_selftest.py`'s
> `PA_GAIN_DB = 18.0` sits above every value in the table (max 17.7 dB at 50 MHz),
> which makes it conservative for a power *budget* (the selftest's own tests assert
> `>= 17.7` for that reason) and wrong as a gain at 2.4 GHz. No one has put a power
> meter on this port.

**Status:** this board's PA makes a standard calibration audible at the connector,
and no userspace mechanism can reach it.

### TX2A does it too

The 20 dB pad and the receiver were moved from TX1 to TX2 and the power cycle
repeated. The prediction was recorded before the run and held:

| | TX1A | **TX2A** |
|---|---|---|
| duration | 4.1 ms / 3.6 ms | **4.6 ms** |
| peak | −4.1 dBFS | **−4.4 dBFS** |
| separation from both control bands | +50.5 / +50.9 dB | **+50.7 dB** |

The duration difference is one analyser block, not a real difference. Both peaks
are at the analyser's clip ceiling, where a 34 dB span of true input reads the
same, so their agreement says nothing about whether the ports are equally strong.
What the pair establishes is that **both ports emit**, at a level that saturates a
receiver through a pad. Both transmit chains are configured on this board
(`adi,2rx-2tx-mode-enable` is in the live device tree and the DDS core exposes all
four `out_voltage0..3` scan elements), and the calibration covers both.

Only one of the two power cycles was captured for TX2: the recording was truncated
at 98 s of an intended 350 s when the host's disk quota filled. One clean event on
TX2, two on TX1.

**The consequence for a bench.** TX2A on this board is the port that had an antenna
fitted. So plugging the board in **radiates** a few milliseconds around 2.400 GHz
at a level that saturated the measuring receiver through 20 dB of pad (at or above
an equivalent commanded attenuation of −20 dB, unbounded above), every time,
before any userspace exists. It is in the 2.4 GHz ISM band and the duty cycle is
negligible, so this is something to know about rather than a licensing problem.
`tx_quiesce`, the affirmation gate and every userspace mechanism in this repo act
far too late to affect it. The only mitigation is operational: **do not leave an
antenna on a transmit port you do not want radiating at power-on.**

## Idle emission, measured with a positive control

TX2A, HackRF One on that port through the bench's 30 dB pad, receiver **fixed at
LNA 24 / VGA 20, front-end amp off, 4 MSPS**, with that gain unchanged for every
capture including the controls.

### Preconditions

- **The termination harnesses are not an RF source.** `cases123.sh`, `case5.sh` and
  `case4b.sh` feed `/dev/zero`. I = 0, Q = 0 is not a signal; the DAC emits nothing
  but residual leakage. Used as a positive control, a harness gives **+0.40 dB at
  the TX LO while the attenuator reads −30 dB**, indistinguishable from idle. Those
  scripts prove the mute through the attenuator read-back, which is valid for their
  question and useless for this one. The control here is a real DDS tone.
- **Receiver gain, not the pad, sets the sensitivity.** LNA 0 / VGA 0 stops ambient
  2.4 GHz Wi-Fi clipping the ADC but throws away about 32 dB of input-referred
  sensitivity. Wi-Fi arrives in bursts, so the analysis keeps the gain and rejects
  any 4096-sample block reaching |s| ≥ 120 of 127, reporting the fraction dropped.
  At LNA 24 / VGA 20 that fraction was 0.0 % in every capture below.
- **Average, or noise reads as a signal.** The maximum of one 2048-bin FFT of pure
  noise sits 8–16 dB above the median. A single-FFT reading showed a "+15 dB bump"
  at the TX LO on a muted board; averaging 4000 FFTs collapsed it to 0.2 dB, and the
  peak moved to a different random offset from each receiver centre.
  `cs8-level.py` reports a single-FFT peak and will do this.

### The ladder

DDS tone on TX2A at 400 kHz, scale 0.25, stepped through the gate, read back from
sysfs at every step:

| commanded | read back | tone | excess over floor |
|---|---|---|---|
| −30 dB | −30.000000 | −20.83 dBFS | +67.19 |
| −50 dB | −50.000000 | −41.05 dBFS | +47.27 |
| −60 dB | −60.000000 | −51.18 dBFS | +37.07 |
| −70 dB | −70.000000 | −61.25 dBFS | +27.12 |
| −80 dB | −80.000000 | −71.00 dBFS | +17.22 |
| −89.75 dB | −89.750000 | −80.01 dBFS | +8.21 |

**The attenuator is linear to better than about 0.2 dB over 60 dB.** Step by step
the deviations are +0.22, +0.13, +0.07, −0.25 and −0.74 dB. The last is the
analyser not subtracting its own floor: at +8.21 dB excess the bin holds signal
*plus* noise, `10·log10(10^0.821 − 1) = 7.50 dB`, so the true signal is
`8.21 − 7.50 = 0.71 dB` below the reading. Predicted 0.71 dB against observed
0.74 dB.

Excess over floor is therefore **not** signal power near the floor. Signal levels
in this file are quoted floor-subtracted, and `tools/tx-idle-cases/avg-level.py`
prints the formula in its docstring. **The idle bound is the exception**: it is
quoted as the raw floor, because with no demonstrated detection threshold a
floor-subtracted non-detection (≈ −105 dBFS) would claim a sensitivity nothing here
established.

### The calibration, and its origin

At −30 dB commanded with scale 0.25 the port level was taken as
`+19 dBm − 12 dB (scale) − 30 dB (atten) = −23 dBm`, which read −20.83 dBFS, giving
**dBm at the SMA = dBFS − 2.17** (`K`).

**That origin is misused.** `+19 dBm` is not a level: in
`tools/selftest/sdr_selftest.py` it is `PA_P1DB_DBM + 1.5 = 17.5 + 1.5`, a
datasheet constant that **caps** the estimate at the amplifier's compression
point. [`docs/measured-performance.md`](docs/measured-performance.md) says to use
+19 dBm as a safe upper figure for planning, not as an output power. A compression
cap cannot be the origin of a 42 dB linear backoff. The correct origin is the
*linear* chain level, which is higher whenever the cap bites: the AD9361's
~+7 dBm plus the PGA-102+'s ≈14 dB at 2 GHz, near **+21 dBm**. So `K ≈ −0.2` rather
than −2.17, and every dBm figure derived here is **about 2 dB optimistic, the
unsafe direction for a bound on emission.** It cannot be corrected by arithmetic,
because the linear origin is itself an estimate. Status: open; **one power-meter
reading on TX2A at the −30 dB ladder point settles it**, and no one has put a meter
on this port.

Scale convention: `dds-tone.sh` sets the I and F1 channels to `scale` in
quadrature, and `scale` is an **amplitude** factor, so 0.25 is
`20·log10(0.25) = −12.04 dB`, not `10·log10`.

### The result

Capture: **centre 2399.4 MHz, 4 MSPS, 60 s**, analysed by
`tools/tx-idle-cases/avg-level.py` with **nfft 4096 → RBW 977 Hz**, averaging
~43,000 periodograms, 0.0 % of blocks discarded for clipping. With the transmitter
idle (no DMA buffer, every DDS scale read back at 0, TX LO powered down, attenuator
read back at −89.75 dB) nothing at 2400.400 MHz rises above the floor (+0.08 dB).
The floor was −88.1 dBFS.

> **Away from 2400.000 MHz, idle emission through the transmit path on TX2A is below
> roughly −87 dBm at the SMA, in a 1465 Hz noise bandwidth, in the 50 kHz window
> around 2400.400 MHz; at 2400.000 MHz, probed separately, the bound fails.**

Each qualifier matters:

- **"roughly −87"**, not −89: the origin is 2 dB optimistic (above), and the figure
  moves with whatever a power meter eventually says.
- **"in a 1465 Hz noise bandwidth"**: 977 Hz is the bin *spacing*, and the Hann
  window's equivalent noise bandwidth (ENBW) is 1.5 bins. Against a synthetic
  capture of known power, `avg-level.py` under-reads a tone by 6.02 dB and noise in
  one ENBW by the **same** 6.02 dB, so a constant calibrated from a tone gives the
  floor's power in 1465 Hz with no correction term. Integrated over the 4 MHz
  captured, this floor permits
  `−87 + 10·log10(4·10⁶/1465) ≈ −87 + 34.4 ≈ −53 dBm` of *broadband* emission, and
  broadband noise from a PA on a powered chain is exactly what would hide there.
  This bound does not constrain it.
- **"in the 50 kHz window around 2400.400 MHz"**, not the 4 MHz captured.
  `avg-level.py` takes the *maximum* only within ±25 kHz of the target and the
  *median* everywhere else, and a narrowband line elsewhere does not move a median
  (which is why the 2400.000 MHz line was found only by targeting it). **The 4 MHz
  was never scanned for peaks**, and 4 MHz is 0.07 % of this transmitter's tuning
  range.
- **"away from 2400.000 MHz"**: see the next section.

**This is a non-detection, with no demonstrated detection threshold.** The positive
control's weakest point was −80.01 dBFS ≈ −82 dBm at the SMA; nothing shows that a
signal between −82 and −87 dBm would have been seen. Taking the ladder below the
floor needs `dds-tone.sh`'s hard-coded `scale 0.25` parameterised down to 0.025 and
0.008. Status: not done.

**The pad costs 30 dB of sensitivity here.** The floor is −88.17 dBFS with the input
*open* and −88.1 dBFS through the cable and the 30 dB pad, so the floor is the
receiver's own, not thermal from the source. The pad protects the receiver from an
accidental transmit, but in the *idle* capture the transmitter is off by
hypothesis. A null taken with 10 dB or no pad would give a bound some 30 dB tighter
at no cost to the floor. Status: not taken.

### At 2400.000 MHz there is a line of unknown origin

A line sits at exactly 2400.000 MHz at −76.7 dBFS, +11.5 dB over the floor. Three
controls establish what it is **not**, each narrower than it looks:

| control | what it excludes | what it does **not** |
|---|---|---|
| attenuator swept 60 dB (−76.71 / −76.72 / −76.69 / −76.55 dBFS at −89.75 / −70 / −50 / −30) | the transmit **signal path** | a board clock harmonic coupling onto the SMA trace, the PA supply, or the cable, none of which passes through the attenuator |
| RX LO retuned to 2399.8 and 2400.2 MHz: it stays pinned | DC leak, IF- and baseband-fixed artefacts | anything at a fixed **RF** frequency, which is what *both* candidate sources are |
| receiver input opened: still −80.17 dBFS, +8.0 over floor | a strong **conducted** external source | radiated pickup (an open SMA is an antenna) and mismatch-induced level change |

None of the three tests the board. The candidates:

| candidate | arithmetic at 2400.000 MHz | where it lives |
|---|---|---|
| HackRF 25 MHz reference | 96 × 25 = 2400.000 | the instrument |
| **Board's `Y3` 40 MHz VCTCXO** | **60 × 40 = 2400.000** | **the board** |
| USB 2.0 high speed | 5 × 480 = 2400.000 | both |

Of the five frequencies probed, **2400 MHz is the only exact multiple of 40, and it
carries the 7 dB excess** over its neighbours (+2.13, +0.73, **+8.02**, +2.14,
+3.74 dB at 2350, 2375, 2400, 2425, 2450). The comb period is not established:
every probe is a multiple of 25, so a 25 MHz comb was never distinguished from a
50 MHz one, and the data fit 50 MHz better.

**At 2400.000 MHz the idle bound fails.** Connecting the cable adds, by incoherent
subtraction, `−76.71 → 2.132e−8`, `−80.17 → 9.617e−9`, difference `1.170e−8` =
**−79.3 dBFS ≈ −81 dBm at the SMA**, above the −87 dBm bound. The coherent worst
case still leaves ≈ −88.6 dBm. So there is an unexplained **cable-dependent
component at exactly the frequency the transmitter's carrier would appear**, at or
above the bound.

The four attenuator readings are monotone, and the whole 0.16 dB of movement is in
the loudest step. An additive transmit-path component of ≈ −91 dBFS raises a
−76.7 dBFS line by exactly that, so: **no more than about −91 dBFS reaches this line
through the transmit path.**

Status: **open.** Three measurements would settle it, none taken:

1. **Capture 2400.000 MHz with the board powered off.** Unchanged means the
   instrument. Changed means the board, by a path that bypasses the attenuator.
2. **Terminate the receiver input in 50 Ω** instead of leaving it open, which
   removes both the accidental antenna and the mismatch.
3. **Measure the line's offset in Hz.** An instrument-generated spur sits at
   *exactly* the nominal frequency as the receiver reckons it, because one clock
   sets both tuning and spur. A 2400.000 MHz signal from the board arrives offset
   by the difference between two independent crystals: at ±10 ppm that is ±24 kHz,
   about 25 bins at 977 Hz RBW. `tools/clock-cal.py` already measures this board's
   offset.

> **Pitfall, whoever owns the line.** A 2.4 GHz measurement of this board with a
> HackRF has *something* on 2400.000 MHz at −76.7 dBFS, and there present and
> absent read alike, as they do on the receiver's DC leak. Offset the receiver from
> the frequency under test, and measure the offset in Hz rather than trusting the
> label.

## Withdrawn and corrected results

Kept so that a figure quoted elsewhere can be traced. None of these stands.

| withdrawn | why | what stands instead |
|---|---|---|
| the earlier idle-emission measurement: −56.0 dBFS transmitting against −88.9 dBFS idle, a 32.9 dB ratio, a 20.8 dB figure, and dBm figures derived from them | the two captures' receive gain was never recorded and their floors differed by 15.6 dB, which is what a gain change looks like; the script is lost, so it cannot be re-run | [Idle emission, measured with a positive control](#idle-emission-measured-with-a-positive-control) |
| power-on burst ≈ +8 dBm at the SMA (−4.1 dBFS mapped through the ladder fit to −11.0 dB equivalent) | −4.1 dBFS is the analyser's clip ceiling: a synthetic tone at amplitude ×2 and ×100 (a 34 dB span) both read −4.39 dBFS with 3072 samples pinned. The mapping also extrapolated the fit 8.9 dB past its loudest point (−13.0 dBFS at −20 dB) | at or above an equivalent −20 dB, no upper bound |
| burst "reproducible to 0.4 dB across two cycles" and "TX1 and TX2 within 0.3 dB" | two saturated readings must agree | both ports emit; relative strength unknown |
| "an ordering problem in the driver"; reorder `ad9361_setup()` so attenuation precedes the calibration | the calibration must transmit to work; muting first leaves nothing to calibrate | no software fix |
| `register 0x002 = 0xEC` as the chip state during the burst | that read happened later and needs a debugfs write, so it cannot describe the burst | the device tree and the TX2A capture |
| `adi,tx-attenuation-mdB` covers "the instant `ad9361_setup()` runs" | the calibration at `:5308` precedes it at `:5326` | layer 1 covers from `:5326` on |
| "`board.py` `transmit(..., pair=1)` does not transmit on TX2", and "no TX2 measurement through `board.py` was real" | `tools/modulation-gallery/campaign.py` is `CH = 1`, drives `board.py` on TX2A at 866.5 MHz, and produced `docs/modulation-gallery.md`; `git log -L` shows `mask_for([2, 3], total)` unchanged since. Re-measured through TX2 → 30 dB → RX2: `pair=1 @ 866.5 MHz, 4.000 MSPS, atten -16 dB` tone 89.7 dB over the noise floor; `pair=1 @ 2400.0 MHz, 3.072 MSPS, atten -30 dB` (the original configuration) 88.8 dB. The original observation (a hardware-DDS tone on TX2 came through, a `board.py` DMA transmit did not) did not reproduce, on an evening with two confirmed cabling errors (the loop was on RX2 at one point) | `board.py` transmits on TX2. The TX2 boot-burst result is unaffected: it is a receive measurement, and its conducted path is established by the DDS ladder tracking attenuation at 1.0 dB/dB over 30 dB |
| "this board cannot keep a network transmit stream fed at 3.072 MSPS", and a case-4 run at `tx_starve_timeout_ms` = 2000 | the relay at 64 KB chunks was the bottleneck | 1 MB chunks, default 250 ms; the 2000 ms figure is not quoted |
| three earlier case-4 attempts, one reading "muted 0.02 s after the drop" | the mute preceded the drop (kernel log −0.053 s); these measured starvation, not a drop | the accepted run, 0.24 s |
| a "client vanishes" row that killed the writer | killing the writer closes the socket, so it is case 2 | case 4 via `tcp-blackhole.py` |
| "kernel log and `/proc/uptime` are the same clock"; case 4 at +0.159 s; "a positive delta proves causation" | printk runs 0.075–0.080 s behind; a delta under the timeout is expected | [Case 4 timing](#case-4-timing-and-the-acceptance-criterion) |
| an earlier `watch.sh` block quoted as proof that nothing was raised | that watcher read channel 0 only, seeded its maximum at −89.75 so an unreadable channel looked quiet, and had no read-failure branch | the current block, both channels, `unreadable` reported |
| the selftest's post-enable check "fails loudly" | it raised `RuntimeError` inside a `try/except Exception` that downgraded it to a WARN (exit 0), and skipped an unreadable attenuator as muted | now `SystemExit`, unreadable is a failure |
| path 6 level −17.1 dBm | required a floor of −87.9 dBFS that was never published | −17.4 dBm |
| path 6's 0.1 dB agreement with `+19 − 6 − 30` as "confirmation of the absolute" | the +19 and 30 dB terms cancel; it is a relative check | `scale` is amplitude; DDS and DMA share full scale |
| "0.57 dB end-to-end residual" as the ladder's linearity | the last step is inflated by the uncorrected floor | linear to about 0.2 dB over 60 dB |
| "977 Hz bin" as the bound's bandwidth | 977 Hz is bin spacing; ENBW is 1465 Hz; the label was 1.76 dB optimistic | value unchanged, label 1465 Hz |
| the 2400.000 MHz line is "the HackRF's own 25 MHz reference, 96 × 25 MHz" | names only the candidate that exonerates the board | origin open; three candidates |
| "`tx_quiesce` has no off switch on this root" | the deployed script reads it | `fw_setenv tx_quiesce 0` works |
| "the 1.688 s probe time cannot be re-checked" | journald keeps `_SOURCE_MONOTONIC_TIMESTAMP` | re-checked: 1.688130 s |
| 15.7 dB as the PA gain at the burst | that is the 900 MHz interpolation | ≈14.0 dB at 2.0 GHz |
| file header: "TX2 has an antenna and was never keyed here" | the body records TX2 keyed with its antenna removed and a pad fitted | TX2 was keyed |

## Status against the contract

| requirement | state |
|---|---|
| stream-termination paths enumerated and read back | **done, all six**: paths 1 to 5 each with a during-stream read-back and the `buf` state at the mute; path 6 on this kernel, in RF as well as sysfs, with the cyclic bound off (still on the air at +72.9 dB after 90 s) and armed (at the noise floor by 70 s) |
| a genuine network drop, distinct from a client being killed | **done**: cases 2 and 4 differ only in whether the FIN arrives, both at the default 250 ms |
| the local-process path `0015` exists for | **done**: case 5, 0.26–0.27 s at the default timeout, `buf` still 1 |
| transmitter provably silent in every idle condition | **partly**. Paths 1 to 5 are quiet by **attenuator and LO read-back only; no RF capture was taken per path**, and they ran at 900 MHz while the RF null was taken at 2400 MHz on TX2A in the *no-buffer* state, which is not the state cases 3, 4 and 5 end in (`buf=1`, datapath switched to the DDS). Path 6, the killed **cyclic** stream every streaming tool here uses, is bounded 60 s after submission by a backstop armed at boot and checked on the air. The idle emission between streams has a **non-detection** with a positive control and a recorded gain: below roughly −87 dBm at the SMA on TX2A, in a 1465 Hz noise bandwidth, in a 50 kHz window, with no demonstrated threshold below −82 dBm, resting on an origin the repo says not to use this way, **and it fails at 2400.000 MHz**, where an unexplained cable-dependent component sits at or above it. The boot window has a capture, which found an emission rather than silence |
| continuous capture across a power cycle | **done, and it failed**: a HackRF through the same pad recorded power cycles on **both** transmit ports; each produced ~4 ms at the TX LO about 1 s after power-on, at or above an equivalent commanded attenuation of −20 dB (the receiver saturated, so no upper bound was established). The contract's "nothing above the noise floor outside deliberate transmissions" is **not** satisfied, on either port |
| no code path raises attenuation without an affirmation | **partly**: the three in-scope host tools are gated and demonstrated; the kernel's cache restore and the out-of-scope paths in rows 1 and 4 of this table are not |
| two consecutive adversarial reviews, no medium-or-above findings | **not met**; see the next section |

## Adversarial review rounds

Eight rounds ran against this work. Every finding was fixed and the fix checked on
the board. **Two consecutive clean rounds were never achieved, and the count did not
converge.** The loop was stopped after round 8, not because it converged: the board
was unavailable and no affirmation was on record, so a ninth round's fixes could not
be exercised on hardware.

| round | findings | what they were |
|---|---|---|
| 1 | several | the termination table's first version; retracted measurements |
| 2 | several | the case-4 attempts that measured starvation instead of a drop |
| 3 | several | the gate's fail-open paths |
| 4 | 11 medium | fixed in `73f1247` |
| 5 | 11 | fixed in `26f8fb5` |
| 6 | 3 high, several medium and low | fixed in `329a236` and the commit that follows it. Two of the three high findings were in code written in response to round 5; the third was a `_tx_affirmed.update({0, 1})` in both verify scripts that made the affirmation gate a no-op while their README said they refuse |
| 7 | **15 high** across four reviewers, plus ~40 medium and low | shell traps that never fire on dash, a `dds-tone.sh` action check where anything but `off` energised, a buffer enable outside its own try/finally, a selftest reporting HEALTHY with an unproven mute, and most of the arithmetic in the idle-emission section. |
| 8 | **high findings from all three reviewers** | **three inside round 7's own fixes**: a trap list widened without an `exit`, so the handler ran and the script carried on into the next case and re-raised; a `rep.add` called with the wrong arity, so the FAIL meant to stop a HEALTHY verdict never counted; and a resolution bandwidth the analyser's docstring claimed but did not deliver |

Rounds 1 to 3 predate per-round bookkeeping, and their counts were not recorded.
From round 4 on the count is the one the round reported. Rounds 7 and 8 each found
more HIGH findings than rounds 4, 5 and 6 combined.

**Rule drawn from round 8:** check a fix by executing it. Round 7's fixes were
checked with `sh -n` and `py_compile`, which prove a file parses and nothing else,
and both of round 8's worst regressions were behavioural (a trapped signal resumes
rather than exits; `Report.add(group, name, verdict, …)` takes the group first). A
single run would have caught either.

## Traps for whoever measures here next

Each of these produced a confident wrong answer first. The shell-trap rules are also
in [`docs/transmitter-safety.md`](docs/transmitter-safety.md#rules-for-programs-that-transmit),
as rules for any program that transmits.

**Compare the kernel's timestamp against your trigger, on one clock.** A poller
that waits for `-89.75` will report "muted 0.02 s after the drop" when the
transmitter muted before it. printk runs 0.075–0.080 s behind `/proc/uptime`. The
watchdog fires `timeout` after the last submitted block, which precedes the
trigger, so `0 < delta <= timeout` always; a delta near **zero** disqualifies a
run. Do not ask a tens-of-milliseconds subtraction to carry a conclusion that the
state at the mute (`buffer/enable`, the sockets, `LO_pd`) carries better.

**A TX stream over the host↔board Ethernet link starves on its own.** At
3.072 MSPS with 256 K-sample buffers it takes one starve mute inside 10 s, with
nothing wrong and no relay in the path; the same test over the board's loopback
takes none. Run the client of any test that needs a *healthy* network stream on the
board, and check `LO_pd` and `dmesg` before believing the stream was live.

**Suspect your own instrument before the board.** A relay copying 64 KB at a time
starved the DAC and produced a plausible wrong conclusion. Anything between the
client and the radio is part of the measurement.

**A killed client leaves the buffer enabled, and the next client cannot open it.**
Case 5 leaves `buf=1` with no owner; the following test then fails with
`Open unlocked: -32` before streaming a byte, which looks like a network-drop
result. Run `./devkit tx-guard reap` between cases and assert `buffer/enable` is
`0` before starting.

**`settimeout` on a socket applies to the whole socket.** A 50 ms recv timeout in
one direction of a relay made `sendall` raise `socket.timeout` in the other as soon
as the send buffer filled, silently tearing the stream down. Use `select` for
readiness and leave the socket blocking for sends.

**libiio opens a second socket per buffer.** A one-connection relay passes
`iio_info` and fails every stream, as an unexplained client-side
`Open unlocked: -32`.

**Do not use `sleep` immediately after `kill -9`** on a background job in a shell
whose `sleep` is a builtin: it returns instantly on `SIGCHLD` and you read the
attenuation ~10 ms after the kill, before the mute. Poll `/proc/uptime` instead.
Debian's `/bin/sleep` is external and does not have this problem; busybox's does.

**Pin the sample rate at the top of a harness.** At 30.72 MSPS, left behind by
another tool, "about 2 seconds of samples" becomes 0.2 s: the stream is over before
the first read-back, and the case measures a normal close.

**A mute that is written but not read back is a message, not a mute.** Four scripts
here reported "both channels muted" on the strength of a write that returned, with
the failure swallowed by `2>/dev/null` or `except Exception: pass`. Write, read
back, compare against −89.75, and say **TREAT THAT PORT AS LIVE** when it
disagrees. Then *act on* the pass/fail: four callers discarded it, which moves the
same silent failure one level up.

**`trap` replaces; it does not append.** With two `trap … EXIT` lines in one script
only the second runs. In `cases123.sh`, the harness that holds TX at −30 dB
longest, the one lost was the mute.

**Trap `HUP` as well.** These scripts run over ssh, and a dropped session delivers
`SIGHUP`, not `INT`. `dds-tone.sh` trapped only `EXIT INT TERM` and would have kept
a DDS tone up through a dropped connection; it opens no DMA buffer, so neither the
stream-stop mute nor the starve watchdog can end it.

**A trapped signal does NOT terminate the shell: the handler must `exit`.** Adding
`HUP` without it is worse than not trapping at all. The handler runs and execution
**resumes at the next statement**: a script with
`trap h EXIT INT TERM HUP PIPE QUIT` reaches its own final line after a `HUP`. In
`cases123.sh` the handler muted and revoked, then the next case opened a TX buffer,
and the kernel's cache restore (which revoking *arms*, by leaving both attenuators
at exactly −89.75) put the port back at the previous stream's −30 dB with the
operator's session already gone. Shape it like this:

```sh
# run on: the board
trap '_quiet_on_exit' EXIT
trap '_quiet_on_exit; trap - EXIT; exit 130' INT
trap '_quiet_on_exit; trap - EXIT; exit 143' TERM HUP PIPE QUIT
```

and mask the signals as the handler's first statement (`trap '' INT TERM HUP PIPE
QUIT`), because with `PIPE` trapped on a dead stdout every remaining `echo`
re-enters it.

**`QUIT` does not fire under dash.** Seen twice on this board: dash accepts the
trap (it lists in `trap`) and then dies without running it. Keep it for other
shells; do not rely on it here. `INT` does fire, but over a plain
`ssh host "sh script"` with no pty, Ctrl-C never reaches the board: the session
drops and the script gets `HUP` and `PIPE` instead.

**`nohup` silently drops the `HUP` handler.** POSIX shells do not install a trap
for a signal that was ignored on entry, and `nohup` ignores `SIGHUP`. A script
launched `nohup … &` has no HUP handler however it was written; `dds-tone.sh` run
that way was found gone with its DDS scales still at 0.25 and no exit line in its
log. Run it in the foreground, or follow it with an explicit `off`.

**`$?` inside `then` after `! cmd` is the status of the negation, always 0.**
`case4b.sh` printed "the gate refused the raise (exit 0)" for every refusal, hiding
which of the gate's codes fired. Capture the status before the `if`.

**Put every process you started in the kill list.** `case4b.sh` tracked its writer
and its feeder but not its relay, so an abort left iiod's socket `ESTABLISHED`, the
state the case creates on purpose, left behind by accident.

**One affirmation covers one run.** Every harness ends with `revoke both`, which
removes the affirmation as well as muting, including on a clean exit. A second run
is a second chance to have moved a cable, so a back-to-back re-run exits 3 at the
gate; the scripts say so.

**Say where your control bands are.** `scan-boot-burst.py`'s two controls are both
*below* the TX band, 1.0 and 3.0 MHz from it, because at 4 MSPS centred 1.5 MHz
under the LO there is no room above it (its README once called them "2 MHz away"
on either side). The test rejects a click across the whole span, but not an event
confined to the half-band above the LO.
