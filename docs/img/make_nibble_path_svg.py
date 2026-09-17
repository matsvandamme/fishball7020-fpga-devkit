#!/usr/bin/env python3
"""Draw docs/img/nibble-path-{light,dark}.svg.

The route a transmit sample takes through the FPGA, and where the low four
bits branch off to the header pins. Left column is the sample on its way to
the antenna; right column is the nibble on its way to JP5. They separate at
util_upack2 and never meet again.

Banded by where each block physically lives, because the names invite the
wrong guess: axi_ad9361 and axi_ad9361_dac_dma are FPGA IP cores in the PL
fabric, not parts of the AD9361 chip. Only the last band is off-chip.

Every box name is a real instance in the block design (system_bd.tcl) or a
real chip, so the picture and the HDL can be checked against each other.

Standard library only. Colours are slots 1-2 of the validated reference
palette at agentskills.io; do not substitute by eye.
"""
import pathlib

W, H = 880, 940
BW, BH = 310, 54                 # box width / height
LX, RX = 44, 500                 # column left edges
GAP = 40

# (y, title, subtitle, kind)
LEFT = [
    (86,  "Your program", "16-bit I/Q words in a DDR buffer", "plain"),
    (86 + (BH + GAP), "TX DMA", "axi_ad9361_dac_dma", "plain"),
    (86 + 2 * (BH + GAP), "util_upack2", "the sample stands at its output", "tap"),
    (86 + 4 * (BH + GAP), "FIR interpolator", "bypassed above 2.083 MSPS", "plain"),
    (86 + 5 * (BH + GAP), "axi_ad9361", "DAC core, then LVDS to the chip", "plain"),
    (86 + 6 * (BH + GAP), "AD9361", "12-bit DAC — takes bits [15:4]", "plain"),
    (86 + 7 * (BH + GAP), "RF out", "antenna port", "rf"),
]
RIGHT = [
    (86,  "EMIO GPIO 21:18", "what the pins do when the flag is 0", "ctl"),
    (86 + (BH + GAP), "GP_CONTROL bit 1", "AXI 0xBC — the enable flag", "ctl"),
    (86 + 2 * (BH + GAP), "tx_gpio_bitmap", "one capture per sample, then choose", "sig"),
    (86 + 3 * (BH + GAP), "ad_iobuf", "one per pin, in system_top.v", "sig"),
    (86 + 6 * (BH + GAP), "JP5 pins 7, 9, 11, 13", "balls V10, U9, U10, T9", "sig"),
]

# (y0, y1, label) - which side of the chip boundary each row sits on
ZONES = [
    (70, 86 + BH + 26, "processing system"),
    (86 + BH + 32, 86 + 5 * (BH + GAP) + BH + 26,
     "FPGA fabric (PL)"),
    (86 + 5 * (BH + GAP) + BH + 32, 86 + 7 * (BH + GAP) + BH + 26,
     "off-chip \u2014 AD9361 and header"),
]

