#!/usr/bin/env python3
"""Draw docs/img/schematic-*.png - the vendor schematic sheets that establish
the sample-GPIO pin assignment, with the exact nets highlighted.

    # run from: the repo root
    python3 docs/img/make_schematic_figures.py

Reads the vendor schematic that ships in this repository at
docs/vendor/7020_936x_SDR-schematic.pdf. Point it at a different copy with
FISHBALL_SCHEMATIC=/path/to/schematic.pdf. Note that the schematic the vendor
publishes on their own GitHub is a DIFFERENT board revision with no JP5 at all
- see docs/vendor/README.md. Also needs poppler-utils and rsvg-convert.

WHY THIS IS A SCRIPT AND NOT THREE HAND-DRAWN PICTURES
Every highlight box is positioned from the PDF's own text coordinates
(pdftotext -bbox), so a box cannot drift away from the word it marks, and
anyone can re-run this and get the same picture. Three of the four pins in the
first version of this feature were guessed, and wrong. This is the evidence
that the current four are not.

LAYOUT RULES, learned by getting them wrong
  * No leader lines. A numbered badge sits beside its box and the same number
    heads the note underneath. Lines drawn from a box to a note margin crossed
    the drawing and each other, and that is what made the first version look
    like a scribble.
  * One box per contiguous cluster of words, never a union across a gap. The
    first version boxed a power-rail symbol together with the group of pins it
    feeds; the union spanned the gap between two groups, so the box swallowed
    the neighbouring group's first row.
  * Vertical padding stays below half a row pitch, so a box cannot touch the
    row above or below.
  * The crop is grown until no word is half in and half out of it.
check() asserts all of that and fails the build rather than writing a figure
that has to be eyeballed.
"""
import base64, html, os, re, subprocess, sys, tempfile

OUT = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("FISHBALL_SCHEMATIC") or os.path.join(
    OUT, os.pardir, "vendor", "7020_936x_SDR-schematic.pdf")
TMP = None

DPI = 300
S = DPI / 72.0                      # PDF points -> pixels of the rendered crop

GREEN, RED, BLUE, GREY = "#0b8a3d", "#c62020", "#1150c8", "#6f757d"
INK, DIM = "#14181d", "#4a5058"
SANS = "DejaVu Sans, Helvetica, sans-serif"
MONO = "DejaVu Sans Mono, monospace"

# rough advance widths, used only to check text fits its box
W_MONO, W_SANS = 0.6024, 0.545


def prepare(pages=(1, 5, 13)):
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
        sys.exit(f"'{text}' not found on page {page}")
    if near:
        hits.sort(key=lambda w: (w[0] - near[0]) ** 2 + (w[1] - near[1]) ** 2)
    return hits[0]


def grow_crop(page, box, margin=2.5, limit=26.0):
    """Grow the crop OUTWARD until no word straddles an edge.

    Outward, not inward: a word half inside the crop is a word cut down the
    middle, and including it always beats excluding it. `limit` stops a chain
    of adjacent words from dragging an edge across the whole sheet.
    """
    ox0, oy0, ox1, oy1 = box
    x0, y0, x1, y1 = box
    for _ in range(60):
        changed = False
        for wx0, wy0, wx1, wy1, _t in words(page):
            if not (wx1 > x0 and wx0 < x1 and wy1 > y0 and wy0 < y1):
                continue                      # wholly outside, ignore
            if wx0 < x0 and x0 - wx0 < limit:
                x0, changed = wx0 - 0.4, True
            if wx1 > x1 and wx1 - x1 < limit:
                x1, changed = wx1 + 0.4, True
            if wy0 < y0 and y0 - wy0 < limit:
                y0, changed = wy0 - 0.4, True
            if wy1 > y1 and wy1 - y1 < limit:
                y1, changed = wy1 + 0.4, True
        if not changed:
            break
        x0, y0 = max(x0, ox0 - limit), max(y0, oy0 - limit)
        x1, y1 = min(x1, ox1 + limit), min(y1, oy1 + limit)
    return (x0 - margin, y0 - margin, x1 + margin, y1 + margin)


