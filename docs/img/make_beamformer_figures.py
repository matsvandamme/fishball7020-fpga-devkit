#!/usr/bin/env python3
"""Draw the two-board beamformer's set-up, in the site's figure style (helpers
from make_start_figures.py), and the light/dark copies of its measured figures.

    # run from: the repo root
    python3 docs/img/make_beamformer_figures.py        # stdlib only

Writes into docs/img/:

    beamformer-setup-{light,dark}.svg     one GPSDO, two boards, four elements, a beacon
    beamformer-emulate-{light,dark}.svg   examples/beamformer.py --emulate on one board, 2026-10-05
    beamformer-check-{light,dark}.svg     its lock check, the same run

The set-up is what docs/radio/beamform-two-boards.md describes; the two
measured figures are the script's own output (docs/img/data/), unedited.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "tools" / "automation" / "examples"))
from make_start_figures import Fig, both   # noqa: E402
from svgplot import retheme                 # noqa: E402


def setup(t):
    f = Fig(900, 400, t)
    f.text(110, 42, "GPS antenna", 12, "muted")
    f.line(110, 48, 110, 68, "muted", 1.6)
    f.box(20, 70, 180, 92, "LBE-1421 GPSDO", ("OUT1 and OUT2: 40 MHz", "3.3 V CMOS, 50 Ω"),
          fill="accent_soft", stroke="accent")
    for y, board, sub in ((50, "Board A", ("RX1, RX2: elements 1, 2", "TX1: the beacon")),
                          (230, "Board B", ("RX1, RX2: elements 3, 4",))):
        f.box(250, y + 32, 150, 56, "DC block + 20 dB", "about 0.65 V p-p")
        f.box(440, y, 200, 120, board, ("EXT_CLK in:", "R107 empty, R109 fitted") + sub,
              fill="ok_soft", stroke="ok")
        f.arrow(200, 116 if y == 50 else 140, 248, y + 60, colour="accent")
        f.arrow(400, y + 60, 438, y + 60, colour="accent")
    # the line array: four elements, evenly half a wavelength apart, facing the beacon
    ex, ey = 760, (125, 185, 245, 305)
    leads = ((640, 80), (640, 140), (640, 260), (640, 320))
    for i, ((lx, ly), y) in enumerate(zip(leads, ey)):
        mx = 690 + 12 * (i if i < 2 else 3 - i)
        f.raw(f'<polyline points="{lx},{ly} {mx},{ly} {mx},{y} {ex},{y}" fill="none" '
              f'stroke="{t["ink"]}" stroke-width="1.4"/>')
        f.raw(f'<path d="M{ex + 14} {y - 10} L{ex} {y} L{ex + 14} {y + 10}" stroke="{t["ink"]}" '
              f'stroke-width="1.8" fill="none"/>')
        f.text(ex - 8, y - 8, f"{i + 1}", 12.5, "ink", 600, "end")
    f.raw(f'<line x1="{ex + 22}" y1="{ey[0]}" x2="{ex + 22}" y2="{ey[-1]}" stroke="{t["muted"]}" '
          f'stroke-width="1" stroke-dasharray="3 3"/>')
    f.text(ex - 10, 345, "λ/2 apart: 61 mm at 2450 MHz", 12, "muted", 400, "middle")
    # the beacon, broadside to the array, fed from board A's TX1 over the top
    bx, by = 880, 215
    f.raw(f'<polyline points="540,50 540,20 {bx},20 {bx},{by}" fill="none" stroke="{t["danger"]}" '
          f'stroke-width="1.4"/>')
    f.raw(f'<path d="M{bx - 14} {by - 10} L{bx} {by} L{bx - 14} {by + 10}" stroke="{t["danger"]}" '
          f'stroke-width="1.8" fill="none"/>')
    f.text(bx, 371, "beacon: board A's TX1,", 12, "danger", 500, "end")
    f.text(bx, 385, "broadside, 1 m or more away", 12, "danger", 500, "end")
    f.text(110, 220, "Network: both boards and", 12, "muted")
    f.text(110, 236, "the PC running beamformer.py", 12, "muted")
    return f


def main():
    both("beamformer-setup", "Two boards on one GPS-disciplined reference, as one four-element receive array", setup)
    for source, name in (("beamformer-emulate-2026-10-05.svg", "beamformer-emulate"),
                         ("beamformer-check-2026-10-05.svg", "beamformer-check")):
        svg = (HERE / "data" / source).read_text()
        for theme in ("light", "dark"):
            (HERE / f"{name}-{theme}.svg").write_text(retheme(svg, theme))
    print("wrote beamformer-{setup,emulate,check}-{light,dark}.svg")


if __name__ == "__main__":
    main()
