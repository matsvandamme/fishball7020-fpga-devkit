# Four header pins that tick with the transmitted waveform

A worked example of getting something out of the FPGA that no software timing
can give you: **four digital output pins whose every edge is locked to a
specific transmitted RF sample**. No drift, no unknown latency, no "about a
millisecond later". You decide, sample by sample, what those pins do.

The trick costs nothing, because the bits it uses were being thrown away.

- [The four bits nobody uses](#the-four-bits-nobody-uses)
- [What "coherent" buys you](#what-coherent-buys-you)
- [What was built](#what-was-built)
- [Building it](#building-it) · [Turning it on](#turning-it-on)
- [Authoring the patterns](#authoring-the-patterns) · [Limits](#limits)

## The four bits nobody uses

Some vocabulary first, because three things here are easy to confuse.

- A **sample** is one number describing the signal at one instant. Transmitting
  means handing the radio a long list of them.
- The **DAC** (digital-to-analog converter) is the chip block that turns each
  sample into a voltage. Its **resolution** is how many bits of each sample it
  actually reads.
- **DMA** (direct memory access) is how those samples get from a buffer in RAM
  to the radio without the CPU copying each one.

Now the useful fact. You hand the AD9361 **16-bit** samples — that is what
libiio, GNU Radio and every tool here produce. **The DAC is only 12 bits.** It
takes the top 12 of your 16 and ignores the rest:

```
your sample:   b15 b14 b13 b12 b11 b10 b9 b8 b7 b6 b5 b4 │ b3 b2 b1 b0
               └──────────── the DAC converts these ────┘  └─ discarded ─┘
```

You can see it in ADI's own HDL — `axi_ad9361_tx_channel.v` does literally
`dac_data_out_int <= dma_data[15:4];`. The bottom four bits (the **low
nibble**, in the usual jargon for "bottom four bits of a byte-ish quantity")
reach the FPGA and stop there. They change nothing about the transmitted
signal, because nothing downstream reads them.

So they are free. This feature routes them to four pins on the expansion
header instead of dropping them.

## What "coherent" buys you

**Coherent** here means: a fixed, unchanging, known relationship in time
between two things. The pins carry bit `b0..b3` of the same sample whose bits
`b4..b15` are being converted to RF at that instant, and both are clocked by
the same sample clock inside the AD9361. If bit 0 flips high on sample 4000,
the edge on that pin and the RF from sample 4000 happen together, every time,
on every run, for as long as the radio streams.

Nothing in software can do this. A GPIO toggled from Linux is tens of
microseconds away from the RF and jitters run to run; even a kernel driver is
at the mercy of the DMA queue depth. Here the timing is structural.

The contributor who proposed this feature uses it for **multi-channel radar**
(1 transmitter, 8 receivers; or 2 and 8). The transmit buffer in DDR holds the
waveform, and the low nibble of each sample carries, on separate pins:

| Pin | Typical use |
|---|---|
| `sample_gpio[0]` | **master clock** — a steady square wave the receivers clock from |
| `sample_gpio[1]` | **frame clock** — one pulse per pulse-repetition interval |
| `sample_gpio[2]` | **sync / trigger** — "the chirp starts *now*" |
| `sample_gpio[3]` | spare: a coded marker, a range gate, a T/R switch line |

Separate receiver hardware then samples with a timebase that is welded to the
transmitted waveform, which is the whole game in radar and in MIMO
(multiple-input multiple-output: several antennas that must agree on phase).

None of those roles is wired into the FPGA. **A pin's role is whatever pattern
you put in that bit**, which is the next section.

## What was built

The FPGA does not *generate* anything. It **transports**: whatever you author
into the low nibble comes out on the pins, one nibble per sample.

```
   DDR buffer ──DMA──> tx_upack ──┬── [15:4] ──> interpolator ──> AD9361 DAC ──> RF
   (16-bit samples)               │
                                  └── [3:0] ───> tx_gpio_bitmap ──> 4 header pins
                                                       ▲
                                    up_dac_gpio_out[1] ┘  (the enable flag)
```

The new module, `tx_gpio_bitmap.v`, is about thirty lines:

- It captures the nibble **once per sample** — not once per clock. In the
  board's 2R2T mode a sample only arrives every second FPGA clock, and
  capturing on the clock would silently double the rate of every pattern you
  wrote. This is the one real bug in the design space, and the testbench exists
  mostly to catch it.
- A flag bit chooses who owns the pins: **0** = ordinary Linux GPIO, **1** =
  the sample nibble. So enabling the feature does not cost you four pins the
  rest of the time.

The tap is deliberately the **raw DMA sample**, upstream of the interpolation
filter. A FIR filter mixes neighbouring samples together; tapping after it
would give you filter output on the pins, not the bits you wrote.

| File | What it is |
|---|---|
| `hdl/projects/pluto/tx_gpio_bitmap.v` | the module |
| `hdl/projects/pluto/system_bd.tcl` | wiring: the nibble slice, the flag slice, EMIO GPIO widened 18 → 22 |
| `hdl/projects/pluto/system_top.v` | an `ad_iobuf` onto the four package pins |
| `hdl/projects/pluto/system_constr.xdc` | the pin assignments |
| `firmware/sim/tb_tx_gpio_bitmap.v` | the self-checking testbench |
| `firmware/patches/optional/0006-tx-sample-nibble-to-gpio.patch` | all of the above, **opt-in** |

### The pins

The board breaks out four free single-ended 3.3 V I/O on the expansion header,
`3V3_IO1..4`, unused by the stock design:

| Signal | Header net | FPGA ball |
|---|---|---|
| `sample_gpio[0]` | `3V3_IO1` | V11 |
| `sample_gpio[1]` | `3V3_IO2` | W9 |
| `sample_gpio[2]` | `3V3_IO3` | T9 |
| `sample_gpio[3]` | `3V3_IO4` | V7 |

> **Check these against your own board before you build.** They were read off
> the vendor schematic for this revision. A wrong `PACKAGE_PIN` in an `.xdc`
> is not a build error — it is a bitstream that drives the wrong pad.

## Building it

The patch is **not** applied by `setup.sh`. Opt in:

```bash
cd firmware
(cd src && git apply ../patches/optional/0006-tx-sample-nibble-to-gpio.patch)
rm -rf src/hdl/projects/pluto/pluto.xpr src/hdl/projects/pluto/pluto.*  # force a fresh Vivado project
./scripts/build_all.sh --hdl-only
./scripts/verify_output.sh
```

Before that, and any time you change the module, run the simulation — it takes
a second and needs only `iverilog`:

```bash
cd firmware
./sim/run_sim.sh            # both modules, checked against golden models
./sim/run_sim.sh --mutate   # and prove the tests can actually fail
```

Flash the result the usual way — **by copying to the SD card partition, never
over DFU**.

## Turning it on

The flag is **bit 1 of the DAC core's `GP_CONTROL` register**, at AXI offset
`0xBC`. (Bit 0 is already taken: it is the interpolator bypass.) There is no
IIO attribute for it yet, so reach it through the debugfs register window on
the board:

```sh
# on the board, as root
cd /sys/kernel/debug/iio
D=$(grep -l cf-ad9361-dds-core-lpc iio:device*/name | xargs dirname)

# read 0xBC, then write it back with bit 1 set
echo 0xBC        > $D/direct_reg_access ; cat $D/direct_reg_access
echo 0xBC 0x2    > $D/direct_reg_access     # enable the bit-map
echo 0xBC 0x0    > $D/direct_reg_access     # back to ordinary GPIO
```

With the flag clear the four pins are EMIO GPIO bits 18–21, i.e. ordinary
`/sys/class/gpio` lines, readable and writable from Linux as usual.

The pins only carry meaningful data while a **TX buffer is streaming**. This
firmware mutes the transmitter and powers down the TX synthesiser between
streams (see the transmitter-safety section of the README), so the nibble
holds its last value when nothing is flowing.

## Authoring the patterns

This is the part people underestimate, so in detail.

There is no "set pin 0 to clock mode" register. **The pattern is data.** You
build the transmit buffer yourself and put the bits in it.

The rule that matters: **OR the nibble in last**, after every scaling, gain or
format conversion step. Anything that multiplies your samples will overwrite
the bottom bits, because to that code they are noise.

```python
import numpy as np, adi

N  = 4096                      # buffer length in samples
n  = np.arange(N)
fs = 61.44e6

# 1. the RF you actually want to transmit, scaled to full-scale int16
sig = (0.5 * 2**15 * np.exp(2j * np.pi * 1e6 * n / fs))
i16 = sig.real.astype(np.int16)
q16 = sig.imag.astype(np.int16)

# 2. the digital side-channel, one bit per pin, as a function of sample index
bit0 = (n % 2  == 0)           # master clock: square wave at fs/2
bit1 = (n % 64 == 0)           # frame clock: one sample high every 64
bit2 = (n == 0)                # sync: a single pulse at the top of the buffer
bit3 = 0
nibble = (bit0 | bit1 << 1 | bit2 << 2 | bit3 << 3).astype(np.int16)

# 3. LAST: clear the low nibble of I and drop the pattern in
i16 = (i16 & ~0x000F) | nibble

sdr = adi.Pluto("ip:192.168.2.1")
sdr.tx_cyclic_buffer = True    # repeat the buffer forever -> a steady clock
sdr.tx([i16, q16])             # libiio hands these to the DAC bit for bit
```

Three things to notice:

- **`tx_cyclic_buffer = True` is how you get a continuous clock.** Author one
  period, let the DMA loop it. Make the buffer length an exact multiple of your
  pattern period or you get a glitch at the wrap.
- **Only channel 0's I samples carry the nibble** in this build. Q
  (`fifo_rd_data_1[3:0]`) is wired up in the same place if you want eight pins
  later; the module already takes an `NBITS` parameter.
- **Your RF loses 4 bits of resolution on I** — you are overwriting real, if
  tiny, signal bits. At full scale that is about a −72 dBFS noise floor
  addition on that path. Irrelevant for radar pulses, worth knowing for a
  sensitive modulation.

### What about GNU Radio?

The ordinary `complex float` flowgraph **will not work**. Every float sink
rescales on its way to int16, and rescaling destroys exactly the bits you care
about. If you want GNU Radio, you have to work at `short` level end to end and
use a sink that hands samples through unscaled. In practice it is easier to
render the buffer with numpy, as above, or to write a raw int16 file and
transmit it directly.

## Limits

- **Rate.** One nibble per sample, so the fastest a pin can toggle is half the
  sample rate: about 30 MHz at 61.44 MSPS. Every pattern is a division of the
  sample rate, and only of the sample rate — you cannot get an arbitrary
  frequency out of this.
- **I only, 4 pins**, unless you widen it.
- **3.3 V LVCMOS**, single-ended, no series termination on the board. Keep the
  wires short; if you need to drive something far away, buffer it.
- **Nothing validates your pattern.** The nibble is copied through untouched,
  which is the entire point and also means a typo goes straight to the pins.
