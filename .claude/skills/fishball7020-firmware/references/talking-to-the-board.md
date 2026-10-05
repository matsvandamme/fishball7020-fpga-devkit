# Talking to the board

## Three routes in

| Route | Reaches | Notes |
|---|---|---|
| libiio network protocol, port 30431 | IIO attributes, sample buffers, **and all of debugfs** | no library needed; `tools/selftest/iiod_min.py` speaks it with the standard library alone |
| ssh `root@192.168.2.1` (password `analog`) | the filesystem: `/mnt/jffs2`, boot scripts, dmesg | busybox on Buildroot; see the shell limits below |
| USB mass storage / serial console | firmware images, boot messages | the debug port's UART shows the whole boot; the OTG port's only appears after Linux is up |

IIO is the Linux Industrial I/O subsystem the radio driver exposes; libiio is
its client library, and `iiod` is the board-side server it talks to.

## Is the board there? Never `ping`

Use `tools/board_addr.py --check`: it prints the address and exits 0 only if
the board answers. `reachable()` makes each service identify itself, because
192.168.2.1 is a private address other networks use too: `iiod` must answer
`VERSION`, or the ssh banner must name **dropbear**. It needs no ICMP, and
**the build container ships no `ping` at all**. Two consequences:

- On **Debian**, sshd is OpenSSH, whose banner any Debian machine sends, so it
  is not proof. A Debian board whose `iiod` is held back (below) makes
  `--check` exit **3**, printing the address where only that ssh answered;
  `./devkit` commands that work over ssh accept it, the iiod ones refuse with
  the journalctl command to run. Exit 1 means nothing answered at all.
- The container has no mDNS either: `tools/container/run.sh` resolves a
  `.local` name on the host and forwards it as `$BOARD` plus `--add-host`.

## No libiio but ssh works, on Debian: iiod is held back by design

`iiod.service` `Requires=fishball-rf-quiesce`: if the boot mute could not be
proven there is no SDR service, and `fishball-usb-bind` brings the gadget up
WITHOUT iiod's USB function so usb0 still works. Read the journal, fix, reboot.
`systemctl start iiod` is safe: `Requires=` re-runs the quiesce first and iiod
starts only if it passes. **Never start iiod by hand** (the unit runs
`/usr/local/sbin/fishball-iiod`): that is the one way around the check that
the transmitter is quiet.

```bash
# run on the board (Debian)
systemctl list-units --failed
journalctl -b -u iiod -u fishball-identity -u fishball-rf-quiesce
```

## When the radio misbehaves, ask what else is writing to it

**On Buildroot** it is `/mnt/jffs2`: the one writable persistent partition,
whose `autorun.sh` runs at every boot. Scripts there survive reflashing the
kernel, device tree and bitstream, appear nowhere in the firmware source, and
can rewrite IIO attributes underneath an application; check it before
rebuilding any kernel over a "firmware bug" (worked case in `debugging.md`).
`./devkit selftest --ssh` lists what is there.

**On Debian nothing runs `autorun.sh`** (no reference from systemd,
`/etc/init.d` or `rc.local`). `/mnt/jffs2` is still mounted (`/dev/mtdblock2`)
but its only job is `hw_serial`, minted once by `fishball-identity.service`,
and the root is a writable ext4 anyway. What moves settings there is systemd
(the commands above). So an `autorun.sh` customisation *silently stops
running* when a board moves to Debian, and one left over from Buildroot is dead
weight that looks live.

## Where the board's address lives, and the file that is a decoy

**Check the userspace first: most of this section is Buildroot only.**

| | Buildroot | Debian |
|---|---|---|
| who configures `eth0` | `S40network`, from U-Boot variables | `/etc/network/interfaces`, a fixed DHCP stanza |
| static address | `fw_setenv ipaddr_eth …` | edit `/etc/network/interfaces`; `ipaddr_eth` is read by nothing |
| hostname / mDNS | `fw_setenv hostname` | `hostnamectl set-hostname`; avahi reads `/etc/hostname` |
| boot-time extras | `/mnt/jffs2/autorun.sh` | a systemd unit; `autorun.sh` is never run |
| `config.txt` on a USB drive | yes | no: there is no mass-storage gadget |

