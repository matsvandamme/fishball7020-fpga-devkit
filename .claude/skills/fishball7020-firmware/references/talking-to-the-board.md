# Talking to the board

## Three routes in

| Route | Reaches | Notes |
|---|---|---|
| libiio network protocol, port 30431 | IIO attributes, sample buffers | no library needed; `tools/selftest/iiod_min.py` speaks it with the standard library alone |
| ssh `root@192.168.2.1` (password `analog`) | sysfs, debugfs, the filesystem | busybox — see limits below |
| USB mass storage / serial console | firmware images, boot messages | the debug port's UART shows the whole boot; the OTG port's only appears after Linux is up |

## Where the board's address lives, and the file that is a decoy

The addresses are in the **U-Boot environment in QSPI flash** (`/dev/mtd1`, per
`/etc/fw_env.config`), not on the SD card. `S40network` regenerates
`/etc/network/interfaces`, `/etc/udhcpd.conf` and `/opt/config.txt` from it at
every boot, so editing those files is a fine way to test and a guaranteed way to
lose the setting. Because it is QSPI, address settings **survive
`./devkit flash --all`**.

`ipaddr_eth` is a switch, not just a value: set = static `eth0`, unset = DHCP.
`fw_setenv ipaddr_eth` with no value deletes it and returns the board to DHCP.

**`uEnv.txt` on the SD card does not change the Linux address.** U-Boot reads it
with `env import`, which touches only the in-RAM environment - there is no
`saveenv` in the SD boot path - and Linux's `fw_printenv` reads `/dev/mtd1`.
The trap is that `uEnv.txt` ships `ipaddr=192.168.2.1` while the QSPI env has no
`ipaddr` at all, and `S40network`'s compiled-in default is the same number, so
"I edited uEnv.txt and it worked" is indistinguishable from the file never being
read. Verified on hardware: `fw_printenv ipaddr` returns `"ipaddr" not defined`.

