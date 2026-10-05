---
icon: material/stethoscope
description: The self-test checks the radio with no cable and nothing transmitted.
---

# Check the radio is healthy

```bash
# run from: the repo root
./devkit selftest --ssh                                    # no cable, never transmits
```

It checks the rails, die temperatures, the digital interface eye and the
receiver.

**You should see:** `24 passed, 0 failed, HEALTHY`.

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