On Debian, `./devkit net dhcp|static|name` refuse and print the equivalent
command; `find` and the status display work on both. The USB network at
192.168.2.1 works on both, and Debian also has a serial console on the same
cable (`/dev/ttyACM0`).

On Buildroot the addresses are in the **U-Boot environment in QSPI flash**
(`/dev/mtd1`, per `/etc/fw_env.config`), not on the SD card. `S40network`
regenerates `/etc/network/interfaces`, `/etc/udhcpd.conf` and `/opt/config.txt`
from it at every boot, so editing those files tests a change and then loses it.
Because it is QSPI, address settings **survive `./devkit flash --target factory --all`**.

`ipaddr_eth` is a switch, not just a value: set = static `eth0`, unset = DHCP.
`fw_setenv ipaddr_eth` with no value deletes it and returns the board to DHCP.

**`uEnv.txt` on the SD card does not change the Linux address.** U-Boot reads it
with `env import`, which touches only the in-RAM environment (there is no
`saveenv` in the SD boot path), and Linux's `fw_printenv` reads `/dev/mtd1`.
`uEnv.txt` ships `ipaddr=192.168.2.1`, the QSPI env has no `ipaddr` at all
(`fw_printenv ipaddr` returns `"ipaddr" not defined`), and `S40network`'s
compiled-in default is the same number, so "I edited uEnv.txt and it worked" is
indistinguishable from the file never being read.

**A static address has no default route and no DNS.** The static branch writes
only `address` and `netmask`, and nothing writes `/etc/resolv.conf`: two
link-scope routes, no `default via`, `ping 8.8.8.8` fails. DHCP sets both
(udhcpc's `default.script`). Prefer a DHCP reservation on the router, or (on
Buildroot) add the route in `/mnt/jffs2/autorun.sh`.

Finding a board whose address you do not know: `iio_info -s` (DNS-SD; prints
address, model and serial, and confirms IIOD is up), or `ip:fishball.local` as
a URI. `usb0` keeps 192.168.2.1 whatever you did to `eth0`, so a USB cable is
always the way back in. Full write-up:
[`docs/networking.md`](../../../../docs/networking.md).

**Never hard-code the board's address in a tool.** `tools/board_addr.py` is the
one place the order is decided: an explicit argument, then `$BOARD`/`$SDR_URI`,
then `fishball.local`, `Fishball7020.local`, `pluto.local`, then the USB gadget
at 192.168.2.1. Python: `from board_addr import resolve, uri`. Shell:
`BOARD="${BOARD:-$(python3 tools/board_addr.py)}"`. It probes candidates
CONCURRENTLY with a deadline, because a `.local` name that does not resolve
blocks `create_connection` for ten seconds or more; probing in turn would add
that to every invocation. CI greps for a re-introduced hard-coded default.

**Use `./devkit net`, not `fw_setenv` by hand** (Buildroot). `net show | dhcp |
static <ip> | name <host> | find`. It reads the environment back BEFORE rebooting and then
re-finds the board by mDNS, because switching to DHCP discards the address you
are connected on.

**Two different names, from different places.** mDNS (`fishball.local`)
follows the `hostname` variable and is answered by avahi on the board. What a
ROUTER lists is DHCP option 12, which stock firmware never sends, so a router
shows a bare MAC even when mDNS works. Patch `0013` adds a `hostname` line to
the dhcp stanza, which busybox ifupdown turns into `udhcpc -x hostname:`.

**The MAC is random on every boot without patch `0013`.** The device tree has no
`local-mac-address`, so the driver logs `invalid hw address, using random`, the
router sees a new device each boot, and a DHCP reservation is impossible.
`0013` adds `hwaddress ether $ETHADDR` (the MAC U-Boot already uses) to BOTH
branches, static and dhcp, since the driver randomises regardless of
addressing mode.

