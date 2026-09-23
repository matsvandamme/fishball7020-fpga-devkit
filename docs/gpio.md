# GPIO: where the pins come from, and how to drive them

A Zynq has more than one kind of GPIO and they are not interchangeable. This
page covers which kinds this board actually has, which pins are free, and the
three ways to drive them — from your host, from Linux on the board, or from
your own logic in the fabric.

For the one feature that uses the fabric route, see
[the sample-locked GPIO outputs](tx-gpio-bitmap.md). This page is the general
picture that feature sits inside.

## The four kinds, and the two this board has

| Kind | What it is | On this board |
|---|---|---|
| **PS MIO** | 54 pins wired straight to the processor, fixed at boot | present, but all consumed by USB, Ethernet, SD, QSPI and the UART |
| **PS EMIO** | up to 64 GPIO lines the processor exports *into the fabric*, which routes them to real pins | **this is the one you use** — 22 wired |
| **AXI GPIO IP** | a soft peripheral in the fabric, memory-mapped over AXI | **not present** — the design has none |
| **Fabric logic** | your HDL drives a pin directly, no processor involved | possible, and used by one feature |

Because the usable pins are **EMIO**, they pass *through the fabric* on their
way out. That is why a bitstream change can alter what a GPIO line does, and
why fabric logic can take a pin away from Linux entirely. Most Zynq GPIO
tutorials assume an AXI GPIO block with its own register map — if an example
wants `/dev/uioN` or an AXI base address for GPIO, it is not describing this
board.

## The map: 118 lines, and the four you can have

```bash
# run on the board
gpiodetect
#  gpiochip0 [zynq_gpio] (118 lines)
```

| Lines | What | Usable? |
|---|---|---|
| `0 – 53` | PS MIO | no — board peripherals |
| `54 – 67` | EMIO 0–13, a 14-bit bidirectional bus | yes, if your carrier exposes them |
| `68 – 70` | EMIO 14–16; 15 and 16 drive the AD9361's `enable` and `txnrx` | **no — leave alone** |
| `71` | EMIO 17 | unused |
| **`72 – 75`** | **EMIO 18–21 → JP5 pins 7, 9, 11, 13** | **yes — these are the free ones** |
| `76 – 117` | EMIO 22–63, not wired in this design | no |

Four of the 118 lines carry names, and they are the four free ones:

```bash
# run on the board
gpioinfo | grep -v unnamed
#  line  72: "sample_gpio0" unused input active-high
#  line  73: "sample_gpio1" unused input active-high
#  line  74: "sample_gpio2" unused input active-high
#  line  75: "sample_gpio3" unused input active-high
```

| Name | Silkscreen | JP5 pin | FPGA ball | libgpiod | sysfs number |
|---|---|---|---|---|---|
| `sample_gpio0` | `3V3_IO1` | 7 | V10 | `gpiochip0 72` | 978 |
| `sample_gpio1` | `3V3_IO2` | 9 | U9 | `gpiochip0 73` | 979 |
| `sample_gpio2` | `3V3_IO3` | 11 | U10 | `gpiochip0 74` | 980 |
| `sample_gpio3` | `3V3_IO4` | 13 | T9 | `gpiochip0 75` | 981 |

Bank 13, **3.3 V**, pulled down. **Ground a probe on JP5 pin 2 or 20.**

## Route one — from your host, over the network

**Anything the IIO driver exposes** is reachable without touching the board:

```bash
# run on your HOST, from anywhere (needs libiio-utils)
iio_attr -u ip:192.168.2.1 -d cf-ad9361-dds-core-lpc                    # list device attributes
iio_attr -u ip:192.168.2.1 -d cf-ad9361-dds-core-lpc tx_sample_gpio_en   # read
iio_attr -u ip:192.168.2.1 -d cf-ad9361-dds-core-lpc tx_sample_gpio_en 1 # write
```

> **Use `-d`, not `-c`.** `-d` is a *device* attribute; `-c` is a *channel*
> attribute. Get it wrong and you are told the channel does not exist, which
> reads like the feature is missing:
>
> ```
> iio_attr: Error : could not find channel (tx_sample_gpio_en)
> ```

**The GPIO lines themselves** have no libiio equivalent, so run the board's own
tools over ssh:

```bash
# run on your HOST, from anywhere
ssh root@192.168.2.1 'gpiofind sample_gpio0'            # -> gpiochip0 72
ssh root@192.168.2.1 'gpioget $(gpiofind sample_gpio0)'
ssh root@192.168.2.1 'gpioset $(gpiofind sample_gpio0)=1'
```

Single quotes matter: they keep `$(...)` for the board to evaluate. Double
quotes expand it on your laptop, where `gpiofind` is not installed.

## Route two — from Linux on the board

```bash
# run on the board
gpiofind sample_gpio0                 # resolve by NAME, never hard-code the number
gpioget  $(gpiofind sample_gpio0)     # read
gpioset  $(gpiofind sample_gpio0)=1   # drive high
```

