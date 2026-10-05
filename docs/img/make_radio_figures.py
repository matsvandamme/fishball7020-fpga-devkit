#!/usr/bin/env python3
"""Draw the "Using the radio" diagrams, each in a light and a dark variant.

    # run from: the repo root
    python3 docs/img/make_radio_figures.py        # stdlib only

Writes docs/img/radio-<name>-{light,dark}.svg, in the same style as the
Getting started figures (it borrows make_start_figures.py's drawing helpers):

    radio-code-places   where your code can run, as three questions
    radio-libiio        a script on the PC reaching the radio through iiod
    radio-verify        what `--verify` does to a capture
    radio-fasttcp       SDR++'s Fast TCP transport: samples and control
    radio-decimator     the FPGA divide-by-8 decimator in the receive path
    radio-adsb          the ADS-B decoder's four parts
    radio-maia          Maia SDR: the FFT on the FPGA
    radio-channel1      the stock receive path, where channel 1 skips the filter
    radio-cyclic        a cyclic buffer: upload once, replayed by the board
    radio-burst         a one-shot burst on a trigger
    radio-chirp         chirp-view's signal path
    radio-leak          the cable loop and the board's internal leak
    radio-limits        what limits streaming, in order
    radio-copies        iiod's two copies against zc-stream's one
    radio-twocore       zc-stream's two-core 8-bit pipeline

Pages show one as `![alt](img/radio-x-light.svg#only-light)` plus the
`-dark.svg#only-dark` twin. Every name and number drawn here comes from the
page that shows the figure.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_start_figures import Fig, both  # noqa: E402


def chain(stages, width=900, box_h=64, gap=30, top=14, labels=(), highlight=()):
    """A row of boxes joined by arrows. stages: (title, sub) with sub a string
    or a tuple of lines; labels: {index: text} above the arrow leaving a box;
    highlight: indexes drawn in the accent colour."""
    labels = dict(labels)

    def draw(t):
        n = len(stages)
        bw = (width - 40 - gap * (n - 1)) / n
        f = Fig(width, top + box_h + 16, t)
        for i, (name, sub) in enumerate(stages):
            x = 20 + i * (bw + gap)
            hl = i in highlight
            f.box(x, top, bw, box_h, name, sub, fill="accent_soft" if hl else "surface",
                  stroke="accent" if hl else "line")
            if i < n - 1:
                f.arrow(x + bw + 2, top + box_h / 2, x + bw + gap - 2, top + box_h / 2, colour="accent")
                if i in labels:
                    f.text(x + bw + gap / 2, top + box_h / 2 - 9, labels[i], 11.5, "muted")
        return f
    return draw


def code_places(t):
    f = Fig(820, 300, t)
    qs = (("Can my PC keep up?", "streaming plateaus near 44 MB/s", "1. On your PC"),
          ("Must it run with no PC,", "or is the data too big to ship?", "2. On the board"),
          ("A new sysfs file, or act", "between samples?", "3. In the kernel"))
    for i, (a, b, place) in enumerate(qs):
        y = 16 + i * 92
        f.box(20, y, 330, 64, a, b, fill="accent_soft", stroke="accent")
        f.arrow(350, y + 32, 478, y + 32, "yes", "ok")
        f.box(480, y, 320, 64, place, ())
        if i < 2:
            f.arrow(185, y + 64, 185, y + 90, colour="muted")
            f.text(205, y + 82, "no", 12, "muted", anchor="start")
    f.arrow(185, 264, 185, 284, colour="muted")
    f.text(205, 280, "no", 12, "muted", anchor="start")
    return f


def code_places_full(t):
    f = code_places(t)
    f.h = 360
    f.box(20, 286, 330, 60, "4. In the FPGA", "high input rate, small output")
    return f


def libiio(t):
    f = Fig(820, 150, t)
    f.box(20, 36, 200, 78, "Your PC", ("a Python script", "pyadi-iio, in a venv"))
    f.arrow(220, 75, 338, 75, "libiio", "accent")
    f.text(279, 96, "Ethernet or USB", 11.5, "muted")
    f.box(340, 16, 460, 118, "", ())
    f.text(570, 38, "The board", 14, "ink", 600)
    f.box(360, 52, 200, 64, "iiod", "port 30431", fill="accent_soft", stroke="accent")
    f.arrow(560, 84, 598, 84, colour="accent")
    f.box(600, 52, 180, 64, "AD9361", "the radio")
    return f


def fasttcp(t):
    f = Fig(820, 250, t)
    f.box(20, 20, 470, 210, "", ())
    f.text(255, 44, "The board", 14, "ink", 600)
    f.box(40, 96, 150, 64, "AD9361", "the radio")
    f.box(260, 58, 210, 64, "zc-stream", ("ports 5555 (RX1), 5556 (RX2)",), fill="accent_soft", stroke="accent")
    f.box(260, 150, 210, 64, "iiod", "port 30431")
    f.arrow(190, 116, 258, 94, colour="accent")
    f.arrow(260, 182, 192, 142, colour="muted")
    f.box(620, 96, 180, 64, "SDR++", "on your PC")
    f.arrow(470, 90, 618, 116, colour="accent")
    f.text(548, 88, "8-bit samples", 12, "accent")
    f.arrow(620, 142, 472, 182, colour="muted")
    f.text(556, 186, "tuning, gain,", 12, "muted")
    f.text(556, 202, "rate, RX port", 12, "muted")
    return f


def channel1(t):
    f = Fig(820, 250, t)
    f.box(20, 30, 200, 64, "Channel 0", "adc_*_i0/q0")
    f.box(20, 150, 200, 64, "Channel 1", "adc_*_i1/q1")
    f.box(310, 30, 220, 64, "rx_fir_decimator", "filter, ÷8", fill="accent_soft", stroke="accent")
    f.box(640, 90, 160, 64, "cpack", ())
    f.arrow(220, 62, 308, 62, colour="accent")
    f.arrow(530, 54, 660, 88, colour="accent")
    f.text(608, 50, "data, valid_out_0", 12, "accent")
    f.arrow(220, 182, 652, 150, colour="danger")
    f.text(430, 196, "stock: straight through, no filter", 12, "danger")
    f.arrow(530, 80, 638, 118, colour="muted", dash=True)
    f.text(470, 122, "fifo_wr_en = valid_out_0:", 11.5, "muted")
    f.text(470, 138, "strobes once per 8 samples", 11.5, "muted")
    return f


def leak(t):
    f = Fig(720, 190, t)
    f.box(20, 60, 150, 64, "TX port", ())
    f.box(550, 60, 150, 64, "RX port", ())
    f.arrow(170, 78, 548, 78, colour="accent")
    f.text(360, 68, "cable + pad", 12.5, "accent")
    f.raw(f'<path d="M 170 106 C 290 176, 430 176, 548 106" fill="none" stroke="{t["danger"]}" '
          f'stroke-width="1.6" stroke-dasharray="5 4" marker-end="url(#a-danger)"/>')
    f.text(360, 176, "leak inside the board", 12.5, "danger")
    return f


def copies(t):
    f = Fig(820, 220, t)
    f.text(20, 26, "iiod: two copies, one thread", 14, "ink", 600, "start")
    f.box(20, 40, 170, 56, "DMA buffer", ())
    f.arrow(190, 68, 318, 68, "copy 1", "danger")
    f.box(320, 40, 190, 56, "iiod's memory", ())
    f.arrow(510, 68, 638, 68, "copy 2", "danger")
    f.box(640, 40, 160, 56, "socket", ())
    f.text(20, 136, "zc-stream: one copy", 14, "ink", 600, "start")
    f.box(20, 150, 170, 56, "DMA buffer", ())
    f.arrow(190, 178, 318, 178, "mapped, no copy", "ok")
    f.box(320, 150, 190, 56, "zc-stream", (), fill="accent_soft", stroke="accent")
    f.arrow(510, 178, 638, 178, "one copy", "accent")
    f.box(640, 150, 160, 56, "socket", ())
    return f


def main():
    both("radio-code-places", "Three questions that decide where your code runs", code_places_full)
    both("radio-libiio", "A script on the PC reaches the radio through iiod on the board", libiio)
    both("radio-verify", "The five steps of the --verify check", chain((
        ("Blank", ("bins within about", "±5 kHz of DC")),
        ("Find", ("the strongest", "tone")),
        ("De-rotate", ("by it: the tone", "stands still")),
        ("Average", ("the phase over", "1000-sample blocks")),
        ("Flag", ("any step above", "0.5 radian")),
    ), width=900, box_h=80))
    both("radio-fasttcp", "The Fast TCP transport: samples through zc-stream, control through iiod", fasttcp)
    both("radio-decimator", "The FPGA decimator between the AD9361 and SDR++", chain((
        ("AD9361", ("8 × the rate", "you pick")),
        ("FPGA filter", ("removes all", "outside the view")),
        ("Decimate", ("keep 1 sample", "in 8")),
        ("The link", ("the rate", "you pick")),
        ("SDR++", ()),
    ), width=900, box_h=80, highlight=(1, 2)))
    both("radio-adsb", "The ADS-B decoder's four parts", chain((
        ("source.py", ("iio_attr setup,", "iio_readdev stream,", "or a recording")),
        ("demod.py", ("finds messages",)),
        ("modes.py", ("checksums, fields,", "positions, table")),
        ("gui.py / adsb.py", ("window or terminal",)),
    ), width=900, box_h=96))
    both("radio-maia", "Maia SDR computes the waterfall's FFT on the FPGA", chain((
        ("AD9361", ("245 MB/s of IQ",)),
        ("FFT", ("on the FPGA",)),
        ("Web server", ("on the ARM cores",)),
        ("Browser", ("real-time waterfall",)),
    ), width=900, labels={2: "a few hundred kB/s"}, gap=110, highlight=(1,)))
    both("radio-channel1", "The stock receive path: channel 1 bypasses the decimating filter", channel1)
    both("radio-cyclic", "A cyclic buffer: uploaded once, then replayed by the board", chain((
        ("Your PC", ("one block", "of samples")),
        ("The board's memory", ("replays it", "until stopped")),
        ("TX1", ("up to 61.44 MS/s",)),
    ), width=760, box_h=80, gap=90, labels={0: "upload once"}, highlight=(1,)))
    both("radio-burst", "A one-shot burst on a trigger", chain((
        ("Trigger", ("UDP datagram, or", "GPIO rising edge")),
        ("tx-burst", ("on the board: one", "memory copy, one push")),
        ("DMA", ("plays the buffer", "once")),
        ("DAC", ("outputs zeros until", "the next trigger")),
    ), width=900, box_h=80, highlight=(1,)))
    both("radio-chirp", "chirp-view's signal path, from the PC round the bench loop and back", chain((
        ("PC", ("one period", "of the sweep")),
        ("Cyclic buffer", ("replayed", "by the FPGA")),
        ("The loop", ("TX1 → 20 dB pad", "→ RX1")),
        ("zc-stream", ("8-bit,", "20 MS/s")),
        ("PC", ("receiver process:", "window and sound")),
    ), width=940, box_h=80, gap=44, labels={0: "upload"}, highlight=(2,)))
    both("radio-leak", "Two paths from the TX port to the RX port: the cable loop, and a leak inside the board", leak)
    both("radio-limits", "What limits streaming, in order", chain((
        ("Your host link", ("the only cheap one", "to change")),
        ("The board's CPU", ()),
        ("LVDS port and converter", ("61.44 MS/s on two channels,", "only with the host", "out of the loop")),
    ), width=820, box_h=96, gap=40))
    both("radio-copies", "iiod copies each sample twice; zc-stream maps the DMA buffer and copies once", copies)
    both("radio-twocore", "zc-stream's 8-bit pipeline on two cores", chain((
        ("DMA block", ()),
        ("CPU0 thread", ("wait, convert", "to 8 bits")),
        ("Ring", ("of four", "converted blocks")),
        ("CPU1 thread", ("send",)),
        ("Network", ()),
    ), width=900, box_h=80, highlight=(1, 3)))


if __name__ == "__main__":
    main()
