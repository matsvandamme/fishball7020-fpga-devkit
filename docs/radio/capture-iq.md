---
icon: material/file-download-outline
description: A self-describing SigMF recording, with a check for lost samples.
---

# Capture IQ to a file

```bash
# run from: the repo root
tools/sigmf-capture.py record out --rate 3e6 --freq 900e6 --seconds 5 \
    --channels both --verify --annotate
```

That writes `out.sigmf-data` (the samples, untouched) and `out.sigmf-meta` (JSON
describing them, including a verdict on whether the capture is intact).
MATLAB reads the same files with `fishball.readSigMF`.

**You should see:** the `--verify` verdict in the output and in `out.sigmf-meta`.

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
