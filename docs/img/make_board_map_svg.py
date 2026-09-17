#!/usr/bin/env python3
"""Draw docs/img/board-map.png - what is where on the board.

    python3 docs/img/make_board_map_svg.py

Labels board.jpg with the parts you need to find in order to use this repo.
Part numbers come from the vendor schematic in docs/vendor/; positions come
from reading the photo.

DELIBERATELY NOT LABELLED
The four SMA ports are marked as a group. Their silkscreen is legible in the
photo but upside down, and the schematic gives the net names without saying
which physical connector is which - that is in the PCB layout, which this
repo does not have. Guessing would be worse than pointing at all four and
telling you to read the silkscreen. The same goes for which USB-C socket is
which: both are labelled on the board itself.

Standard library only. Colours are slots 1-2 of the validated reference
palette at agentskills.io; do not substitute by eye.
"""
import base64, pathlib, subprocess

HERE = pathlib.Path(__file__).parent
PHOTO = HERE / "board.jpg"
PW = 800                            # the photo is 800x800
OX, OY = 372, 34                    # where the photo sits on the canvas
W, H = 1560, 950

C = dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
         muted="#8a8985", line="#b9b8b3", s1="#2a78d6", s2="#eb6834")

# (photo x, photo y, side, title, subtitle)
PARTS = [
    (396, 185, "R", "4 × SMA RF ports",
     "TX1A, RX1A, TX2A, RX2A - read the silkscreen"),
    (516, 262, "R", "TX_LO / RX_LO", "U.FL, external LO in/out"),
    (398, 312, "R", "AD9361", "RF transceiver, 70 MHz - 6 GHz"),
    (496, 420, "R", "2 × MT41K256M16", "DDR3L, 1 GB total on a 32-bit bus"),
    (491, 551, "R", "BOOT switch", "2-position: SD 0 0, QSPI 1 0, JTAG 1 1"),
    (465, 564, "R", "microSD", "where the five boot files go"),
    (470, 662, "R", "2 × USB-C",
     "FT2232HL (JTAG + console) and USB OTG"),
    (277, 263, "L", "EXT_CLK", "U.FL, external 40 MHz reference"),
    (285, 425, "L", "JP5 expansion header",
     "2x10; pins 7/9/11/13 are sample_gpio[3:0]"),
    (390, 455, "L", "Zynq XC7Z020", "CLG400, dual Cortex-A9 + PL fabric"),
    (315, 610, "L", "HR911130A", "gigabit RJ45, RTL8211F PHY behind it"),
]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build():
    b64 = base64.b64encode(PHOTO.read_bytes()).decode()
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" '
         f'xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Helvetica, Arial, '
         f'sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{C["surface"]}"/>',
         f'<image x="{OX}" y="{OY}" width="{PW}" height="{PW}" '
         f'xlink:href="data:image/jpeg;base64,{b64}"/>']

    o.append(f'<text x="34" y="36" font-size="18" font-weight="600" '
             f'fill="{C["primary"]}">What is where on the board</text>')

    left = [p for p in PARTS if p[2] == "L"]
    right = [p for p in PARTS if p[2] == "R"]
    for group, side in ((left, "L"), (right, "R")):
        group.sort(key=lambda p: p[1])
        n = len(group)
        span = H - 240
        for i, (px, py, _, title, sub) in enumerate(group):
            ty = 96 + (span * i) / max(n - 1, 1)
            ax, ay = OX + px, OY + py
            if side == "L":
                tx, anchor, elbow = 330, "end", 352
            else:
                tx, anchor, elbow = OX + PW + 42, "start", OX + PW + 20
            o.append(f'<path d="M {ax} {ay} L {elbow} {ty - 5}" fill="none" '
                     f'stroke="{C["line"]}" stroke-width="1.4"/>')
            o.append(f'<circle cx="{ax}" cy="{ay}" r="5.5" fill="none" '
                     f'stroke="{C["s2"]}" stroke-width="2.4"/>')
            o.append(f'<circle cx="{ax}" cy="{ay}" r="1.8" fill="{C["s2"]}"/>')
            o.append(f'<text x="{tx}" y="{ty}" font-size="15" '
                     f'font-weight="600" fill="{C["primary"]}" '
                     f'text-anchor="{anchor}">{esc(title)}</text>')
            o.append(f'<text x="{tx}" y="{ty + 19}" font-size="12.5" '
                     f'fill="{C["secondary"]}" text-anchor="{anchor}">'
                     f'{esc(sub)}</text>')

    o.append(f'<text x="34" y="{H - 20}" font-size="12" fill="{C["muted"]}">'
             f'Part numbers from the vendor schematic in docs/vendor/. '
             f'The four SMA ports and the two USB-C sockets are labelled on '
             f'the board itself - read them there rather than counting from '
             f'this picture.</text>')
    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    svg = HERE / "_board-map.svg"
    svg.write_text(build(), encoding="utf8")
    png = HERE / "board-map.png"
    subprocess.run(["rsvg-convert", "-o", str(png), str(svg)], check=True)
    svg.unlink()
    print(png)