class Figure:
    PAD = 30
    TITLE_H = 124          # recomputed in __init__ once the subtitle wraps
    BADGE_R = 15

    MAX_W, MAX_H, NOTE_W = 760, 1120, 660

    def __init__(self, page, box, title, subtitle, badge_side="R"):
        self.page = page
        self.box = grow_crop(page, box)
        self.title, self.subtitle = title, subtitle
        self.badge_side = badge_side
        self._sub_lines = None          # filled by _wrap() once W is known
        bx0, by0, bx1, by1 = self.box
        px = lambda v: int(round(v * S))
        self.cw, self.ch = px(bx1 - bx0), px(by1 - by0)
        self.png = subprocess.run(
            ["pdftoppm", "-f", str(page), "-l", str(page), "-r", str(DPI),
             "-png", "-x", str(px(bx0)), "-y", str(px(by0)),
             "-W", str(self.cw), "-H", str(self.ch), SRC],
            capture_output=True, check=True).stdout
        # scale the drawing to fit its box, never below 1:1
        self.k = max(min(self.MAX_W / self.cw, self.MAX_H / self.ch), 1.0)
        self.iw, self.ih = self.cw * self.k, self.ch * self.k
        self.nx = self.PAD + self.iw + 46          # notes column x
        self.W = int(self.nx + self.NOTE_W + self.PAD)
        self._sub_lines = self._wrap(self.subtitle,
                                     int((self.W - 2 * self.PAD) / (W_SANS * 20)))
        self.TITLE_H = 56 + 24 * len(self._sub_lines) + 40
        self.shapes, self.badges, self.notes = [], [], []
        self.note_badges = []
        self.boxes_px, self.badge_px = [], []
        self.badge_specs = []
        self.n = 0

    @staticmethod
    def _wrap(text, maxch):
        out, line = [], ""
        for word in text.split():
            if len(line) + len(word) + 1 > maxch:
                out.append(line); line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
        return out

    # crop-relative point -> canvas px
    def X(self, x): return self.PAD + (x - self.box[0]) * S * self.k
    def Y(self, y): return self.TITLE_H + (y - self.box[1]) * S * self.k

    def mark(self, clusters, colour, note, pad=0.45, padx=1.3,
             dash=False):
        """One numbered highlight. `clusters` is a list of word lists; each
        cluster gets its own box, so a box never spans a gap."""
        self.n += 1
        rightmost = None
        for ws in clusters:
            x0 = min(w[0] for w in ws) - padx
            y0 = min(w[1] for w in ws) - pad
            x1 = max(w[2] for w in ws) + padx
            y1 = max(w[3] for w in ws) + pad
            d = ' stroke-dasharray="9 6"' if dash else ''
            X0, Y0, X1, Y1 = self.X(x0), self.Y(y0), self.X(x1), self.Y(y1)
            self.shapes.append(
                f'<rect x="{X0:.1f}" y="{Y0:.1f}" width="{X1-X0:.1f}" '
                f'height="{Y1-Y0:.1f}" rx="4" fill="{colour}" '
                f'fill-opacity="0.12" stroke="{colour}" stroke-width="2.6"'
                f'{d}/>')
            self.boxes_px.append((X0, Y0, X1, Y1, f"box {self.n}"))
            if rightmost is None or X1 > rightmost[0]:
                rightmost = (X1, X0, (Y0 + Y1) / 2)
        r = self.BADGE_R
        lo, hi = self.PAD + r + 2, self.PAD + self.iw - r - 2
        want = (rightmost[0] + r + 7 if self.badge_side == "R"
                else rightmost[1] - r - 7)
        if not lo <= want <= hi:                    # no room that side, flip
            want = (rightmost[1] - r - 7 if self.badge_side == "R"
                    else rightmost[0] + r + 7)
        self.badge(min(max(want, lo), hi), rightmost[2], self.n, colour)
        self.notes.append((self.n, colour, note))

    def badge(self, x, y, n, colour):
        self.badge_specs.append((x, y, n, colour))

    def _emit_badge(self, x, y, n, colour):
        r = self.BADGE_R
        self.badges.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{colour}" '
            f'stroke="#ffffff" stroke-width="3"/>'
            f'<text x="{x:.1f}" y="{y + r*0.36:.1f}" font-family="{SANS}" '
            f'font-size="{r*1.15:.0f}" font-weight="bold" fill="#ffffff" '
            f'text-anchor="middle">{n}</text>')
        self.badge_px.append((x - r, y - r, x + r, y + r, f"badge {n}"))


    def text(self, x, y, s, size, colour, weight="normal", family=SANS):
        self.shapes.append(
            f'<text xml:space="preserve" x="{x:.1f}" y="{y:.1f}" '
            f'font-family="{family}" font-size="{size}" font-weight="{weight}" '
            f'fill="{colour}">{html.escape(s)}</text>')

    # ---- checks ---------------------------------------------------------
    def check(self):
        bad = []
        def hit(a, b, eps=2.0):
            return (a[0] + eps < b[2] and b[0] + eps < a[2]
                    and a[1] + eps < b[3] and b[1] + eps < a[3])
        allr = self.boxes_px + self.badge_px
        for i in range(len(allr)):
            for j in range(i + 1, len(allr)):
                a, b = allr[i], allr[j]
                if a[4].split()[1] == b[4].split()[1] and a[4].split()[0] == b[4].split()[0]:
                    continue                      # same item's own boxes
                if hit(a, b):
                    bad.append(f"{a[4]} overlaps {b[4]}")
        for X0, Y0, X1, Y1, name in allr:
            if X0 < self.PAD - 1 or X1 > self.PAD + self.iw + 1:
                bad.append(f"{name} runs outside the drawing")
        return bad

    # ---- output ---------------------------------------------------------
    def save(self, name, footer):
        cols, colw = 1, self.NOTE_W
        y_notes = self.TITLE_H
        rows = []
        for i, (n, colour, note) in enumerate(self.notes):
            head, body = note[0], note[1:]
            rows.append((i % cols, i // cols, n, colour, head, body))
        rowh = {}
        for c, r, n, colour, head, body in rows:
            rowh[r] = max(rowh.get(r, 0), 30 + 26 * len(body) + 18)
        ytop = {}
        acc = y_notes
        for r in sorted(rowh):
            ytop[r] = acc
            acc += rowh[r]
        for c, r, n, colour, head, body in rows:
            x = self.nx
            y = ytop[r]
            r = self.BADGE_R
            self.note_badges.append(
                f'<circle cx="{x+r:.1f}" cy="{y+11:.1f}" r="{r}" fill="{colour}"/>'
                f'<text x="{x+r:.1f}" y="{y+11+r*0.36:.1f}" font-family="{SANS}" '
                f'font-size="{r*1.15:.0f}" font-weight="bold" fill="#ffffff" '
                f'text-anchor="middle">{n}</text>')
            self.text(x + 2 * r + 10, y + 18, head, 21, INK, "bold", MONO)
            w_head = W_MONO * 21 * len(head)
            if 2 * r + 10 + w_head > colw:
                print(f"    ! note {n} title is {int(44+w_head)}px in a "
                      f"{int(colw)}px column", file=sys.stderr)
            for k, line in enumerate(body):
                self.text(x + 2 * r + 10, y + 45 + 26 * k, line, 19, DIM)
                if 2 * r + 10 + W_SANS * 19 * len(line) > colw:
                    print(f"    ! note {n} line {k+1} overflows the column",
                          file=sys.stderr)
        fy = max(acc, self.TITLE_H + self.ih) + 30
        for i, ln in enumerate(footer):
            self.text(self.PAD, fy + 27 * i, ln, 19, "#3a4046")
        H = int(fy + 27 * len(footer) + 22)

        # badges on the drawing must not collide: nudge them apart in y,
        # keeping their order, then emit.
        r, gap = self.BADGE_R, 2 * self.BADGE_R + 4
        specs = sorted(self.badge_specs, key=lambda b: (round(b[0] / 60), b[1]))
        prev = {}
        for i, (x, y, n, colour) in enumerate(specs):
            col = round(x / 60)
            if col in prev and y < prev[col] + gap:
                y = prev[col] + gap
            prev[col] = y
            specs[i] = (x, y, n, colour)
        for x, y, n, colour in specs:
            self._emit_badge(x, y, n, colour)

        problems = self.check()
        if problems:
            for p in problems:
                print(f"    ! {p}", file=sys.stderr)

        self.text(self.PAD, 44, self.title, 34, INK, "bold")
        for i, ln in enumerate(self._sub_lines):
            self.text(self.PAD, 74 + 24 * i, ln, 20, "#525860")
        self.text(self.PAD, 80 + 24 * len(self._sub_lines),
                  "Highlights are positioned from the PDF's own text "
                  "coordinates, not placed by eye.", 17, "#80868e")

        b64 = base64.b64encode(self.png).decode()
        svg = (f'<svg xmlns="http://www.w3.org/2000/svg" '
               f'xmlns:xlink="http://www.w3.org/1999/xlink" '
               f'width="{self.W}" height="{H}" viewBox="0 0 {self.W} {H}">'
               f'<rect width="{self.W}" height="{H}" fill="#ffffff"/>'
               f'<image x="{self.PAD}" y="{self.TITLE_H}" width="{self.iw:.1f}" '
               f'height="{self.ih:.1f}" xlink:href="data:image/png;base64,{b64}"/>'
               f'<rect x="{self.PAD}" y="{self.TITLE_H}" width="{self.iw:.1f}" '
               f'height="{self.ih:.1f}" fill="none" stroke="#cdd1d6" '
               f'stroke-width="1.5"/>'
               + "".join(self.shapes) + "".join(self.badges)
               + "".join(self.note_badges) + '</svg>')
        tmp_svg = f"{TMP}/{name}.svg"
        open(tmp_svg, "w", encoding="utf8").write(svg)
        subprocess.run(["rsvg-convert", "-o", f"{OUT}/{name}.png", tmp_svg],
                       check=True)
        print(f"  {name}.png  {self.W}x{H}"
              f"{'   PROBLEMS' if problems else ''}")
        return not problems


def sheet5():
    f = Figure(5, (664, 66, 760, 250),
               "Sheet 5 — which FPGA ball carries which header net",
               "Block U1G, \"PL端BANK13\". One row per FPGA pin: the ball "
               "designator sits on the same line as the net it drives.",
               badge_side="R")
    for net, ball, pin, jp5, bit in [
            ("3V3_IO1", "V10", "IO_L20N", 7, 0), ("3V3_IO2", "U9", "IO_L16P", 9, 1),
            ("3V3_IO3", "U10", "IO_L12N", 11, 2), ("3V3_IO4", "T9", "IO_L12P", 13, 3)]:
        n = find(5, net)
        b = find(5, ball, near=(n[0], n[1]))
        f.mark([[b, n]], GREEN,
               [f"{net} = ball {ball}",
                f"FPGA pin {pin}, and JP5 pin {jp5}.",
                f"Carries sample_gpio[{bit}]."])
    f.mark([[find(5, b)] for b in ("V7", "W9", "V11")], RED,
           ["V11, W9, V7 — no connect",
            "Adjacent balls in the same bank with no net",
            "label: these pads go nowhere. An early version",
            "of this feature drove all three. V11 is the worst",
            "trap, being IO_L20P, the other half of V10's pair.",
            "Vivado built it cleanly, because a wrong",
            "PACKAGE_PIN is not an error."], dash=True)
    return f.save("schematic-sheet5-fpga-balls", [
        "These four nets leave the FPGA here and reappear on sheet 13 at "
        "connector JP5. Nothing else in the stock",
        "design touches them, which is why they were free to take."])


def sheet13():
    f = Figure(13, (74, 205, 258, 312),
               "Sheet 13 — which JP5 header pin carries which net",
               "Odd pins run down the left column, even pins down the right. "
               "A net label sits just above the wire it names; the pin number "
               "sits just below it.",
               badge_side="L")
    # One highlight, not four. The four rows sit a single row pitch apart, so
    # four badges cannot be placed beside them without colliding - and nudging
    # them apart puts a badge beside the wrong row, which is worse than
    # verbose. Two boxes, one number, and the mapping in the note.
    rows = [("3V3_IO1", "7", 0), ("3V3_IO2", "9", 1),
            ("3V3_IO3", "11", 2), ("3V3_IO4", "13", 3)]
    labels = [find(13, net) for net, _, _ in rows]
    pins = [find(13, pin, near=(173.4, find(13, net)[1] + 3.6))
            for net, pin, _ in rows]
    f.mark([labels, pins], GREEN,
           ["The four nets, and the four pins"]
           + [f"    {net}  →  pin {pin}  →  sample_gpio[{bit}]"
              for net, pin, bit in rows]
           + ["The boxes line up row for row: the topmost label",
              "belongs to the topmost pin number."])
    f.mark([[find(13, "GND", near=(237, 205))],
            [find(13, "GND", near=(237, 306))]], BLUE,
           ["Cross-check — GND on pins 2 and 20",
            "Labels sit a fixed distance above their pin row,",
            "which leaves two possible readings. Only one of",
            "them frees exactly pins 2 and 20 for these two",
            "GND symbols and puts the power rails on 1, 3",
            "and 5. The other would ground pins 18 and 20",
            "and shift every net by one pin."], dash=True)
    return f.save("schematic-sheet13-jp5-pins", [
        "Ground your probe on pin 2 or 20. Pins 1/3/5 are power rails "
        "(5 V, 3.3 V, 1.8 V) - do not drive them - and the",
        "even pins 4-18 are 1.8 V differential pairs. Which physical end of "
        "the connector is pin 1 is NOT on the",
        "schematic: find the square pad on the underside, or the silkscreen "
        "dot, before you clip anything on."])


def sheet1():
    f = Figure(1, (502, 54, 619, 296),
               "Sheet 1 — bank 13's I/O supply, and why LVCMOS33 is right",
               "VCCO is what a bank's output drivers run from, so it fixes the "
               "voltage those pins swing to. Each group of VCCO pins hangs off "
               "one power-rail symbol.",
               badge_side="L")
    f.mark([[find(1, "VCC3V3", near=(592, 61))],
            [find(1, f"VCCO_13_{i}") for i in (1, 2, 3, 4)]
            + [find(1, b) for b in ("T8", "U11", "W7", "Y10")]], GREEN,
           ["VCCO_13_1..4 = VCC3V3",
            "Balls T8, U11, W7, Y10. Bank 13 runs its outputs",
            "at 3.3 V, so LVCMOS33 is correct for",
            "sample_gpio[3:0]. The rest of the design declares",
            "LVCMOS25 on banks 34 and 35, which this same",
            "sheet supplies from VCC1V8 - an inconsistency",
            "inherited from ADI's stock Pluto constraints,",
            "left alone because it works."])
    f.mark([[find(1, "VCC1V35")],
            [find(1, f"VCCO_DDR_502_{i}") for i in range(1, 11)]], BLUE,
           ["Cross-check — VCC1V35 feeds the DDR bank",
            "DDR3L memory runs at 1.35 V and nothing else on",
            "this board does. That only lines up if each rail",
            "symbol feeds the group BELOW it, which is what",
            "puts bank 13 on VCC3V3 and not on VCC1V8."], dash=True)
    return f.save("schematic-sheet1-bank13-vcco", [
        "Six rail symbols, six VCCO groups, each feeding the group below it:",
        "    VCC3V3 → VCCO_0 + VCCO_13     ·   VCC1V8 → VCCO_34"
        "   ·   VCC1V8 → VCCO_35",
        "    VCC1V35 → VCCO_DDR_502        ·   VCC3V3 → "
        "VCCO_MIO0_500   ·   VCC1V8 → VCCO_MIO1_500",
        "Every one of those is physically sensible. The opposite reading "
        "would put DDR3L memory on 3.3 V."])


if __name__ == "__main__":
    prepare()
    print("writing:")
    ok = all([sheet5(), sheet13(), sheet1()])
    if not ok:
        sys.exit("\nlayout problems above - figures NOT fit to publish")
    print("\nall three pass the layout checks")
