#!/usr/bin/env python3
"""Draw docs/img/schematic-*.png - the vendor schematic sheets that establish
the sample-GPIO pin assignment, with the exact nets highlighted.

    python3 docs/img/make_schematic_figures.py

Reads the vendor schematic that ships in this repository at
docs/vendor/7020_936x_SDR-schematic.pdf. Point it at a different copy with:

    FISHBALL_SCHEMATIC=/path/to/schematic.pdf python3 docs/img/make_schematic_figures.py

Note that the schematic the vendor publishes on their own GitHub is a
DIFFERENT board revision with no JP5 at all - see docs/vendor/README.md.

Also needs poppler-utils (pdftotext, pdftoppm) and rsvg-convert.

WHY THIS IS A SCRIPT AND NOT THREE HAND-DRAWN PICTURES
Every highlight box is positioned from the PDF's own text coordinates
(pdftotext -bbox), so a box cannot drift away from the word it marks, and
anyone can re-run this and get the same picture. Three of the four pins in
the first version of this feature were guessed, and wrong. This is the
evidence that the current four are not.
"""
import base64, html, os, re, subprocess, sys, tempfile

OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("FISHBALL_SCHEMATIC") or os.path.join(
    OUT, os.pardir, "vendor", "7020_936x_SDR-schematic.pdf")
TMP = None                          # scratch dir, set by prepare()
DPI = 420
S = DPI / 72.0                      # PDF points -> pixels

GREEN, RED, BLUE, GREY = "#0b8a3d", "#c62020", "#1150c8", "#7d838b"
INK, DIM = "#14181d", "#4a5058"
SANS = "DejaVu Sans, Helvetica, sans-serif"
MONO = "DejaVu Sans Mono, monospace"


def prepare(pages=(1, 5, 13)):
    """Extract per-word bounding boxes for the pages we annotate."""
    global TMP
    if not os.path.isfile(SRC):
        sys.exit(f"schematic not found:\n  {os.path.abspath(SRC)}\n"
                 "Expected it at docs/vendor/, or set FISHBALL_SCHEMATIC.")
    TMP = tempfile.mkdtemp(prefix="fishball-schematic-")
    for p in pages:
        subprocess.run(["pdftotext", "-f", str(p), "-l", str(p), "-bbox",
                        SRC, f"{TMP}/bbox_p{p}.xml"], check=True)


def words(page):
    xml = open(f"{TMP}/bbox_p{page}.xml", encoding="utf8").read()
    return [(float(a), float(b), float(c), float(d), html.unescape(e))
            for a, b, c, d, e in re.findall(
                r'<word xMin="([\d.]+)" yMin="([\d.]+)" '
                r'xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', xml)]


def find(page, text, near=None):
    hits = [w for w in words(page) if w[4] == text]
    if not hits:
        raise SystemExit(f"'{text}' not found on page {page}")
    if near:
        hits.sort(key=lambda w: (w[0] - near[0]) ** 2 + (w[1] - near[1]) ** 2)
    return hits[0]


