---
icon: material/robot-outline
description: A server on the board and a Python client, for repeatable bench measurements.
---

# Automate a measurement

The automation server runs on the board. A script on your PC asks it to set
the radio, record a capture and hand over the file. It never transmits.

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

Every call, the limits and the measurements: [the automation server](../automation.md).
