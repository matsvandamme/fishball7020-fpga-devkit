# Throughput and modulation quality at high sample rates

How fast samples move between this board and a host, where each limit sits, and
how clean modulated signals (QPSK, 16-QAM, OFDM and others) are up to the full
61.44 MSPS. Read it before planning a capture or transmit stream above a few
MSPS; the radio's own tone measurements are in
[measured-performance.md](measured-performance.md). For the tasks:
[transmit a waveform on repeat](radio/transmit-on-repeat.md), [capture IQ to a file](radio/capture-iq.md).

The limit you meet first is the host link and the board's CPU, not the radio. To
transmit at any rate without the host in the loop, load the waveform once and
let the hardware repeat it (cyclic transmit):

```bash
# run from: your host - -c makes the transmit buffer cyclic
iio_writedev -u ip:192.168.129.200 -c -b 262144 -s 262144 \
  cf-ad9361-dds-core-lpc voltage2 voltage3 < waveform.bin
```

!!! danger "Set transmit attenuation only after the DMA buffer is open, then read it back"
    Writing it before a stream starts guarantees nothing. Every measurement here
    checked that both channels returned to the −89.75 dB floor afterwards.

## Reproducing it

Anything above a few MSPS needs the board on Ethernet. Give it a static address
in the U-Boot environment and reboot:

```bash
# run from: the board
fw_setenv ipaddr_eth 192.168.129.200
fw_setenv netmask_eth 255.255.254.0
reboot
```

`S40network` reads those at boot and writes `/etc/network/interfaces`; an empty
`ipaddr_eth` falls back to DHCP. The USB gadget on `192.168.2.1` keeps working
as a fallback route. The measurements are ordinary `libiio` calls; see
[Talking to the board](../.claude/skills/fishball7020-firmware/references/talking-to-the-board.md).
Raw results: [`img/data/modulation-throughput.json`](img/data/modulation-throughput.json)
and [`img/data/throughput.json`](img/data/throughput.json).

## Terms and conditions

| Term | Meaning |
|---|---|
| **dBFS** | Decibels relative to *full scale*, the largest value the receiver represents. Always negative; −20 dBFS is comfortable |
| **dBc** | Decibels relative to the wanted carrier; a bigger number means a cleaner signal |
| **MSPS** | Million samples per second. One I/Q sample is two signed 16-bit numbers, **four bytes** |
| **EVM** | Error vector magnitude: how far received symbols land from where they should. 1% excellent, 5% usable, above 15% unrecoverable |
| **PAPR** | Peak-to-average power ratio. Transmit power is limited by the peak, so a spiky signal delivers less average power |
| **SFDR** | Spurious-free dynamic range: how far a tone stands above the largest unwanted line |