class Sheet:
    PAD_T, PAD_L, GUTTER, PAD_B = 176, 26, 120, 40

    def __init__(self, page, box, title, subtitle, margin=900):
        self.page, self.box = page, box
        px = lambda v: int(round(v * S))
        self.iw, self.ih = px(box[2] - box[0]), px(box[3] - box[1])
        self.png = subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI),
             "-png", "-x", str(px(box[0])), "-y", str(px(box[1])),
             "-W", str(self.iw), "-H", str(self.ih), SRC],
            capture_output=True, check=True).stdout
        self.mx = self.PAD_L + self.iw + self.GUTTER
        self.W = self.mx + margin
        self.bottom = self.PAD_T + self.ih
        self.parts, self.badges = [], []
        self.title, self.subtitle = title, subtitle
        self.n = 0

    # -- PDF points -> canvas pixels ---------------------------------------
    def X(self, x): return self.PAD_L + (x - self.box[0]) * S
    def Y(self, y): return self.PAD_T + (y - self.box[1]) * S

    def mark(self, ws, colour, pad=0.7, dash=False, fill=0.13):
        dash_attr = ' stroke-dasharray="11 7"' if dash else ''
        x0, y0 = min(w[0] for w in ws) - pad, min(w[1] for w in ws) - pad
        x1, y1 = max(w[2] for w in ws) + pad, max(w[3] for w in ws) + pad
        self.parts.append(
            f'<rect x="{self.X(x0):.1f}" y="{self.Y(y0):.1f}" '
            f'width="{(x1-x0)*S:.1f}" height="{(y1-y0)*S:.1f}" rx="5" '
            f'fill="{colour}" fill-opacity="{fill}" stroke="{colour}" '
            f'stroke-width="3.4"{dash_attr}/>')
        return self.X(x1), (self.Y(y0) + self.Y(y1)) / 2

    def badge(self, x, y, n, colour, r=23):
        self.badges.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{colour}" '
            f'stroke="#ffffff" stroke-width="3"/>'
            f'<text x="{x:.1f}" y="{y + r*0.37:.1f}" font-family="{SANS}" '
            f'font-size="{r*1.15:.0f}" font-weight="bold" fill="#ffffff" '
            f'text-anchor="middle">{n}</text>')

    def leader(self, frm, to, colour, n=None):
        (x0, y0), (x1, y1) = frm, to
        mid = max(x0 + (x1 - x0) * 0.42,
                  self.PAD_L + self.iw + 34)
        self.parts.append(
            f'<path d="M {x0:.1f} {y0:.1f} H {mid:.1f} V {y1:.1f} H {x1:.1f}" '
            f'fill="none" stroke="{colour}" stroke-width="3" '
            f'stroke-opacity="0.8" stroke-linejoin="round"/>')
        if n is not None:
            self.badge(mid, (y0 + y1) / 2, n, colour)

    def text(self, x, y, s, size=27, colour=INK, weight="normal",
             family=SANS, anchor="start"):
        self.parts.append(
            f'<text xml:space="preserve" x="{x:.1f}" y="{y:.1f}" '
            f'font-family="{family}" '
            f'font-size="{size}" font-weight="{weight}" fill="{colour}" '
            f'text-anchor="{anchor}">{html.escape(s)}</text>')

    def callout(self, y, lines, colour, width=820, n=None):
        h = 30 + 38 * len(lines)
        self.parts.append(
            f'<rect x="{self.mx}" y="{y-34:.1f}" width="{width}" '
            f'height="{h}" rx="9" fill="{colour}" fill-opacity="0.07" '
            f'stroke="{colour}" stroke-width="2.5"/>')
        for i, (s, bold) in enumerate(lines):
            self.text(self.mx + 40, y + 4 + 38 * i, s, 29 if bold else 27,
                      INK if bold else DIM, "bold" if bold else "normal",
                      MONO if bold else SANS)
        self.bottom = max(self.bottom, y - 34 + h)
        if n is not None:
            self.badge(self.mx, y - 34 + h / 2, n, colour)
        return self.mx, y - 34 + h / 2

    def note(self, y, lines, width=820):
        """An untitled grey explainer block in the callout column."""
        h = 26 + 34 * len(lines)
        self.parts.append(
            f'<rect x="{self.mx}" y="{y-30:.1f}" width="{width}" height="{h}" '
            f'rx="9" fill="#f2f4f6" stroke="#d4d9de" stroke-width="2"/>')
        for i, (s, bold) in enumerate(lines):
            self.text(self.mx + 26, y + 2 + 34 * i, s, 25, INK if bold else DIM,
                      "bold" if bold else "normal", MONO if bold else SANS)
        self.bottom = max(self.bottom, y - 30 + h)
        return y - 30 + h

    def link(self, a, b, colour):
        """A short connector between two marks on the same row."""
        self.parts.append(
            f'<path d="M {a[0]:.1f} {a[1]:.1f} L {b[0]:.1f} {b[1]:.1f}" '
            f'fill="none" stroke="{colour}" stroke-width="3" '
            f'stroke-dasharray="7 5" stroke-opacity="0.75"/>')

    def save(self, name, footer):
        self.text(self.PAD_L, 58, self.title, 45, INK, "bold")
        self.text(self.PAD_L, 102, self.subtitle, 28, "#525860")
        self.text(self.PAD_L, 140, "Every highlight is positioned from the "
                  "PDF's own text coordinates, not placed by eye. "
                  "Numbers tie a box to its note.", 23, "#80868e")
        fy = self.bottom + 54
        for i, ln in enumerate(footer):
            self.text(self.PAD_L, fy + 34 * i, ln, 25, "#3a4046")
        self.H = int(fy + 34 * len(footer) + 26)
        b64 = base64.b64encode(self.png).decode()
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
               f'xmlns:xlink="http://www.w3.org/1999/xlink" '
               f'width="{self.W}" height="{self.H}" '
               f'viewBox="0 0 {self.W} {self.H}">'
               f'<rect width="{self.W}" height="{self.H}" fill="#ffffff"/>'
               f'<image x="{self.PAD_L}" y="{self.PAD_T}" width="{self.iw}" '
               f'height="{self.ih}" xlink:href="data:image/png;base64,{b64}" '
               f'image-rendering="optimizeQuality"/>'
               f'<rect x="{self.PAD_L}" y="{self.PAD_T}" width="{self.iw}" '
               f'height="{self.ih}" fill="none" stroke="#c8ccd2" '
               f'stroke-width="2"/>'
               + "".join(self.parts) + "".join(self.badges) + '</svg>')
        # the SVG is scratch: it carries the page crop inline as base64, so
        # committing it would put a second copy of every pixel in the repo.
        tmp_svg = f"{TMP}/{name}.svg"
        open(tmp_svg, "w", encoding="utf8").write(svg)
        subprocess.run(["rsvg-convert", "-o", f"{OUT}/{name}.png", tmp_svg],
                       check=True)
        print(f"  {OUT}/{name}.png  ({self.W}x{self.H})")
        return f"{OUT}/{name}.png"


