# How fast can you actually push it?

Every number on this page came off one board on **2026-09-23**, running the v1.4
firmware, over **gigabit Ethernet**. The radio path was a cable from `TX2A`
through a **20 dB attenuator** into `RX2A`, tuned to 900 MHz, transmitting at
−30 dB attenuation into a receiver set to 20 dB of manual gain.

It answers a question [`measured-performance.md`](measured-performance.md) does
not: the self-test measures the *radio* with tones. This page measures what
happens when you push **real modulated signals at real sample rates**, and where
the limits actually sit.

The short answer is that the limit people hit first is not the radio.

Raw results are in
[`img/data/modulation-throughput.json`](img/data/modulation-throughput.json).

## The units, first

If EVM and dBc are not already familiar, read this box; the rest of the page
leans on it.

| Term | What it means |
|---|---|
| **dB** | A ratio on a logarithmic scale. Every 10 dB is a factor of ten in power; 3 dB is roughly double. |
| **dBFS** | Measured against *full scale* — the loudest the receiver can represent before clipping. Always negative. −20 dBFS is a comfortable signal. |
| **dBc** | Measured against the *carrier*, the wanted signal. Says how far **below** it an unwanted signal sits, so a bigger number is cleaner. |
| **MSPS** | Million samples per second. Each sample is an I/Q pair — two signed 16-bit numbers, so **four bytes**. |
| **EVM** | Error Vector Magnitude. How far received symbols land from where they should, as a percentage. The single best summary of link quality: 1% is excellent, 5% usable, above 15% unrecoverable. |
| **PAPR** | Peak-to-average power ratio — how spiky a waveform is. Matters because transmit power is limited by the *peak*, so a spiky signal delivers less average power. |
| **Constellation** | The set of points a modulation uses. QPSK has 4, 16-QAM has 16. |

## The short version

- **The radio runs clean at its full 61.44 MSPS.** QPSK holds **2.17%** EVM and
  16-QAM **2.24%** at the top of its range, across 18 MHz of occupied bandwidth.
- **The 5 MSPS ceiling people hit is a host-streaming artefact**, not a hardware
  limit. It disappears entirely when transmit stops needing a continuous feed.
- **Continuous streaming saturates near 30 MB/s** through the board's CPU and
  network stack. At four bytes per sample in each direction that lands at about
  5 MSPS — which is exactly where it breaks.
- **Capture is bit-perfect at 5 MSPS.** Above that it picks up a handful of
  discrete sample drops: 2 to 4 per two million samples, even at 61.44 MSPS.
- **OFDM measures far worse than QPSK** on the same link, and that is real, not a
  measurement artefact. It is a consequence of peak-to-average ratio.

## Where the 5 MSPS ceiling comes from

Streaming samples continuously in both directions — the obvious way to drive the
board — makes the host, the network and the board's CPU carry every single
sample. Measured with QPSK, EVM against sample rate:

| Link | 2.5 MSPS | 4 MSPS | 5 MSPS | 7.5 MSPS | 10 MSPS | 15 MSPS |
|---|---|---|---|---|---|---|
| USB gadget | 1.34% | **49.5%** | — | — | — | — |
| Gigabit Ethernet | 3.54% | — | **1.89%** | 67.8% | 76.9% | 93.0% |

Ethernet roughly doubles the usable rate, from about 2.5 to 5 MSPS. It does
**not** give twelve times the throughput the wire suggests, because the wire was
never the constraint — raw capture rises from roughly 10 MB/s over USB to about
31 MB/s over Ethernet, and stops there.

> **What is actually failing.** Above the ceiling this is not noise. The
> transmitted waveform is *not the one you generated*: the transmit DMA starves,
> substitutes zeros, and the symbols break up. An EVM above about 15% here means
> corruption, not a weak signal.

## The fix: let the hardware repeat the waveform

The transmit DMA on this board has `CYCLIC = 1`. Load a buffer once and the
hardware replays it forever with no further help from the host, which frees the
entire link for capture.

