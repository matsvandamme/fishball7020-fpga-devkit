# 03 — Two coherent receivers

```bash
# run from: the repo root
gnuradio-companion examples/03-coherent-receivers/coherent_rx.grc
```

Receive only. Nothing here transmits. Put an antenna on **both** RX1 and RX2.

This is the measurement a one-channel radio cannot make, and nothing else in
this repository demonstrates it. RX1 and RX2 live inside one AD9361, behind one
local oscillator and one sample clock. The phase between them is therefore a
property of the signal and the cabling — not of two clocks wandering apart.

## What you are looking at

The **cross-correlation** of the two channels: multiply RX1 by the conjugate of
RX2, average, and take the angle of the result. The angle is the phase
difference. The magnitude, normalised, is the *coherence*.

**Read coherence before you read the angle.** Two independent noise streams
correlate to a number that random-walks toward zero, and its angle is therefore
a random number that the display shows just as confidently as a real one.
Coherence near 1 means the two inputs are hearing the same thing and the angle
means something. Near 0 means you are reading noise with a decimal point on it.
With 4096 samples per estimate, independent noise gives about
1/√4096 = 0.016 — asserted in [`../test_blocks.py`](../test_blocks.py).

**The dial**, bottom middle, is a constellation sink used as a polar meter: the
point's angle is the phase, its radius is the coherence, and the unit circle is
the edge of the plot. A dot pinned to the rim is a measurement. A dot wandering
near the origin is not.

## Three things to try, in order

**1. Find a steady carrier and move one antenna a few centimetres.** The angle
moves; put the antenna back and the angle comes back. That repeatability *is*
the coherent-receiver property. Two independent radios would not do this — their
oscillators would drift and the phase would wander regardless of the antennas.

**2. Tick `zero`, then move an antenna.** The reading is now relative to where
you zeroed. It latches on the rising edge only: holding the box ticked would
re-zero forever and the reading would sit at zero no matter what the antennas
did, which is a convincing way to measure nothing. The raw, unzeroed angle stays
on its own readout precisely so zeroing can never hide it.

**3. Widen `band-select` past the LO offset.** Coherence will climb toward 1 and
sit there, steady and convincing — and it will be measuring the receiver's own
LO leak talking to itself. This is the failure the whole example is arranged to
avoid, and it is worth seeing once so that you recognise it somewhere else.

## Why the band-select filter is not optional

The receiver's local oscillator leaks into its own mixer, in both channels, and
it is **the same leak**. It is therefore almost perfectly correlated with
itself. Correlate the raw channels and you measure the leak: coherence pins to
1 and the angle is a property of the board, not of anything in the air.

So two things happen before the correlation. The LO is offset, putting the leak
away from the signal; and each channel is band-selected around the signal by a
filter that is **identical** to the other. Identical matters: whatever phase a
filter adds, an identical filter adds twice, and it cancels out of the
difference. Two filters with different taps would make the measurement partly a
measurement of the filters. Both filters read the same `sel_taps` expression for
exactly that reason.

## Averaging the correlation, never the angle

The estimate is `mean(x1 · conj(x2))`, and the angle is taken **after** the
averaging. Averaging angles instead is a mistake that hides itself: angles wrap
at ±180°, so a true phase near 180° has samples landing at +179° and −179°,
which average to roughly zero. A signal hard against the wrap point would read
as no phase shift at all. Summing complex numbers has no wrap to fall foul of.

[`../test_blocks.py`](../test_blocks.py) asserts this directly: a true phase of
179°, noisy enough that individual chunks land on both sides of the boundary,
still reads 178.7° rather than something near zero.

## Repeatable is not calibrated

Each receive path has its own fixed delay through its own balun and its own
traces, so there is a phase offset that has nothing to do with what is in the
air. `zero` subtracts it, which makes later readings relative to that moment.
That is useful and it is honest.

It does **not** make the angle a direction of arrival. That needs a splitter,
matched cables and a known geometry. The offset also changes with frequency, so
zeroing at 2.4 GHz does not hold at 5 GHz.
[measured-performance.md](../../docs/measured-performance.md) has the measured
asymmetry between these two channels — about 1.5 dB of receive gain, which is
normal — and [both-receive-channels.md](../../docs/both-receive-channels.md) has
more on running the pair.

## The controls

| control | live? | what it does |
|---|---|---|
| Sample rate | yes | 2.56–10 MS/s. Two channels, so twice the bytes of one. |
| Centre frequency | yes | 70 MHz to 6 GHz. |
| LO offset | yes | Fraction of span. Keeps the LO leak out of the correlation. |
| Band-select width | yes | 20–3000 kHz. Widen it past the offset to see the trap. |
| RX1 / RX2 gain | yes | Separate on purpose: these two receivers are not identical. |
| Averaging | yes | Estimates in the complex-domain average. Steadier, slower. |
| `zero` | yes | Latches the current phase as the reference, on the rising edge. |
| `chunk` | **no** | Samples per estimate. It is the block's decimation, so it is a port rate and fixed when the flowgraph is built. |

Unequal gains change the amplitudes but **not** the phase. Worth proving to
yourself on the dial — it is a good check that you are measuring what you think.

## What is inside

[`../lib/phase_meter.py`](../lib/phase_meter.py), a decimating embedded Python
block: one estimate per `chunk` input samples, which is what a display can use
and about a thousand times less work than one per sample. It publishes the
zeroed phase, the coherence, the raw phase, and `coherence · exp(j·phase)` for
the dial.

## A figure for this one

There is no figure here yet, and that is a gap rather than a decision. The
script to make one exists and works:

```bash
# run from: the repo root
python3 examples/capture_examples.py 03     # one two-channel capture
python3 examples/plot_examples.py 03        # light and dark SVG
```

It takes a single two-channel capture and then sweeps the band-select filter
**in software** over those same samples, so the coherence curve is a property
of the filter rather than of what happened to be on the air a minute later —
and it shows the LO-leak trap as a measurement rather than a warning. The
capture did not complete on the board this was written against: its receive
DMA wedged repeatedly, and `dmesg` showed the AD9361's interface tuning
failing (`ad9361_dig_tune_delay: Tuning TX FAILED!`), which a reboot clears.
If yours behaves, the two commands above are all it takes.

## Verified

`grcc` compiles it, the generated Python parses, and it runs against the board.
The DSP claims are assertions in `../test_blocks.py`, which needs no radio:
phases of 0°, 37°, 120° and −95° recovered to better than 0.5°, coherence above
0.999 for identical inputs and below 0.06 for independent ones, the ±180° wrap
case, and that `zero` latches once rather than continuously.