def sheet5():
    s = Sheet(5, (656, 62, 778, 258),
              "Sheet 5 — which FPGA ball carries which header net",
              "Block U1G, \"PL端BANK13\". One row per FPGA pin.", margin=960)
    y = s.note(s.PAD_T + 30, [
        ("How to read one row", True),
        ("ball designator and net label share a line;", False),
        ("the IO_Lxx pin name sits just below them.", False),
        ("A ball with no net label to its right is a", False),
        ("pad that goes nowhere.", False)], 880)
    rows = [("3V3_IO1", "V10", "IO_L20N", 7, 0), ("3V3_IO2", "U9", "IO_L16P", 9, 1),
            ("3V3_IO3", "U10", "IO_L12N", 11, 2), ("3V3_IO4", "T9", "IO_L12P", 13, 3)]
    marks = []
    for net, ball, pin, jp5, bit in rows:
        n = find(5, net)
        b = find(5, ball, near=(n[0], n[1]))
        marks.append((s.mark([b, n], GREEN), net, ball, pin, jp5, bit))
    marks.sort(key=lambda r: r[0][1])
    for i, (a, net, ball, pin, jp5, bit) in enumerate(marks):
        s.n += 1
        s.leader(a, s.callout(y + 96 + i * 150, [
            (f"{net}  =  ball {ball}", True),
            (f"FPGA pin {pin}  ·  JP5 pin {jp5}", False),
            (f"carries sample_gpio[{bit}]", False)], GREEN, 700, n=s.n), GREEN, n=s.n)
    s.n += 1
    anchors = [s.mark([find(5, b)], RED, dash=True, fill=0.16)
               for b in ("V7", "W9", "V11")]
    tgt = s.callout(y + 96 + 4 * 150 + 34, [
        ("V11, W9, V7 — NO CONNECT", True),
        ("Adjacent balls in the same bank, no net label:", False),
        ("these pads go nowhere. An early version of this", False),
        ("feature used all three. V11 is the nastiest — it", False),
        ("is IO_L20P, the other half of V10's pair. Vivado", False),
        ("built it cleanly: a wrong PACKAGE_PIN is not an", False),
        ("error, just a bitstream driving nothing.", False)], RED, 700, n=s.n)
    for a in anchors:
        s.leader(a, tgt, RED)
    s.badge(*[(a[0] + (tgt[0]-a[0])*0.42, (a[1]+tgt[1])/2) for a in anchors][1],
            s.n, RED)
    return s.save("schematic-sheet5-fpga-balls", [
        "The four nets leave the FPGA here and reappear on sheet 13 at connector "
        "JP5. Nothing else in the stock design",
        "touches them, which is why they were free to take."])


def sheet13():
    s = Sheet(13, (68, 198, 264, 318),
              "Sheet 13 — which JP5 header pin carries which net",
              "Odd pins down the left column, even pins down the right.",
              margin=980)
    y = s.note(s.PAD_T + 30, [
        ("How to read one row", True),
        ("a net label sits just above the wire it names;", False),
        ("the pin number sits just below that wire.", False)], 900)
    for i, (net, pin, bit) in enumerate(
            [("3V3_IO1", "7", 0), ("3V3_IO2", "9", 1),
             ("3V3_IO3", "11", 2), ("3V3_IO4", "13", 3)]):
        s.n += 1
        n = find(13, net)
        p = find(13, pin, near=(173.4, n[1] + 3.6))
        a1 = s.mark([n], GREEN)
        a2 = s.mark([p], GREEN, pad=1.1)
        s.link(a1, (a2[0] - (p[2] - p[0] + 2.2) * S, a2[1]), GREEN)
        s.leader(a2, s.callout(y + 80 + i * 130, [
            (f"{net}  →  JP5 pin {pin}", True),
            (f"the pad that carries sample_gpio[{bit}]", False)],
            GREEN, 720, n=s.n), GREEN, n=s.n)
    s.n += 1
    anchors = [s.mark([find(13, "GND", near=xy)], BLUE, pad=1.1, dash=True)
               for xy in ((237, 205), (237, 306))]
    tgt = s.callout(y + 80 + 4 * 130 + 30, [
        ("Cross-check — GND lands on pins 2 and 20", True),
        ("Labels sit a fixed distance above their pin row,", False),
        ("and only one choice of row is consistent: it", False),
        ("leaves exactly pins 2 and 20 for these two GND", False),
        ("symbols and puts the power rails on 1, 3 and 5.", False),
        ("Reading it the other way would ground pins 18", False),
        ("and 20 and shift every net by one pin.", False)], BLUE, 830, n=s.n)
    for a in anchors:
        s.leader(a, tgt, BLUE)
    return s.save("schematic-sheet13-jp5-pins", [
        "Ground your probe on pin 2 or 20. Pins 1/3/5 are power rails (5 V, 3.3 V, "
        "1.8 V) — do not drive them, and the even",
        "pins 4–18 are 1.8 V differential pairs. Which physical end of the "
        "connector is pin 1 is NOT on the schematic:",
        "find the square pad on the underside, or the silkscreen dot, before you "
        "clip anything on."])


