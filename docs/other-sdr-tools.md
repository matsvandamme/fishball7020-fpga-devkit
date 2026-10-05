# Other tools, and when they beat GNU Radio

Which SDR tool to reach for, by task. The [`examples/`](../examples/) use GNU
Radio, best for building a signal chain from parts; other jobs suit other tools.

## The short version

| What you are doing | Reach for | Why not GNU Radio |
|---|---|---|
| Looking at a wide band in real time, at the full 61.44 MS/s | **the FPGA fabric** (this repo) or **Maia SDR** | No host link carries 245 MB/s. The work has to happen on the board. |
| "What is this signal?" on a recording | **inspectrum** | You want to measure a capture by eye and by cursor, not build a flowgraph to look at it. |
| Reverse-engineering a protocol's bits | **Universal Radio Hacker** | URH does demodulation, framing and fuzzing as one workflow. Rebuilding that in GNU Radio Companion (GRC) takes weeks. |
| Listening to something, with a demodulator that already exists | **SDRangel**, **SDR++**, **GQRX** | A dozen demodulators, a scanner and a recorder, already wired up. |
| Getting a *number* out of the radio | **pyadi-iio + NumPy** | A measurement is a script, not a stream. Most of this repo's own tools work this way. |
| The same, but your analysis is already in MATLAB | **[MATLAB](matlab.md)** | The same job as pyadi, in a language you may already use for the rest of your work. It reaches only ONE of the two receivers on its own; see that page. |
| DSP that must run on the board's ARM cores | **liquid-dsp** | GNU Radio's runtime on two Cortex-A9s spends its time scheduling. |
| DSP that must run at the sample clock | **Verilog**, or **Amaranth** | Nothing running on a CPU is in the sample-rate path. |
| Sharing a capture with somebody | **SigMF** | Not a competitor, a file format. Use it. |

## Maia SDR: a waterfall computed on the FPGA

