# Ten modulations, measured on a HackRF One

This page is what one Fishball7020 actually puts on the air, received on a
separate radio and measured. Nothing here is simulated, and nothing is quoted
from a datasheet: every number comes from the captures the figures are drawn
from, and the code that produced all of it is in
[`tools/modulation-gallery/`](../tools/modulation-gallery/).

The receiver is a **HackRF One** — a deliberately independent instrument. A
board that receives its own transmission shares one clock with itself, which
hides every oscillator problem there is. Two radios that have never met hide
nothing.

![Ten modulations transmitted by a Fishball7020 and received on a HackRF One. Ten spectrum panels in a grid: CW tone, OOK, 2-FSK, BPSK, QPSK, GMSK, 16-QAM, 64-QAM, OFDM and a LoRa-style chirp, each showing about 85 dB of dynamic range above the muted noise floor.](img/modulation/01-signal-set.png)

## The setup

| | |
|---|---|
| Transmitter | Fishball7020, Zynq XC7Z020 + AD9361, **TX2A**, 866.5 MHz, 4 MSPS, −16 dB attenuation |
| Receiver | **HackRF One**, 16 MSPS, 12 MHz analog filter, LNA 24 dB / VGA 24 dB |
| Band | 866.5 MHz, inside the European 863–870 MHz ISM band |
| Link | over the air, a short hop across a desk |

**Jargon, once.** *EVM* (error vector magnitude) is how far each received symbol
lands from where it should, as a percentage of the signal's own size — smaller is
better. *PAPR* (peak-to-average power ratio) is how much louder the loudest
moment is than the average; it decides how much headroom an amplifier must keep
in reserve. *Constellation* is a plot of every received symbol as a dot, so the
pattern shows the modulation and the blur shows the damage.

## What was measured

| Signal | Tier | Occupied BW | PAPR | EVM | |
|---|---|---|---|---|---|
| CW tone | simple | 0.004 MHz | 0.28 dB | — | the reference |
| OOK | simple | 0.306 MHz | 4.96 dB | — | 250 kbaud |
| 2-FSK | simple | 0.857 MHz | 0.33 dB | — | 250 kbaud, ±250 kHz |
| BPSK | moderate | 1.165 MHz | 4.03 dB | 7.26 % | 6.01 % equalised |
| QPSK | moderate | 1.164 MHz | 3.69 dB | 9.48 % | 6.06 % equalised |
| GMSK | moderate | 0.994 MHz | 0.29 dB | — | BT = 0.3 |
| 16-QAM | complex | 1.165 MHz | 5.56 dB | 9.59 % | 6.11 % equalised |
| 64-QAM | complex | 1.165 MHz | 6.02 dB | 10.47 % | 6.17 % equalised |
| OFDM, 52 × QPSK | complex | 1.650 MHz | 9.35 dB | 10.97 % | 128-point FFT, ¼ cyclic prefix |
| LoRa-style CSS | complex | 0.990 MHz | 4.84 dB | — | **128 of 128 symbols decoded** |

All the linear modulations run at 1 Msym/s with root-raised-cosine shaping,
α = 0.35.

## Constellations

![Constellations measured over the air: BPSK, QPSK, 16-QAM, 64-QAM and OFDM, each a density-shaded cloud of received symbols with amber rings marking the transmitted positions.](img/modulation/02-constellations.png)

The 64-QAM grid is fully resolved — all 64 points separate cleanly — which is the
useful thing to look at here, more than the EVM number beside it.

## The number that does not improve

Every linear modulation lands at **6.0–6.2 % EVM after equalisation**, and it is
the same figure for BPSK as for 64-QAM. That flatness is the whole story. A
transmitter running out of linearity punishes dense constellations far harder
than sparse ones; an impairment that is identical across four modulation orders
is additive, and comes from the link rather than from the board.

Three measurements pin it down, and all three are in the figure below:

- **An unmodulated carrier through the same path already measures 7.4 %
  equivalent EVM**, of which 4.22° is RMS phase error and only 0.98 % is
  amplitude. A CW tone has no modulation to get wrong, so whatever that is, the
  transmitter's modulator did not cause it.
- **In-band signal-to-noise is 42–45 dB**, which on its own would allow
  0.6–0.8 % EVM. Noise is not the limit either.
- **Image rejection is 52.6–55.6 dB**, measured by fitting the received symbols
  to `a·s + b·conj(s)` — a widely linear fit, which catches I/Q imbalance
  precisely because no ordinary equaliser can. The board's I/Q balance is fine.

What is left is phase noise between two independent oscillators, and it is a
property of the measurement, not of the radio. On the OFDM constellation you can
see it directly: the clouds are stretched tangentially, around the origin,
which is what a phase error does and what an amplitude error does not.

![Four summary panels: PAPR shown as a complementary cumulative distribution for six signals; EVM per modulation before and after equalisation against the link's own 7.4 percent floor; the link's phase noise in dBc per hertz; and a spur attribution plot showing which spurs track the carrier.](img/modulation/05-summary.png)

## Whose spur is it?

The CW spectrum has companions either side of the carrier, and a plot on its own
cannot say whether the transmitter or the receiver made them. Turning the
transmitter down settles it: a spur made in the transmitter tracks the carrier,
so its ratio in dBc stays fixed, while anything the receiver contributes does
not follow.

