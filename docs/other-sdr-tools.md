# Other tools, and when they beat GNU Radio

The examples in [`examples/`](../examples/) are GNU Radio because GNU Radio is
the best thing there is for *building a signal chain out of parts and watching
it work*. That is not the same as being the best tool for every job, and a few
of the jobs it is worst at are jobs this board is especially good at.

This page is organised by what you are trying to do, because that is what
picks the tool. Nothing here is a criticism of GNU Radio; it is a list of
places where reaching for something else will save you an afternoon.

## The short version

| What you are doing | Reach for | Why not GNU Radio |
|---|---|---|
| Looking at a wide band in real time, at the full 61.44 MS/s | **the FPGA fabric** (this repo) or **Maia SDR** | No host link carries 245 MB/s. The work has to happen on the board. |
| "What is this signal?" on a recording | **inspectrum** | You want to measure a capture by eye and by cursor, not build a flowgraph to look at it. |
| Reverse-engineering a protocol's bits | **Universal Radio Hacker** | URH does demodulation, framing and fuzzing as one workflow. Rebuilding that in GRC is weeks. |
| Listening to something, with a demodulator that already exists | **SDRangel**, **SDR++**, **GQRX** | A dozen demodulators, a scanner and a recorder, already wired up. |
| Getting a *number* out of the radio | **pyadi-iio + NumPy** | A measurement is a script, not a stream. Most of this repo's own tools work this way. |
| DSP that must run on the board's ARM cores | **liquid-dsp** | GNU Radio's runtime on two Cortex-A9s spends its time scheduling. |
| DSP that must run at the sample clock | **Verilog**, or **Amaranth** | Nothing running on a CPU is in the sample-rate path. |
| Sharing a capture with somebody | **SigMF** | Not a competitor - a file format. Use it. |

## The one that matters most for this board: Maia SDR

