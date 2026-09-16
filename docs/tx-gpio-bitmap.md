# Four header pins that tick with the transmitted waveform

A worked example of getting something out of the FPGA that no software timing
can give you: **four digital output pins whose every edge is locked to a
specific transmitted RF sample**. Not "about a millisecond later, give or take"
— a fixed offset you measure once and then trust. You decide, sample by
sample, what those pins do.

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
between two things. It does **not** mean simultaneous, and the difference
matters enough to spell out.

The pins carry bits `b0..b3` of a sample; bits `b4..b15` of that same sample
become RF. But the pin is driven one FPGA clock after the sample leaves the
DMA unpacker, while the RF still has to cross the fabric interpolation filter,
the AD9361's own digital filters, the DAC and the analog transmit chain. **So
the pins lead the RF**, by something on the order of a microsecond depending
on how the filters are configured.

What makes that useful is that the lead is *constant*. It does not drift, it
does not vary sample to sample, and it comes out the same on every run as long
as you do not change the sample rate or the filter configuration. Measure it
once — with a scope on a pin and a second one on the RF, or by looping the
transmitter back into the receiver and cross-correlating — and subtract it
forever after.

Nothing in software gets you even that. A GPIO toggled from Linux is tens of
microseconds away from the RF and the delay changes from run to run and from
pulse to pulse; even a kernel driver is at the mercy of the DMA queue depth.
Here the offset is structural, so it is a calibration constant instead of a
source of error.

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

The new module, `tx_gpio_bitmap.v`, is thirty lines of logic under a much
longer comment. Three things in it are deliberate:

- It captures the nibble **once per sample** — not once per clock. In the
  board's 2R2T mode a sample only arrives every second FPGA clock, and
  capturing on the clock would silently double the rate of every pattern you
  wrote. This is the one real bug in the design space, and the testbench exists
  mostly to catch it.
- It captures on the strobe that says *the new word is here now*
  (`fifo_rd_valid | fifo_rd_underflow`), not the one that says *a word has been
  requested* (`fifo_rd_en`). The unpacker registers its output, so those are
  one clock apart, and getting it wrong puts the previous sample on the pins
  forever — coherent, repeatable, and one sample wrong. Including the underflow
  strobe means that when the DMA starves and the DAC is fed zeros, the pins
  carry those zeros too: the promise "the pins are the low nibble of what the
  DAC got" has no exceptions.
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

It costs a handful of LUTs and four flip-flops per pin. No DSP slices, no
block RAM, no new clock.

### The pins

The board breaks out four free single-ended 3.3 V I/O on connector **JP5**,
`3V3_IO1..4`, unused by the stock design. Read off the vendor schematic,
sheet 5 (`U1G`, "PL端BANK13"):

| Signal | Header net | JP5 pin | FPGA ball | FPGA pin name |
|---|---|---|---|---|
| `sample_gpio[0]` | `3V3_IO1` | 7 | **V10** | IO_L20P |
| `sample_gpio[1]` | `3V3_IO2` | 9 | **U9** | IO_L16P |
| `sample_gpio[2]` | `3V3_IO3` | 11 | **U10** | IO_L12N |
| `sample_gpio[3]` | `3V3_IO4` | 13 | **T9** | IO_L12P |

The bit number matches the header label, so `sample_gpio[0]` is the pin
silkscreened `3V3_IO1`. JP5 also carries VCC1V8, VCC3V3 and VCC5V (pins 1, 3,
5) and the four 1.8 V differential pairs, which are where an I+Q widening
would go.

`LVCMOS33` is the right standard: sheet 1 ties `VCCO_13_1..4` (balls T8, U11,
W7, Y10) to **VCC3V3**. Note that this differs from the rest of the design,
which declares `LVCMOS25` and `LVDS_25` on banks 34 and 35 that the same sheet
supplies from **VCC1V8** — an inconsistency inherited from ADI's stock Pluto
constraints, left alone here because the board demonstrably works.

> **Do not guess these balls.** V11, W9 and V7 are adjacent bank-13 balls and
> look like plausible candidates — an earlier draft of this feature used them.
> The schematic marks all three "no connect". Vivado accepted them without
> complaint and produced a clean, timing-met bitstream that drove three pads
> wired to nothing, because a wrong `PACKAGE_PIN` is not a build error.

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
`/sys/class/gpio` lines, readable and writable from Linux as usual. On Zynq
the EMIO lines follow the 54 MIO ones, so these are GPIO numbers
`base + 54 + 18` … `base + 54 + 21`; read `base` from
`/sys/class/gpio/gpiochip*/base`.

**Changing the interpolation factor does not clobber the flag.** The driver
read-modify-writes only bit 0 of this register (`cf_axi_interpolation_set`),
so a `sampling_frequency` change that engages or bypasses the FPGA filter
leaves bit 1 alone.

### Checking it works without a scope

The pin inputs are wired back to EMIO GPIO bits 18–21 **unconditionally** —
including while the fabric is driving them. So Linux can read the actual pin
level even in bit-map mode:

```sh
G=$(( $(cat /sys/class/gpio/gpiochip*/base | head -1) + 54 + 18 ))   # pin 0
echo $G > /sys/class/gpio/export
echo in > /sys/class/gpio/gpio$G/direction
cat /sys/class/gpio/gpio$G/value
```

Reading through sysfs takes microseconds, so on a fast clock pattern you will
just see 0 and 1 at random — which is itself informative, since a dead pin
reads the same value every time. For a definite answer, transmit a cyclic
buffer that holds one bit **high for the whole buffer**, confirm the pin reads
1, then transmit one that holds it low and confirm it reads 0. That exercises
the entire path — your authoring code, the DMA, the tap, the mux, the pad —
with nothing but `cat`.

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
  sample rate — about 30 MHz at 61.44 MSPS. "Sample rate" here means the one
  libiio reports, the rate of the buffer *you* write. When the FPGA
  interpolator is engaged for low sample rates, that is one eighth of the rate
  the AD9361 runs internally, and the pins follow your buffer, not the chip.
  Every pattern is a whole-number division of that rate — you cannot get an
  arbitrary frequency out of this.
- **Skew.** The four outputs are not timing-constrained, so the spread between
  them is whatever the router produced: a few hundred picoseconds, unverified.
  Nothing next to a 16 ns sample period, but do not build a picosecond-accurate
  instrument on it without constraining and checking.
- **I only, 4 pins**, unless you widen it.
- **3.3 V LVCMOS**, single-ended, no series termination on the board. Keep the
  wires short; if you need to drive something far away, buffer it.
- **Nothing validates your pattern.** The nibble is copied through untouched,
  which is the entire point and also means a typo goes straight to the pins.
