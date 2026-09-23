# Modulation gallery — the measurement behind the pictures

Transmits ten modulations from the board, receives each one on a **HackRF One**,
measures it, and draws the figures in
[`docs/modulation-gallery.md`](../../docs/modulation-gallery.md).

Everything is seeded, so the transmitted reference regenerates exactly and a
capture can be re-analysed without going back on the air.

## What you need

- the board reachable over libiio (`BOARD=<address>`, default `192.168.2.1` —
  see [changing the board's IP address](../../docs/networking.md))
- a **HackRF One** with an antenna, and GNU Radio with the SoapySDR HackRF
  module (`gnuradio`, `soapysdr0.8-module-hackrf`)
- an antenna on **TX2A**, and a frequency you are allowed to transmit on
- numpy, scipy, matplotlib

## Run it

```bash
# run from: tools/modulation-gallery/
python3 dsp.py          # spectrum calibration, against analytic answers
python3 waveforms.py    # every waveform normalised and cyclic-seamless
python3 chain.py        # the anti-alias chain, and an interferer pushed through it
python3 rx.py           # the demodulator, against a synthetic channel of known SNR

python3 band.py         # what is actually on the air, and what only looks like it
python3 pickLO.py       # which receiver tuning leaves the analysis band cleanest

BOARD=192.168.2.1 python3 campaign.py    # transmit, capture, measure  (~5 min)
BOARD=192.168.2.1 python3 spurs.py       # attribute the spurs        (~2 min)

python3 fig1.py && python3 fig2.py && python3 fig3.py && python3 fig4.py && python3 fig5.py
```

The four self-tests come first on purpose. Each one has to pass before a real
capture means anything, and they run in seconds.

## The files

| | |
|---|---|
| `waveforms.py` | the ten signals. All cyclic-seamless, because the board transmits from a repeating DMA buffer |
| `chain.py` | the receive chain: offset tuning, the anti-alias filter, decimation |
| `dsp.py` | spectra, PAPR, occupied bandwidth — each calibrated against a known answer |
| `rx.py` | carrier and timing recovery, EVM, the impairment budget, the chirp decoder |
| `board.py` | transmit from the Fishball7020 over libiio, safely |
| `hackrf_cap.py` | capture N samples from the HackRF, headless |
| `campaign.py` · `spurs.py` | the two measurement runs |
| `spurhunt.py` · `band.py` · `ip2.py` · `pickLO.py` | receiver-only diagnostics: is a peak a signal, a receiver spur, or a distortion product, and which tuning avoids it |
| `theme.py` · `palette.py` | the plot style, and the check that its colours are separable |
| `fig1.py` … `fig5.py` | the five figures |

## Three things that are easy to get wrong

**Transmitting from a cyclic buffer needs a seamless waveform.** The board
repeats the buffer forever; if the end does not join the beginning, the seam
sprays spurs across the span once per wrap and gets measured as if it were the
modulation. Everything here is pulse-shaped by circular convolution and checked
by comparing one buffer's spectrum against four laid end to end.

**Set the transmit attenuation *after* the buffer starts, and read it back.**
Firmware patch 0005 restores a cached attenuation when a stream starts on a chip
that looks muted, so a value written before `OPEN` is not what goes on the air.
`board.py` writes it after and refuses to continue if the read-back disagrees.

**A peak in the spectrum is not necessarily a signal.** The first run of this
had a sharp peak 1.5 MHz below centre in every spectrum. It was not the board —
it was there with the transmitter muted — but it was not an external transmitter
either: retune the receiver and a real signal stays at the same absolute
frequency, and this one vanished at four tunings out of five. It was the
receiver's own second-order distortion of a strong carrier at 864.0 MHz,
appearing at exactly twice that carrier's baseband offset. Because the product
lands at `2 × carrier − LO`, tuning the receiver *above* the transmitter rather
than below moves it 9.8 MHz away and the digital filter removes it: 21.5 dB
above the noise floor becomes 3.8 dB. `spurhunt.py`, `band.py` and `ip2.py`
reproduce the diagnosis without transmitting.

**Check the analysis before trusting it.** `rx.py`'s self-test runs the whole
demodulator on a synthetic channel at a known signal-to-noise ratio and requires
the EVM that comes out to match the EVM that must come out. Its first version
reported 17.5 % at every SNR — and the bug was in the test, which rolled the
signal after applying the frequency offset and so created a phase discontinuity
no real transmission has.

## Safety

`campaign.py` transmits. It mutes both chains and powers the TX local oscillator
down in a `finally:` block, so an interrupted run does not leave the transmitter
live — but read [transmitter safety](../../docs/transmitter-safety.md) first, and
pick a frequency you are licensed to use.
