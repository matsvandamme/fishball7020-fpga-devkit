# TX idle-case harnesses

The scripts behind the measurements in [`../../IDLE-CASES.md`](../../IDLE-CASES.md):
how a transmit stream can end and what the transmitter does next, how loud the
power-on calibration burst is, and whether the loopback bench's RF paths and
decimators are sound. Re-run them to reproduce any number in that file.

**They transmit.** Each one that keys a channel needs an affirmation on record for
that channel (see [`docs/transmitter-safety.md`](../../docs/transmitter-safety.md))
and refuses without one. The port you name needs at least 20 dB of attenuation on
it before you affirm.

## Quick start

```bash
# run from: the repo root, on the HOST
./devkit tx-guard status                     # also pushes tx-guard.sh to the board

# CH is the transmit channel: 0 = TX1A, 1 = TX2A. Every harness that transmits
# requires it and none has a default. Look at that port before you affirm it.
CH=0
./devkit tx-guard affirm $CH

# cases 1, 2, 3
scp -O tools/tx-idle-cases/cases123.sh fishball:/tmp/ && ssh fishball "sh /tmp/cases123.sh $CH"

# case 5
scp -O tools/tx-idle-cases/case5.sh fishball:/tmp/ && ssh fishball "sh /tmp/case5.sh $CH"

# case 4 - the relay and the poller go too
scp -O tools/tcp-blackhole.py tools/tx-idle-cases/case4{b.sh,-poller.sh} fishball:/tmp/
ssh fishball "sh /tmp/case4b.sh $CH"

./devkit tx-guard revoke both                # when you are done
```

**One affirmation covers one run.** Every harness ends by calling
`tx-guard.sh revoke both`, which mutes and removes the affirmation, including on a
clean exit. A second run is a second chance to have moved a cable, so it asks
again: `affirm` before each run. A back-to-back re-run that exits 3 at the gate is
the gate working, not a fault, and each script says so on the way out.

**The channel is a required argument.** A script that picks a transmit port for
you is the same class of defect as a gate that defaults to affirmed, and one of
the two ports may have an antenna on it. `cs8-level.py`, `avg-level.py` and
`watch.sh` only observe and take no channel.

## What each one is for

| script | runs on | channel arg | measures |
|---|---|---|---|
| `cases123.sh` | the board | required | cases 1, 2 and 3: normal close, a network client killed so the FIN *does* arrive, and starvation with the client still alive and holding the buffer |
| `case5.sh` | the board | required | case 5: a **local** client `SIGKILL`ed. No iiod, no socket: the path `firmware/patches/0015` exists for |
| `case4b.sh` | the board | required | case 4: a genuine network **drop**. Needs `tcp-blackhole.py` and `tx-guard.sh` pushed to `/tmp` (see above) |
| `case4a.sh` | the host | required, 5th arg | case 4 over real Ethernet. **Expected to ABORT**: the host↔board link cannot keep the DAC fed at 3.072 MSPS, so the watchdog fires before the drop. Kept because that abort is itself the result |
| `case4-poller.sh` | the board | required | waits for a loud→quiet transition and records `buffer/enable`, `LO_pd` and `ss` *at that instant* |
| `resume-after-starve.py` | the host | none, commands no output | feeds one buffer, stalls it, feeds it again: does the transmitter come back after a starve mute, and does it mute again (`0024`)? Zero samples at -89.5 dB; takes a libiio URI, e.g. `usb:1.5.5` |
| `watch.sh` | the board | none, watches both | polls flat out for N seconds and reports whether the TX buffer was **ever** enabled and the loudest attenuation on **either** channel, with an explicit `unreadable` flag |
| `dds-tone.sh` | the board | required | drives the FPGA's hardware DDS (the built-in tone generator) on one chain, **no DMA buffer at all**. The most dangerous script here; see the warning below |
| `cs8-level.py` | the host | none | a **single-FFT peak**, a floor and `max\|sample\|` with a clipping flag. Good for a strong tone; it reads noise as a carrier 8-16 dB over the median, so it is not the analyser behind the calibration ladder (`avg-level.py` is) |
| `avg-level.py` | the host | none | the averaged analyser behind the idle-emission measurement: per-bin mean over every FFT in a window, clipped blocks rejected and counted |
| `tone.py` | the host | **required, 3rd arg** | a cyclic tone at a commanded attenuation, through the gate; the calibration ladder's source |
| `scan-boot-burst.py` | the host | none | finds the power-on emission in a long second-receiver capture (see below) |
| `verify-rf-paths.py` | the host | none, does both | TX_LO == RX_LO, and the tone lands where it was sent, at each decimation |
| `verify-decimator.py` | the host | none, does both | anti-alias rejection at the predicted fold frequency |

> ### `dds-tone.sh` is the one to be careful with
>
> It opens **no DMA buffer**, so neither patch `0004`'s stream-stop mute nor `0015`'s
> starve watchdog can reach it: there is no stream to stop and no data to stop
> arriving. It powers the TX LO up by hand and can drive either chain. So it gates
> on an affirmation for that channel, traps its own exit to turn the tone off and
> mute both channels, and holds in a loop so the trap is what ends it. Without
> those, an interrupted run leaves a tone up that nothing in the firmware can end.
> Run it in the foreground: under `nohup` its `HUP` trap is not installed.

**The three termination harnesses record a cache restore at the buffer enable
rather than aborting on it.** Opening a transmit buffer restores the last stream's
gain (see `IDLE-CASES.md`), and after one of these runs that cache holds the run's
own gain, so aborting would make them fail on every second run. They print that it
happened, mute, verify the mute, and carry on. A tool that *intends* silence should
abort instead, which is what `tx_gate.assert_quiet_after_enable` does.

