#!/usr/bin/env python3
"""Draw docs/img/board-map.png - what is where on the board.

    python3 docs/img/make_board_map_svg.py

Labels board.jpg (800 x 800, the vendor's product photo) with the parts you
would want to find. Part numbers come from the vendor schematic in
docs/vendor/; positions come from reading the photo, zoomed.

TWO KINDS OF MARKER, AND WHY
The photo is 800 px across, so only the big parts carry legible markings.

  solid ring   identified from the part itself: a readable marking or logo
               (AD9361, Zynq, Micron DDR3, Realtek, HanRun), silkscreen
               (EXT_CLK, TX_LO/RX_LO), or an unmistakable shape (the header,
               the DIP switch, the connectors)
  dashed ring  INFERRED: the package and position fit exactly one part in the
               schematic, but the marking is not legible. Labelled "likely".
               E.g. the two SOT-89 parts beside the outer SMA ports are the
               only SOT-89s on the RF side, and the schematic's PA, the
               PGA-102+, is a SOT-89.

Anything that could not be pinned down that way is left off rather than
guessed: the power regulators (not in the published schematic at all), the
MAX809, the TXS02612, the FT2232's EEPROM, the LEDs, and which oscillator can
is which apart from the 40 MHz one beside the AD9361.

DELIBERATELY NOT LABELLED INDIVIDUALLY
Which SMA is TX1A/RX1A/TX2A/RX2A and which USB-C is which: the silkscreen
is on the board but too small to read reliably in this photo, and the
schematic does not say. Read the board.

The column order is set by hand, and the layout checks itself before
writing (see check()): no two leader lines cross, no leader passes over another part's marker, no two labels overlap,
nothing leaves the canvas. It refuses to write a figure that fails.

Standard library only. Colours are slots 1-2 of the validated reference
palette at agentskills.io; do not substitute by eye.
"""
import base64, pathlib, subprocess, sys

HERE = pathlib.Path(__file__).parent
PHOTO = HERE / "board.jpg"          # 800 x 800
CROP = (228, 150, 576, 745)         # the board itself, without the vendor logo
S = 1.6                             # photo scale on the canvas
W = 1600
OX, OY = 520, 118                   # where the crop's top-left lands
PWC = (CROP[2] - CROP[0]) * S
PHC = (CROP[3] - CROP[1]) * S
H = int(OY + PHC + 150)

C = dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
         muted="#8a8985", line="#a9a8a2", ring="#eb6834")

# side, title, subtitle, sure?, [anchors in photo px]. Column labels are
# listed top to bottom in the order they are drawn; check() proves the order
# leaves no crossing.
PARTS = [
    ("T", "4 × SMA RF ports", "silkscreened TX1A, RX1A, TX2A, RX2A — read the board for which is which",
     True, [(308, 200), (373, 200), (436, 200), (500, 200)]),

    ("L", "RX balun", "T1–T4 (one of four), feeding the AD9361 · likely", False, [(360, 261)]),
    ("L", "EXT_CLK  (RF1)", "U.FL: feed an external reference in", True, [(279, 265)]),
    ("L", "TX balun + PGA-102+ amplifier", "the transmit chain, U12/U13 · likely",
     False, [(333, 276), (329, 314)]),
    ("L", "40 MHz VCTCXO  (Y3)", "the radio's reference; tunable from JP5 pin 15 · likely",
     False, [(354, 345)]),
    ("L", "JP5 expansion header", "2×10; pins 7/9/11/13 are the sample-locked GPIO", True, [(279, 405)]),
    ("L", "Zynq XC7Z020  (U1)", "two Cortex-A9 cores + FPGA fabric", True, [(372, 436)]),
    ("L", "RTL8211F  (IC2)", "gigabit Ethernet PHY", True, [(324, 517)]),
    ("L", "USB3320C  (U9)", "USB 2.0 OTG PHY · likely", False, [(371, 518)]),
    ("L", "HR911130A  (RJ1)", "RJ45 jack with magnetics", True, [(317, 613)]),
    ("L", "microSD card", "the boot files live here", True, [(427, 692)]),

    ("R", "RX balun", "T1–T4 (one of four) · likely", False, [(434, 261)]),
    ("R", "TX_LO / RX_LO  (RF2, RF3)", "U.FL: the AD9361's local oscillators", True,
     [(518, 250), (518, 274)]),
    ("R", "TX balun + PGA-102+ amplifier", "U12/U13 · likely", False, [(467, 281), (464, 314)]),
    ("R", "AD9361  (U11)", "the radio: 2×2 transceiver, 70 MHz – 6 GHz", True, [(410, 311)]),
    ("R", "2 × MT41K256M16 DDR3L  (U2, U3)", "1 GB on a 32-bit bus", True, [(492, 410), (492, 464)]),
    ("R", "RST button  (SW1)", "resets the board", True, [(459, 531)]),
    ("R", "BOOT DIP switch", "SD 0 0 · QSPI 1 0 · JTAG 1 1", True, [(491, 553)]),
    ("R", "W25Q128 QSPI flash", "16 MB · likely", False, [(523, 552)]),
    ("R", "FAN1 header", "2-pin, unswitched 5 V · likely", False, [(466, 562)]),
    ("R", "FT2232H  (U8)", "USB to JTAG + serial console · likely", False, [(420, 580)]),
    ("R", "2 × USB-C", "one USB OTG (network), one DEBUG (JTAG + console)", True,
     [(418, 655), (513, 657)]),
]

