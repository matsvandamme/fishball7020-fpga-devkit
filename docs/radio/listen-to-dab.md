---
icon: material/radio
description: The patched SDR++ carries a DAB+ decoder - pick a block, wait for SYNC LOCKED, click a station.
---

# Listen to DAB+ radio

DAB+ is digital radio in Band III (174–240 MHz): one 1.536 MHz-wide block, a
*multiplex*, carries a dozen or so stations at once. The
[patched SDR++](install-patched-sdrpp.md) carries a DAB+ decoder, F4JTV's
`dab_decoder` module, which uses welle.io's receiver.

1. Point the board at a Band III antenna, on RX2 or whichever input is
   cabled, and set a sample rate of **2.4 MS/s or more**. The decoder takes
   its own 2.048 MS/s slice from whatever SDR++ receives.
2. **Module Manager**: add an instance of `dab_decoder`, if there is not one
   already.
3. In the DAB Decoder panel, pick a block from the dropdown (`8C` is
   199.360 MHz). This tunes the radio.
4. Wait for **SYNC LOCKED**. The multiplex name and its stations appear within
   a few seconds; click a station to hear it.

**You should see:** **SYNC LOCKED**, then the multiplex name and its stations.
In Paris, block 8C carries "Métropolitain 2": France Inter, FIP, RMC and ten
more.

!!! tip "A good antenna matters more than gain"
    A block at 25 dB above the noise decoded cleanly.

The decoder works the same on libiio and on the
[Fast TCP transport](stream-20-msps.md). More: [SDR++](../sdrpp.md#dab-radio).