**`config.txt` on the USB mass-storage drive still overrides everything**
(Buildroot). It is not on the SD card: it is a loopback vfat image at
`/opt/vfat.img` that `/sbin/update.sh` re-reads when the host EJECTS the drive.
`0013` does not touch `update.sh`, so editing `ipaddr_eth` there still forces a
static address. The section heading is `[USB_ETHERNET]`, but it configures the
RJ45 socket.

## IIOD protocol gotchas

All against IIOD 0.25.

- **The channel mask is fixed-width**: exactly 8 hex characters per 32 scan
  channels. `00000003` enables channels 0 and 1. Both `3` and
  `0000000000000003` fail with `-22 EINVAL` and no hint.
- **`WRITEBUF` is acknowledged twice**, before and after the payload. Skip the
  first status and the stream desyncs, with your samples arriving as the next
  "response line".
- **`VERSION` answers with a bare line**, not a length-prefixed payload: the
  one command that breaks the general framing rule.
- **Large transfers time out on the board, not the client.** 1,048,576 samples
  succeeds; 4,194,304 fails with `-110 ETIMEDOUT`, and raising the client
  timeout does not help. Chunk at 262,144 and loop `READBUF` on one open buffer.
- **Receive is 12-bit sign-extended into int16** (full scale ±2047). **Transmit
  is the full 16 bits.** Scaling transmit samples to ±2047 emits 24 dB low.

## A capture that completes is not a capture that is intact

`iio_readdev` returns the byte count you asked for whether or not the DMA
overflowed underneath it, so a capture that lost samples is the same size as one
that did not. Receive only, over Ethernet: one channel at 10 MSPS (40 MB/s) is
clean; **two channels at 10 MSPS (80 MB/s) drop**; two at 3 MSPS (24 MB/s) are
clean. The ~31 MB/s plateau in `docs/modulation-and-throughput.md` is a
*bidirectional* figure; receive alone sustains closer to 40.

A drop leaves a step in phase: de-rotate the strongest tone and the residual
should be flat. `tools/sigmf-capture.py --verify` does that and records the
verdict in the recording's own SigMF sidecar; `docs/capturing-iq.md` explains
the method. Inject a tone with `bist_tone` if the air is quiet: mode 2 is
inside the chip and transmits nothing.

**Blank the bins around DC first.** With no tone present the strongest bin is
the LO leak at DC, and de-rotating by ~0 Hz measures the phase of noise
(2968 "jumps" out of 3000 blocks, a confident false alarm). Treat a detector
that flags most of the capture as broken rather than as a finding.

## Two devices, two channel numberings

```
ad9361-phy      input voltage0 = RX1,        voltage1 = RX2      (gain, rate, bandwidth)
cf-ad9361-lpc   input voltage0/1 = RX1 I/Q,  voltage2/3 = RX2 I/Q  (the sample stream)
```

Setting RX2's gain via phy `voltage2` fails silently: that channel exists but
has no `hardwaregain`. Use phy `voltage1` (RX1 at 10 dB against RX2 at 73 dB
makes stream words 0,1 exactly 32.4 dB quieter than words 2,3). `RX_LO` is an
**output** channel and needs `-o`; reading it with `-i` returns nothing.

## Attributes this firmware refuses, and how to notice

Two AD9361 attributes fail with `Invalid argument (22)`. `rf_port_select` on
receive accepts only `A_BALANCED`, although `rf_port_select_available`
advertises twelve including `TX_MONITOR1/2`; it is refused from an idle ENSM
state as readily as from a running one, so nothing reaches the TX monitor
path. `filter_fir_en 1` is refused until coefficients are loaded through
`filter_fir_config`. The quadrature, RF DC and baseband DC tracking enables do
apply. **Check `iio_attr`'s exit status** (1 on refusal, 0 on success) and
never send its errors to `/dev/null`, or a rejected setting looks exactly like
an applied one.

## A retune is not in the samples for ~35 frames

