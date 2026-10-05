# Transmitter safety

What the firmware does to keep the transmitter quiet, what it cannot protect
against, and the rules a transmitting program must follow. For the four rules
to follow before you cable anything, see
[before you transmit](start/before-you-transmit.md). The evidence is in
[`IDLE-CASES.md`](../IDLE-CASES.md) and [`tools/IDLE-CASES.md`](../tools/IDLE-CASES.md);
the short version is in the [README](../README.md).

!!! danger "The numbers that matter"
    - **Transmit output, flat out:** **about +19 dBm** (an estimate capped at the PA's compression point; never metered)
    - **Receiver absolute-maximum input:** **+2.5 dBm**, about 16 dB below what the transmitter puts out
    - **Attenuation in any TX→RX loopback:** **at least 20 dB**
    - **Every power-on:** **a ~4 ms burst on both transmit ports**, before any software runs
    - **Opening a transmit buffer:** can raise output by itself: **28.25 dB** measured, from a muted board

| Term | Meaning |
|---|---|
| **TX** / **RX** | transmit / receive |
| **Attenuation** | turns the transmit output down, from 0 dB (full power) to −89.75 dB (the floor, "muted") |
| **DMA buffer** | the block of samples a program hands the kernel to send; opening one starts a transmit stream |
| **cyclic buffer** | one block the hardware repeats forever |
| **TX LO** | the transmit local oscillator |
| **debugfs** | the kernel's debug file interface under `/sys/kernel/debug` |

## Before you transmit

| Rule | Why, and where it is explained |
|---|---|
| **Terminate every transmit port** | never transmit at power into an open one: [the power budget](#a-txrx-loopback-without-an-attenuator-will-destroy-your-receiver) |
| **Fit at least 20 dB of attenuation in any TX→RX loopback** | the receiver's absolute maximum input is +2.5 dBm; the transmitter reaches about +19 dBm |
| **Take the antenna off any transmit port you do not want radiating when the board powers up** | every power-on emits a few milliseconds at the TX LO on both ports, and no software can prevent it: [details](#every-power-on-transmits-and-no-software-here-can-stop-it) |
| **Affirm the channel you will raise, after looking at that port** | `./devkit tx-guard affirm 0` for TX1A, `1` for TX2A: [details](#raising-output-needs-a-human-on-record) |
| **Know which target the board runs** | `grep ^ID= /etc/os-release` on the board: Debian is the modern target, Buildroot the factory one. The protections differ |
| **On the factory kernel, re-mute after any debugfs `initialize`** | and read both attenuations back: [why](#debugfs-initialize-on-the-factory-kernel) |
| **Set TX attenuation after the buffer starts, and read it back; mute before tearing the buffer down** | [why](#opening-a-transmit-buffer-is-not-a-neutral-act) |
| **Never flash with DFU** | see [flashing](flashing.md) |

## A TX→RX loopback without an attenuator will destroy your receiver

![Two rows. With the attenuator: TX1A at about +19 dBm, through a 20 dB attenuator, reaches RX1A at about -1 dBm, under its +2.5 dBm limit. Without it: +19 dBm goes straight into RX1A, about 16 dB over the limit, and destroys it.](img/start-loopback-light.svg#only-light)
![Two rows. With the attenuator: TX1A at about +19 dBm, through a 20 dB attenuator, reaches RX1A at about -1 dBm, under its +2.5 dBm limit. Without it: +19 dBm goes straight into RX1A, about 16 dB over the limit, and destroys it.](img/start-loopback-dark.svg#only-dark)

!!! danger "+2.5 dBm is the AD9361's absolute-maximum RF input"
    This board is sold in a variant with a Mini-Circuits
    [**PGA-102+**](https://www.minicircuits.com/pdfs/PGA-102+.pdf) power amplifier on transmit
    (its gain is below), with P1dB (1 dB compression point) around **+17.5 dBm**. Plan for **about
    +19 dBm** flat out, roughly **16 dB above what its own receive port survives**.
    That is the self-test's estimate, capped at the compression point; no power
    meter has measured it. The non-PA variant is 10–18 dB quieter; check which you have.

PGA-102+ gain:

| GHz | 0.05 | 0.8 | 2.0 | 3.0 | 4.0 | 6.0 |
|---|---|---|---|---|---|---|
| **Gain (dB)** | **17.7** | 15.9 | 14.0 | 12.5 | 11.5 | 10.4 |

| Rule | Why |
|---|---|
| **Do not transmit at power into an unterminated port** | neither the AD9361 datasheet (TX into a matched 100 Ω load, ~6.5 dBm max) nor the PGA-102+ datasheet states a tolerance for an open, a short or high VSWR |
| **Fit at least 20 dB of attenuation** in any loopback | the receiver's +2.5 dBm limit |
| **Measure through exactly 20 dB** | with 50 dB the board's internal TX→RX leak is as strong as the loop above about 1.5 GHz ([details](measured-performance.md#the-boards-own-tx-to-rx-leak)) |
| **Start at maximum attenuation** and raise power in steps | [`tools/selftest/`](../tools/selftest/README.md) never transmits with less than 35 dB of its own attenuation |

<sub>This table and these figures are the canonical copy; `tools/selftest/README.md`
and the agent skill point here. Update them here first.</sub>

## What the firmware protects, per target

| protection | factory target (5.15, Buildroot) | modern target (6.12, Debian) | limit |
|---|---|---|---|
| probe at maximum attenuation | yes (`patches/0011`) | yes (its device tree) | applied after the power-on calibration, which has already transmitted |
| mute at boot, before anything can stream | `tx_quiesce` in `S21misc` | `fishball-rf-quiesce.service`; `iiod` does not start unless it succeeded | `fw_setenv tx_quiesce 0` turns it off |
| mute when a stream stops | yes (`0004`, `0005`) | yes | fires on buffer teardown only |
| mute when the DAC starves (a killed or stalled program) | yes (`0015`), 250 ms | yes, 250 ms | exempts cyclic streams; fires once |
| bound on a cyclic stream | **off** (`tx_cyclic_timeout_ms` = 0) | **60 s**, armed at every boot | off on the factory target unless you set it each boot |
| TX-disable latch | yes (`0016`), off by default | yes, off by default | root can clear it |
| die-temperature ceiling | yes (`0018`), off by default | yes, off by default | |
| a cached attenuation of zero is never restored | **no**: debugfs `initialize` can key full output | yes (`firmware-modern/patches/0019`) | |

!!! note "Stock firmware has none of these"
    At power-on the AD9361 comes up in ENSM `fdd` (its state machine, both chains
    powered) with the TX synthesiser running and only 10 dB of attenuation, so the
    port emits LO leakage continuously.

The examples use `iio:device0` for `ad9361-phy` and `iio:device2` for
`cf-ad9361-dds-core-lpc` (the transmit DMA device), as the modern target numbers
them. The numbers are not guaranteed across kernels; in a script, find each
device by its `name` file:

```bash
# run from: the board
for d in /sys/bus/iio/devices/iio:device*; do echo "$d $(cat $d/name)"; done
```

### Muting when a stream stops

`patches/0004` calls ADI's `ad9361_tx_mute()` from the TX buffer lifecycle:

| event | what happens |
|---|---|
| boot | TX at maximum attenuation from the device tree, but **not from the instant power is applied** ([why](#every-power-on-transmits-and-no-software-here-can-stop-it)). The boot mute is `fishball-rf-quiesce` on Debian and `S21misc` on Buildroot |
| a TX buffer starts streaming | TX unmuted: your gain if you set one, else the last you used |
| the buffer stops | TX muted and the synthesiser powered down |

The unmute restores the cached attenuation only if nothing has been set since the
mute (`patches/0005`): set a gain then start the stream, and you get the gain you
set; start with nothing set, and you get the last gain used.

!!! warning "Remove any watchdog script that polls `buffer/enable` to re-apply a gain"
    On a board with a power amplifier it applies a fixed gain to both channels a
    second or two after *any* stream starts.

| Where to look | |
|---|---|
| Buildroot | `/mnt/jffs2/autorun.sh` first: it survives reflashing and appears nowhere in the source |
| Debian | nothing runs `autorun.sh`; look at `systemctl list-units 'fishball*'` and `systemctl --failed` |
| either | `tools/selftest/sdr_selftest.py --ssh` reports what is in `/mnt/jffs2` and whether anything would run it |

### When the program dies: the starve watchdog

Kill a program that is transmitting *from the board itself* and `buffer/enable`
stays `1`: teardown never runs, so the stream-stop mute never fires.
`patches/0015` mutes instead when no data reaches the DAC for 250 ms while the
transmitter is on: a killed program, a stalled one, or a buffer enabled and never
fed.

| Measured | Time to −89.75 dB |
|---|---|
| a killed local transmitter, both kernels ([`tools/IDLE-CASES.md`](../tools/IDLE-CASES.md), case B) | **0.26–0.27 s** |
| a killed streaming transmitter, with `0022` | 280 ms |
| a buffer enabled and never fed (64 KB block), with `0022` | 315 ms |

```bash
# run from: the board - how long the DAC may starve before muting, 0 disables
cat /sys/bus/iio/devices/iio:device2/tx_starve_timeout_ms
fw_setenv tx_starve_ms 1000   # a different timeout, from the next boot on (20 ms minimum)
fw_setenv tx_starve_ms 0      # no starve mute, from the next boot on
fw_setenv tx_starve_ms        # back to the default
```

**A large first block gets time to arrive** (`patches/0022`). A buffer is
enabled before its data is uploaded, so the first wait is 250 ms plus the time
to upload one block at 1 MB/s, capped at 10 s. After the first block, 250 ms
applies as before. Two channels at 40, 50 and 60 MS/s ran unmuted.

| Without `0022` | |
|---|---|
| symptom | silence plus a DMA underflow |
| cause | a 4.4 MB cyclic buffer (two channels at 40 MS/s) was muted before it landed, and the mute also switches the DAC away from the DMA |

It exempts cyclic streams, and it fires once (both below).

### Cyclic transmits and the 60 s bound

A cyclic stream outlives the program that started it by design, so the starve
watchdog leaves it alone. **Every streaming tool in this devkit transmits
cyclically.** A separate bound, `tx_cyclic_timeout_ms`, covers it; the kernel's
compiled-in default is `0`, off.

| Target | Bound |
|---|---|
| **Modern (Debian root)** | **armed at 60 s on every boot.** `fishball-rf-quiesce` writes it before `iiod` starts, and `iiod` does not start unless that unit succeeded (`Requires=`). The board stays reachable over `usb0`; see [the Debian root reference](debian-root-reference.md#transmitter-safety-at-boot). After a cold boot `tx_cyclic_timeout_ms` reads `60000` |
| **Factory (Buildroot ramdisk)** | **not armed**, unless you set `fw_setenv tx_cyclic_bound <ms>`, which `S21misc` applies at every boot (`patches/0023`) |

```bash
# run from: the board - check it, change it, or turn it off
cat /sys/bus/iio/devices/iio:device2/tx_cyclic_timeout_ms   # 60000 after boot (Debian)
echo 10000 > /sys/bus/iio/devices/iio:device2/tx_cyclic_timeout_ms   # this boot only
fw_setenv tx_cyclic_bound 10000    # a different bound, from the next boot on
fw_setenv tx_cyclic_bound 0        # no bound at all, from the next boot on
```

- The timer is armed when the block is submitted, so it also mutes a healthy,
  unattended cyclic transmit 60 s after it started.
- `tx_cyclic_bound` is separate from `tx_quiesce`, so turning off the boot mute
  does not also unbound every cyclic transmit.
- `tools/sample_gpio_clock.py` holds a cyclic stream until Ctrl-C: its RF goes
  quiet after 60 s, its pins do not, and it prints the bound at start.

### The starve watchdog fires once

It does not re-arm. After a starve-mute a gain write raises the attenuator and
**nothing re-mutes it** until a fresh buffer enable:

```
atten0=-30.000000  LO_pd=1  buf=1      (gain written AFTER the watchdog fired)
```

!!! warning "Never judge `hardwaregain` alone"
    What keeps that port silent is the **powered-down TX LO**, not the attenuator.
    Read `out_altvoltage1_TX_LO_powerdown` beside it.

### Refusing to transmit at all

```bash
# run from: the board
echo 1 > /sys/bus/iio/devices/iio:device0/tx_disable
```

A latch that forces maximum attenuation and **cannot be cleared by debugfs**
(`initialize`, or `bist_tone` mode 1), both reachable over port 30431 (`iiod`,
no authentication). A root write to the same file clears it, and it reads `0`
unless somebody sets it.

### Refusing to transmit when hot

```bash
# run from: the board - millidegrees C; 0 (the default) disables it
echo 60000 > /sys/bus/iio/devices/iio:device0/tx_temp_limit
```

Above it, requests to get louder are refused and logged; muting never is. Armed
below the die temperature, it makes transmit code testable with an antenna on:

```bash
# run from: the board - 1 C, so nothing can ever get louder
echo 1000 > /sys/bus/iio/devices/iio:device0/tx_temp_limit
dmesg | tail -1
# ad9361 spi0.0: die at 40.351 C is over the 1.000 C transmit limit - staying muted
```

!!! tip "Prove the gate is live"
    Make an explicit `-60 dB` write first: an empty log proves nothing if nothing was armed.

### Raising output needs a human on record

Nothing on the board can tell what is attached to a transmit port, so the devkit
records what a person says, **per channel** (0 is TX1A, 1 is TX2A), and refuses
to raise that channel without it.

=== "bash (Linux, macOS)"

    ```bash
    # run from: the repo root
    ./devkit tx-guard affirm 0        # only after LOOKING at TX1A
    ./devkit tx-guard check 0         # exit 0 affirmed, 3 not
    ./devkit tx-guard revoke both     # withdraw, and force maximum attenuation
    ```

=== "Python (Windows, any shell)"

    The same gate, with the same commands and exit codes. It needs `paramiko`,
    in a venv, and logs in with the board key from `./devkit ssh-key` if there
    is one, else the root password:

    ```bash
    # run from: the repo root, in cmd or PowerShell (on Linux or macOS: .venv/bin/ in place of .venv\Scripts\)
    python -m venv .venv
    .venv\Scripts\pip install paramiko
    .venv\Scripts\python tools/tx_gate.py affirm 0
    .venv\Scripts\python tools/tx_gate.py status
    ```

    `tools/tx_gate.py` picks this route by itself on Windows, so a script that
    imports it (as `sample_gpio_clock.py` does) works there too.

| | |
|---|---|
| where the record lives | the board's `/tmp` (RAM): **a reboot withdraws it** |
| refuse without it | `./devkit selftest --loopback`, `tools/sample_gpio_clock.py`, `tools/modulation-gallery/board.py`, the [automation server](automation.md#transmitting)'s `Transmit` and `TransmitCapture` |
| checked, not gated (they never command output) | `./devkit selftest` alone, `./devkit gpio-check` |
| **muting** | **never gated** |
| one affirmation covers | one run: the harnesses in `tools/tx-idle-cases/` call `tx-guard.sh revoke both` on exit |

!!! note "This raises the floor; it is not a lock"
    A direct write to `out_voltageN_hardwaregain` walks past it, and the
    affirmation file can be forged by any process. The mute costs no output power:
    over a 50 dB loopback, commanded and applied attenuation matched to 0.01 dB at
    every point including 0 dB.

## What the firmware does not protect against

### Every power-on transmits, and no software here can stop it

!!! danger "Do not leave an antenna on a transmit port you do not want radiating when the board is powered up"
    **About one second after power is applied, both TX1A and TX2A emit a
    narrowband burst of roughly 4 ms at the transmit LO frequency.**

| | |
|---|---|
| level | around 50 dB above two control bands 1.0 and 3.0 MHz below it; it saturated the receiver through 20 dB, so this is a lower bound, equivalent to at least −20 dB of commanded attenuation |
| captured on | a separate HackRF One through a pad (the board's own receiver powers up with it and cannot see it) |
| band, duty | the 2.4 GHz ISM band, negligible duty cycle |
| cause | **normal AD9361 behaviour**: `ad9361_tx_quad_calib()` drives a test tone through the transmit path to correct I/Q imbalance, at `ad9361.c:5308`, *before* `ad9361_set_tx_atten()` applies the device tree's value at `:5326`. The PGA-102+ amplifier is what makes it loud here |
| why nothing helps | `tx_quiesce`, the affirmation gate, the starve watchdog and `tx_disable` all act too late, so the mitigation is operational |

Measurements: [`IDLE-CASES.md`](../IDLE-CASES.md#the-capture-was-taken-and-the-boot-window-is-not-quiet).

### Opening a transmit buffer is not a neutral act

**The unmute restores whatever gain the last stream used, on a bare buffer
enable, with nothing having asked for output.** On a board fully muted:

```
before anything                 atten0=-89.750000  LO_pd=1  buf=0
after a bare buffer enable      atten0=-61.500000  LO_pd=0  buf=1
```

A **28.25 dB** raise, bounded only by the loudest gain used since boot. Two rules
follow:

!!! danger "Two rules for every program that streams"
    - **Write your attenuation *after* the buffer starts, and read it back.** Anything
      written before the enable is what the restore overwrites.
    - **Mute *before* you tear the buffer down, never after.** The stream-stop hook
      caches whatever attenuation it finds before applying maximum, so closing first
      hands your gain to whoever streams next. `tools/tx-guard.sh`'s `reap` follows
      the same ordering.

A program meant to stay silent while streaming must read both attenuators right
after the enable and stop if either moved. All four of the devkit's streaming
tools do (`tools/tx_gate.py:assert_quiet_after_enable`); an unreadable attenuator
counts as a failure.

### debugfs `initialize` on the factory kernel

On the factory kernel, debugfs `initialize` wipes the cached attenuation to zero,
and **zero attenuation is full output**:

```bash
# run from: the board. On the factory kernel, with an antenna fitted, do NOT.
echo 1 > /sys/kernel/debug/iio/iio:device0/initialize
# ...then anything at all that opens a transmit buffer...
```

leaves the transmitter keyed flat out (TX2 read `0.000000 dB` on hardware).

| Target | Fix |
|---|---|
| modern | [`firmware-modern/patches/0019`](../firmware-modern/patches/README.md#0019-never-restore-a-cached-attenuation-of-zero) seeds the cache with maximum attenuation |
| factory | **re-mute after any `initialize`** and read both attenuations back, below |

```bash
# run from: your HOST
U=ip:192.168.2.1
for c in 0 1; do iio_attr -u $U -c -o ad9361-phy voltage$c hardwaregain; done
```

## Rules for programs that transmit

!!! danger "A mute you did not read back is not a mute"
    A write to `out_voltageN_hardwaregain` can fail, and `2>/dev/null` or
    `except Exception: pass` hides it. Every mute in this repo writes, reads back,
    compares against −89.75 dB, and says **TREAT THAT PORT AS LIVE** when they
    disagree. A caller that discards a pass/fail return value moves the silent
    failure one level up.

Shell scripts that run on the board:

| Rule | Why |
|---|---|
| **Trap `HUP`, not just `EXIT INT TERM`** | a dropped ssh session delivers `HUP`; untrapped, the script dies and leaves running whatever it started (for `tools/tx-idle-cases/dds-tone.sh`, a DDS tone that neither `0004` nor `0015` can reach) |
| **Install one handler** | `trap` replaces, it does not append |
| **Mute before you tear the buffer down, on the error paths too** | the stream-stop hook caches the gain it finds |
| **The handler must `exit`** | a trapped signal does NOT terminate the shell: execution resumes at the next statement, which in a harness can open a TX buffer and restore the previous stream's gain after the operator has gone |
| **Mask the signals as the handler's first statement** (`trap '' INT TERM HUP PIPE QUIT`) | with `PIPE` trapped on a dead stdout, every `echo` re-enters it |
| **Do not rely on `QUIT`** | `QUIT` does not fire under dash, and over `ssh host "sh script"` with no pty, Ctrl-C arrives as `HUP` and `PIPE`, not `INT` |
| **No `nohup`** | `nohup` silently drops the `HUP` handler (a signal ignored on entry cannot be trapped). Run such scripts in the foreground, or follow with an explicit `off` |

Shape the traps like this:

```sh
# run from: the board
trap '_quiet_on_exit' EXIT
trap '_quiet_on_exit; trap - EXIT; exit 130' INT          # (1)!
trap '_quiet_on_exit; trap - EXIT; exit 143' TERM HUP PIPE QUIT
```

1.  Each handler mutes, clears the `EXIT` trap so the mute does not run twice,
    and **exits**: a trapped signal alone does not end the shell.
