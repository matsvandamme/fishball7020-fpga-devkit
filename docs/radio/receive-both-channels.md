---
icon: material/call-split
description: RX1 and RX2, sample-aligned, in one recording.
---

# Receive on both channels

```bash
# run from: the repo root
tools/sigmf-capture.py record out --channels both --rate 3e6 --seconds 5 --verify
```

One file, `core:num_channels: 2`, interleaved **RX1-I, RX1-Q, RX2-I, RX2-Q** per
sample instant. `--split` writes two single-channel recordings instead.

| Good to know | |
|---|---|
| **rate** | 2 channels at 3 MSPS are clean; at 10 MSPS they drop samples |
| **with the FPGA ÷8 decimator** | both channels are filtered (patch `0021`, applied by every build): at least 69.7 dB of alias suppression on channel 1 |
| **IIO channel names** | `cf-ad9361-lpc` input voltage0/1 = RX1 I/Q, voltage2/3 = RX2 I/Q; gain, rate and bandwidth live on `ad9361-phy` |

!!! warning "Coherent, but not calibrated"
    Both receivers share one `RX_LO`, so their phase relationship is stable. The
    analogue phase offset through baluns and traces is real, tens of degrees and
    frequency-dependent: measure it with a splitter and matched cables before
    trusting any angle.

??? question "Without the capture tool?"
    ```bash
    # run from: your host
    iio_attr -u ip:192.168.2.1 -i -c cf-ad9361-lpc voltage0 sampling_frequency 7680000

    # channel 0 is voltage0/voltage1, channel 1 is voltage2/voltage3
    iio_readdev -u ip:192.168.2.1 -b 131072 -s 262144 cf-ad9361-lpc \
      voltage0 voltage1 voltage2 voltage3 > both.bin
    ```

More: [capturing IQ](../capturing-iq.md#both-receivers-at-once) ·
[two receivers that both survive decimation](../both-receive-channels.md).