Unless stated otherwise: one board, v1.4 firmware, on **gigabit Ethernet**; the
host has **no wired interface**, so every network figure crossed WiFi (540 Mbit/s)
and a router. A wired gigabit host was measured later, for streaming only: [on a direct cable](streaming-paths.md#on-a-direct-cable). `TX2A` → **20 dB
attenuator** → `RX2A`, 900 MHz, −30 dB transmit attenuation, 20 dB manual receive
gain, `iio_readdev` buffer 64 Ksamples. Only channel 1 (`TX2A`/`RX2A`) is cabled;
nothing here characterises `TX1A`/`RX1A`. One board, one cable, one session: not
a specification.

## The short version

| | |
|---|---|
| **The radio at 61.44 MSPS** | runs clean: QPSK **2.17%** and 16-QAM **2.24%** EVM across 18 MHz of occupied bandwidth |
| **Continuous streaming, both directions** | breaks above about **5 MSPS**: a host-streaming limit that disappears with cyclic transmit |
| **Streaming throughput** | depends on buffer size: ~30 MB/s at 64 Ksamples, ~45 MB/s / 11.3 MS/s (one channel) at 1 Msample |
| **On the board, no network** | capture reaches **183–220 MB/s** on one channel, close to what the converter produces |
| **Capture integrity** | bit-perfect at 5 MSPS; above it, 2 to 4 discrete drops per two million samples, even at 61.44 MSPS |
| **OFDM** | measures far worse than QPSK, because of its peak-to-average ratio |

## Where the 5 MSPS ceiling comes from

QPSK EVM against sample rate, streaming both directions:

| Link | 2.5 MSPS | 4 MSPS | 5 MSPS | 7.5 MSPS | 10 MSPS | 15 MSPS |
|---|---|---|---|---|---|---|
| USB gadget | 1.34% | **49.5%** | — | — | — | — |
| Gigabit Ethernet | 3.54% | — | **1.89%** | 67.8% | 76.9% | 93.0% |

Ethernet doubles the usable rate, not twelve-fold, because the wire is not the
constraint: raw capture rises from ~10 MB/s (USB) to ~31 MB/s (Ethernet) and
stops. Above the ceiling the transmit DMA starves and substitutes zeros, so the
transmitted waveform is not the one you generated; an EVM above ~15% here means
corruption, not a weak signal.

### What each configuration demands

`4 bytes × channels × sample rate`, against a gigabit link (125 MB/s each way):

| Active channels | At 61.44 MS/s | Busiest single direction | Rate a gigabit link allows |
|---|---:|---:|---:|
| 1 TX or 1 RX | 245.8 MB/s | 245.8 MB/s | 31.25 MS/s |
| 2 TX or 2 RX | 491.5 MB/s | 491.5 MB/s | 15.62 MS/s |
| 1 RX + 1 TX | 491.5 MB/s | 245.8 MB/s | 31.25 MS/s |
| 1 RX + 2 TX, or 2 RX + 1 TX | 737.3 MB/s | 491.5 MB/s | 15.62 MS/s |
| 2 RX + 2 TX | 983.0 MB/s | 491.5 MB/s | 15.62 MS/s |

Ethernet is full duplex, so the busiest single direction is what matters; the
directions still share the board's CPU.

The AD9361's LVDS port has 6 lanes each way, double data rate, `DATA_CLK` up to
245.76 MHz (data sheet Rev. G): 2.949 Gbit/s per direction, which is
122.88 MS/s for one 24-bit channel or **61.44 MS/s for two**, exactly the
converter's maximum. The board runs `adi,2rx-2tx-mode-enable`, so both channels
occupy the interface whether or not you read both.

Limits in the order you meet them:

![The limits in the order you meet them: your host link, the only cheap one to change; then the board's CPU; then the LVDS port and converter, 61.44 MS/s on two channels, reached only with the host out of the loop.](img/radio-limits-light.svg#only-light)
![The limits in the order you meet them: your host link, the only cheap one to change; then the board's CPU; then the LVDS port and converter, 61.44 MS/s on two channels, reached only with the host out of the loop.](img/radio-limits-dark.svg#only-dark)

### Throughput against buffer size

`iio_readdev -b`, receive only, 33.6 Msamples per run, mean of three runs, over
the WiFi path (~68 MB/s at the PHY):

| Buffer | 1 RX channel | 2 RX channels |
|---|---|---|
| 16 Ksamples | 14.9 MB/s | 16.6 MB/s |
| 64 Ksamples | **28.3 MB/s** (used for the EVM tables) | 28.0 MB/s |
| 256 Ksamples | 39.1 MB/s | 34.7 MB/s |
| 1 Msample | 45.4 MB/s | 44.8 MB/s |
| 2 Msamples | **46.2 MB/s** | 40.0 MB/s |
| 4 Msamples | 44.4 MB/s | 44.9 MB/s |

It plateaus near **44 MB/s** above ~1 Msample. Plotted by
[`tools/plot_throughput.py`](../tools/plot_throughput.py).

!!! warning "Repeats spread by up to 13 MB/s, so do not trust single runs"

### On the board, with no network

The same capture run on the board, interleaved across kernels (same tool, buffer,
rate and counts, three repeats each):

| Kernel | 33.6 M, 1 ch | 33.6 M, 2 ch | 134.4 M, 1 ch | 134.4 M, 2 ch |
|---|---|---|---|---|
| 6.12 | 183.1 MB/s | 346.4 MB/s | 220.0 MB/s | 430.8 MB/s |
| 5.15 | 183.1 MB/s | 346.4 MB/s | 220.0 MB/s | 430.8 MB/s |
| 6.12 again | 183.1 MB/s | 341.8–346.4 MB/s | 220.0 MB/s | 429.0–430.8 MB/s |

The kernel makes no difference. Four to eight times any network figure; the
buffer size barely matters locally (216 MB/s at 64 K against 200 MB/s at 1 M), so
the buffer effect is a property of the link. `iio_readdev`'s start-up sits inside
the timed window, so compare runs with **the same sample count**. Re-run with
[`tools/throughput-ab.sh`](../tools/throughput-ab.sh).

## Cyclic transmit: let the hardware repeat the waveform

The transmit DMA has `CYCLIC = 1`: load a buffer once (`-c` above) and the
hardware replays it forever, freeing the whole link for capture. Same setup:

| Sample rate | QPSK EVM | 16-QAM EVM | Implied SNR |
|---|---|---|---|
| 5.00 MSPS | 1.76% | 1.61% | ~35 dB |
| 15.00 MSPS | 1.67% | 1.62% | ~36 dB |
| 30.72 MSPS | 2.05% | 2.04% | ~34 dB |
| **61.44 MSPS** | **2.18%** | **2.26%** | ~33 dB |

A cyclic buffer carries no unique data: it suits test signals, beacons, radar
chirps and calibration, not messages.

## The radio itself at full rate

A tone generated inside the FPGA takes the host out of transmit; it still leaves
`TX2A`, crosses the pad and returns to `RX2A`:

| Sample rate | Bandwidth | Throughput | Tone SNR | SFDR | Image rejection | Sample drops |
|---|---|---|---|---|---|---|
| 5.00 MSPS | 4.0 MHz | 16.3 MB/s | 90.1 dB | 43.2 dB | 43.2 dB | **0** |
| 15.00 MSPS | 12.0 MHz | 26.3 MB/s | 89.9 dB | 48.2 dB | 65.6 dB | 2 |
| 30.72 MSPS | 24.6 MHz | 31.4 MB/s | 88.1 dB | 46.4 dB | 76.5 dB | 3 |
| 61.44 MSPS | 49.2 MHz | 26.6 MB/s | 85.4 dB | 42.1 dB | 65.9 dB | 4 |

Tone SNR falls only 4.7 dB across the sweep; image rejection improves with rate
because quadrature calibration works better with the tone further from centre.
Throughput plateaus near 31 MB/s, limited by the board's CPU, not the wire.

**Detecting drops:** de-rotate the capture by the tone frequency and the residual
phase should be constant; a lost chunk is a step. Every step here is exactly π (a
multiple of four samples at `fs/8`), with flat phase between, so these are
discrete dropped packets. The AD9361's internal BIST tone (built-in self-test,
injected inside the chip, no RF) gives the same picture, so the drops are in the
capture path, not the radio. [`tools/sigmf-capture.py --verify`](capturing-iq.md)
runs this check. The counts are occasional scheduling, not a rate.

```bash
# run from: your host - inject a known tone inside the chip, no RF
iio_attr -u ip:192.168.129.200 -D ad9361-phy bist_tone "2 7680000 0 0"
# ... capture ...
iio_attr -u ip:192.168.129.200 -D ad9361-phy bist_tone "0 0 0 0"   # off again
```

## Every waveform at 61.44 MSPS

Same transmit attenuation, full 56 MHz receive bandwidth:

| Waveform | RX rms | PAPR | Occupied BW | Key figure |
|---|---|---|---|---|
| CW tone | −16.74 dBFS | 0.75 dB | 30 kHz | image rejection **71.1 dBc**, LO leak 62.0 dBc, SNR 71.0 dB |
| Two-tone | −19.73 dBFS | 3.56 dB | 4.02 MHz | IMD3 (third-order intermodulation) **55.8 dBc** |
| QPSK | −20.66 dBFS | 4.14 dB | 17.96 MHz | EVM **2.17%** |
| 16-QAM | −22.84 dBFS | 6.20 dB | 18.12 MHz | EVM **2.24%** |
| OFDM | −27.90 dBFS | 11.06 dB | 50.19 MHz | EVM 51.2%, see below |
| Band-limited noise | −27.84 dBFS | 11.23 dB | 43.83 MHz | flatness **0.81 dB** std |
| Linear chirp | −17.09 dBFS | 1.14 dB | 39.62 MHz | flatness not valid: its line spectrum is partly resolved by the analysis window |

**Why OFDM measures worse.** Its 52 subcarriers peak 11.06 dB above average
against 4.14 dB for QPSK, so at the same peak it puts about **7 dB less average
power** on the link (the received levels are 7.24 dB apart): same noise floor,
less signal. Run against the clean transmit file the demodulator reads 0.00%.
Backing off makes EVM steadily worse, the signature of noise, not compression:

| TX backoff | RX rms | OFDM EVM |
|---|---|---|
| 0 dB | −29.2 dBFS | 13.4% |
| −6 dB | −35.1 dBFS | 19.6% |
| −12 dB | −40.4 dBFS | 28.4% |
| −18 dB | −44.3 dBFS | 38.0% |

It is not band-edge roll-off, cyclic-prefix length, or the AD9361's tracking
loops. OFDM varies 13% to 51% run to run, matching this board's
[spread in transmit quadrature calibration](measured-performance.md#transmit-chain).

!!! warning "Pitfall when measuring EVM"
    Estimating QPSK carrier phase with the fourth-power method lands the
    constellation 45° off the reference lattice and reads about 76%, which looks like
    a broken radio. Always run the analysis against the clean transmit file first;
    it should read ~0%.

## A WiFi hop in the path

A WiFi hop between host and board can collapse the rate, not just lower it
(board on 1000 Mb/s full duplex, Wi-Fi 6 at −47 dBm):

| | |
|---|---|
| board against **itself** (loopback) | **1.89 Gbit/s**, 0 retransmits |
| board at **1000 Mb/s**, through WiFi | 679 Mbit/s burst, **807 retransmits**, then **7 Mbit/s for 24 s** |
| board at **100 Mb/s**, through WiFi | no collapse; ~94 Mbit/s peaks, avg 48 |

The board is not the bottleneck: a gigabit sender fills buffers faster than the
WiFi hop drains them, and TCP does not recover within thirty seconds. It is not
thermal, not the supply rails, and logs no kernel error.

!!! warning "`iio_readdev` returns the byte count you asked for whether or not the DMA overflowed"
    So a capture across a stall looks perfect and is not. With WiFi in the path, use
    the USB gadget (`192.168.2.1`) or a wired route.

!!! note "There is no Ethernet flow control"
    Link-up logs `flow control off` and `ethtool -a eth0` answers *"Operation not
    supported"*: this `macb` driver has no `get_pauseparam`/`set_pauseparam`. An
    overwhelmed board drops frames. On a wired gigabit path that does not matter;
    with something slower between, it does.

## Further reading

[capturing-iq.md](capturing-iq.md): recording with metadata and a drop check ·
[transmitter-safety.md](transmitter-safety.md): before anything transmits