def sheet1():
    s = Sheet(1, (498, 50, 642, 300),
              "Sheet 1 — bank 13's I/O supply, and why LVCMOS33 is right",
              "Each group of VCCO pins hangs off one power-rail symbol.",
              margin=900)
    y = s.note(s.PAD_T + 20, [
        ("What VCCO decides", True),
        ("VCCO is the supply for a bank's output drivers,", False),
        ("so it fixes the voltage those pins swing to. Get", False),
        ("the IOSTANDARD wrong and the pin drives the", False),
        ("wrong level — or nothing at all.", False)], 860)
    s.n += 1
    s.mark([find(1, "VCC3V3", near=(592, 61))], GREEN)
    a = s.mark([find(1, f"VCCO_13_{i}") for i in (1, 2, 3, 4)]
               + [find(1, b) for b in ("T8", "U11", "W7", "Y10")],
               GREEN, pad=1.4, fill=0.09)
    s.leader(a, s.callout(y + 90, [
        ("VCCO_13_1..4  =  VCC3V3", True),
        ("balls T8, U11, W7, Y10", True),
        ("Bank 13 runs its outputs at 3.3 V, so LVCMOS33", False),
        ("is correct for sample_gpio[3:0]. The rest of the", False),
        ("design declares LVCMOS25 on banks 34 and 35,", False),
        ("which this same sheet supplies from VCC1V8 — an", False),
        ("inconsistency inherited from ADI's stock Pluto", False),
        ("constraints, left alone because it works.", False)], GREEN, 740, n=s.n),
        GREEN, n=s.n)
    s.n += 1
    a = s.mark([find(1, "VCC1V8", near=(592, 111.6))]
               + [find(1, f"VCCO_34_{i}") for i in (1, 6)],
               GREY, dash=True, fill=0.06, pad=1.4)
    s.leader(a, s.callout(y + 90 + 380, [
        ("the next group down: bank 34 = VCC1V8", True),
        ("this is where the 3.3 V group stops.", False)], GREY, 740, n=s.n),
        GREY, n=s.n)
    s.n += 1
    a = s.mark([find(1, "VCC1V35")]
               + [find(1, f"VCCO_DDR_502_{i}") for i in (1, 10)],
               BLUE, dash=True, fill=0.07, pad=1.4)
    s.leader(a, s.callout(y + 90 + 530, [
        ("Cross-check — VCC1V35 feeds VCCO_DDR_502", True),
        ("DDR3L memory runs at 1.35 V and nothing else on", False),
        ("this board does. That only lines up if each rail", False),
        ("symbol feeds the group BELOW it — which is what", False),
        ("puts bank 13 on VCC3V3 and not on VCC1V8.", False)], BLUE, 740, n=s.n),
        BLUE, n=s.n)
    return s.save("schematic-sheet1-bank13-vcco", [
        "Six rail symbols, six VCCO groups, read top-down:",
        "    VCC3V3 → {VCCO_0, VCCO_13}        VCC1V8 → VCCO_34        "
        "VCC1V8 → VCCO_35",
        "    VCC1V35 → VCCO_DDR_502            VCC3V3 → VCCO_MIO0_500    "
        "VCC1V8 → VCCO_MIO1_500",
        "Every one of those is physically sensible. The opposite reading would put "
        "DDR3L memory on 3.3 V."])


if __name__ == "__main__":
    prepare()
    print("writing:")
    for f in (sheet5, sheet13, sheet1):
        f()
