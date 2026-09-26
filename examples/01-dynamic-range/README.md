# 01 — Dynamic range, and how to lose it

```bash
# run from: the repo root
gnuradio-companion examples/01-dynamic-range/dynamic_range.grc
```

Receive only. Nothing here transmits.

A spectrum and a waterfall, and a number that says how much dynamic range this
configuration is actually delivering. *Dynamic range* here means peak minus
noise floor, in dB, on the trace you are looking at — the distance between the
strongest thing on screen and the level below which you could not see anything
at all.

The point of the example is not to show you a good spectrum. It is to let you
**break the measurement on purpose and watch the number move**, because almost
everything that ruins a spectrum ruins it silently: the picture still looks
like a spectrum.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../../docs/img/examples-01-dark.svg">
  <img src="../../docs/img/examples-01-light.svg" alt="Two panels. Left: one capture of real air at 2437 MHz processed three times, once per window; the three traces nearly coincide because nothing loud is present, and the receiver's own LO leak stands up as a single spike 1.25 MHz below centre where offset tuning puts it. Right: the same three windows asked to measure a tone whose true level is -60 dBFS sitting 40 bins from a full-scale carrier - rectangular reports -41.4 dBFS, an error of +18.6 dB, while Hann and Blackman-Harris report -61.4 and -60.8." width="100%">
</picture>

## Do this first

Find any strong carrier — a Wi-Fi access point at 2437 MHz will do, and that is
the default. Then change **FFT window** from Blackman-Harris to Rectangular and
back.

That one dropdown is worth up to **78 dB**. Measured, on a synthetic two-tone
test in [`../test_blocks.py`](../test_blocks.py): 40 bins away from a full-scale
carrier, the leakage each window leaves behind is

| window | sidelobes | leakage 40 bins from a full-scale carrier |
|---|---|---|
| rectangular | −13 dB | **−42 dBFS** |
| hann | −31 dB | −106 dBFS |
| blackman-harris | −92 dB | **−120 dBFS** |

and the consequence is the row that matters: asked to measure a tone whose true
level is −60 dBFS, sitting 40 bins from that carrier,

| window | reads | error |
|---|---|---|
| rectangular | −41.4 dBFS | **+18.6 dB** |
| hann | −61.4 dBFS | −1.4 dB |
| blackman-harris | −60.8 dBFS | −0.8 dB |

A rectangular window does not merely blur the weak tone. It *replaces* it with
the skirt of its loud neighbour and reports that instead, confidently. The cost
of Blackman-Harris is about two bins of extra width. That is the whole trade.

There is one case where the rectangular window is perfect, and it is worth
knowing because it makes bad tests look good: a tone sitting *exactly* on a bin
centre leaks nothing at all. Every other bin is mathematically zero. Real
signals are never exactly on a bin centre, which is why the test above puts
both tones half a bin off.

## Then try these

**Set LO offset to 0.** The spike that appears in the middle of the span is the
receiver looking at itself — the local oscillator leaking into its own mixer.
At any other setting the radio is tuned *beside* what you asked for and the
result is shifted back digitally, so the x-axis still reads true frequency and
the leak lands harmlessly off to one side. This is called offset tuning, and
almost every measurement in this repository uses it. The control is a *fraction
of the span* rather than a number of hertz so that it stays sensible when you
change the sample rate.

**Switch Gain mode to slow_attack.** The automatic gain control will now change
the receiver's own reference level while you are reading levels off it. The
dynamic-range number stays plausible and the vertical axis stops meaning
anything. AGC is right for listening and wrong for measuring; every measurement
tool in this repo uses manual gain for exactly this reason.

**Raise the Noise floor percentile** through a band that is half occupied. The
reported floor climbs into the signals, because a percentile cannot tell noise
from traffic. The slider exists to make that visible: "noise floor" is a
definition you chose, not a property of the air. 10% is honest for a quiet band
and optimistic for a busy one.

**Turn Averaging down to 1.** The trace gets noisy and the peak gets *higher* —
a single frame's worth of noise has taller spikes than an average does. The
averaging here happens in the power domain, which is the only correct way;
averaging decibels computes a geometric mean of powers and biases every noisy
bin low.