[Maia SDR](https://maia-sdr.org/) puts the FFT **on the FPGA** and a web server
on the ARM cores, avoiding the streaming ceiling in
[modulation-and-throughput.md](modulation-and-throughput.md):

![Maia SDR's path: the AD9361 produces 245 MB/s of IQ, the FFT runs on the FPGA, a web server runs on the ARM cores, and a few hundred kB/s reach a real-time waterfall in the browser.](img/radio-maia-light.svg#only-light)
![Maia SDR's path: the AD9361 produces 245 MB/s of IQ, the FFT runs on the FPGA, a web server runs on the ARM cores, and a few hundred kB/s reach a real-time waterfall in the browser.](img/radio-maia-dark.svg#only-dark)

It can also record raw IQ to the board's memory; recordings open in
[IQEngine](https://www.iqengine.org/) in a browser.

!!! warning "It is a different firmware, not an application"
    Installing it replaces this devkit's bitstream, kernel and root filesystem, and
    with them the sample-locked GPIO outputs, the transmit-mute patches, the thermal
    limit and the `tx_disable` latch. `sudo ./devkit write-card /dev/sdX` brings them
    back (the factory firmware: `./devkit flash --target factory --all`).

!!! warning "Its FPGA design targets the ADALM-Pluto"
    XC7Z010, one receiver, one transmitter. This board is an XC7Z020 running 2R2T,
    often with a power amplifier: expect to rebuild Maia's bitstream for
    `xc7z020clg400-2` and work out the second channel yourself.

Project: <https://maia-sdr.org/> · code: <https://github.com/maia-sdr/maia-sdr> ·
firmware builds: <https://github.com/maia-sdr/plutosdr-fw> · write-up:
<https://destevez.net/2023/02/maia-sdr/>

## Analysing a capture: inspectrum

[inspectrum](https://github.com/miek/inspectrum) opens a recorded IQ file as a
spectrogram with cursors: measure a burst's length, read a symbol rate, extract
and demodulate a slice. This repo's capture tools
([`tools/sigmf-capture.py`](capturing-iq.md) and the [MCP server](mcp-server.md)'s
`sdr_capture_iq`) write SigMF, which it reads:

```bash
# run from: the repo root - capture, then look at it
tools/sigmf-capture.py record out --rate 3e6 --freq 900e6 --seconds 5
inspectrum out.sigmf-data
```

## Protocol work: Universal Radio Hacker

[URH](https://github.com/jopohl/urh) demodulates, finds the framing, labels
fields across captures and re-transmits, with direct PlutoSDR-class support.

!!! danger "Its transmit side is a real transmitter"
    [transmitter-safety.md](transmitter-safety.md) applies, more strongly than on the
    hardware URH's documentation assumes, because of this board's power amplifier.

## Listening: SDRangel, SDR++, GQRX

[SDRangel](https://github.com/f4exb/sdrangel) has PlutoSDR input and output
plugins and many demodulators; [SDR++](https://github.com/AlexandreRouma/SDRPlusPlus)
is a faster interface over a smaller feature set; [GQRX](https://gqrx.dk/) is the
simplest. All reach the board through libiio or SoapySDR at `ip:fishball.local`.
SDR++'s PlutoSDR source reads only RX1;
[Using SDR++ with this board](sdrpp.md) covers its settings, the rates USB
carries, and a patched build with RX2, the FPGA /8 decimator and the AD9361's
correction controls.

## Measuring: pyadi-iio and NumPy

For anything whose output is a number, a script beats a flowgraph.
[`tools/selftest/sdr_selftest.py`](../tools/selftest/sdr_selftest.py) works this
way, and [`tools/selftest/iiod_min.py`](../tools/selftest/iiod_min.py) talks the
IIOD protocol with only the standard library, so a libiio version mismatch cannot
block a health check. [pyadi-iio](https://github.com/analogdevicesinc/pyadi-iio)
is the convenient version ([install it in a venv](radio/talk-from-python.md)):

```python
# run from: your project's folder, as: .venv/bin/python example.py (a venv with pyadi-iio)
import adi, numpy as np
sdr = adi.ad9361(uri='ip:fishball.local')
sdr.rx_lo = 2_437_000_000
sdr.sample_rate = 4_000_000
sdr.gain_control_mode_chan0 = 'manual'
sdr.rx_hardwaregain_chan0 = 40
sdr.rx_buffer_size = 32768
x = sdr.rx()                      # raw int16 counts, full scale +/-2047
sdr.rx_destroy_buffer()           # or the script segfaults on exit
```

!!! warning "Release the buffer before the script ends"
    Or the process segfaults during interpreter shutdown ([why](your-own-project.md#1-on-your-pc--start-here)).

!!! warning "Mind the scale"
    pyadi returns raw counts; gr-iio's `fc32` sources divide by 2047. Mixing them is
    a 66 dB error ([`examples/lib/spectrum_engine.py`](../examples/lib/spectrum_engine.py)).

## On the board's ARM cores: liquid-dsp

[liquid-dsp](https://liquidsdr.org/) is a plain C library of modems, filters and
synchronisers with no runtime or scheduler. GNU Radio runs on the two 667 MHz
Cortex-A9s, but its per-block scheduling eats much of the budget.

## At the sample clock: the fabric

For anything that must keep up with 61.44 MS/s, that is what this repository is
for: [block-design.md](block-design.md) is the stock design IP by IP,
[tx-gpio-bitmap.md](tx-gpio-bitmap.md) a small feature end to end,
[wbfm-channelizer.md](wbfm-channelizer.md) a real DSP block with a testbench, and
[the course](course/index.html) the Verilog and Vivado crash course.
[Amaranth](https://github.com/amaranth-lang/amaranth), a Python-based HDL (Maia
SDR's), is an alternative way in.

## Not an alternative: SigMF

[SigMF](https://github.com/sigmf/SigMF) stores samples with a JSON sidecar of
sample rate, centre frequency, hardware and timestamps. Every tool above reads
it; use it for anything you keep. [capturing-iq.md](capturing-iq.md) covers
recording it from this board.

## Further reading

- [`examples/`](../examples/): the three graded GNU Radio showcases
- [modulation-and-throughput.md](modulation-and-throughput.md): what the link
  carries, and why the FPGA answer exists
- [measured-performance.md](measured-performance.md): the board's loopback
  performance
