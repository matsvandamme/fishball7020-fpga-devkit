---
icon: material/repeat
description: A cyclic buffer - the board replays one waveform at full rate, with the safe ordering.
---

# Transmit a waveform on repeat

A **cyclic buffer** is one block of samples the board replays from its own
memory until stopped: up to 61.44 MS/s, with nothing needed from your PC while
it plays.

!!! danger "Read [before you transmit](../start/before-you-transmit.md) first"
    The board puts out about +19 dBm and its receivers survive only +2.5 dBm:
    never loop TX into RX without at least 20 dB of attenuation, and transmit only
    where you are allowed to.

```python
# run from: your PC, in a venv: .venv/bin/pip install pyadi-iio numpy; .venv/bin/python example.py
import adi, numpy as np

sdr = adi.ad9361("ip:192.168.2.1")      # or ip:fishball.local over Ethernet
sdr.tx_enabled_channels = [0]           # TX1
sdr.sample_rate = 30_720_000            # shared by RX and TX on this chip
sdr.tx_lo = 433_920_000                 # a licence-free band
sdr.tx_cyclic_buffer = True             # play the buffer forever

N  = 3840                               # exactly 125 cycles of 1 MHz at 30.72 MS/s
n  = np.arange(N)
iq = 0.5 * 2**15 * np.exp(2j * np.pi * 1e6 * n / sdr.sample_rate)

sdr.tx(iq)                              # starts it; returns at once
for _ in range(10):                     # AFTER the start: set, then read back
    sdr.tx_hardwaregain_chan0 = -40     # dB; -89.75 is muted, 0 is maximum
    if abs(sdr.tx_hardwaregain_chan0 + 40) < 0.3:
        break
else:
    raise RuntimeError("TX attenuation did not apply")

input("transmitting - press Enter to stop")
sdr.tx_hardwaregain_chan0 = -89.75      # mute FIRST...
assert sdr.tx_hardwaregain_chan0 <= -89.0
sdr.tx_destroy_buffer()                 # ...then stop
```

| The two rules in the code | Why |
|---|---|
| **Set the attenuation after `tx()`, and read it back** | starting a buffer restores a cached attenuation, which can be louder than what you set before it |
| **Mute before `tx_destroy_buffer()`, never after** | stopping caches whatever attenuation it finds, for the next buffer to restore |

- **To change the waveform:** mute, `tx_destroy_buffer()`, then `tx()` the new
  one and set the attenuation again. The output stops for the moment in between.
- **Both transmitters:** `sdr.tx_enabled_channels = [0, 1]` and
  `sdr.tx([iq_tx1, iq_tx2])`; they start together and stay sample-aligned.

From the command line, waveform design, and the board's limits:
[cyclic buffers and triggers](../cyclic-buffers.md).

**Next:** [watch a sweep live](watch-a-sweep.md), a cyclic buffer you can see.
