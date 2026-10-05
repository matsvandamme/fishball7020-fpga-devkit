---
icon: material/check-circle-outline
description: Lock bits, a frequency measurement, and xo_correction.
---

# Check which reference the radio uses

**The settings alone do not tell you:** a board whose reference was not what its
device tree said still reported every PLL locked. Check the locks, then the
frequency.

```bash
# run from: the board
D=/sys/kernel/debug/iio/iio:device0
for r in 0x05E 0x247 0x287; do echo $r > $D/direct_reg_access; echo "$r $(cat $D/direct_reg_access)"; done
#   0x05E 0x81   bit 7: BBPLL locked
#   0x247 0x2    bit 1: RX synthesizer locked
#   0x287 0x2    bit 1: TX synthesizer locked
```

**The frequency itself:** stream at 20 MS/s on the board (`iio_readdev -u local:`)
and time the samples against `CLOCK_MONOTONIC_RAW`, the Zynq's own 33.333 MHz
crystal. Over 120 s this resolves a few ppm: enough to tell a 40 MHz
reference from a 10 MHz one, not to discipline one.

!!! warning "Use the RAW clock"
    Right after boot, network time slews `CLOCK_MONOTONIC`: a stock board read
    −93 ppm instead of +2.

**You should see:** all three lock bits set, and the stock board measuring
40.0001 MHz.

## Correcting the frequency, without soldering

`xo_correction` tells the driver what `Y3` really runs at; the PLLs are then
programmed from it. Accuracy, not stability.

```bash
# run from: the board
cat /sys/bus/iio/devices/iio:device0/xo_correction_available
#   [39992000 1 40008000]     min, step, max  -> 1 Hz steps, about 0.025 ppm
cat /sys/bus/iio/devices/iio:device0/xo_correction
#   40000000
```

Measure the board with `./devkit clock measure`; SDR++'s **Freq. corr. (ppm)**
takes the result ([SDR++](../sdrpp.md)).

**Reference:** [which reference is the radio really using](../hardware.md#which-reference-is-the-radio-really-using).
