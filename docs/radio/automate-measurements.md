---
icon: material/robot-outline
description: A server on the board and a Python client, for repeatable bench measurements.
---

# Automate a measurement

The automation server runs on the board. A script on your PC asks it to set
the radio, record a capture and hand over the file, and, on a port you have
vouched for, transmit while it records.

1. Install the server on the board, once. It needs the Debian root.

    ```bash
    # run from: the repo root on your PC
    ./devkit automation install
    ./devkit automation status
    ```

2. Write the measurement.

    ```python
    # run from: tools/automation, as: .venv/bin/python example.py
    from fishball_automation.client import Fishball

    with Fishball("fishball.local") as board:
        board.configure(rx_lo_hz=868_000_000, sample_rate_hz=20_000_000,
                        rx1_gain_mode="manual", rx1_gain_db=30)
        rec = board.capture(samples=2_000_000, channels=[1, 2], path="loop")
        print(rec.samples, "samples per channel,", rec.lost_samples, "lost")
        x = rec.read()                   # complex64, shape (2, 2000000)
    ```

3. Run it with the client's venv, which `./devkit automation status` created
   in `tools/automation/.venv`.

**You should see:** `loop.sigmf-data` and `loop.sigmf-meta` beside your script,
and `0 lost`: a capture is recorded on the board, gap-free, then fetched.

??? question "It says the receive buffer is in use"
    Another program is streaming from the board: SDR++, a capture, a CI run.
    The message names it. Close it and run again;
    `./devkit automation status` shows who holds the buffers.

## Transmit and record in one call

1. Fit at least 20 dB between the transmitter and the receiver: TX1A →
   20 dB → RX1A. Look at the port, then put that on record. The record dies at
   the next reboot.

    ```bash
    # run from: the repo root on your PC
    ./devkit tx-guard affirm 0
    ```

2. Upload the waveform once, then play it and record.

    ```python
    # run from: tools/automation, as: .venv/bin/python tone.py
    import numpy as np
    from fishball_automation.client import Fishball

    rate = 4_800_000
    with Fishball("fishball.local") as board:
        board.configure(sample_rate_hz=rate, rx_lo_hz=868_000_000, tx_lo_hz=868_000_000,
                        rx1_gain_mode="manual", rx1_gain_db=20)
        t = np.arange(76_800) / rate                     # a multiple of 32 samples
        w = board.upload_waveform(0.5 * 32767 * np.exp(2j * np.pi * 1e6 * t))
        rec = board.transmit_capture(w, 1 << 20, tx_channels=[1], rx_channels=[1],
                                     attenuation_db=-40, pad_db=20, path="tone")
        board.delete_waveform(w)
    ```

**You should see:** `tone.sigmf-data` with a tone 1 MHz above the LO, and
both transmitters back at −89.75 dB: `./devkit automation status`. When you
are done, withdraw the record: `./devkit tx-guard revoke both`.

??? question "It says TX1 has no affirmation on record"
    Step 1 is missing, or the board rebooted since. Look at TX1A, then
    `./devkit tx-guard affirm 0`.

??? question "It says louder than −10 dB needs pad_db"
    `pad_db` is the attenuator you fitted, in dB. The transmitter reaches about
    +19 dBm and a receiver survives +2.5 dBm, so the server wants at least 20.

For timing between transmit and receive, record a reference channel as well:
the hardware does not start both together
([why](../automation.md#transmitting)).

Every call, the limits and the measurements: [the automation server](../automation.md).