```bash
# run on your HOST - -c is the whole trick
iio_writedev -u ip:192.168.129.200 -c -b 262144 -s 262144 \
  cf-ad9361-dds-core-lpc voltage2 voltage3 < waveform.bin
```

Measured that way, with the same cable and the same settings:

| Sample rate | QPSK EVM | 16-QAM EVM | Implied SNR |
|---|---|---|---|
| 5.00 MSPS | 1.76% | 1.61% | ~35 dB |
| 15.00 MSPS | 1.67% | 1.62% | ~36 dB |
| 30.72 MSPS | 2.05% | 2.04% | ~34 dB |
| **61.44 MSPS** | **2.18%** | **2.26%** | ~33 dB |

Clean at every rate. EVM degrades by less than half a percentage point across a
**twelve-fold** increase in sample rate.

The catch is the obvious one: a cyclic buffer repeats, so it carries no unique
data. It is right for test signals, beacons, radar chirps and calibration; it is
not a way to send a message.

## What the radio itself does at full rate

Generating the tone *inside the FPGA* removes transmit from the host entirely,
so this measures the radio and the capture path with nothing else in the way. The
signal still leaves `TX2A`, crosses the pad, and returns to `RX2A`.

| Sample rate | Bandwidth | Throughput | Tone SNR | SFDR | Image rejection | Sample drops |
|---|---|---|---|---|---|---|
| 5.00 MSPS | 4.0 MHz | 16.3 MB/s | 90.1 dB | 43.2 dB | 43.2 dB | **0** |
| 15.00 MSPS | 12.0 MHz | 26.3 MB/s | 89.9 dB | 48.2 dB | 65.6 dB | 2 |
| 30.72 MSPS | 24.6 MHz | 31.4 MB/s | 88.1 dB | 46.4 dB | 76.5 dB | 3 |
| 61.44 MSPS | 49.2 MHz | 26.6 MB/s | 85.4 dB | 42.1 dB | 65.9 dB | 4 |

Two things worth noticing. Tone signal-to-noise falls only **4.7 dB across the
whole sweep**, and image rejection *improves* with rate — 43 dB at 5 MSPS against
76 dB at 30.72 — because the quadrature calibration works better with the tone
further from centre.

Throughput plateaus near **31 MB/s**. The gigabit wire is not the limit; the
board's own CPU moving samples through the network stack is.

### How the drops were detected

De-rotate the capture by the measured tone frequency and the residual phase
should be constant. A lost chunk of samples shows up as a step. Every step
observed was **exactly π**, which at a tone of `fs/8` means a loss of a multiple
of four samples. Between the steps the phase is flat to four decimal places, so
these are discrete dropped packets, not continuous degradation.

The same test run with the AD9361's internal BIST tone — injected inside the chip
on the receive path, so no RF is involved at all — gives the identical picture.
That places the drops in the capture and transport path, not in the radio.

```bash
# run on your HOST - inject a known tone inside the chip, no RF
iio_attr -u ip:192.168.129.200 -D ad9361-phy bist_tone "2 7680000 0 0"
# ... capture ...
iio_attr -u ip:192.168.129.200 -D ad9361-phy bist_tone "0 0 0 0"   # off again
```

## Every waveform at 61.44 MSPS

All seven at the same transmit attenuation, captured across the full 56 MHz
receive bandwidth.

| Waveform | RX rms | PAPR | Occupied BW | Key figure |
|---|---|---|---|---|
| CW tone | −16.74 dBFS | 0.75 dB | 30 kHz | image rejection **71.1 dBc**, LO leak 62.0 dBc, SNR 71.0 dB |
| Two-tone | −19.73 dBFS | 3.56 dB | 4.02 MHz | IMD3 **55.8 dBc** |
| QPSK | −20.66 dBFS | 4.14 dB | 17.96 MHz | EVM **2.17%** |
| 16-QAM | −22.84 dBFS | 6.20 dB | 18.12 MHz | EVM **2.24%** |
| OFDM | −27.90 dBFS | 11.06 dB | 50.19 MHz | EVM 51.2% — see below |
| Band-limited noise | −27.84 dBFS | 11.23 dB | 43.83 MHz | flatness **0.81 dB** std |
| Linear chirp | −17.09 dBFS | 1.14 dB | 39.62 MHz | flatness figure is an artefact — see below |

