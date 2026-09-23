#!/usr/bin/env python3
"""One instrument-panel theme for every figure, and a non-aliasing spectrum plot."""
import numpy as np, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import rcParams

BG      = "#0f1218"
PANEL   = "#151b25"
GRID    = "#232c3c"
INK     = "#E6EAF2"
INK2    = "#98A3B8"
INK3    = "#6B7585"
# Validated in palette.py: min normal-vision dE 15.7, min CVD separation 20.4,
# contrast 7.1-10.6:1 against BG.
BLUE, AMBER, GREEN, PINK, VIOLET, TEAL = ("#4DA3FF", "#FFB454", "#5BD99A",
                                          "#FF7AB6", "#B69BFF", "#34D3CB")
TIER = {"simple": TEAL, "moderate": BLUE, "complex": AMBER}


def apply():
    rcParams.update({
        "figure.facecolor": BG, "axes.facecolor": PANEL, "savefig.facecolor": BG,
        "text.color": INK, "axes.labelcolor": INK2, "axes.edgecolor": GRID,
        "xtick.color": INK3, "ytick.color": INK3,
        "grid.color": GRID, "grid.linewidth": 0.6, "axes.grid": True,
        "font.family": "DejaVu Sans", "font.size": 9,
        "axes.titlesize": 10.5, "axes.titleweight": "semibold",
        "axes.spines.top": False, "axes.spines.right": False,
        "legend.frameon": False, "figure.dpi": 150,
        "axes.axisbelow": True, "lines.antialiased": True,
    })


def envelope(x, y, npix=1100):
    """Per-pixel min/max of a dense trace.

    Matplotlib draws a line by joining the points it is given; with 32 768
    spectrum bins across 1 100 pixels that decimates the trace on screen and the
    noise floor gets thinner and lower than it really is - display aliasing, the
    same folding the receive chain was designed to avoid, happening in the plot.
    Reducing by per-pixel min and max keeps the true extent of every pixel column.
    """
    idx = np.linspace(0, len(x), npix + 1).astype(int)
    xs, lo, hi = [], [], []
    for a, b in zip(idx[:-1], idx[1:]):
        if b <= a:
            continue
        xs.append(x[(a + b) // 2]); lo.append(y[a:b].min()); hi.append(y[a:b].max())
    return np.array(xs), np.array(lo), np.array(hi)


def spectrum(ax, f, p, color, floor=None, label=None, lw=0.9):
    xs, lo, hi = envelope(f / 1e6, p)
    ax.fill_between(xs, lo, hi, color=color, alpha=0.35, lw=0, zorder=3)
    ax.plot(xs, hi, color=color, lw=lw, zorder=4, label=label,
            solid_joinstyle="round")
    if floor is not None:
        ax.axhline(floor, color=INK3, lw=0.8, ls=(0, (4, 3)), zorder=2)
    return ax


def stamp(fig, left, right=None):
    fig.text(0.008, 0.012, left, color=INK3, fontsize=7.5, ha="left", va="bottom")
    if right:
        fig.text(0.992, 0.012, right, color=INK3, fontsize=7.5, ha="right", va="bottom")
