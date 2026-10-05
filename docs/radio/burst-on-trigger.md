---
icon: material/flash-outline
description: Play a prepared buffer once per UDP datagram or GPIO edge, with tx-burst on the board.
---

# Send a burst on a trigger

`tools/tx-burst` runs on the board: it loads the burst once, then plays it
**once per trigger** (a UDP datagram, or a rising edge on a JP5 pin), and the
DAC outputs zeros in between.

!!! danger "Read [before you transmit](../start/before-you-transmit.md) first"
    At least 20 dB in any TX→RX loop.

```bash
# run from: the board. Build once (apt install gcc make libiio-dev), or copy a binary built elsewhere.
make -C tx-burst
# play burst.iq once per UDP datagram to port 5556, TX1 at -40 dB:
./tx-burst/tx-burst -f burst.iq -u 5556 -a -40
```

```python
# run from: any computer that can reach the board - fires one burst
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.sendto(b"fire", ("fishball.local", 5556))
print(s.recv(64).decode())             # "fired 1 139": burst number, microseconds to queue it
```

**You should see:** `fired N LATENCY_US` back for each datagram.

| Option | Meaning |
|---|---|
| `-f FILE` | the burst: int16 I,Q per sample for TX1; with `-2`, I1,Q1,I2,Q2 for both transmitters |
| `-u PORT` | trigger on a UDP datagram; the sender gets back `fired N LATENCY_US` |
| `-g LINE` | trigger on a rising edge of GPIO line `LINE`: 72 to 75 are JP5 pins 7, 9, 11 and 13, 3.3 V |
| `-a DB` | TX attenuation while armed, from -89.75 (muted, the default) to 0 |
| `-m` | markers: JP5 pin 11 pulses on each burst's first sample, JP5 pin 13 is high while it plays |
| `-n COUNT` | exit after COUNT bursts |

A trigger **in** is software-timed: the FPGA design this board ships has no
hardware trigger input. Timing measurements and triggering other equipment:
[cyclic buffers and triggers](../cyclic-buffers.md#one-shot-bursts-on-a-trigger).