Over USB at 2.304 MSPS with 4096-sample frames, a looped tone stays at the OLD
offset for 34 more frames after a 500 kHz retune while `altvoltage0 frequency`
already reads the new value: `iio_readdev`, the FIFO, the socket and the
board's DMA ring all hold old samples. **Reading the register back proves
nothing**; measure the samples. Destroy and rebuild the buffer after any
configuration change (pyadi-iio's `rx_destroy_buffer()`), and the change lands
on the next frame. The pyadi form of the same effect is below.

## A pyadi script that used a buffer segfaults on exit

On a healthy board the capture succeeds, the samples are complete, and the
process then dies with SIGSEGV during interpreter shutdown (exit 139). The
fault is inside `iio_buffer_destroy()`, reached through ctypes from
`Py_FinalizeEx`: Python frees objects in no guaranteed order at shutdown, and
the buffer outlives the context it points into.

Call `sdr.rx_destroy_buffer()` / `sdr.tx_destroy_buffer()` before the script
ends. **It is not a version mismatch**: it reproduces identically with pip
`pylibiio` 0.25 and with Ubuntu's `python3-libiio` 0.23 against its own
`libiio.so.0.23`, so do not send anyone off to build libiio from source over it.
The same call is separately needed after a settings change, for the reason
below.

## pyadi-iio returns receive data from BEFORE your last change

libiio keeps a few kernel blocks queued for a receive buffer. Once they fill,
the DMA stops and the old blocks wait, so after changing any setting the next
few `sdr.rx()` calls return samples captured at the PREVIOUS setting. Every
reading lags one step, which looks exactly like "TX attenuation does nothing"
while the mute patches are fine. Call `sdr.rx_destroy_buffer()` before each
measurement that follows a change.

After a low-rate run through pyadi (below 2.083 MSPS) the AD9361's own FIR is
left enabled in x4 mode. Restore by setting the rate back with pyadi's setter
FIRST, then `in_out_voltage_filter_fir_en = 0`; the other order is invalid
below 2.083 MSPS. Check `rx_path_rates` afterwards.

## Receive over USB: the ceiling, the FPGA /8, and small buffers

- **USB carries ~20 MB/s: 5 MS/s arrives complete**, 6 MS/s 84%, 10 MS/s 50%
  (measured 2026-10-02 by bytes per wall-clock second, which a drop does lower,
  unlike a fixed-count capture). The FPGA /8 does not raise it: 7.68 MS/s after
  /8 is still 30.7 MB/s on the cable and arrives at 65%.
- **The FPGA /8 is chosen by `cf-ad9361-lpc` `voltage0` `sampling_frequency`**:
  equal to the AD9361 rate bypasses it, an eighth engages it
  (`sampling_frequency_available` lists both). Set the AD9361 rate first; with
  `filter_fir_en 1` the AD9361 refuses high rates, so use `ad9361_set_bb_rate`
  (libad9361) or turn the FIR off, and **read the lpc rate back**: a refused
  write leaves the old rate and the stream runs at the wrong speed silently.
  Put it back to the AD9361 rate when done; other programs assume bypass.
- **Which address you stream to can halve the rate.** On 2026-10-03, 4 MS/s from
  RX1 arrived complete at `ip:192.168.2.1`, but at only 1.3-3.5 MS/s at
  `ip:fishball.local`, which that host's resolver answered with an IPv6
  link-local address (routed via `docker0`). `./devkit adsb` warns `LINK TOO
  SLOW` when this happens; anything streaming near the USB ceiling should
  measure delivered samples per second, not assume them.
- **Small buffers plus a late host lose samples on the board.** SDR++'s
  1/200 s blocks (2500 samples at 500 kS/s) with libiio's default kernel buffer
  count lost 31% of the data while `iio_readdev` with the same block size got
  99%: the reader was late, not the link. `iio_device_set_kernel_buffers_count(dev, 8)`
  before creating the buffer fixed it. `docs/sdrpp.md` has the measurements.

## Two applications cannot hold the board at once

Opening it in SDRangel or anything else that claims the USB device reconfigures
the composite gadget: the Ethernet gadget disappears and `ip:192.168.2.1` stops
answering until that application closes. Not a fault; the device is exclusive.

## What the board's shell does and does not have

**Which userspace?** `cat /etc/os-release`: Debian means the ext4 root from
`firmware-modern/debian`; no output means Buildroot on a RAM disk. Nearly
everything in this section differs between them.

- **`pkill` exists on Debian and NOT on Buildroot.** `/usr/bin/pkill`,
  `/usr/bin/pgrep` and `/usr/bin/killall` are all present under Debian and none
  under Buildroot. Two separate traps:
  - **On Buildroot**, `pkill -9 foo 2>/dev/null` silently does nothing, so a
    starve-watchdog test built on it reports the watchdog *broken* while the
    unkilled writer keeps re-arming it. Use `ps`, `kill -9 <pid>`, then `ps`
    again.
  - **On your HOST**, `pkill -f` / `pgrep -f` match the shell issuing them;
    see `debugging.md`.
- **Not on Debian either:** no compiler (`gcc`, `make`), no `pip3`, no `git`,
  no `strace`, no `tcpdump`, and **no libgpiod tools** (`gpiofind`, `gpioinfo`,
  `gpioget` and `gpiodetect` are all absent), so resolve GPIO lines by chip
  label through `/sys/class/gpio/`. What you do get: `apt`, `systemctl`,
  `journalctl`, `python3` with numpy, and 6.8 GB free.
- **No ftrace function tracer**, so no kprobes. `dump_stack()` in a driver plus
  `dmesg` is the substitute. The 6.12 kernel in `firmware-modern/` compiles the
  ftrace *framework* in (`CONFIG_FTRACE=y`, a side effect of
  `CONFIG_DEBUG_KERNEL`), but without `CONFIG_FUNCTION_TRACER` the only tracer
  on the board is `nop`. `trace_marker` does work, which is enough to timestamp
  from userspace.
- An empty `dmesg` is information: the kernel is not doing what you suspect.

## Useful sysfs and debugfs

```
/sys/bus/iio/devices/iio:device0        ad9361-phy
/sys/bus/iio/devices/iio:device1        xadc  (supply rails, die temperature)
/sys/bus/iio/devices/iio:device2        cf-ad9361-dds-core-lpc  (TX)
/sys/bus/iio/devices/iio:device3        cf-ad9361-lpc  (RX)
/sys/kernel/debug/iio/iio:device0/      bist_prbs, bist_tone, bist_timing_analysis,
                                        loopback, calib_mode, gaininfo_rx1/2,
                                        digital_tune, and every adi,* device-tree value
```

These indices are the usual ones; in tools, resolve `iio:deviceN` by name.

**Debugfs does not need ssh.** IIOD's `READ` and `WRITE` take `DEBUG` as an
attribute kind alongside `INPUT` and `OUTPUT`, so every attribute above is
reachable on port 30431: that is what `iio_attr -D` does, and
`iiod_min.read_debug`/`write_debug` do it with the standard library alone. Do
not shell out over ssh for debugfs. ssh is still the only route to the
*filesystem*.

`bist_timing_analysis` needs a write to trigger, then a read: it walks all 16×16
clock/data delay combinations with a PRBS running and prints the eye. It is a
one-shot: the read clears the flag, so **a second read returns `0`**, which
looks like a failure and is not. The driver mutes TX for the duration ("we
don't want to transmit the PRBS") and restores the cached attenuation after.
`loopback` = 1 routes DAC data back into the ADC path inside the chip, which
exercises both DMAs and the LVDS link with no RF at all. Set it back to 0
afterwards.

**`bist_tone` takes exactly four integers**, `mode freq_Hz level_dB mask`, or
the driver returns `EINVAL`. Mode 2 injects on **receive** and radiates
nothing; **mode 1 injects on transmit, which goes out through the PA** and is
not muted for you (since `patches/0016` it is refused while `tx_disable` is
set). The frequency field is 2 bits wide, so the only tones available are
`fs/32`, `fs/16`, `3·fs/32` and `fs/8`; anything else is rounded silently.
Level quantises to 6 dB steps. `mask` zeroes individual I/Q streams; `0` leaves
all four alone.

**FPGA core registers: set bit 31 of the address.** The two cores' debug
register access (`direct_reg_access`, pylibiio `dev.reg_read/reg_write`)
decides by bit 31 where an address goes. On **`cf-ad9361-lpc`** (the ADC core)
a plain address such as `0xB8` goes to the **AD9361 over SPI**; only
`0x800000B8` reaches the FPGA core's register. The DAC core runs in
"standalone" mode and maps plain addresses to itself, so the same code "works"
on one core and silently reads and writes radio-chip registers on the other,
where a read-modify-write can rewrite a radio register. Always use the flag for
core registers (`drivers/iio/adc/cf_axi_adc_core.c`, `axiadc_reg_access`):

```python
# run on your HOST (pylibiio): the ADC core's GP input and GP_CONTROL registers
adc.reg_read(0x80000000 | 0xB8)
adc.reg_write(0x80000000 | 0xBC, value)   # read-modify-write: bit 0 is the kernel's
```

## The sample-locked GPIO pins (JP5 7/9/11/13)

Four header pins carry each transmit sample's low nibble (patches 0006-0009;
balls V10/U9/U10/T9, bank 13, 3.3 V, pulled down). End to end:
[`docs/tx-gpio-bitmap.md`](../../../../docs/tx-gpio-bitmap.md).

- **Line offsets are 72-75 on every kernel** (a property of the bitstream).
  Legacy sysfs numbers are `base + 72`, and the base moves: 906 on 5.15 (pins
  978-981), 512 on 6.12 (584-587). **Resolve the base by chip label, not with
  `gpiofind`**: libgpiod-tools is not installed on the Debian rootfs.
  `tools/tx-gpio-bitmap-check.py` does it portably:
  `for g in /sys/class/gpio/gpiochip*; do grep -q zynq_gpio $g/label && cat $g/base; done`.
- Enable: `echo 1 > /sys/bus/iio/devices/iio:deviceN/tx_sample_gpio_en` on
  `cf-ad9361-dds-core-lpc`, `N` resolved by name. Verify with
  `./devkit gpio-check` (no scope, no antenna; it opens a TX buffer, so it
  follows the rules in `rf-safety.md`).
- Pin-to-pin timing: all four within 1.5 ns, every sample present up to
  61.44 MSPS (logic analyser). The pins LEAD the RF by a constant offset of
  roughly a microsecond that is designed-for, not measured: never write "the
  pin edge and its RF happen together".
- Always compare a spectrum against a muted reference in absolute dBFS: a
  normalised spectrum makes silence look like "a spray of components".
- Three ways to fool yourself: a pin read with `direction=out` returns what you
  *wrote*; a pin's level alone never says who drives it (stream two different
  nibbles); and the nibble must be OR-ed into the samples **last**.