## Pitfalls

- **Reap between cases.** A killed client leaves `buffer/enable` at `1` with no
  owner, and the *next* client then fails with `Open unlocked: -32` before
  streaming a byte, which looks like a result. Run `./devkit tx-guard reap` first;
  `cases123.sh` and `case4b.sh` assert `buffer/enable` is `0` before they start.
- **Pin the sample rate.** These scripts set it explicitly. At 30.72 MSPS, left
  behind by another tool, "about 2 seconds of samples" becomes 0.2 s: the stream
  is over before the first read-back and case 1 measures a normal close.
- **`case4b.sh` needs `--chunk` large.** At 64 KB per `recv`/`sendall` the relay
  itself starves the DAC on this board's CPU, which looks exactly like the board
  being unable to keep up. It passes `--chunk 1048576`; do not lower it.

## Not here

The script behind the **withdrawn** idle-emission capture (the −56.0 / −88.9 dBFS
pair) is lost, and that measurement is withdrawn from `IDLE-CASES.md` in full: its
two captures had unrecorded receive gain and floors 15.6 dB apart. Its replacement
is reproducible from this directory: `avg-level.py` is the analyser, `dds-tone.sh`
the positive control, and the receiver gain is stated with the result.

## The power-on capture, with a second receiver

`scan-boot-burst.py` and `tone.py` find and calibrate the power-on emission
recorded in `../../IDLE-CASES.md`. They need a **second receiver**, because the
board's own receiver powers up with the board. The bench used a HackRF One cabled
to TX1 through the same 20 dB pad.

```bash
# run from: the repo root, on the HOST. Tune OFF the board's LO: with its carrier
# on the receiver's own DC leak, present and absent read alike.
hackrf_transfer -r /tmp/cycle.cs8 -f 2398500000 -s 4000000 -n 1400000000   # 350 s
#   ... power-cycle the board once or twice while that runs ...
./tools/tx-idle-cases/scan-boot-burst.py /tmp/cycle.cs8 15
```

`scan-boot-burst.py` compares the TX-LO band against two control bands for every
0.5 ms FFT in the file, and reports only where the TX band wins by the threshold.
That rejects a broadband power-on click instead of reporting it, and finds a 4 ms
event in a 350 s file without being told where to look.

Both controls are on the **same side**: 1.0 MHz and 3.0 MHz *below* the TX band.
The capture is centred 1.5 MHz under the TX LO at 4 MSPS, so only 0.5 MHz of
spectrum sits above the TX band, too little for a control. The test therefore
rejects a click that lifts the whole span, but would not reject an event confined
to the half-band above the LO.

To turn dBFS into dBm, run the ladder with the receiver **unchanged** and fit it;
the cable and pad then cancel out of the comparison:

```bash
# run from: the repo root. CH is the transmit channel; affirm it first.
CH=0
for a in -55 -45 -35 -25 -20; do ./tools/tx-idle-cases/tone.py $a 8 $CH & sleep 3
  hackrf_transfer -r /tmp/ref$a.cs8 -f 2398500000 -s 4000000 -n 8000000; wait; done
```

**Check for clipping every time.** The burst pinned the receiver's ADC at full
scale (`max|sample| = 127`), which makes its measured power a lower bound. Print
`max(abs(samples))` alongside any level you quote, and re-run at lower receiver
gain if it saturates.

## Verifying the RF paths and the decimators

`verify-rf-paths.py` and `verify-decimator.py` check the two things a loopback
bench has to get right before any measurement through it means anything: that the
receiver is tuned where the transmitter is, and that decimation (dropping samples
after a low-pass filter to lower the rate) does not move or fold the signal. Both
use the selftest's own `Board` class for capture, because an ad-hoc receive
harness gave a peak-to-floor of 13 dB at frequencies matching neither sent tone,
on channels that work.

```bash
# run from: the repo root. Needs both loops and an affirmation per channel.
./devkit tx-guard affirm 0 && ./devkit tx-guard affirm 1
./tools/tx-idle-cases/verify-rf-paths.py      # LO equality + decimated rates
./tools/tx-idle-cases/verify-decimator.py     # anti-alias rejection
./devkit tx-guard revoke both
```

Results with TX1 → 20 dB → RX1 and TX2 → 30 dB → RX2:

| | TX1 → RX1 | TX2 → RX2 |
|---|---|---|
| TX_LO − RX_LO | **+0.0 Hz** | **+0.0 Hz** |
| tone 300 kHz out, received at | 300.000 kHz, **0.0 Hz error** | 300.000 kHz, **0.0 Hz error** |
| tone through ÷1 and ÷8 | same bin, 0 Hz error | same bin, 0 Hz error |
| anti-alias rejection at the fold frequency | **63.8 dB** | **85.3 dB** |

**Both decimators are in the path.** The AD9361's own FIR reports `Rx: 128,2`
(128 taps, ÷2) and is enabled (`in_out_voltage_filter_fir_en = 1`). The FPGA
channelizer is the ÷8: the RX device advertises exactly two delivered rates,
`3071997` and `383999`, and you select one by writing
`in_voltage_sampling_frequency` on `cf-ad9361-lpc`, **not** on the phy, which
holds the converter rate.

**Test the fold frequency, not just the rate.** A decimator that changed the
sample rate and nothing else would pass a naive test. The out-of-band tone goes at
600 kHz and the check is the level at `((600 + fs/2) mod fs) − fs/2` = −168 kHz,
where it would land if nothing filtered it. Looking for "the strongest peak"
instead finds unrelated residue elsewhere and reads like rejection when it is not.
