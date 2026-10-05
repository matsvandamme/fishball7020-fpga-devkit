---
icon: material/alert-octagon-outline
description: Four rules that keep the receiver and the bench intact.
---

# Before you transmit

This board has a power amplifier: about **+19 dBm** out, against a receiver
that survives **+2.5 dBm**.

| Rule | |
|---|---|
| **1. Put at least 20 dB of attenuation in any TX→RX loop** | without it, the transmitter destroys its own receiver |
| **2. Terminate every transmit port**, or leave it unused | never transmit at power into an open port |
| **3. No antenna on a transmit port you do not want radiating at power-on** | every power-on emits a ~4 ms burst on both transmit ports, before any software runs |
| **4. Affirm the channel before raising it** | `./devkit tx-guard affirm 0` for TX1A, `1` for TX2A, after looking at that port |

```bash
# run from: the repo root
./devkit tx-guard affirm 0        # only after LOOKING at TX1A
./devkit tx-guard revoke both     # withdraw, and force maximum attenuation
```

Writing your own transmit code? Two more rules apply: set the attenuation
**after** the buffer starts and read it back, and mute **before** tearing the
buffer down. Why, with the measurements:
[transmitter safety reference](../transmitter-safety.md).

**Next:** use the radio: [capture IQ](../capturing-iq.md) or [SDR++](../sdrpp.md).
