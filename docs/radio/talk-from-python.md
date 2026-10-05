---
icon: material/language-python
description: A venv, pyadi-iio, then tune and receive in six lines.
---

# Talk to the board from Python

The board's `iiod` daemon serves the radio over the network; anything speaking
**libiio** can drive it, from any language. From Python:

![A Python script on your PC, using pyadi-iio in a venv, talks libiio over Ethernet or USB to iiod on the board, port 30431, which drives the AD9361 radio.](../img/radio-libiio-light.svg#only-light)
![A Python script on your PC, using pyadi-iio in a venv, talks libiio over Ethernet or USB to iiod on the board, port 30431, which drives the AD9361 radio.](../img/radio-libiio-dark.svg#only-dark)

```bash
# run from: your project's folder, on your PC
python3 -m venv .venv                     # a venv: Python packages for this project only
.venv/bin/pip install pyadi-iio           # this is the whole install
```

```python
# run from: your project's folder, as: .venv/bin/python example.py
import adi
sdr = adi.ad9361("ip:fishball.local")     # or ip:192.168.2.1 over USB
sdr.rx_lo             = 2_400_000_000     # tune to 2.4 GHz
sdr.sample_rate       = 4_000_000
sdr.rx_rf_bandwidth   = 4_000_000
sdr.rx_buffer_size    = 65536
x = sdr.rx()                              # 65536 complex samples
sdr.rx_destroy_buffer()                   # not optional - see below
```

**You should see:** `x` holding 65536 complex samples.

| Rule | Why |
|---|---|
| **Call `rx_destroy_buffer()` (or `tx_destroy_buffer()`) before the script ends** | otherwise the script can segfault on exit (code 139) inside `iio_buffer_destroy()`: the data is fine, but the crash fails tests and CI |
| **Full scale is ±2047** (12-bit), not 32768 | dividing by 32768 reads every level 24 dB low |
| **One program receives at a time** | the board has one receive buffer |

!!! danger "Transmitting?"
    Read [before you transmit](../start/before-you-transmit.md) first: at least
    20 dB in any TX→RX loop, attenuation set **after** the buffer starts and read
    back, mute **before** teardown. The safe pattern: [transmit a waveform on repeat](transmit-on-repeat.md).

**Next:** [capture IQ to a file](capture-iq.md).