## Why OFDM measures worse, and why that is not a fault

OFDM reads far worse than QPSK on the same link in the same run. It is tempting
to blame the analysis. That was checked: run against the *clean transmit file*
the demodulator reads **0.00%**, so the chain is sound.

The cause is **peak-to-average ratio**. OFDM is the sum of 52 independent
subcarriers, so it peaks about 11 dB above its own average against roughly 4 dB
for QPSK. Transmit power is limited by the peak, so at the same peak OFDM puts
about **9 dB less average power** on the link. Same noise floor, less signal.

That it is noise and not clipping was measured directly, by backing the transmit
level off in 6 dB steps:

| TX backoff | RX rms | OFDM EVM |
|---|---|---|
| 0 dB | −29.2 dBFS | 13.4% |
| −6 dB | −35.1 dBFS | 19.6% |
| −12 dB | −40.4 dBFS | 28.4% |
| −18 dB | −44.3 dBFS | 38.0% |

Monotonically **worse** as the signal weakens — the signature of a noise-limited
link. Compression would have improved with backoff. Ruled out along the way:
band-edge filter roll-off (degradation is uniform across subcarriers, only 1.2×
edge-to-centre), cyclic-prefix length (16 to 128 samples barely moved it), and
the AD9361's adaptive DC and quadrature tracking loops (switching them off made
it worse).

OFDM also varies a lot run to run — 13% to 51% at nominally identical settings —
which matches this board's
[documented spread in transmit quadrature calibration](measured-performance.md).

## What these numbers are not

- **Not a specification.** One board, one cable, one afternoon.
- **The chirp flatness figure is a measurement artefact.** A chirp repeating every
  8192 samples has a line spectrum, and the analysis window partly resolves those
  lines. The broadband noise run, which has no line structure, is the honest
  flatness figure: **0.81 dB**.
- **The sample-drop counts are not a rate.** Two to four events per two million
  samples was what these particular captures saw; it is occasional scheduling,
  and a busier host or network will see more.
- **Nothing here characterises `TX1A`/`RX1A`.** Only channel 1 was cabled.

> ### Two measurement traps that cost real time here
>
> **A 45° constellation rotation makes good data look terrible.** Estimating
> carrier phase by raising QPSK to the fourth power and taking `angle/4` lands the
> constellation on 0/90/180/270°, but the reference lattice sits at 45°. The
> resulting EVM is about **76%** — and it looks exactly like a broken radio. This
> was hit twice, on two different estimators.
>
> **Always run the analysis against the clean transmit file first.** If the
> demodulator does not read ~0% on the waveform you generated, the bug is yours.
> That one check caught both instances immediately and is worth making reflexive.

## Reproducing it

The board needs to be on Ethernet for anything above a few MSPS. Give it a static
address in the U-Boot environment and reboot:

```bash
# run on the BOARD
fw_setenv ipaddr_eth 192.168.129.200
fw_setenv netmask_eth 255.255.254.0
reboot
```

`S40network` reads those at boot and writes `/etc/network/interfaces`; leaving
`ipaddr_eth` empty falls back to DHCP. The USB gadget on `192.168.2.1` keeps
working either way, which is a useful escape route.

From there the measurements are ordinary `libiio` calls — see
[Talking to the board](../.claude/skills/fishball7020-firmware/references/talking-to-the-board.md)
for the command forms, and remember the rule that applies to all of them:

> **Set transmit attenuation only after the DMA buffer is open, then read it
> back.** Writing it before a stream starts guarantees nothing. Every measurement
> on this page asserted both channels returned to the −89.75 dB floor afterwards.