LEFT_X = OX - 70            # right edge of left-column text
RIGHT_X = OX + PWC + 70     # left edge of right-column text
TOP_Y = OY + 58              # first column label baseline
BOT_Y = OY + PHC - 20        # last column label baseline


def cx(px): return OX + (px - CROP[0]) * S
def cy(py): return OY + (py - CROP[1]) * S


def text_w(s, size):
    """A conservative width estimate for DejaVu Sans."""
    return len(s) * size * 0.60


def layout():
    """Place every label: columns evenly spaced in the order listed."""
    items = []
    for side in ("L", "R"):
        grp = [p for p in PARTS if p[0] == side]
        n = len(grp)
        ys = [TOP_Y + (BOT_Y - TOP_Y) * i / (n - 1) for i in range(n)]
        items += [placed(p, y) for p, y in zip(grp, ys)]
    for p in PARTS:
        if p[0] == "T":
            items.append(placed(p, OY - 44))
        if p[0] == "B":
            items.append(placed(p, OY + PHC + 58))
    return items


def placed(p, ty):
    side, title, sub, sure, anchors = p
    pts = [(cx(x), cy(y)) for x, y in anchors]
    if side == "L":
        tx, anchor, ex = LEFT_X, "end", LEFT_X + 14
        segs = [((ex, ty - 5), pt) for pt in pts]
        box = (tx - max(text_w(title, 15), text_w(sub, 12.5)), ty - 15, tx, ty + 24)
    elif side == "R":
        tx, anchor, ex = RIGHT_X, "start", RIGHT_X - 14
        segs = [((ex, ty - 5), pt) for pt in pts]
        box = (tx, ty - 15, tx + max(text_w(title, 15), text_w(sub, 12.5)), ty + 24)
    else:                                   # T / B: centred over the anchors
        tx, anchor = sum(x for x, _ in pts) / len(pts), "middle"
        half = max(text_w(title, 15), text_w(sub, 12.5)) / 2
        box = (tx - half, ty - 15, tx + half, ty + 24)
        edge = ty + 30 if side == "T" else ty - 20
        segs = [((x, edge), (x, y)) for x, y in pts]
    return dict(title=title, sub=sub, sure=sure, tx=tx, ty=ty, anchor=anchor,
                segs=segs, pts=pts, box=box)


def cross(s1, s2):
    (a, b), (c, d) = s1, s2
    def orient(p, q, r):
        v = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (v > 1e-9) - (v < -1e-9)
    if a == c or a == d or b == c or b == d:
        return False
    return (orient(a, b, c) != orient(a, b, d)) and (orient(c, d, a) != orient(c, d, b))


def seg_point_dist(seg, p):
    (x1, y1), (x2, y2) = seg
    dx, dy = x2 - x1, y2 - y1
    t = max(0, min(1, ((p[0] - x1) * dx + (p[1] - y1) * dy) / (dx * dx + dy * dy or 1)))
    return ((x1 + t * dx - p[0]) ** 2 + (y1 + t * dy - p[1]) ** 2) ** 0.5


