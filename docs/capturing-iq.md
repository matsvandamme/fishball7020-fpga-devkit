# Capturing IQ that is still useful in a year

Two problems with a raw capture off this board, and `tools/sigmf-capture.py`
exists for both.

**The file does not describe itself.** `iio_readdev` writes bare samples with no
header — no sample rate, no centre frequency, no gain, no date. Six months later
it is a file you are afraid to delete.

**The file does not tell you it is broken.** `iio_readdev` returns the byte count
you asked for whether or not the hardware kept up. A capture that overflowed
looks exactly like one that did not.

```bash
# run from: the repo root
tools/sigmf-capture.py record out --rate 3e6 --freq 900e6 --seconds 5 \
    --channels both --verify --annotate
```

That produces `out.sigmf-data` (the samples, untouched) and `out.sigmf-meta`
(JSON describing them), and the sidecar carries its own verdict on whether the
capture is intact.

## What SigMF is

**SigMF** — Signal Metadata Format — is a convention, not a library. Rename the
capture `x.sigmf-data`, write a small JSON file `x.sigmf-meta` beside it, and
every tool that read the bare file still reads it while the file now explains
itself.

Everything in the sidecar is **read back from the board after configuration**,
never copied from the command line. The AD9361 quantises gain to its own table,
`rf_bandwidth` snaps to what the filter design supports, and
`sampling_frequency` lands on what the clock tree can produce. A value you wrote
is an intention; a value you read back is a fact.

## The one field that is not optional

```json
"core:datatype": "ci16_le",
"fishball:full_scale": 2047,
"fishball:scaling_note": "Samples are signed 12-bit sign-extended into int16.
                          Divide by 2047 for full scale, NOT 32768."
```

`ci16_le` means *complex, signed integer, 16 bits, little-endian* — four bytes
per sample, I then Q. It describes the **container** and has no way to say what
counts as full scale, so a reader will reasonably assume ±32767.

On this board it is **±2047**, because the converters are 12-bit sign-extended
into an int16. The board says so itself: `iio_attr -i -c cf-ad9361-lpc` reports
the format as `le:S12/16>>0`.

Divide by 32768 instead and every absolute level you publish is **24 dB** too
low — uniformly, so nothing looks wrong. Spectra keep their shape and every SNR
and EVM figure is unchanged, because those are ratios and the error cancels.
Only absolute levels move, and they move together.

## How fast you can actually go

Measured on one board over gigabit Ethernet, receive only, with `TX2A` looped to
`RX2A` through a 20 dB pad and `RX1A` open — see the last section, because that
cabling is visible in the numbers. Each channel is
4 bytes per sample, so two channels is 8.

| | Data rate | 1 s of samples took | Phase jumps |
|---|---|---|---|
| 1 channel @ 10 MSPS | 40 MB/s | 1.19 s | 0 — clean |
| 2 channels @ 10 MSPS | 80 MB/s | 1.69–1.71 s | **3 to 21 — dropping** |
| 2 channels @ 3 MSPS | 24 MB/s | 1.10–1.29 s | 0 — clean |

The jump count in the middle row varies run to run, because how badly the DMA
overflows depends on what else the host and the network are doing at the time.
That variability is itself the argument for `--verify`: you cannot tell from the
file, and you cannot tell from one good run either.

The ~31 MB/s plateau in
[`modulation-and-throughput.md`](modulation-and-throughput.md) is a
**bidirectional** figure — transmit feeding the DMA while receive drained it.
Receive alone has the link to itself and sustains closer to 40 MB/s. Above that
the DMA overflows, samples are discarded, and the capture still completes.

`-b 1048576` matters. Smaller buffers fall over sooner.

## `--verify`: does the capture have holes in it?

### How it works

A dropped chunk leaves no marker in the file. What it does leave is a **step in
phase**.

1. Find the strongest tone in the capture.
2. **De-rotate** by it — multiply every sample by a complex exponential at minus
   that frequency, which stands the tone still.
3. What remains should be a constant phase. Average it over 1000-sample blocks.
4. Any step bigger than 0.5 radian between adjacent blocks is samples that are
   not there.

If the air is quiet, inject a tone inside the chip. The AD9361's built-in self
test generates one on the receive path with no RF involved at all:

```bash
# run on your HOST — mode 2 injects into RX; nothing transmits
iio_attr -u ip:192.168.129.200 -D ad9361-phy bist_tone "2 375000 12 0"
#   ... capture ...
iio_attr -u ip:192.168.129.200 -D ad9361-phy bist_tone "0 0 0 0"
```

### What it writes

A clean capture:

```json
"fishball:integrity": {
  "checked": true,
  "channel": "RX1",
  "method": "phase continuity of the strongest tone, averaged over 1000-sample blocks",
  "tone_hz": 375000.0,
  "blocks_tested": 6000,
  "phase_jumps": 0,
  "verdict": "continuous"
}
```

A broken one records where, and **every discontinuity also becomes a SigMF
annotation** so a reader who ignores the private `fishball:` namespace still
trips over it in a standard field:

```json
"verdict": "DISCONTINUOUS - samples were dropped",
"phase_jumps": 21,
"worst_jump_rad": 2.7395,
"jump_at_samples": [8388000, 8389000, 9437000, ...]
```

```json
{"core:sample_start": 8388000, "core:sample_count": 1,
 "core:label": "dropped samples (RX1)",
 "core:comment": "phase discontinuity: the stream is not continuous across this point"}
```

### Three verdicts, not two

`continuous`, `DISCONTINUOUS`, and — just as important — **`inconclusive`**. The
third exists because of a bug found while testing this:

