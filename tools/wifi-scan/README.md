# Which Wi-Fi channels are busy?

A GNU Radio application that sweeps the 2.4 GHz and 5 GHz bands with the
Fishball7020 and draws what it found.

```bash
# run from: tools/wifi-scan/
./wifi_scan.py --uri ip:fishball.local --band both -o scan.json
./plot_scan.py scan.json                 # -> scan-2.4.png, scan-5.png
```

There is also a **flowgraph you can open in GNU Radio Companion**, for watching
one channel live instead of sweeping the whole band:

```bash
# run from: tools/wifi-scan/
gnuradio-companion fishball_wifi_live.grc
```

It makes **five measurements from one receive stream**:

| | |
|---|---|
| **Spectrum + waterfall** | what is on the air, from *both* receivers |
| **Channel power** | the selected 20 MHz channel alone, in dBFS, with the rest of the band filtered away |
| **Busy %** | how much of the captured time that channel spent above a threshold you set |
| **Burst envelope** | individual packets, in the time domain |
| **RX1 − RX2 phase** | the two coherent receivers against each other |

Pick a channel, press play, and **turn on Max Hold** in the frequency sink's
control panel — Wi-Fi is silent between bursts and the average alone will tell
you an occupied channel is empty. To use the busy percentage, first read the
channel power with nothing transmitting, then set the threshold a few dB above
it.

**It sweeps.** The checkbox starts a Python Snippet — a controller that lives
inside the flowgraph — stepping the chooser through the channel list a second at
a time. A sweep cannot be drawn as *wires*, because it is a loop over time
rather than a path for samples; but GRC will happily carry the thread that
drives one, and setting the chooser variable is exactly what clicking it does.

### How the pieces earn their place

- **The channel filter** is a frequency-translating FFT filter. It shifts the
  chosen channel to baseband and throws the other 36 MHz away, so the power and
  busy readings are about that channel and nothing else — including none of the
  LO leak.
- **The radio is deliberately not tuned to the channel centre.** It sits 15 MHz
  below, so the AD9361's own LO leak lands clear of the traffic. Every display
  is corrected back, so the x-axis reads true frequency and the spike 15 MHz
  below the channel is visibly the receiver looking at itself. This is also why
  the sample rate is the full 61.44 MSPS: a narrower window cannot hold a 20 MHz
  channel *and* keep it clear of DC.
- **The phase is averaged as a complex number before the angle is taken.**
  Averaging angles directly is wrong — they wrap, and the mean of +179° and
  −179° is not zero.
- **The duty cycle is the mean of a 0/1 signal**, which is what a duty cycle is.
  The threshold has 2 dB of hysteresis so a signal sitting on it does not
  chatter.

### Three things to hold lightly

- **The phase reading is not calibrated.** Each port has its own fixed offset
  through its own balun and traces, so it is a repeatable number rather than a
  bearing, and it changes with frequency. Measure the offset with a splitter and
  matched cables before trusting any angle.
- **Busy % is a percentage of *captured* time.** At 61.44 MSPS the link carries
  roughly an eighth of the samples, so this is a fair sample of the channel's
  state rather than a census of it. Spectra are unaffected — every transform
  still sees contiguous samples.