def check(items):
    problems = []
    segs = [(i, s) for i, it in enumerate(items) for s in it["segs"]]
    for k, (i, s1) in enumerate(segs):
        for j, s2 in segs[k + 1:]:
            if i != j and cross(s1, s2):
                problems.append(f"leaders cross: {items[i]['title']} / {items[j]['title']}")
    for i, s in segs:
        for j, it in enumerate(items):
            if j == i:
                continue
            for p in it["pts"]:
                if seg_point_dist(s, p) < 9:
                    problems.append(f"leader of {items[i]['title']} passes over "
                                    f"the marker of {it['title']}")
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            A, B = a["box"], b["box"]
            if A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3]:
                problems.append(f"labels overlap: {a['title']} / {b['title']}")
        x0, y0, x1, y1 = a["box"]
        if x0 < 8 or y0 < 50 or x1 > W - 8 or y1 > H - 8:
            problems.append(f"label off canvas: {a['title']}")
    return sorted(set(problems))


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build(items):
    b64 = base64.b64encode(PHOTO.read_bytes()).decode()
    ix, iy = OX - CROP[0] * S, OY - CROP[1] * S
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" '
         f'xmlns:xlink="http://www.w3.org/1999/xlink" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="DejaVu Sans, Helvetica, Arial, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="{C["surface"]}"/>',
         f'<defs><clipPath id="c"><rect x="{OX}" y="{OY}" width="{PWC}" height="{PHC}" rx="6"/>'
         f'</clipPath></defs>',
         f'<image x="{ix}" y="{iy}" width="{800 * S}" height="{800 * S}" clip-path="url(#c)" '
         f'xlink:href="data:image/jpeg;base64,{b64}"/>',
         f'<text x="34" y="40" font-size="19" font-weight="600" fill="{C["primary"]}">'
         f'What is where on the board</text>']
    for it in items:
        for (x1, y1), (x2, y2) in it["segs"]:
            o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                     f'stroke="{C["line"]}" stroke-width="1.3"/>')
    for it in items:
        for x, y in it["pts"]:
            dash = '' if it["sure"] else ' stroke-dasharray="3 2.2"'
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="none" '
                     f'stroke="{C["surface"]}" stroke-width="4.5"/>')
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="none" '
                     f'stroke="{C["ring"]}" stroke-width="2.4"{dash}/>')
            o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="1.9" fill="{C["ring"]}"/>')
        o.append(f'<text x="{it["tx"]:.1f}" y="{it["ty"]:.1f}" font-size="15" font-weight="600" '
                 f'fill="{C["primary"]}" text-anchor="{it["anchor"]}">{esc(it["title"])}</text>')
        o.append(f'<text x="{it["tx"]:.1f}" y="{it["ty"] + 19:.1f}" font-size="12.5" '
                 f'fill="{C["secondary"]}" text-anchor="{it["anchor"]}">{esc(it["sub"])}</text>')
    ly = H - 28
    o.append(f'<circle cx="44" cy="{ly - 4}" r="7" fill="none" stroke="{C["ring"]}" stroke-width="2.4"/>')
    o.append(f'<text x="60" y="{ly}" font-size="12.5" fill="{C["secondary"]}">identified from '
             f'the part itself: marking, logo or silkscreen</text>')
    o.append(f'<circle cx="474" cy="{ly - 4}" r="7" fill="none" stroke="{C["ring"]}" '
             f'stroke-width="2.4" stroke-dasharray="3 2.2"/>')
    o.append(f'<text x="490" y="{ly}" font-size="12.5" fill="{C["secondary"]}">"likely": '
             f'package and position match one part in the vendor schematic; marking not legible '
             f'at this resolution</text>')
    o.append("</svg>")
    return "\n".join(o)


if __name__ == "__main__":
    items = layout()
    problems = check(items)
    if problems:
        print("layout check FAILED:\n  " + "\n  ".join(problems))
        sys.exit(1)
    svg = HERE / "_board-map.svg"
    svg.write_text(build(items), encoding="utf8")
    png = HERE / "board-map.png"
    subprocess.run(["rsvg-convert", "-o", str(png), str(svg)], check=True)
    svg.unlink()
    print(f"layout check passed ({len(items)} labels); wrote {png}")