> Run `--verify` on a quiet capture with no tone and the strongest bin is the
> **LO leak at 0 Hz**. It cleared the original 20 dB threshold comfortably, so
> the test ran, de-rotated by about 0 Hz (which does nothing), and then measured
> the phase of pure noise. It reported **2968 jumps out of 3000 blocks** — a
> confident, completely false "your capture is broken".

Three changes fixed it, and all three are worth knowing if you write something
similar:

1. **Blank the bins around DC before searching for the tone.** Every zero-IF
   receiver leaks its own oscillator there, so that spike is always the
   strongest thing present when the air is quiet.
2. **Raise the bar to 30 dB** above the noise floor.
3. **Treat a detector that flags everything as broken, not as a finding.** Real
   drops are occasional. If more than a fifth of blocks trip, the de-rotation
   never locked, and the honest output is `inconclusive` with the reason — not a
   scary verdict the data does not support.

Two further limits: **absence of a check is recorded**, so skipping `--verify`
leaves `"checked": false` with a reason rather than an empty field that reads as
a pass; and it detects **discontinuities**, not every possible corruption — a
drop of an exact multiple of the tone's period would slip through.

## `--annotate`: what is actually in the capture

Two passes, both cheap, both written as standard SigMF annotations with absolute
frequency edges.

**Spectrum.** Periodograms averaged from segments spread across the file, then
peak-picked — peaks with a guard band, not everything above a threshold, because
a strong tone's window skirts sit well above any sensible floor and would be
reported as one enormously wide signal. Each peak gets its −20 dB width.

**Clipping.** Any sample at or beyond ±2047. A clipped capture generates
harmonics that were never on the air, and analysing one wastes an afternoon.

The spike at 0 Hz offset is labelled as an **artefact, not a signal**:

```json
{"core:label": "LO leakage (artefact, not a signal)",
 "core:comment": "Zero-IF receivers leak their own local oscillator to 0 Hz.
                  This is the receiver, not the air."}
```

Every zero-IF receiver has one. Mistaking it for a carrier is a rite of passage,
and there is no reason to let the next person do it.

## Both receivers at once

```bash
# run from: the repo root
tools/sigmf-capture.py record out --channels both --rate 3e6 --seconds 5 --verify
```

One file, `core:num_channels: 2`, interleaved **RX1-I, RX1-Q, RX2-I, RX2-Q** per
sample instant. `--split` writes two independent single-channel recordings
instead, for tools that do not handle multi-channel SigMF.

That order is verified on hardware rather than assumed: setting RX1 to 10 dB
while RX2 sat at 73 dB made words 0 and 1 exactly **32.4 dB** quieter than words
2 and 3.

> ### Two devices, two different channel numberings
>
> ```
> ad9361-phy      input voltage0 = RX1,        voltage1 = RX2
> cf-ad9361-lpc   input voltage0/1 = RX1 I/Q,  voltage2/3 = RX2 I/Q
> ```
>
> Gain, rate and bandwidth live on the first; the sample stream is the second.
> Reaching for `voltage2` to set RX2's gain fails silently — that channel exists
> on the phy but has no `hardwaregain`. Note also that `RX_LO` is an **output**
> channel, so it needs `-o`; reading it with `-i` returns nothing and leaves a
> null frequency in the sidecar.

### Coherent, but not calibrated

Both receivers share one `RX_LO`, so their phase relationship is stable — that is
what makes direction finding possible on this board at all. Measured with the
BIST tone, the inter-channel phase held **0.000° mean with 0.0000° standard
deviation across 15 million samples**.

Read that correctly. BIST injects its tone *digitally* into both chains, so it
proves the two streams are **sample-aligned in the buffer**. It says nothing
about the analogue phase offset through the baluns and traces, which is real,
tens of degrees, and different at every frequency.

Measure that offset with a splitter and matched cables before trusting any angle.
The sidecar carries the warning in a field of its own for the same reason.

## Reading one back

```python
# run from: anywhere, beside the capture
import json, numpy as np

meta = json.load(open("out.sigmf-meta"))
fs   = meta["global"]["core:sample_rate"]
full = meta["global"]["fishball:full_scale"]        # 2047, not 32768
nch  = meta["global"].get("core:num_channels", 1)

v = np.fromfile("out.sigmf-data", dtype="<i2").reshape(-1, 2 * nch)
rx1 = (v[:, 0] + 1j * v[:, 1]) / full
rx2 = (v[:, 2] + 1j * v[:, 3]) / full if nch > 1 else None

print(meta["global"]["fishball:integrity"]["verdict"])
```

`<i2` is numpy's spelling of `ci16_le`: little-endian, signed integer, two bytes.

## Reproducing the measurements on this page

```bash
# run from: the repo root — the drop threshold, found by walking the rate up
for r in 3e6 5e6 10e6; do
  tools/sigmf-capture.py record /tmp/t --channels both --rate $r --seconds 2 --verify
done
```

Every figure here came off one board on gigabit Ethernet, with `TX2A` looped
back to `RX2A` through a 20 dB attenuator and `RX1A` left open. Both
transmitters were at the −89.75 dB floor throughout.

That cabling shows up in the numbers, and is worth understanding before you
compare your own: with the transmitter muted, the **looped** channel still read
about **13 dB hotter** than the open one (RSSI 110.5 against 123.75 dB below full
scale). A loopback cable does not only carry your signal — it carries the
transmit chain's residual noise into the receiver even when nothing is being
sent. An open port, by contrast, sees only whatever the room is doing.

Treat all of this as indicative of one board and one bench, not as a
specification.