- **Two limits of the GRC block itself**, both found by compiling it: the gain
  slider stops at 62 dB, which is the ceiling above 4 GHz (below 4 GHz the chip
  allows 71, so raise the slider's stop for a 2.4 GHz channel); and its bandwidth
  field refuses anything above 52 MHz although the driver accepts 56.

Needs `gnuradio` with `gr-iio` (the `fmcomms2` blocks), plus `numpy`, `scipy`
and `matplotlib`. **Receive antennas on RX1** — without one the sweep returns
the board's own noise floor and reports every channel free.

---

## What it is doing

Some vocabulary first, because four of these terms carry the whole design.

- **dBFS** — decibels relative to the converter's full scale. `0 dBFS` is the
  loudest signal the receiver can represent; everything here is negative.
- **Resolution bandwidth (RBW)** — how finely the spectrum is sliced. Narrower
  slices contain less noise, so a weak signal stands further above the floor.
- **Max-hold** — for every frequency, the loudest value seen at any moment
  during the sweep. This is the right detector for Wi-Fi, which is silent
  between bursts.
- **Dwell** — one tuning of the radio, held long enough to measure. The band is
  wider than the radio's 56 MHz window, so a sweep is a sequence of dwells that
  get stitched together afterwards.

The flowgraph is ordinary GNU Radio; what makes it a *scanner* is that a sweep
controller retunes the source between dwells while the graph keeps running:

```
fmcomms2_source_fc32 → stream_to_vector → fft_vcc(window, shift)
                     → complex_to_mag_squared → FrameSink
```

`FrameSink` is a small Python block holding two accumulators per dwell: a
running sum for the average and a running maximum for the max-hold.

## The parameters, and why each one is what it is

| Parameter | Value | Why |
|---|---|---|
| Sample rate | **61.44 MSPS** | The AD9361's maximum. Wider windows mean fewer dwells, so the sweep finishes sooner and each channel is revisited more often. |
| RF bandwidth | **56 MHz** | The widest analog filter the chip has, matched to the sample rate so nothing aliases in from outside. |
| Transform size | **4096 points** | Gives **15.0 kHz** RBW. A 20 MHz Wi-Fi channel is then ~1300 bins wide — its shape is unmistakable — while the narrow slices put the noise floor about 36 dB below where a wideband power measurement would find it. |
| Window | **4-term Blackman-Harris** | The most important choice here. See below. |
| Frames per dwell | **1024** | Two jobs at once: averaging 1024 spectra smooths the noise floor so weak signals emerge, and the dwell then spans several **beacon intervals** (an access point on an idle channel transmits roughly every 100 ms — a short dwell would call it free). |
| LO step | **24 MHz** | Much less than the ~50 MHz each dwell keeps, so every frequency is measured by two or more dwells at different offsets from the centre. That overlap is what makes artefact rejection possible. |
| Excised around each centre | **±1 MHz** | Where the receiver's own local-oscillator leak lands. Never measured; always covered by a neighbouring dwell instead. |
| Dropped at each edge | **9 MHz** | The analog filter is 56 MHz wide and half the sample rate is 61.44/2 = 30.72 MHz, so the outer ~3 MHz of every dwell sits on the filter's shoulder. Keeping it puts a ripple in the stitched result with exactly the period of the LO step — measured at **14.9 dB peak to peak** in an empty part of the 5 GHz band. Dropping 9 MHz keeps only the flat middle and still leaves 41 MHz per dwell. |
| Settling time | **80 ms** | Discarded after each retune, so the synthesiser has locked before anything is recorded. |
| Gain | **manual, auto-ranged per band** | Set once per band by a pre-pass, then never touched — and clamped to the range the radio itself publishes, which is **not the same in the two bands** (see below). |
| Headroom | **12 dB** | The gain is chosen so the loudest thing the pre-pass saw sits 12 dB below full scale. Wi-Fi bursts are far stronger than the average, and a clipped burst is not a measurement. |

Change any of them from the command line: `--sample-rate`, `--nfft`,
`--frames`, `--band`. The values actually used are written into the output JSON,
so a scan is self-describing.

## The five things that buy dynamic range

Dynamic range is the gap between the strongest signal you can measure without
clipping and the weakest you can still see. Everything above is in service of it.

1. **The window.** Each block of samples is tapered before the transform;
   without a taper, a signal that does not fit a whole number of cycles in the
   block smears across the entire spectrum. The usual Hann window leaks at
   −31 dB. Blackman-Harris leaks at **−92 dB**. That is the difference between
   being able to say "channel 9 is quiet" while channel 11 is loud, and not
   being able to say it at all. The price is a wider main lobe — irrelevant when
   the thing being measured is 20 MHz wide.

2. **Nothing is measured near DC.** The AD9361 is a direct-conversion receiver,
   so its own local oscillator leaks into its own output and lands exactly at
   the centre of whatever it is tuned to. In the first test capture of this band
   that artefact sat **17.8 dB above everything else**. Each dwell therefore
   discards ±1 MHz around its own centre, and the overlapping tuning plan
   guarantees some other dwell covers that sliver from a different offset.

3. **Overlapping dwells are combined by taking the minimum** of the averaged
   trace. A receiver artefact — LO leak, the quadrature image, a clock harmonic
   — sits at a fixed offset from the LO, so it *moves* in absolute frequency
   when the LO moves. A real transmitter does not. Keeping the lowest reading
   among the dwells that covered a frequency therefore deletes the receiver's
   own artefacts while leaving the traffic untouched. The max-hold trace is
   combined with *maximum* instead, because there the job is to catch a burst.

4. **The gain is fixed.** Automatic gain control would move the reference level
   between dwells, and a stitched spectrum whose reference level moves is not a
   spectrum. The pre-pass measures the band at a known gain, works out what it
   can afford, sets it, and leaves it alone. The value is recorded.

5. **Averaging.** The noise floor of a single transform is itself noisy, jumping
   several dB bin to bin. Averaging 1024 of them in the power domain settles it
   down, and a signal 3 dB above a smooth floor is visible where one 3 dB above
   a ragged floor is not.

## The trap that cost a sweep

**The AD9361's maximum receive gain depends on the frequency.** It carries three
gain tables and swaps them as it tunes, and the range genuinely differs:

```
2437 MHz   hardwaregain_available = [-3 1 71]      # min, step, max in dB
5320 MHz   hardwaregain_available = [-10 1 62]
```

So 71 dB is a legal gain in the 2.4 GHz band and an **illegal** one in the
5 GHz band. The first version of this scanner hard-coded 71 as its ceiling, and
what happened was worse than an error: `gr-iio` only *logs* the driver's
refusal, so the gain quietly stayed where it was while the output file went on
claiming 71 dB. Every 5 GHz level in that sweep was referred to a number that
was never in force.

The scanner now reads `hardwaregain_available` after retuning into the band,
clamps to it, rounds to the 1 dB step the radio actually accepts, and **reads
the gain back** — refusing to continue if the radio disagrees. It re-checks once
more after the first real retune, because `gr-iio` re-applies the gain every
time the frequency changes.

[`ad9361-gain-tables.md`](../../.claude/skills/fishball7020-firmware/references/ad9361-gain-tables.md)
in this repo states the rule outright: *"Re-read `hardwaregain_available` after
retuning; clamp to it."* It was right there, and worth re-reading before
trusting any level this board reports.

## Reading the pictures

**The spectrum panel** is the one to read first. A Wi-Fi carrier is a flat-topped
hump about 20 MHz wide; that shape is how you tell a transmitter from a spur.
Filled area is max-hold, the line is the long-term average, and the gap between
them is how bursty the traffic is — a busy access point shows a small gap, an
idle one beaconing every 100 ms shows a large one.

**The occupancy panel** answers a different question: what a device *on channel
N* would have to put up with. Two bars per channel, because two different things
are worth knowing:

- **loudest burst** — how far the strongest single moment rose. This answers
  "is anything transmitting here at all".
- **sustained average** — how far the long-term average rose. This answers "how
  heavily is it actually used". A channel with a tall burst bar and a flat
  sustained bar carries a beacon and nothing else.

Each is measured against a floor taken from **its own statistic**: the quiet
tenth of the band on the max-hold trace for the burst bar, and on the average
trace for the sustained bar. That sounds fussy and is not. The max-hold of pure
noise sits about 13 dB above the average of the same noise on this setup,
because it keeps the largest of a thousand random draws — so scoring a max-hold
against an average-derived floor adds that offset to every channel including the
empty ones, and an idle band comes out looking 30 dB busy. The first version of
this tool did exactly that.

In the 2.4 GHz band the channels overlap — spaced 5 MHz apart, 20 MHz wide — so
a single transmitter necessarily raises four or five neighbouring bars. **That is
not an error.** It is the reason 1, 6 and 11 are the only three non-overlapping
choices, and the panel shows you exactly why. The 5 GHz channels do not overlap,
so there each bar stands alone.

## What this cannot tell you

- **Levels are dBFS, not dBm.** Absolute power would need a calibrated
  reference this repository does not have.
- **The two bands are not comparable to each other.** Three separate reasons,
  each enough on its own: the board's flatness is only established from
  [200 MHz to 1 GHz](../../docs/measured-performance.md); its RF baluns carry no
  part number in the schematic, so nothing says what the front end does at
  5 GHz; and the gain-table swap at 4 GHz is itself measured to put a **4.6 dB
  step** in this board's loop gain. Within one band the numbers are comparable;
  across the two they are not.
- **It does not demodulate.** It measures energy, so it cannot tell you an
  SSID, and it cannot distinguish Wi-Fi from a microwave oven, a video sender or
  Bluetooth. The 20 MHz flat-topped shape is strong evidence, not proof.
- **A quiet channel may still have an access point on it.** A longer
  `--frames` makes that less likely; it cannot make it impossible.
- **Occupancy is relative to the band's own floor**, taken as the quietest
  tenth of the band. If every channel were busy, that reference would rise and
  the bars would understate the crowding.
- **It cannot see a channel's width directly**, only infer it. An 80 MHz
  802.11ac carrier lights up four adjacent 5 GHz channels, which looks identical
  to four separate 20 MHz networks until you look at the spectrum panel and see
  one continuous flat top rather than four.

## Checking it against something else

The honest test is to compare against a receiver that decodes rather than
measures:

```bash
# run on your HOST — what the laptop's own wifi card can see
nmcli -f IN-USE,SSID,CHAN,FREQ,SIGNAL dev wifi list
```

Every channel that card reports should appear as a hump in the spectrum panel.
The reverse does not hold: the SDR sees energy the card ignores, including
non-Wi-Fi occupants of the same band.
