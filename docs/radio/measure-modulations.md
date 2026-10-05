---
icon: material/sine-wave
description: Transmit ten modulations, capture them on a HackRF One, and redraw the gallery's figures.
---

# Measure ten modulations

`tools/modulation-gallery/` transmits ten modulations from the board, from a CW
tone to 64-QAM, OFDM and a LoRa-style chirp, captures each on a separate radio
and measures it.

![Ten modulations transmitted by a Fishball7020 and received on a HackRF One. Ten spectrum panels in a grid: CW tone, OOK, 2-FSK, BPSK, QPSK, GMSK, 16-QAM, 64-QAM, OFDM and a LoRa-style chirp, each showing about 85 dB of dynamic range above the muted noise floor.](../img/modulation/01-signal-set.png)

!!! danger "This transmits"
    866.5 MHz is inside the European ISM band and the levels are low, but the band
    has duty-cycle and power limits that differ by country; what leaves the antenna
    port is the operator's responsibility (see [before you transmit](../start/before-you-transmit.md)).

```bash
# run from: tools/modulation-gallery/
python3 -m venv --system-site-packages .venv   # a venv that still sees the system's GNU Radio
.venv/bin/pip install numpy scipy matplotlib
.venv/bin/python campaign.py   # transmit each signal, capture it, measure it
.venv/bin/python fig1.py       # ... through fig5.py, redraw the figures
```

You need a HackRF (or any SoapySDR receiver, by editing `hackrf_cap.py`), GNU
Radio for the capture, and the board reachable over libiio. `board.py` takes the
board's address as its argument ([changing the board's IP](../networking.md)).
Every waveform comes from a fixed seed, so captures can be re-analysed without
transmitting again. The measurement chain is checked against known answers:

```bash
# run from: tools/modulation-gallery/
.venv/bin/python dsp.py          # spectrum calibration against known answers
.venv/bin/python waveforms.py    # every waveform normalised and cyclic-seamless
.venv/bin/python rx.py           # the demodulator, against a known synthetic channel
.venv/bin/python chain.py        # anti-alias filter, and what it does to an interferer
```

**You should see:** the captures measured, and `fig1.py` to `fig5.py` redrawing
the figures.

The results, and which spurs belong to the board:
[ten modulations, received on a HackRF One](../modulation-gallery.md).