**Push Sample rate to 61.44 MS/s.** The span gets twelve times wider, every bin
gets about 11 dB noisier, and the stream now needs 245 MB/s, which no Ethernet
link carries. Raise `buf` first and re-run — see below.

## The controls

| control | live? | what it does |
|---|---|---|
| Sample rate | yes | 2.56 to 61.44 MS/s. Lower is better for dynamic range. |
| Centre frequency | yes | 70 MHz to 6 GHz. |
| LO offset | yes | Fraction of the span; moves the LO leak off your signal. |
| Gain mode | yes | manual, slow_attack, fast_attack. |
| RX1 gain | yes | 0–71 dB, and above 4 GHz that ceiling is a lie — see below. |
| FFT window | yes | The one this example is about. |
| Averaging | yes | Frames in the power-domain average. |
| Noise floor percentile | yes | What counts as "noise". |
| Max hold | yes | Unticking it is also the reset. |
| Display rate | yes | FFTs per second; the rest are dropped deliberately. |
| `nfft` | **no** | FFT size. See below. |
| `buf` | **no** | libiio buffer, in samples. |

## Three things that will bite you

**The gain slider goes to 71 and above 4 GHz the maximum is 62.** The AD9361's
gain table depends on the band. gr-iio only *logs* a refusal from the driver, so
a value past the end of the table leaves the gain where it was and nothing on
screen says so. If a level looks stuck, check it took: `./devkit status`.

**FFT size is not a runtime control, and no GUI could make it one.** It is the
width of a vector port, and GNU Radio fixes port widths when the flowgraph is
built. Edit the `nfft` variable and re-run. This is a real property of the
framework, not a shortcut taken here.

**The buffer size is a trade, not a setting.** `buf` defaults to 262144 samples
— 1 MB, about 52 ms at the default rate — which keeps the controls feeling
immediate. A bigger buffer was measured to be worth about 3× the throughput
over a network ([modulation-and-throughput.md](../../docs/modulation-and-throughput.md)),
and you will need 1048576 or more before selecting a high sample rate. It is
fixed when the flowgraph starts, so changing it needs a re-run.

## What is inside

Not the stock frequency sink. GNU Radio's `qtgui_freq_sink_x` takes its window
as a constructor argument and exposes no callback to change it, so with it you
could never *watch* the thing this example is about. The transform therefore
happens in an embedded Python block,
[`../lib/spectrum_engine.py`](../lib/spectrum_engine.py), which buys three
things at once: the window changes while the flowgraph runs, the averaging
happens in the power domain where it belongs, and the dynamic-range number is
computed from the very trace on screen — so the picture and the number cannot
disagree.

That last one is not hypothetical. An earlier tool in this repository scored a
max-hold trace against a noise floor derived from an *averaged* trace and
reported about 13 dB more dynamic range than the board had. Two traces, two
floors, one number: wrong, and plausible. Here the metric comes from one trace
and max-hold is display-only.

The frames the engine does not need are dropped **on purpose**, by a
keep-one-in-n block, down to a dozen a second. A Python FFT cannot keep up with
1200 frames a second, and a block that cannot keep up applies backpressure all
the way to the radio — which turns into dropped buffers you did not choose.
Dropping deliberately is cheaper and visible.

## Levels are dBFS

Decibels relative to the converter's full scale, not dBm. A full-scale tone
reads 0.000 dBFS through every window here — asserted in
[`../test_blocks.py`](../test_blocks.py), along with each window's scalloping
loss (3.92 / 1.42 / 0.83 dB), because a window whose own gain is not divided
back out puts every level wrong by tens of decibels, differently per window.

There is no calibration to absolute power anywhere in this repository. A dBFS
figure says nothing about what is at the antenna until you add one.

## Verified

Run against the board for 75 s at 5 MS/s with **zero overflows**; a single `O`
appears at startup while the first buffer fills. `grcc` compiles it and the
generated Python parses. The DSP claims above are the assertions in
`../test_blocks.py`, which needs no radio.
