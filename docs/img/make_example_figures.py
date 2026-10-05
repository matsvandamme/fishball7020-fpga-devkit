#!/usr/bin/env python3
"""Make light and dark copies of the figures the automation examples drew.

The examples (tools/automation/examples/) write SVGs that follow the viewer's
system theme. The docs site switches theme itself, so each figure here gets a
fixed -light and -dark copy. The sources in docs/img/data/ are the examples'
own output from real runs, unedited:

    data/clock-stress-2026-10-05.svg   clock_stress.py, one board, TX1 -> 20 dB -> RX1

Usage:  python3 make_example_figures.py
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "tools" / "automation" / "examples"))
from svgplot import retheme   # noqa: E402

FIGURES = {
    "clock-stress-2026-10-05.svg": "automation-clock-stress",
}

for source, name in FIGURES.items():
    svg = (HERE / "data" / source).read_text()
    for theme in ("light", "dark"):
        (HERE / f"{name}-{theme}.svg").write_text(retheme(svg, theme))
    print(f"wrote {name}-{{light,dark}}.svg")