## MATLAB and Simulink

Details and measurements: [`docs/matlab.md`](../../../../docs/matlab.md).
`./devkit matlab` checks the toolboxes, the support package and the board, and
`./devkit matlab shell` starts MATLAB with `matlab/+fishball/` (`connect`,
`capture2`, `spectrum`, `phase`, `evm`, `safeTransmit`, `readSigMF`, `doctor`)
and the examples on the path.

- **Never accept MATLAB's offer to update the firmware**: that image is for a
  Zynq-7010 ADALM-Pluto. A `git describe` in `fw_version` stops MATLAB
  connecting outright, which is why `fishball-identity` publishes `fw_version`
  and `fw_build` separately
  ([docs](../../../../docs/matlab.md#the-firmware-version-string)).
- **MATLAB sees ONE of the two receivers**: `ChannelMapping must be equal to 1`
  on *both* `sdrrx` and `sdrtx`, because the ADALM-Pluto support package is
  written for a 1R1T radio. RX2 and TX2 are reachable only through
  `fishball.capture2` / `fishball.safeTransmit` (via `iio_readdev` and
  `iio_writedev -c`).
- **Full scale depends on the output type**: `int16` gives raw counts
  (**±2047**), `double`/`single` give counts÷**2048** (±1.0), transmit is
  **±32767**; mixing the first two is a 66 dB mistake that raises no error.
- Setting a property on a running System object does nothing; `release()` and
  rebuild.
- Simulink: `fishball.RxSource` / `fishball.TxSink` reach both channels and
  MUST run with `SimulateUsing = 'Interpreted execution'`: they call
  `system()`, which cannot be code-generated, and the default setting fails to
  compile with a message that names nothing
  ([docs](../../../../docs/matlab.md#set-simulate-using-to-interpreted-execution)).
- **A System object must not touch the radio in `setupImpl`.** Simulink calls
  it during COMPILE as well as at start, so a transmitter opened there is
  started, torn down and started again, with the radio silent in between (the
  model's own receive log reads 1 count of 2047). Open lazily on the first
  step ([docs](../../../../docs/matlab.md#rules-for-system-objects-that-touch-the-radio)).
- At the full 2.304 MSPS MATLAB cannot keep up, so receive buffers stay full
  and samples arrive about **34 frames late**: engage the FPGA ÷8 decimator
  (receive only; never the TX interpolator) and the host keeps up.

## Writing to the SD card from the board

Do not flash by hand: `./devkit flash` does the backup, verify-before-swap,
clean unmount, reboot and post-boot check (see `build-and-flash.md`). If you
must copy a file, `mkdir -p` the mount point after a reboot (or `scp` writes
nothing and the board reboots into the old image), and compare md5sums before
rebooting.

## The login message says what the board runs (modern Debian)

An ssh login prints the boot-file build and the Debian-root build (red when they
differ), the GitHub release each one is with its releases/tag link (a `git
describe` string with commits after the tag says "none, N commits after vX.Y"
and links vX.Y), the FPGA design, both TX attenuators and the temperatures, from
`/etc/update-motd.d/10-fishball`. The build facts are `fishball_build`,
`fishball_xsa`, `fishball_fpga` and `fishball_bitstream` in `/boot/uEnv.txt`,
stamped by `firmware-modern/build_all.sh`; `ssh fishball 'grep ^fishball_ /boot/uEnv.txt'`
reads them without logging in interactively. `fishball-bootbin [--pl-sha256]` on
the board lists BOOT.bin's partitions and hashes, no bootgen needed; it hashes the
bitstream exactly as `firmware/scripts/check_bootbin.py` does (`01e6f3063e780a20`
= the v1.7 design every v2.x release carries). A command over ssh
(`ssh fishball cmd`) does not print the message; only interactive logins do.

`fishball-help` on the board prints a cheat sheet of every command that matters,
grouped by job (look, receive, transmit, persistent `fw_setenv` switches, logs,
services). Logs are only in the systemd journal: there is no rsyslog, so there is
no `/var/log/syslog`; use `journalctl -b`, `-k`, `-u iiod`, `-b -1`. Note that
`systemctl restart iiod` does NOT re-run the mute (fishball-rf-quiesce is a
oneshot with RemainAfterExit); `systemctl restart fishball-rf-quiesce` mutes and
restarts iiod with it.

## Streaming ceiling over the network (docs/streaming-paths.md)

RX2 to a PC sustains **11 MS/s through iiod 0.26** (44-46 MB/s), **11 through
libiio 1.0's iiod**, **12 through tools/stream-paths/zc-stream** int16 (raw TCP,
one copy), and **20 MS/s through `zc-stream -8`** (int8, convert and send on
separate cores, sender pinned to CPU1). The 16-bit paths stop with one
Cortex-A9 core at 100%; the 8-bit one stops at ~42.7 MB/s, the kernel's TCP
send path plus the network softirq on CPU0, and a synthetic source stops there
too. MSG_ZEROCOPY from the IIO DMA mapping fails with EFAULT. 8 bits cost
~24 dB of dynamic range (48 vs 72 dB). The patched SDR++ reads it as
**Transport: Fast TCP, 8-bit**: all controls via libiio, samples from
`zc-stream -D -8` (RX1 on 5555, RX2 on 5556), installed on the Debian root with
`make install` + `systemctl enable --now zc-stream`. Not over USB.
`tools/stream-paths/rx-rate.py` (`--bps 2` for int8) measures any reader.
The patched SDR++'s libiio path fetches 1/20 s blocks (SDR++'s own 1/200 s ones
delivered 83% of 7.68 MS/s over Wi-Fi: each block is an iiod round trip; with
1/20 s, 99.9% and 10 MS/s in full), so libiio in SDR++ reaches ~10 MS/s.
zc-stream sizes its DMA blocks to ~50 ms of the rate at connect (a fixed 1 M
blocks took 4 s each at the decimator's 250 kS/s). **Gain mode `hybrid` pins RX
gain at 73 dB on this board** (measured: 73 dB in hybrid, 55-56 in the AGC modes), which
clips a strong band; only `manual` accepts `hardwaregain` writes (exit 1 in
every automatic mode), so the patched SDR++ slider switches to manual when moved.

**One receive buffer, and libiio breaks the stream it fails to join.** libiio's
local open writes `buffer/enable` 0 before opening the device, so a second
streamer's failed (EBUSY) attempt stops the first one's DMA, whose refill then
times out. zc-stream refuses clients while `buffer/enable` is 1 and rebuilds
its buffer after a refill timeout. Any other local streamer can still do this
to iiod. While SDR++ streams through zc-stream, `./devkit selftest` and Hardware
CI cannot stream; stop SDR++ (or `systemctl stop zc-stream`) first.

## chirp-view: TX1 sweep watched on RX1 (tools/chirp-view, docs/chirp-view.md)

`--channel 2` runs it on TX2 -> pad -> RX2 (TX1 muted, zc-stream port 5556,
mirror calibration cached under its own `ch=2` key). TX2's raw image measured
-51 dBc, worse than TX1's; calibrated to -64..-69 dBc through a 30 dB loop.

`--reference loops|split` times pulse compression against the other receiver:
both RX read from ONE libiio buffer (sample-simultaneous; zc-stream cannot, its
two ports each open the single RX buffer), each block rolled so the reference
peak sits mid-period, readout RX1 - RX2. `loops` plays one pulse on TX1 and TX2
together. libiio 2ch x 16 bit caps it at 5.5 MS/s (default 4.8, 1.6 MHz). With
every PC core loaded (42-77% of samples arriving, 138 losses) RX1 - RX2 held at
-0.44..-0.49 ns; without the reference the peak jumped across the whole period.

A PC program: cyclic sweep on TX1 (8 modes), live spectrum/waterfall/response
of RX1 through the 20 dB loop, at 20 MS/s via `zc-stream` (8-bit) in its own
process. TX and RX LOs both sit below the sweep (offset tuning), so TX LO
leakage and RX DC land together outside it. Measured IQ images with a tone and
the LOs 0.3 MHz apart: **TX -58..-61 dBc, RX -76..-86 dBc** with RX quadrature
tracking on. Its "Calibrate mirror" fits a per-frequency TX pre-correction
`x - a*conj(x)` (a ~ -1.1e-3) from five probes per point and gets TX to
-78..-84 dBc. **Do not disable RX quadrature tracking to "hold it still"**: the
chip then drops its correction and the RX image rose to -32 dBc. A libiio RX
buffer left open (e.g. by a calibration capture) makes zc-stream refuse the next
client ("in use by another program"): destroy it after each capture.
Pulsed mode (period <= 10 ms) adds a matched-filter view: 7 MHz x 100 us gives
123 ns -3 dB width (theory 127), -18 dB sidelobes, 28.5 dB B*T. It folds by
sample count, so RX losses move the peak (counted as re-alignments, ~1/s at
20 MS/s over Wi-Fi). Drawing a 20k-point antialiased curve at 25 fps slowed the
receive process enough that zc-stream delivered 90% instead of 98%: draw only
the visible span.