| TX attenuation | Carrier | Spur at ±1 MHz | Ratio | Spur at 865.0 MHz |
|---|---|---|---|---|
| −30 dB | −22.9 dBFS | −63.2 dBFS | −40.3 dBc | −66.0 dBFS |
| −24 dB | −17.0 dBFS | −56.5 dBFS | −39.5 dBc | −66.8 dBFS |
| −20 dB | −13.0 dBFS | −53.2 dBFS | −40.2 dBc | −66.0 dBFS |
| −16 dB | −9.2 dBFS | −49.4 dBFS | −40.2 dBc | −66.3 dBFS |

So the ±1 MHz pair is **the board's own, about −40 dBc**, sitting at exactly a
quarter of the 4 MSPS transmit rate. The one at 865.0 MHz never moves, and it is
present at the same level with the transmitter muted — that one belongs to the
receiver.

## The chirp

![A LoRa-style chirp spread spectrum signal: a wide spectrogram showing a staircase of diagonal chirps, a dechirped FFT with a single sharp peak 55.6 dB above the median bin, a scatter of decoded against transmitted symbols lying exactly on the diagonal, and the signal envelope.](img/modulation/03-chirp.png)

Spreading factor 9 over 1 MHz: 512 possible symbols, each the same up-chirp
cyclically shifted. Dechirping collapses each one to a single tone whose FFT bin
*is* the symbol, and here that peak stands **55.6 dB above the median bin**. All
128 symbols in the buffer came back correct.

A chirp is nominally constant-envelope, and this one measures 4.84 dB of PAPR.
That is not an error: band-limiting it to its own 1 MHz channel turns the
frequency wrap at each symbol boundary — a genuine discontinuity — into envelope
ripple.

## Time domain

![Eight panels: the CW tone as two sinusoids ninety degrees apart, OOK as a switching envelope, 2-FSK and GMSK as instantaneous frequency traces, and eye diagrams for BPSK, QPSK, 16-QAM and 64-QAM showing two, two, four and eight distinct levels.](img/modulation/04-time-domain.png)

The eye diagrams are drawn from the same matched-filter output the EVM was
computed on, so they are the same signal, not an illustration of it. The number
of distinct levels at the sampling instant — two, two, four, eight — is the
modulation order showing itself.

## Keeping the pictures honest

Three things had to be right before any of these plots meant anything.

**No DC spike.** A direct-conversion receiver puts a large artefact at its own
local-oscillator frequency, and on most SDR screenshots it sits in the middle of
the signal. Here the HackRF is deliberately tuned **3.5 MHz below** the
transmitter, so that artefact lands in the stopband of the digital filter that
follows and is rejected by about 135 dB rather than cosmetically blanked. Every
spectrum on this page is genuinely free of it.

**No aliasing.** 16 MSPS with a 12 MHz analog filter puts the fold point 2 MHz
inside the analog stopband; the digital filter that follows passes 2 MHz, stops
at 2.6 MHz, and reaches 120 dB, and decimation to 8 MSPS then has 2 MHz of pure
margin. Pushed through this chain, a DC artefact twelve times the wanted signal
and an interferer six times it come out 113 dB down. The plots are reduced for
display by per-pixel min and max rather than by dropping points, because drawing
32 768 spectrum bins into 1 100 pixels aliases the *picture* too.

**A measurement chain that was checked before it was believed.** The spectrum
estimator is calibrated against signals with analytic answers — a full-scale tone
must read 0 dBFS, unit-variance noise must read −10·log₁₀(fs) dBFS/Hz. The
demodulator is run against a synthetic channel at a known signal-to-noise ratio
and has to return the EVM that the noise implies, including the processing gain
of the matched filter, before it is allowed near a real capture. Both checks run
from the command line:

```bash
# run from: tools/modulation-gallery/
python3 dsp.py          # spectrum calibration against known answers
python3 waveforms.py    # every waveform normalised and cyclic-seamless
python3 rx.py           # the demodulator, against a known synthetic channel
python3 chain.py        # anti-alias filter, and what it does to an interferer
```

That discipline earned its keep. The demodulator's first version reported 17.5 %
EVM at every signal-to-noise ratio; the fault was in the *test*, which rolled the
signal after applying the frequency offset and so created a phase discontinuity
no real transmission has.

## Repeating it

Everything the board transmits is generated from a fixed seed, so the reference
regenerates exactly and the captures can be re-analysed without transmitting
again.

```bash
# run from: tools/modulation-gallery/
python3 campaign.py            # transmit each signal, capture it, measure it
python3 fig1.py                # ... through fig5.py, redraw the figures
```

You need a HackRF (or any SoapySDR receiver, by editing `hackrf_cap.py`), GNU
Radio for the capture, and the board reachable over libiio. `board.py` takes the
board's address as its argument — see [changing the board's IP
address](networking.md) if it is not on the default.

> **Transmitting.** These runs put a real signal on a real antenna. 866.5 MHz is
> inside the European ISM band, and the levels here are low, but the band has
> duty-cycle and power limits and the rules differ by country. What leaves the
> antenna port is the operator's responsibility — see [transmitter
> safety](transmitter-safety.md).

## What this page does not establish

- **Absolute transmit power.** Nothing here is metered in dBm; every level is
  relative to the receiver's full scale. The board's output power is estimated
  elsewhere and never measured with a power meter — see
  [measured performance](measured-performance.md).
- **The board's true EVM.** The link's own 7.4 % floor sits above whatever the
  transmitter contributes, so these figures are an upper bound on the board's
  modulation error, not a measurement of it. Separating the two needs either a
  shared reference clock between the two radios or a better receiver.
- **How it behaves at full power.** Everything here is at −16 dB attenuation,
  comfortably inside the amplifier's linear region. Compression is a different
  experiment.
