# Transmitting with this board without destroying it

**The receiver is the fragile end.** The AD9361's RX input is rated to about
**+2.5 dBm**. That is the number every decision here is measured against.

## This board may have a power amplifier

It is sold in two variants, "with PA" and "without PA", and the vendor does not
publish the difference. The PA is a Mini-Circuits **PGA-102+**, whose gain is
strongly frequency dependent:

| GHz | 0.05 | 0.8 | 2.0 | 3.0 | 4.0 | 6.0 |
|---|---|---|---|---|---|---|
| **Gain (dB)** | **17.7** | 15.9 | 14.0 | 12.5 | 11.5 | 10.4 |

P1dB is about +17.5 dBm. Plan for **about +19 dBm** flat out - roughly
**16 dB above what its own receive port survives**. That is the self-test's
estimate (scaled up from a quiet measurement, capped at the PA's compression
point), not a power-meter reading: never write "+19 dBm measured".

<sub>Canonical copy of this table: `docs/transmitter-safety.md`. Change it
there first, then mirror it here.</sub>

Sizing a loopback for a bare AD9361 (+7 dBm) is therefore wrong by 10-18 dB,
and most Pluto advice on the internet does exactly that.

`tools/selftest/sdr_selftest.py --loopback` reports which variant a board is,
by comparing measured loop gain against both models.

## Rules

- **Never loop TX to RX without an attenuator.** Fit at least 20 dB. More is
  equally safe, but for *measurement* 20 dB is also the right choice: the
  board's own TX->RX leak equals a 33-60 dB pad on channel 0 above 1 GHz, so a
  50 dB loop there measures the leak as much as the cable (see `measuring.md`).
- **Never transmit into an antenna** unless you hold a licence for the
  frequency. This board covers the FM broadcast band, and with the PA it is
  not a trivial transmitter.
- Start at maximum attenuation and work down, measuring as you go. Never start
  loud and back off.
- The self-test never transmits with less than **35 dB** of its own
  attenuation: worst case (full-scale drive, 18 dB of PA gain, no external
  pad) that is -10 dBm, 12.5 dB under the RX rating.

## TX muting in this firmware

`patches/0004` mutes the transmitter whenever no DMA buffer is streaming, and
unmutes when one starts. `patches/0005` makes that unmute non-destructive:

| What you do | What you get |
|---|---|
| set a gain, then start the stream | the gain you set |
| start the stream having set nothing | the last gain you used |
| stop the stream | maximum attenuation, TX synthesiser down |

The `postdisable` hook runs even if the application crashed, because teardown
happens on file close — which is why this is a guarantee and a userspace
watchdog is not.

**Both mechanisms earn their place.** Measured at 900 MHz with the receive LO
offset by 1 MHz, so leakage could be told apart from the receiver's own DC
offset: muting the attenuators alone leaves residual LO **26 dB above the noise
floor**; powering the synthesiser down as well takes it a further **19.9 dB**,
to within 6 dB of the floor — about −89 dBm at the port. Neither is sufficient
alone, and measuring at DC will not show you this, because RX LO = TX LO puts
the leakage exactly where the receiver's own offset lives.

If you find a script polling `buffer/enable` to re-apply a gain, it is a
workaround for the pre-0005 behaviour and should be deleted; it overrides the
application silently. Look in `/mnt/jffs2/autorun.sh`.

## Measuring, not guessing

Received levels are dBFS against a **12-bit** converter (full scale ±2047).
Transmit is **16-bit** — scaling transmit samples to ±2047 emits 24 dB low.

RX gain is not linear in the way its label suggests: the AD9361's gain table
changes the LNA/mixer word at commanded 5, 17, 27, roughly 31-37, 52, and
every step above 63, and the real gain steps by up to 10 dB there while the
label claims 1 dB. **38-51 dB is the widest window with no transition in it**
in any band, and it is the only place a gain sweep means anything. Fitting a
line across the whole range reports ~0.67 dB/dB for a perfectly healthy front
end.

The legal gain range also moves with frequency: `[-1, 73]` below 1.3 GHz,
`[-3, 71]` to 4 GHz, `[-10, 62]` above. Writing outside it returns `-22 EINVAL`.

## Stopping a transmission is two steps, in this order

A one-shot buffer finishes by itself. A **cyclic** one does not: the DMA keeps
feeding the DAC from the same buffer with no further help from the writer, so
the order matters.

**Mute first, then kill the writer.** Killing the writer first leaves a window
where the DMA is still running and nothing is holding the attenuation.

Measured this session: a trap that muted both channels ran correctly on SIGTERM
and the attenuation read back `-89.750000 dB` - and `iio_writedev` was **still
running**. Muted but still streaming. Clear it explicitly:

```bash
# run on your HOST
pkill -x iio_writedev
```

**Then read the hardware back, not the log.** A script printing "muting" proves
only that the line executed. Four things are worth checking, and the last one
catches what the others miss:

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

The DDS sweep is the one people skip. A leftover tone generator transmits
**independently of the DMA path**, so a muted attenuator and a dead writer say
nothing about it. All eight should read `0.000000`.

**Never `pkill -f` a script by its filename** while stopping it from a shell
whose own command line contains that filename - `pkill` matches itself and kills
the shell mid-sequence, typically between the mute and the verification. Kill by
PID, or use a bracket pattern.

## What protects the transmitter when nothing is streaming

Two mechanisms, both verifiable on a running board rather than inferred:

```bash
# run on the board
grep -c tx_quiesce /etc/init.d/S21misc      # boot-time quiesce present
```

`tx_quiesce` in `S21misc` sets the attenuation at boot, because the AD9361 comes
up in ENSM `fdd` with the TX chain biased and only 10 dB of attenuation - so the
port emits LO leakage from power-on with nothing in the DAC DMA. It sets
**attenuation only, deliberately not the TX LO**: powering the synthesiser down
at boot would leave a later stream transmitting into a dead LO, silently.

From then on `patches/0004` hands muting to the kernel, which unmutes when a TX
DMA buffer starts and re-mutes when it stops. That is what mutes the radio when
a writer is killed.
