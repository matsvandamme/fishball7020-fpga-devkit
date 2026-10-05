---
icon: material/chart-line
description: A complete automation script - both loopbacks swept from 100 MHz to 5.8 GHz, measured, written to a CSV.
---

# Sweep both loopbacks across frequency

A complete measurement script, built on [the automation server](../automation.md).
At 14 frequencies from 100 MHz to 5.8 GHz it plays a tone on both transmitters,
records both receivers in the same call, and measures four things in each
spectrum:

| Column | What it is |
|---|---|
| **level** | the tone as received, in dBFS: decibels below a full-scale sample |
| **image** | the tone's mirror on the other side of the LO, in dBc (decibels below the tone). It shows how well the receiver's I and Q are balanced |
| **LO** | what sits on the LO frequency itself, in dBc: carrier leakage |
| **spur** | the largest other component in the band, in dBc |

It takes 15 seconds, and writes a CSV and an SVG figure of it (`loopback_sweep.svg`, open it in a browser). The script is
[`tools/automation/examples/loopback_sweep.py`](../../tools/automation/examples/loopback_sweep.py),
about 150 lines; copy it as the starting point for your own measurements.

**You need:** the server installed ([automate a measurement](automate-measurements.md), step 1),
and both loops cabled with an attenuator: TX1A → 20 dB → RX1A, TX2A → 30 dB → RX2A.
Never less than 20 dB: the transmitter reaches about +19 dBm and a receiver
survives +2.5 dBm.

1. Look at both transmit ports, then put them on record. The record dies at the
   next reboot.

    ```bash
    # run from: the repo root on your PC
    ./devkit tx-guard affirm 0
    ./devkit tx-guard affirm 1
    ```

2. Run the sweep. The CSV is written to the directory you run it from.

    ```bash
    # run from: tools/automation
    .venv/bin/python examples/loopback_sweep.py
    ```

3. Withdraw the record.

    ```bash
    # run from: the repo root on your PC
    ./devkit tx-guard revoke both
    ```

**You should see** a row per frequency as it is measured, then a summary.
Measured on 2026-10-05:

```text
FISH Ball PlutoSDR Rev.A (Z7020/AD9361), firmware v2.0-9-g5ae29d94-dirty, server 0.1.0, die 40.4 C
TX1 and TX2 at -40 dB, RX1 and RX2 at 20 dB gain, tone 1 MHz above the LO

  LO MHz  RX1 dBFS  image     LO   spur   RX2 dBFS  image     LO   spur   (image, LO, spur in dBc)
  100.00     -29.7  -59.7  -55.4  -57.2      -38.9  -57.7  -48.8  -48.1
  200.00     -25.8  -64.1  -58.6  -58.5      -35.4  -52.9  -50.7  -50.3
  433.92     -25.3  -59.1  -57.8  -56.7      -35.0  -62.1  -51.8  -51.4
  600.00     -25.6  -58.8  -60.2  -55.9      -35.6  -55.1  -48.0  -52.0
  868.00     -24.8  -71.7  -58.1  -57.3      -35.1  -65.5  -50.9  -50.9
 1000.00     -25.4  -76.1  -59.3  -59.2      -35.9  -69.1  -47.2  -50.8
 1500.00     -25.8  -73.8  -56.5  -56.6      -35.0  -67.0  -46.6  -49.7
 2000.00     -27.2  -44.9  -51.8  -53.0      -37.3  -44.2  -44.0  -48.9
 2400.00     -29.7  -47.9  -52.7  -46.6      -38.9  -46.0  -43.2  -46.2
 3000.00     -33.4  -55.7  -45.9  -48.8      -44.2  -51.6  -37.5  -41.0
 3500.00     -34.8  -61.6  -46.9  -52.2      -46.4  -51.7  -32.1  -40.1
 4000.00     -38.7  -58.2  -37.7  -48.3      -48.2  -36.5  -32.6  -38.0
 5000.00     -38.6  -53.5  -36.6  -40.7      -45.6  -38.1  -31.0  -38.1
 5800.00     -41.8  -50.4  -37.9  -44.7      -51.8  -31.8  -25.0  -34.5

14 frequencies in 15 s; die 41.2 C; TX1 -89.75 dB, TX2 -89.75 dB
RX1: level -41.8 to -24.8 dBFS (a 17.0 dB spread), image at worst -44.9 dBc at 2000 MHz
RX2: level -51.8 to -35.0 dBFS (a 16.8 dB spread), image at worst -31.8 dBc at 5800 MHz
written to /home/you/fishball7020-fpga-devkit/tools/automation/loopback_sweep.csv
```

The last line before the summary matters most: both transmitters read
−89.75 dB, the floor. If either does not, the script says
**A TRANSMITTER IS NOT MUTED** and exits with status 1.

## Reading the result

