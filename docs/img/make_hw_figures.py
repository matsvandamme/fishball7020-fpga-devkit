#!/usr/bin/env python3
"""Draw the Hardware and I/O figures, in the same style as the Getting started
ones (the helpers come from make_start_figures.py).

    # run from: the repo root
    python3 docs/img/make_hw_figures.py        # stdlib only; the photo figure needs ImageMagick

Writes into docs/img/:

    hw-refclock-{light,dark}.svg    the three R107/R109 configurations of the reference clock
    hw-pin-owner-{light,dark}.svg   who drives the four free JP5 pins
    hw-user-led-{light,dark}.svg    what drives the USER LED
    hw-sma-ports.svg                the case's antenna end, labelled (from plutosky-r1-antennas.jpg)

Every name and number drawn here comes from docs/hardware.md, docs/gpio.md,
docs/tx-gpio-bitmap.md and docs/user-led.md.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_start_figures import Fig, both, photo_figure  # noqa: E402


# --- the reference clock: three configurations ---------------------------------

def refclock(t):
    f = Fig(860, 430, t)
    rows = (
        ("As shipped: R107 fitted, R109 empty", True, False,
         "the radio runs from Y3; EXT_CLK is connected to nothing", "muted"),
        ("Reference in: R107 empty, R109 fitted", False, True,
         "the radio runs from whatever is on EXT_CLK: at most 1.3 V p-p, AC-coupled", "ok"),
        ("Both fitted: reference out only", True, True,
         "Y3's 40 MHz appears on EXT_CLK. Never connect a source here", "danger"),
    )
    for i, (title, r107, r109, verdict, colour) in enumerate(rows):
        y = 14 + i * 142
        f.text(20, y + 14, title, 14, "ink", 600, "start")
        by = y + 30
        f.box(20, by, 130, 56, "Y3", "40 MHz oscillator")
        f.box(365, by, 130, 56, "AD9361", "XTALN, ball M12", fill="accent_soft", stroke="accent")
        f.box(710, by, 130, 56, "EXT_CLK", "RF1, U.FL")
        for x1, x2, name, fitted in ((150, 365, "R107", r107), (495, 710, "R109", r109)):
            mid = (x1 + x2) / 2
            if fitted:
                f.line(x1, by + 28, mid - 44, by + 28, "ink", 1.8)
                f.line(mid + 44, by + 28, x2, by + 28, "ink", 1.8)
                f.raw(f'<rect x="{mid - 44}" y="{by + 16}" width="88" height="24" rx="4" '
                      f'fill="{t["surface"]}" stroke="{t["ink"]}" stroke-width="1.8"/>')
                f.text(mid, by + 33, f"{name} 33 Ω", 12, "ink", 600)
            else:
                f.line(x1, by + 28, mid - 44, by + 28, "line", 1.8)
                f.line(mid + 44, by + 28, x2, by + 28, "line", 1.8)
                f.raw(f'<rect x="{mid - 44}" y="{by + 16}" width="88" height="24" rx="4" fill="none" '
                      f'stroke="{t["muted"]}" stroke-width="1.5" stroke-dasharray="4 3"/>')
                f.text(mid, by + 33, f"{name} empty", 12, "muted")
        f.text(20, by + 78, verdict, 12.5, colour, 500, "start")
    return f


# --- who drives the four free pins ---------------------------------------------

def pin_owner(t):
    f = Fig(860, 230, t)
    f.box(20, 14, 240, 74, "Linux", ("EMIO GPIO 18–21", "gpiochip0 lines 72–75"))
    f.box(20, 148, 240, 62, "The transmit samples", ("low four bits of channel 0's I",))
    f.box(350, 78, 200, 74, "tx_sample_gpio_en", ("0: Linux drives the pins", "1: the samples do"),
          fill="accent_soft", stroke="accent")
    f.arrow(260, 51, 348, 96, colour="muted")
    f.arrow(260, 179, 348, 134, colour="muted")
    f.text(300, 60, "0", 13, "ink", 600)
    f.text(300, 176, "1", 13, "ink", 600)
    f.arrow(550, 115, 638, 115, colour="accent")
    f.box(640, 78, 200, 74, "JP5 pins 7, 9, 11, 13", ("3.3 V, pulled down", "0 at power-on: Linux"),
          fill="ok_soft", stroke="ok")
    return f


# --- the USER LED --------------------------------------------------------------

def user_led(t):
    f = Fig(860, 210, t)
    f.box(20, 20, 250, 62, "A TX attenuation change", ("ad9361_set_tx_atten()",), mono_sub=True)
    f.arrow(270, 51, 328, 51, colour="accent")
    f.box(330, 14, 200, 74, "tx-active trigger", ("lit: a chain is out of mute", "dark: both at −89.75 dB"),
          fill="accent_soft", stroke="accent")
    f.arrow(530, 51, 618, 51, colour="accent")
    f.box(620, 20, 220, 62, "USER LED", ("led0:green, PS MIO pin 0",), fill="ok_soft", stroke="ok")
    f.box(330, 122, 200, 74, "Your own setting", ("trigger and brightness", "in /sys/class/leds"))
    f.arrow(530, 159, 700, 84, colour="muted")
    f.box(20, 122, 250, 74, "Your HDL", ("cannot drive it: MIO pins are", "not routed into the fabric"),
          fill="danger_soft", stroke="danger")
    return f


def main():
    both("hw-refclock", "The three configurations of R107 and R109 around the reference clock", refclock)
    both("hw-pin-owner", "Who drives the four free JP5 pins", pin_owner)
    both("hw-user-led", "What drives the USER LED", user_led)
    # The case from the antenna end: plutosky-r1-antennas.jpg is 1337x1086.
    photo_figure("hw-sma-ports", "The case's antenna end", "plutosky-r1-antennas.jpg", "710x590+140+470", (426, 354), (
        ("Which is which?", "read the board's silkscreen, lid off", "left", 120, (84, 150)),
        ("4 × SMA", "TX1A, RX1A, TX2A, RX2A", "left", 230, (150, 196)),
        ("Case labels", "in the wrong order on some units", "right", 300, (262, 250)),
    ))


if __name__ == "__main__":
    main()