TH = {"light": dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
                    muted="#8a8985", grid="#e6e5e1", body="#d8d7d2",
                    s1="#2a78d6", s2="#eb6834"),
      "dark": dict(surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7",
                   muted="#8a8985", grid="#33322f", body="#2c2b29",
                   s1="#3987e5", s2="#d95926")}


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(t):
    c = TH[t]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Helvetica, Arial, '
         f'sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{c["surface"]}"/>',
         f'<defs>'
         f'<marker id="a{t}" markerWidth="9" markerHeight="7" refX="8" refY="3.5" '
         f'orient="auto"><path d="M0,0 L9,3.5 L0,7 z" fill="{c["muted"]}"/></marker>'
         f'<marker id="s{t}" markerWidth="9" markerHeight="7" refX="8" refY="3.5" '
         f'orient="auto"><path d="M0,0 L9,3.5 L0,7 z" fill="{c["s2"]}"/></marker>'
         f'<marker id="c{t}" markerWidth="9" markerHeight="7" refX="8" refY="3.5" '
         f'orient="auto"><path d="M0,0 L9,3.5 L0,7 z" fill="{c["s1"]}"/></marker>'
         f'</defs>']

    for z0, z1, zl in ZONES:
        o.append(f'<rect x="{LX-16}" y="{z0}" width="{W - 2*(LX-16)}" '
                 f'height="{z1-z0}" rx="10" fill="{c["grid"]}" '
                 f'fill-opacity="0.55" stroke="none"/>')
        o.append(f'<text x="{W - LX + 12}" y="{z1 - 9}" font-size="11.5" '
                 f'fill="{c["muted"]}" text-anchor="end">{esc(zl)}</text>')

    o.append(f'<text x="{LX}" y="34" font-size="17" font-weight="600" '
             f'fill="{c["primary"]}">Where the low four bits leave the '
             f'transmit path</text>')
    o.append(f'<text x="{LX}" y="56" font-size="12.5" fill="{c["secondary"]}">'
             f'Box names are real instances in system_bd.tcl. The two paths '
             f'split at util_upack2; the bands say what is on which chip.</text>')

    def box(x, y, title, sub, kind):
        edge = {"sig": c["s2"], "ctl": c["s1"], "tap": c["s2"],
                "rf": c["muted"], "plain": c["body"]}[kind]
        wide = 2.2 if kind in ("sig", "tap") else 1.4
        dash = ' stroke-dasharray="5 4"' if kind == "rf" else ""
        o.append(f'<rect x="{x}" y="{y}" width="{BW}" height="{BH}" rx="7" '
                 f'fill="{c["surface"]}" stroke="{edge}" stroke-width="{wide}"'
                 f'{dash}/>')
        o.append(f'<text x="{x+16}" y="{y+23}" font-size="14" font-weight="600" '
                 f'fill="{c["primary"]}">{esc(title)}</text>')
        o.append(f'<text x="{x+16}" y="{y+42}" font-size="12" '
                 f'fill="{c["secondary"]}">{esc(sub)}</text>')

    def arrow(x1, y1, x2, y2, colour, marker, dash=False):
        d = ' stroke-dasharray="6 5"' if dash else ""
        o.append(f'<path d="M{x1},{y1} L{x2},{y2}" stroke="{colour}" '
                 f'stroke-width="1.8" fill="none" marker-end="url(#{marker}{t})"'
                 f'{d}/>')

    def label(x, y, s, colour, size=11.5, anchor="start", weight="normal"):
        o.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{colour}" '
                 f'text-anchor="{anchor}" font-weight="{weight}">{esc(s)}</text>')

    for y, title, sub, kind in LEFT:
        box(LX, y, title, sub, kind)
    for y, title, sub, kind in RIGHT:
        box(RX, y, title, sub, kind)

    cxl, cxr = LX + BW / 2, RX + BW / 2
    tap_y = LEFT[2][0]                       # util_upack2
    mod_y = RIGHT[2][0]                      # tx_gpio_bitmap

    # left column, top to bottom
    for i in (0, 1):
        arrow(cxl, LEFT[i][0] + BH, cxl, LEFT[i + 1][0] - 4, c["muted"], "a")
    for i in (3, 4, 5):
        arrow(cxl, LEFT[i][0] + BH, cxl, LEFT[i + 1][0] - 4, c["muted"], "a")

    # the split, drawn as one long arrow with the discarded bits called out
    arrow(cxl, tap_y + BH, cxl, LEFT[3][0] - 4, c["muted"], "a")
    label(cxl + 12, tap_y + BH + 34, "bits [15:4] — the only ones the DAC reads",
          c["secondary"])
    label(cxl + 12, tap_y + BH + 52, "bits [3:0] carry on down and are dropped here",
          c["muted"])

    # the branch: tap -> module
    arrow(LX + BW, tap_y + BH / 2, RX - 4, mod_y + BH / 2, c["s2"], "s")
    label(LX + BW + 16, tap_y + BH / 2 - 10, "bits [3:0]", c["s2"], 13,
          weight="600")
    label(LX + BW + 16, tap_y + BH / 2 + 24, "the tap", c["secondary"])

    # control inputs into the module
    arrow(cxr, RIGHT[0][0] + BH, cxr, RIGHT[1][0] - 4, c["s1"], "c", dash=True)
    arrow(cxr, RIGHT[1][0] + BH, cxr, mod_y - 4, c["s1"], "c", dash=True)
    label(cxr + 12, RIGHT[0][0] + BH + 22, "flag = 1", c["s1"], 11.5)
    label(cxr + 12, RIGHT[1][0] + BH + 22, "flag = 0", c["s1"], 11.5)

    # module -> pad -> header
    arrow(cxr, RIGHT[2][0] + BH, cxr, RIGHT[3][0] - 4, c["s2"], "s")
    arrow(cxr, RIGHT[3][0] + BH, cxr, RIGHT[4][0] - 4, c["s2"], "s")
    label(cxr + 12, RIGHT[3][0] + BH + 64, "out through the package ball",
          c["secondary"])
    label(cxl + 12, LEFT[4][0] + BH + 17, "LVDS, off the FPGA", c["secondary"])

    # the two ends, side by side at the bottom
    y = LEFT[6][0] + BH + 30
    o.append(f'<rect x="{LX}" y="{y}" width="{W - 2*LX}" height="78" rx="7" '
             f'fill="{c["grid"]}" stroke="none"/>')
    label(LX + 16, y + 24, "The pins lead the RF by a fixed offset.",
          c["primary"], 12.5, weight="600")
    label(LX + 16, y + 44,
          "Capture strobe: fifo_rd_valid | fifo_rd_underflow \u2014 never "
          "fifo_rd_en, which asks one clock too early.",
          c["secondary"], 12)
    label(LX + 16, y + 63,
          "A pad changes one clock after the tap. The matching RF still has "
          "the interpolator, the AD9361 and the DAC ahead of it.",
          c["secondary"], 12)

    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    here = pathlib.Path(__file__).parent
    for t in ("light", "dark"):
        p = here / f"nibble-path-{t}.svg"
        p.write_text(build(t), encoding="utf8")
        print(p)