> **`gpioset` lets go the instant it exits.** The kernel releases a line when
> the process holding it dies, and `gpioset` returns immediately. Measured:
>
> ```bash
> # run on the board
> $ gpioset $(gpiofind sample_gpio0)=1
> $ gpioget $(gpiofind sample_gpio0)
> 0      # not 1 — released, and the pull-down took over
> ```
>
> To hold a level use `gpioset --mode=wait ...` and leave it running, or sysfs.

The legacy sysfs interface persists after the shell exits:

```bash
# run on the board
BASE=$(cat /sys/class/gpio/gpiochip*/base | head -1)   # 906 on this firmware
N=$((BASE + 54 + 18))                                  # 978 = sample_gpio0
                                                       # 54 MIO first, then EMIO 18
echo $N  > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio$N/direction
echo 1   > /sys/class/gpio/gpio$N/value
echo $N  > /sys/class/gpio/unexport                    # release when done
```

> **The two interfaces will not share a line.** While one is exported through
> sysfs, libgpiod cannot have it: `gpioget: error reading GPIO values: Device
> or resource busy`. Unexport first.

## Route three — from the fabric

Every Zynq EMIO pin is three buses, and your bitstream sits in the middle of
them:

| Bus | Direction | Meaning |
|---|---|---|
| `GPIO_O` | PS → fabric | the value Linux wants to drive |
| `GPIO_T` | PS → fabric | tristate: 1 = input, 0 = drive |
| `GPIO_I` | fabric → PS | what Linux reads back |

To take a pin over from your own logic, put a multiplexer between those buses
and the pad and select with a register bit. To hand it back, select the EMIO
side again — and route the pad's real level into `GPIO_I`, or reads from Linux
become meaningless.

[`tx_gpio_bitmap.v`](tx-gpio-bitmap.md) is a worked example already in the
firmware: it can take the four header pins and drive them with the low nibble
of every transmitted sample. One bit selects it, and it resets to 0, so the
pins are ordinary GPIO at power-on.

```bash
# run on your HOST, from anywhere
iio_attr -u ip:192.168.2.1 -d cf-ad9361-dds-core-lpc tx_sample_gpio_en 1  # fabric owns the pins
iio_attr -u ip:192.168.2.1 -d cf-ad9361-dds-core-lpc tx_sample_gpio_en 0  # Linux owns them again
```

## How these pins were verified

Not by reasoning about the HDL — with a **Saleae Logic 8** on JP5 pins 7, 9, 11
and 13, transmitter muted, streaming a known counter so every sample has a value
the capture can be checked against.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="img/saleae-timing-dark.svg">
  <img src="img/saleae-timing-light.svg" alt="Logic-analyser capture of the four sample-locked GPIO pins carrying a 4-bit counter at 5 MSPS, with the decoded value D, E, F, 0, 1 and so on under each 200 ns sample" width="760">
</picture>

Each column is one transmitted sample, 200 ns apart at 5 MSPS, and the decoded
nibble underneath counts D, E, F, 0, 1 — the pins are carrying the data, in
order, with nothing missing.

| What was checked | Result |
|---|---|
| Every sample present at full rate — pin 0 toggling at 30.72 MHz from 61.44 MSPS | **every sample present** |
| The four pins switch together | **within 1.5 ns**, same-direction edges |
| Both transmit channels on, the every-other-clock case | **0 errors** at 5 MSPS and at 61.44 MSPS |

The 1.5 ns figure *includes the analyser's own channel skew*, so the real
figure is at least that good. The analyser sampled at 50 MS/s — 20 ns
apart — which is coarser than the skew being reported, so that number comes
from the analyser's timing measurement rather than from counting samples.

The raw bench data is in [`img/data/saleae-bench.json`](img/data/saleae-bench.json)
and the figures are redrawn from it by
[`img/make_saleae_figures.py`](img/make_saleae_figures.py), so the pictures and
the numbers cannot drift apart.

> **One thing the analyser cannot tell you.** It measures the *pins*, not the
> RF. The pins lead the transmitted RF by a roughly constant offset of about a
> microsecond, and that offset is designed-for rather than measured — so never
> treat a pin edge and its RF as simultaneous.

## Four ways to fool yourself

**Reading a pin back does not tell you what is on the pad.** With
`direction=out` the sysfs `value` file returns *what you wrote*. A broken track
reads back perfectly.

**A pin's level never says who is driving it.** When the fabric releases these
pins the pull-down holds them low — which is also what the fabric drives for a
zero. Test by driving **two different** values and asking whether the pin
follows.

**Numbers move, names do not.** `iio:device2`, GPIO base 906, line 978: all
true of this firmware and not guaranteed of the next. Resolve IIO devices by
their `name` file and GPIO lines with `gpiofind`.

**EMIO is not AXI GPIO.** See the first section — the difference decides
whether any tutorial you find applies here.