[Maia SDR](https://maia-sdr.org/) is the most interesting alternative here,
because it solves the problem this board actually has. It puts the FFT **on the
FPGA** and a web server on the ARM cores, so a browser gets a real-time
waterfall over HTTP and the sample stream never crosses the network at all.
That sidesteps the ceiling measured in
[modulation-and-throughput.md](modulation-and-throughput.md) completely: the
link carries a rendered spectrogram of a few hundred kB/s instead of 245 MB/s
of IQ. It also records raw IQ to the board's own memory and hands you the file
afterwards, which is a much better way to capture a burst than streaming and
hoping.

Read the caveat before you try it, because it is a big one.

**Maia SDR is a different firmware, not an application.** It ships a complete
image - bitstream, kernel and root filesystem - and installing it *replaces*
what this devkit builds. Everything in this repository that lives in the FPGA
or the driver goes with it: the sample-locked GPIO outputs of
[tx-gpio-bitmap.md](tx-gpio-bitmap.md), the transmit-mute patches, the thermal
limit, the `tx_disable` latch. You get it back by reflashing this devkit's
`BOOT.bin` and `uImage` with `./devkit flash --all`, so it is reversible, but
it is not something you run *alongside*.

**And its FPGA design targets the ADALM-Pluto, which is not this board.** The
Pluto is an XC7Z010 configured one receiver and one transmitter; this board is
an XC7Z020 running 2R2T, and on the common variant it has a power amplifier the
Pluto does not. A prebuilt Pluto image is therefore not a drop-in - expect to
rebuild Maia's bitstream for `xc7z020clg400-2` and to work out the second
channel yourself. Budget real time for that. If you only want one receiver and
a waterfall, it may still be the fastest route to a *good* one.

Its recordings open in [IQEngine](https://www.iqengine.org/) in a browser,
which is a pleasant way to look at a capture without installing anything.

  - Project: <https://maia-sdr.org/> · code: <https://github.com/maia-sdr/maia-sdr>
  - Firmware builds: <https://github.com/maia-sdr/plutosdr-fw>
  - Daniel Estévez's write-up: <https://destevez.net/2023/02/maia-sdr/>

## Analysing a capture: inspectrum

[inspectrum](https://github.com/miek/inspectrum) opens a recorded IQ file and
lets you drag cursors over a spectrogram: measure a burst's length, read a
symbol rate off the screen, extract a slice and demodulate it. For the question
"what *is* this?", it is far better than anything you would build in a
flowgraph, because the loop is *look, adjust, look again* and a flowgraph makes
that loop slow.

This repo already produces files it can read. `./devkit` captures and the MCP
server's `sdr_capture_iq` write SigMF, and there are `.sigmf-data` /
`.sigmf-meta` pairs in the working tree from exactly this kind of session.

```bash
# run from: the repo root - capture, then look at it
python3 tools/selftest/sdr_selftest.py --help    # what the capture tools offer
inspectrum out.sigmf-data
```

Pair it with GNU Radio rather than choosing: record with a flowgraph or a
script, understand the recording in inspectrum, then go back and build the
receiver once you know what you are building.

## Protocol work: Universal Radio Hacker

[URH](https://github.com/jopohl/urh) is the tool for the whole job of turning a
signal into bits and then into meaning: it demodulates, finds the framing,
labels fields across many captures, and will re-transmit what you tell it to.
It supports PlutoSDR-class hardware directly. If your goal is a protocol rather
than a waveform, starting in GNU Radio means building a lot of URH badly.

The transmit side of URH is a real transmitter. Everything in
[transmitter-safety.md](transmitter-safety.md) applies, and on this board the
power amplifier means it applies harder than on the hardware URH's
documentation assumes.

## Listening: SDRangel, SDR++, GQRX

If somebody has already written the demodulator, use theirs.
[SDRangel](https://github.com/f4exb/sdrangel) has both input and output plugins
for PlutoSDR-class radios and a long list of demodulators and decoders;
[SDR++](https://github.com/AlexandreRouma/SDRPlusPlus) is a cleaner, faster
interface over a smaller feature set; [GQRX](https://gqrx.dk/) is the simplest
of the three. All three reach the board through libiio or SoapySDR, so the
`ip:fishball.local` you use everywhere else works.

What you give up is the thing this repo is about: you cannot see inside, and
you cannot put your own block in the middle.

## Measuring: pyadi-iio and NumPy

For anything whose output is a *number* - a gain slope, an image-rejection
figure, a noise floor against gain - a script beats a flowgraph, and this
repository is mostly evidence of that.
[`tools/selftest/sdr_selftest.py`](../tools/selftest/sdr_selftest.py) measures
56 gain slopes, image rejection, harmonics and mute depth without a flowgraph
anywhere, and [`tools/selftest/iiod_min.py`](../tools/selftest/iiod_min.py)
talks the IIOD protocol over a plain socket using nothing but the standard
library, precisely so that a health check cannot be blocked by a version
mismatch.

[pyadi-iio](https://github.com/analogdevicesinc/pyadi-iio) is the comfortable
version of the same idea:

```python
# run from: anywhere with pyadi-iio installed
import adi, numpy as np
sdr = adi.ad9361(uri='ip:fishball.local')
sdr.rx_lo = 2_437_000_000
sdr.sample_rate = 4_000_000
sdr.gain_control_mode_chan0 = 'manual'
sdr.rx_hardwaregain_chan0 = 40
sdr.rx_buffer_size = 32768
x = sdr.rx()                      # raw int16 counts, full scale +/-2048
```

Note the scale: pyadi hands you raw converter counts, where gr-iio's `fc32`
sources hand you the same samples divided by 2048. Mixing the two conventions
is a 66 dB error that looks like a broken board -
[`examples/lib/spectrum_engine.py`](../examples/lib/spectrum_engine.py) records
the measurement that pinned the constant down.

Reach for a flowgraph when you want a *stream* and a picture; reach for a
script when you want a table you can commit.

## On the board's ARM cores: liquid-dsp

If the DSP has to run on the board, [liquid-dsp](https://liquidsdr.org/) is a
plain C library of modems, filters and synchronisers with no runtime and no
scheduler. GNU Radio *will* run on two 667 MHz Cortex-A9s, but its per-block
scheduling overhead is a large fraction of the budget, and you will spend your
time tuning buffer sizes rather than doing signal processing.

## At the sample clock: the fabric

For anything that must keep up with 61.44 MS/s, no processor is in the running
and no host link is either. That is the whole reason this repository exists.
[block-design.md](block-design.md) is the stock design IP by IP,
[tx-gpio-bitmap.md](tx-gpio-bitmap.md) is a small feature end to end, and
[wbfm-channelizer.md](wbfm-channelizer.md) is a real DSP block in Verilog with
a testbench. [`docs/course/`](course/) is the Verilog and Vivado crash course
for getting there from nothing.

[Amaranth](https://github.com/amaranth-lang/amaranth) - a Python-based HDL, and
what Maia SDR's FPGA design is written in - is worth knowing about if Verilog is
the part putting you off. It is a different way in to the same fabric.

## Not an alternative: SigMF

[SigMF](https://github.com/sigmf/SigMF) is a file format: the samples in one
file, a JSON sidecar describing sample rate, centre frequency, hardware and
timestamps beside it. Every tool above reads it. Use it for anything you intend
to keep, because an IQ file without its metadata is a pile of numbers - and the
sample rate you were certain you would remember is the one you will not.

## Where to go back to

- [`examples/`](../examples/) - the three graded GNU Radio showcases
- [modulation-and-throughput.md](modulation-and-throughput.md) - what the link
  carries, measured, and why the FPGA answer exists
- [measured-performance.md](measured-performance.md) - what one board actually does
