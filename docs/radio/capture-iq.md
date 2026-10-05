---
icon: material/file-download-outline
description: A self-describing SigMF recording, with a check for lost samples.
---

# Capture IQ to a file

`tools/sigmf-capture.py` records IQ into a file that describes itself and says
whether samples were lost.

```bash
# run from: the repo root
tools/sigmf-capture.py record out --rate 3e6 --freq 900e6 --seconds 5 \
    --channels both --verify --annotate
```

That writes `out.sigmf-data` (the samples, untouched) and `out.sigmf-meta` (JSON
describing them, including a verdict on whether the capture is intact).
MATLAB reads the same files with `fishball.readSigMF`.

**You should see:** the `--verify` verdict in the output and in `out.sigmf-meta`.
This is a real run, both receivers at 3 MSPS, with the chip's built-in test
tone injected and without `--annotate`:

```text
# run from: the repo root - output of the command above, captured from the board
recording 15000000 instants (5.00 s) x 2 channels at 3.000000 MSPS = 24.0 MB/s, 120.0 MB total
+ iio_readdev -u ip:fishball.local -b 1048576 -s 15000000 cf-ad9361-lpc voltage0 voltage1 voltage2 voltage3 > out.bin
captured in 5.61 s wall (21.4 MB/s sustained)
verify RX1: continuous
verify RX2: continuous
out.sigmf-data  120.0 MB, 15000000 sample instants x 2 channels, 5.000 s
out.sigmf-meta  3.000000 MSPS, 900000000 Hz centre, RX1 + RX2
ok   integrity RX1: continuous
ok   integrity RX2: continuous
```

| Good to know | |
|---|---|
| **lost samples** | the capture still completes; only `--verify` tells you |
| **receive alone sustains** | about **40 MB/s**: 1 channel at 10 MSPS clean, 2 channels at 10 MSPS drop samples; 2 channels at 3 MSPS clean |
| **full scale** | **±2047** (12-bit): dividing by 32768 reads every level 24 dB low |
| **why not `iio_readdev`** | a bare capture has no sample rate, frequency or gain in it, and returns the byte count you asked for whether or not the hardware kept up |

??? question "How do I find my own rate limit?"
    ```bash
    # run from: the repo root
    for r in 3e6 5e6 10e6; do
      tools/sigmf-capture.py record /tmp/t --channels both --rate $r --seconds 2 --verify
    done
    ```

Reading a capture back, `--verify` and `--annotate` in detail:
[capturing IQ](../capturing-iq.md).

**Next:** [receive on both channels](receive-both-channels.md).
