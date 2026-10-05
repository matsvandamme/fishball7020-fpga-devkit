---
icon: material/stethoscope
description: The self-test checks the radio with no cable and nothing transmitted.
---

# Check the radio is healthy

The self-test checks the board in about 15 seconds, with no cable and nothing
transmitted.

```bash
# run from: the repo root
./devkit selftest --ssh                                    # no cable, never transmits
```

It checks the rails, die temperatures, the digital interface eye and the
receiver.

**You should see:** every line `PASS`, no failures, and `HEALTHY`. The end of
a real run:

```text
# run from: the repo root - the last lines of the command above, captured from the board
== Receiver (no cable) ==
  PASS   capture returns the requested length
           16384 of 16384 samples
  PASS   I and Q are both live
           10 distinct I values, 11 distinct Q - a stuck converter shows one or two
  PASS   DC offset within range
           -90.6 dBFS (I +0.1, Q -0.0 LSB)
  PASS   RX gain chain responds at the top of its range
           noise floor -106.4 -> -102.4 -> -102.0 -> -87.9 -> -79.4 dBFS at 0/20/40/60/70 dB gain; converter-limited below ~40 dB, +22.7 dB over the top 30 dB
  PASS   second receive channel alive
           RX2 floor -100.9 dBFS (its input is whatever is on the RX2 port)
  PASS   RX synthesiser tunes across the range
           8 of 8 points from 70 to 6000 MHz

== RF loopback ==
  info   skipped
           not requested. Cable TX1 to RX1 through a 20-30 dB pad and add --loopback to measure the analogue path.

25 passed, 0 warnings, 0 failed in 15 s
HEALTHY
(analogue front end untested - rerun with --loopback)
```

??? question "It hangs, or reports Calibration TIMEOUT?"
    Power the board from a **mains charger**: on laptop USB bus power alone, a
    board with a power amplifier browns out under sustained use
    ([troubleshooting](../troubleshooting.md#the-board-stops-responding-after-a-while)).

**The loopback test transmits.** Cable a transmit port to a receive port through
**a single 20 dB pad** first, and affirm the channel
([before you transmit](../start/before-you-transmit.md)):

```bash
# run from: the repo root
./devkit selftest --ssh --loopback --pad 20 --channel 0 \
    --sweep-points 60 --sweep-start 70e6 --sweep-stop 6e9 --json run1.json
```

What one board measured, and what the numbers mean:
[measured performance](../measured-performance.md).