**A static address has no default route and no DNS.** The static branch writes
only `address` and `netmask`; nothing writes `/etc/resolv.conf`. Measured: two
link-scope routes, no `default via`, `ping 8.8.8.8` fails. DHCP does set both
(udhcpc's `default.script`). Prefer a DHCP reservation on the router, or add the
route in `/mnt/jffs2/autorun.sh`.

Finding a board whose address you do not know: `iio_info -s` (DNS-SD, prints
address + model + serial and confirms IIOD is up), or `ip:pluto.local` as a URI
and never hard-code an address. `usb0` keeps 192.168.2.1 whatever you did to
`eth0`, so a USB cable is always the way back in. Full write-up:
[`docs/networking.md`](../../../../docs/networking.md).

## IIOD protocol gotchas

All confirmed against a live board running IIOD 0.25.

- **The channel mask is fixed-width**: exactly 8 hex characters per 32 scan
  channels. `00000003` enables channels 0 and 1. Both `3` and
  `0000000000000003` fail with `-22 EINVAL` and no hint.
- **`WRITEBUF` is acknowledged twice**, before and after the payload. Skip the
  first status and the stream desyncs, with your samples arriving as the next
  "response line".
- **`VERSION` answers with a bare line**, not a length-prefixed payload — the
  one command that breaks the general framing rule.
- **Large transfers time out on the board, not the client.** 1,048,576 samples
  succeeds; 4,194,304 fails with `-110 ETIMEDOUT`. Raising the client timeout
  does not help. Chunk at 262,144 and loop `READBUF` on one open buffer.
- **Receive is 12-bit sign-extended into int16** (full scale ±2047). **Transmit
  is the full 16 bits.** Scaling transmit samples to ±2047 emits 24 dB low.

## A capture that completes is not a capture that is intact

`iio_readdev` returns the byte count you asked for whether or not the DMA
overflowed underneath it, so a capture that lost samples is the same size as one
that did not. Measured, receive only, over Ethernet: one channel at 10 MSPS
(40 MB/s) is clean; **two channels at 10 MSPS (80 MB/s) drops**, and two at
3 MSPS (24 MB/s) is clean. The ~31 MB/s plateau in
`docs/modulation-and-throughput.md` is a *bidirectional* figure — receive alone
sustains closer to 40.

What a drop leaves is a step in phase: de-rotate the strongest tone and the
residual should be flat. `tools/sigmf-capture.py --verify` does that and records
the verdict in the recording's own SigMF sidecar; `docs/capturing-iq.md` explains
the method. Inject a tone with `bist_tone` if the air is quiet — mode 2 is inside
the chip and transmits nothing.

**The trap inside the trap:** with no tone present the strongest bin is the LO
leak at DC, and de-rotating by ~0 Hz then measures the phase of noise. That
reported 2968 jumps out of 3000 blocks — a confident false alarm. Blank the bins
around DC, and treat a detector that flags most of the capture as broken rather
than as a finding.

## Two devices, two channel numberings

```
ad9361-phy      input voltage0 = RX1,        voltage1 = RX2      (gain, rate, bandwidth)
cf-ad9361-lpc   input voltage0/1 = RX1 I/Q,  voltage2/3 = RX2 I/Q  (the sample stream)
```

Setting RX2's gain via phy `voltage2` fails silently — that channel exists but
has no `hardwaregain`. `RX_LO` is an **output** channel and needs `-o`; reading
it with `-i` returns nothing. Verified on hardware: RX1 at 10 dB against RX2 at
73 dB made stream words 0,1 exactly 32.4 dB quieter than words 2,3.

## pyadi-iio returns receive data from BEFORE your last change

libiio keeps a few kernel blocks queued for a receive buffer. Once they fill,
the DMA stops and the old blocks wait. So after changing any setting, the next
few `sdr.rx()` calls return samples captured at the PREVIOUS setting. Every
reading lags one step, which looks exactly like "TX attenuation does nothing" -
it cost five runs to find, and the firmware's mute patches were fine. Call
`sdr.rx_destroy_buffer()` before each measurement that follows a change.

After a low-rate run through pyadi (below 2.083 MSPS) the AD9361's own FIR is
left enabled in x4 mode. Restore by setting the rate back with pyadi's setter
FIRST, then `in_out_voltage_filter_fir_en = 0`; the other order is invalid
below 2.083 MSPS. Check `rx_path_rates` afterwards.

## Two applications cannot hold the board at once

Opening it in SDRangel or anything else that claims the USB device reconfigures
the composite gadget, the Ethernet gadget disappears, and `ip:192.168.2.1` stops
answering until that application closes. Not a fault; just exclusive.

## busybox limits

- **No `pkill`.** Use `ps` and `kill` with a PID. (And beware: `pkill -f
  <pattern>` run from your own shell can match your own command line and kill
  the shell — this has happened here more than once.)
- **No ftrace**, so no kprobes. `dump_stack()` in a driver plus `dmesg` is the
  available substitute.
- `dmesg` being empty is information: it means the kernel is not doing what you
  suspect.

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

`bist_timing_analysis` needs a write to trigger, then a read: it walks all 16×16
clock/data delay combinations with a PRBS running and prints the eye. `loopback`
= 1 routes DAC data back into the ADC path inside the chip, which exercises both
DMAs and the LVDS link with no RF at all — remember to set it back to 0.

**FPGA core registers: set bit 31 of the address.** The two cores' debug
register access (`direct_reg_access`, pylibiio `dev.reg_read/reg_write`)
decides by bit 31 where an address goes. On **`cf-ad9361-lpc`** (the ADC core)
a plain address such as `0xB8` is passed to the **AD9361 over SPI**. Only
`0x800000B8` reaches the FPGA core's register. The DAC core happens to run in
"standalone" mode and maps plain addresses to itself, so the same code
"works" on one core and silently reads and writes radio-chip registers on the
other. Always use the flag for core registers:

```python
# pylibiio: the ADC core's GP input and GP_CONTROL registers
adc.reg_read(0x80000000 | 0xB8)
adc.reg_write(0x80000000 | 0xBC, value)   # read-modify-write: bit 0 is the kernel's
```

(`drivers/iio/adc/cf_axi_adc_core.c`, `axiadc_reg_access`. Found when the ADC
core's GP input read 0 while the design drove it. The value read, from the
AD9361, happened to be 0, so writing it back changed nothing. Had it not
been, a read-modify-write would have rewritten a radio register.)

## Mounting the SD card from the board

```bash
# Do not flash by hand - ./devkit flash does backup, verify-before-swap, clean
# unmount, reboot and a post-boot check. See build-and-flash.md.
```

Forgetting `mkdir -p` after a reboot is a good way to have `scp` write nothing
and then reboot into the old image believing you flashed. Always compare md5sums
before rebooting.
