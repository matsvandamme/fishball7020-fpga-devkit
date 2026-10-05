---
icon: material/pin-outline
description: Four free 3.3 V pins on JP5, where ground is, and what not to touch.
---

# Wire something to the JP5 header

Four pins on `JP5` are free for you: **7, 9, 11 and 13**, 3.3 V, pulled down.
**Ground is pins 2 and 20.**

![JP5 pinout: a 2x10 header, with pins 7, 9, 11, 13 carrying sample_gpio[0..3] and grounds on pins 2 and 20](../img/jp5-pinout-light.svg#only-light)
![JP5 pinout: a 2x10 header, with pins 7, 9, 11, 13 carrying sample_gpio[0..3] and grounds on pins 2 and 20](../img/jp5-pinout-dark.svg#only-dark)

| JP5 pin | Silkscreen | Signal | FPGA ball | Linux line |
|---|---|---|---|---|
| 7 | `3V3_IO1` | `sample_gpio[0]` | V10 | `gpiochip0 72` |
| 9 | `3V3_IO2` | `sample_gpio[1]` | U9 | `gpiochip0 73` |
| 11 | `3V3_IO3` | `sample_gpio[2]` | U10 | `gpiochip0 74` |
| 13 | `3V3_IO4` | `sample_gpio[3]` | T9 | `gpiochip0 75` |

| Before you connect | |
|---|---|
| **Find pin 1 on the board** | square pad, silkscreen dot or "1": neither the schematic nor the photos show which end it is. Odd pins run down one column, even pins down the other |
| **Pins 1, 3, 5 are power rails** | VCC1V8, VCC3V3 and VCC5V, not signals |
| **The rest of the header** | four 1.8 V differential pairs, `XTAL_VTC` (pin 15), `PTT` (pin 17) |
| **Levels** | `LVCMOS33`, no series termination: keep wires short, buffer anything long |
| **Fast signals** | give each its own ground (pin 2 or 20): a pin toggling at 15–30 MHz put 20 ns glitches on its neighbour through unshielded logic-analyser leads |

!!! warning "Any other header pin needs the schematic first"
    Driving a pin that is an input or tied elsewhere can damage the board.
    And **do not guess FPGA balls**: V11, W9 and V7 are adjacent bank-13 balls the
    schematic marks no connect, and Vivado accepts a wrong `PACKAGE_PIN` with
    perfect timing.

!!! warning "Pin 15 is `XTAL_VTC`, the 40 MHz oscillator's pin 1"
    Measure it before driving it: as an enable, a jumper to ground there stops
    the radio's clock and survives a reboot ([external reference](external-reference-clock.md)).

**Next:** [toggle a GPIO pin from Linux](toggle-a-gpio.md), or
[make the pins follow the transmit samples](pins-follow-transmit.md).
