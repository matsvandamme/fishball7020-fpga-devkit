#!/usr/bin/env python3
"""Draw docs/img/jp5-pinout-{light,dark}.svg.

JP5 is the 2x10 expansion header on the board edge. Four of its pins are the
TX-sample-nibble outputs (see docs/tx-gpio-bitmap.md); the rest are power, two
grounds, four 1.8 V differential pairs and three board control signals.

Pin NUMBERING is from the vendor schematic and is certain. Pin 1's PHYSICAL
position is not marked on the schematic and cannot be read off the board photo
in this repo, so the drawing tells you how to find it rather than guessing.

Standard library only. Colours are slots 1-2 of the validated reference
palette at agentskills.io; do not substitute by eye.
"""
import pathlib

# (pin, label, kind)  - kind drives the colour
LEFT = [(1, "VCC5V", "pwr"), (3, "VCC3V3", "pwr"), (5, "VCC1V8", "pwr"),
        (7, "3V3_IO1   sample_gpio[0]", "sig"),
        (9, "3V3_IO2   sample_gpio[1]", "sig"),
        (11, "3V3_IO3   sample_gpio[2]", "sig"),
        (13, "3V3_IO4   sample_gpio[3]", "sig"),
        (15, "XTAL_VTC", "other"), (17, "PTT", "other"),
        (19, "AD936X_SYNC", "other")]
RIGHT = [(2, "GND", "gnd"), (4, "1V8_IO1_P", "diff"), (6, "1V8_IO1_N", "diff"),
         (8, "1V8_IO3_P", "diff"), (10, "1V8_IO3_N", "diff"),
         (12, "1V8_IO5_P", "diff"), (14, "1V8_IO5_N", "diff"),
         (16, "1V8_IO7_P", "diff"), (18, "1V8_IO7_N", "diff"),
         (20, "GND", "gnd")]

W, H = 760, 630
PITCH = 31
X1, X2 = 292, 352          # pad column centres
Y0 = 120                   # first row centre
PAD = 11

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
    colour = {"sig": c["s2"], "gnd": c["primary"], "pwr": c["s1"],
              "diff": c["muted"], "other": c["muted"]}
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Helvetica, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{c["surface"]}"/>']

    o.append(f'<text x="30" y="34" font-size="17" font-weight="600" '
             f'fill="{c["primary"]}">JP5 — expansion header (2×10, 2.54 mm)</text>')
    o.append(f'<text x="30" y="56" font-size="12.5" fill="{c["secondary"]}">'
             f'Pin numbers from the vendor schematic. '
             f'<tspan fill="{c["s2"]}" font-weight="600">Orange = TX sample nibble outputs.</tspan></text>')

    # connector body
    top = Y0 - PITCH / 2 - 9
    height = 10 * PITCH + 18
    o.append(f'<rect x="{X1-30}" y="{top}" width="{X2-X1+60}" height="{height}" '
             f'rx="7" fill="{c["body"]}" stroke="{c["grid"]}" stroke-width="1.5"/>')

    for i in range(10):
        y = Y0 + i * PITCH
        for (col, x, items, anchor, tx) in (
                ("L", X1, LEFT, "end", X1 - 30 - 12),
                ("R", X2, RIGHT, "start", X2 + 30 + 12)):
            pin, label, kind = items[i]
            fill = colour[kind]
            # pin 1 is a square pad, every other pin round - the usual convention
            if pin == 1:
                o.append(f'<rect x="{x-PAD/2-1}" y="{y-PAD/2-1}" width="{PAD+2}" '
                         f'height="{PAD+2}" fill="{fill}"/>')
            else:
                o.append(f'<circle cx="{x}" cy="{y}" r="{PAD/2}" fill="{fill}"/>')
            o.append(f'<text x="{x + (16 if col=="R" else -16)}" y="{y+4}" '
                     f'font-size="11.5" text-anchor="{"start" if col=="R" else "end"}" '
                     f'fill="{c["muted"]}">{pin}</text>')
            weight = "600" if kind == "sig" else "400"
            size = 12.5 if kind == "sig" else 11.5
            o.append(f'<text x="{tx}" y="{y+4}" font-size="{size}" '
                     f'font-weight="{weight}" text-anchor="{anchor}" '
                     f'fill="{c["primary"] if kind in ("sig","gnd") else c["secondary"]}" '
                     f'font-family="DejaVu Sans Mono, monospace">{esc(label)}</text>')

    # pin-1 callout
    o.append(f'<text x="{X1}" y="{top-9}" font-size="11" text-anchor="middle" '
             f'fill="{c["s1"]}">square pad = pin 1  ▼</text>')

    # how to orient
    notes = [
        ("Finding pin 1 on the board:", True),
        ("odd pins 1–19 are one column, even pins 2–20 the other. Pin 1 is",
         False),
        ("normally a SQUARE pad on the underside, or marked by a silkscreen",
         False),
        ("dot, triangle or “1”. Confirm before probing — this drawing cannot",
         False),
        ("tell you which way round the connector sits on your board.", False),
        ("", False),
        ("Logic analyser: ground on pin 2 or 20, probes on 7, 9, 11, 13.", True),
        ("Those four are 3.3 V LVCMOS. The 1V8_* pairs are 1.8 V — do not", False),
        ("drive them at 3.3 V. Pins 1/3/5 are power rails, not signals.", False),
    ]
    ny = top + height + 38
    for line, strong in notes:
        if line:
            o.append(f'<text x="30" y="{ny}" font-size="11.5" '
                     f'font-weight="{"600" if strong else "400"}" '
                     f'fill="{c["primary"] if strong else c["secondary"]}">{esc(line)}</text>')
        ny += 16

    o.append("</svg>")
    return "\n".join(o)


out = pathlib.Path(__file__).resolve().parent
for t in TH:
    (out / f"jp5-pinout-{t}.svg").write_text(build(t))
print(f"wrote {out}/jp5-pinout-{{light,dark}}.svg")