![Two panels against LO frequency, 100 MHz to 5.8 GHz, from two runs. Top: tone level. RX1 sits near -25 dBFS from 200 MHz to 1.5 GHz and falls to -42 dBFS at 5.8 GHz; RX2 has the same shape about 10 dB lower; the two runs differ by at most 1.2 dB. Bottom: image rejection, one dot per run. RX1 is best, -72 to -79 dBc, between 868 MHz and 1.5 GHz; both are near -45 dBc at 2 GHz, and RX2 is -32 to -38 dBc above 4 GHz; the two runs land up to 14 dB apart.](../img/automation-sweep-light.svg#only-light)
![Two panels against LO frequency, 100 MHz to 5.8 GHz, from two runs. Top: tone level. RX1 sits near -25 dBFS from 200 MHz to 1.5 GHz and falls to -42 dBFS at 5.8 GHz; RX2 has the same shape about 10 dB lower; the two runs differ by at most 1.2 dB. Bottom: image rejection, one dot per run. RX1 is best, -72 to -79 dBc, between 868 MHz and 1.5 GHz; both are near -45 dBc at 2 GHz, and RX2 is -32 to -38 dBc above 4 GHz; the two runs land up to 14 dB apart.](../img/automation-sweep-dark.svg#only-dark)

Two runs, a few minutes apart, on one board:

| | Largest difference between the runs |
|---|---|
| Tone level | 1.2 dB (RX1 at 100 MHz) |
| Image | 14.5 dB (RX2 at 100 MHz: −57.7 and −43.3 dBc) |
| LO leakage | 6.3 dB |
| Worst spur | 5.1 dB |

- **The level is flat from 200 MHz to 1.5 GHz and falls by about 17 dB to
  5.8 GHz.** That is the transmitter, the receiver and the cables together.
  RX2 reads about 10 dB below RX1 because its attenuator is 10 dB bigger.
- **The level repeats; the image does not.** Run a measurement of image, LO
  leakage or spurs several times and report the worst, not one run.
- **This is not a calibrated measurement.** dBFS is relative to the receiver's
  full scale at 20 dB gain, not to a power meter. For the board's loop gain
  with the pad added back, see
  [measured performance](../measured-performance.md#frequency-response).

## How the script is built

It is one pattern, and it is the one to copy:

```python
# run from: tools/automation (an excerpt of examples/loopback_sweep.py)
with Fishball(a.host, timeout=60) as board:
    board.configure(sample_rate_hz=RATE, ...)                          # (1)!
    wave = board.upload_waveform(0.5 * 32767 * np.exp(2j * np.pi * TONE_HZ * t))   # (2)!
    try:
        with tempfile.TemporaryDirectory() as tmp:
            for lo in lo_list:
                board.configure(rx_lo_hz=int(lo), tx_lo_hz=int(lo))
                info = board.transmit_capture(wave, BLOCKS * BLOCK,       # (3)!
                                              tx_channels=[1, 2], rx_channels=[1, 2],
                                              attenuation_db=a.attenuation, pad_db=a.pad, settle_s=0.3)
                x = board.fetch(info, os.path.join(tmp, "c")).read()     # (4)!
                board.delete(info.id)
                m1, m2 = measure(x[0]), measure(x[1])
    except FishballError as e:                                           # (5)!
        print(f"the board refused: {e.code}: {e}")
    finally:
        board.delete_waveform(wave)
        board.mute()                                                     # (6)!
        board.configure(sample_rate_hz=30_720_000, ...)
        s = board.status()
```

1.  Settings that hold for the whole run go first. Manual receive gain, so
    every frequency is measured at the same gain.
2.  The waveform is uploaded once and played by its id at every frequency.
    76 800 samples hold exactly 16 000 cycles of the 1 MHz tone, so it repeats
    without a seam; its length must be a multiple of 32 samples.
3.  One call: the server starts the transmitters muted, raises them to the
    asked attenuation, waits `settle_s`, records, and mutes before it releases
    the buffer. It refuses without an affirmation, or with `pad_db` under 20.
4.  The capture is fetched as a SigMF pair into a temporary directory and read
    as complex samples in counts (±2048 full scale). `measure()` turns each
    receiver's samples into the four numbers.
5.  A refusal arrives as `FishballError`, with the reason the server gave:
    the script prints it rather than a stack trace.
6.  However the loop ended, the script mutes, puts the board back to its
    defaults, and reads both transmitters back.

## Make it measure something else

| To | Change |
|---|---|
| sweep other frequencies | `--mhz 400,433.92,450`; the AD9361 tunes 70 MHz to 6 GHz |
| measure one channel | `tx_channels=[1]` and `rx_channels=[1]`; the other transmitter is held at −89.75 dB |
| drive harder | `--attenuation -30`. Louder than −10 dB is refused unless `--pad` states at least 20 |
| measure something new | add it to `measure()`, which gets one receiver's samples |
| plot the result | `loopback_sweep.svg` is drawn for you (`--plot ''` turns it off); [`docs/img/make_automation_sweep_svg.py`](../img/make_automation_sweep_svg.py) drew the figure above from two runs' CSVs |

??? question "It says TX2 has no affirmation on record"
    Step 1 is missing for that channel, or the board rebooted since. Look at
    TX2A, then `./devkit tx-guard affirm 1`.

??? question "It says the transmit buffer is in use"
    Another program holds it: SDR++, an MCP transmit, a CI run. The message
    names the process. Stop it and run again.

Every call and every rule: [the automation server](../automation.md#transmitting).
