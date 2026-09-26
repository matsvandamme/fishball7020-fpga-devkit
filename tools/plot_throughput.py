#!/usr/bin/env python3
"""Render the host-streaming throughput figures from measured data.

    # run from: the repo root
    python3 tools/plot_throughput.py docs/img/data/throughput.json

Draws two panels, light and dark, into docs/img/:

  left   throughput against libiio buffer size, for one and two receive
         channels, with the spread over repeats shown rather than hidden
  right  the sample rate each configuration can sustain, which is the same
         measurement divided by four bytes per complex sample

The point of the left panel is that the ceiling people quote for this board is
a property of the buffer they used, not of the board. Every point is the mean
of three runs of 33.6 Msamples each; the band is the full spread.
"""
from __future__ import annotations

import json
import textwrap
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# Blue against orange survives both deuteranopia and protanopia. Identity is
# also carried by marker shape and line style, so the pair reads in greyscale.
SERIES = {
    "1 receive channel": ("#1f6feb", "o", "-"),
    "2 receive channels": ("#d1690a", "s", "--"),
}
THEMES = {
    "light": dict(fg="#1c1e21", muted="#5b6470", grid="#e3e6ea", bg="white",
                  band=0.16),
    "dark": dict(fg="#e6e6e6", muted="#9aa4b2", grid="#2b3038", bg="#0d1117",
                 band=0.24),
}


def draw(data, theme_name, path):
    t = THEMES[theme_name]
    plt.rcParams.update({
        "font.size": 9, "text.color": t["fg"], "axes.labelcolor": t["fg"],
        "axes.edgecolor": t["muted"], "xtick.color": t["muted"],
        "ytick.color": t["muted"], "axes.facecolor": t["bg"],
        "figure.facecolor": t["bg"], "savefig.facecolor": t["bg"],
        "axes.spines.top": False, "axes.spines.right": False,
        "grid.color": t["grid"], "grid.linewidth": 0.7,
    })
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12.2, 4.4),
                                 gridspec_kw={"width_ratios": [1.45, 1],
                                              "wspace": 0.28})

    # ---- left: throughput against buffer size --------------------------
    for label, (colour, marker, style) in SERIES.items():
        pts = data["buffer_sweep"][label]
        x = np.array([p["buffer_samples"] for p in pts], dtype=float)
        mean = np.array([p["mean_mbs"] for p in pts])
        lo = np.array([p["min_mbs"] for p in pts])
        hi = np.array([p["max_mbs"] for p in pts])
        ax.fill_between(x, lo, hi, color=colour, alpha=t["band"], linewidth=0)
        ax.plot(x, mean, color=colour, linestyle=style, marker=marker,
                markersize=5, linewidth=2, label=label)

    ax.set_xscale("log", base=2)
    ax.set_xticks([1 << k for k in (14, 16, 18, 20, 22)])
    ax.set_xticklabels(["16K", "64K", "256K", "1M", "4M"])
    ax.set_xlabel("libiio buffer size, samples")
    ax.set_ylabel("throughput, MB/s")
    ax.grid(axis="y")
    ax.set_ylim(0, 55)

    # The claim the figure exists to correct, marked where it comes from.
    quoted = data["previously_quoted"]
    ax.axhline(quoted["mbs"], color=t["muted"], linewidth=1.1,
               linestyle=(0, (4, 3)))
    ax.annotate("a small buffer costs you two thirds\nof the rate, on any link",
                xy=(quoted["buffer_samples"], quoted["mbs"]),
                xytext=(26000, 8.5), fontsize=8, color=t["fg"],
                arrowprops=dict(arrowstyle="->", color=t["muted"], lw=1))

    plateau = data["plateau_mbs"]
    ax.annotate(f"plateau ≈ {plateau:.0f} MB/s", xy=(2_097_152, plateau),
                xytext=(0, 9), textcoords="offset points", ha="center",
                fontsize=8, color=t["fg"], fontweight="bold")

    ax.annotate("where this plateau sits depends on your link.\n"
                "that it MOVES with the buffer does not.",
                xy=(0.5, 0.97), xycoords="axes fraction", ha="center",
                va="top", fontsize=8, color=t["muted"], linespacing=1.4)

    ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    ax.set_title("Streaming to a host? Raise the buffer.",
                 loc="left", fontsize=10.5, color=t["fg"], pad=8)

    # ---- right: what that means in samples per second -------------------
    cfg = data["configurations"]
    names = [c["name"] for c in cfg]
    vals = [c["msps_per_channel"] for c in cfg]
    meas = [c["measured"] for c in cfg]
    pos = np.arange(len(names))

    # Measured bars solid; derived bars hollow and hatched, so the two are
    # never mistaken for each other.
    for i, (v, m) in enumerate(zip(vals, meas)):
        if m:
            bx.barh(pos[i], v, height=0.6, color="#1f6feb",
                    edgecolor=t["bg"], linewidth=1)
        else:
            bx.barh(pos[i], v, height=0.6, color="none", edgecolor="#d1690a",
                    linewidth=1.4, hatch="///")
        bx.annotate(f"{v:.1f}", (v, pos[i]), xytext=(5, 0),
                    textcoords="offset points", va="center", fontsize=8.5,
                    color=t["fg"], fontweight="bold")

    bx.set_yticks(pos)
    bx.set_yticklabels(names, fontsize=8.5)
    bx.invert_yaxis()
    bx.set_xlabel("sustained sample rate per channel, MS/s")
    bx.grid(axis="x")
    bx.set_xlim(0, max(max(vals), data["radio_msps"]) * 1.16)
    bx.set_title("What the board can do, and what the link allows",
                 loc="left", fontsize=10.5, color=t["fg"], pad=8)

    # Inside the axes, in the empty space the short bars leave, rather than
    # floating in the margin below the figure.
    radio = data["radio_msps"]
    bx.axvline(radio, color=t["muted"], linewidth=1.1, linestyle=(0, (4, 3)))
    bx.annotate(f"converter\n{radio:.2f} MS/s", xy=(radio, len(names) - 0.4),
                xytext=(-4, 0), textcoords="offset points", ha="right",
                va="bottom", fontsize=7.5, color=t["muted"], linespacing=1.3)
    bx.annotate("the top two are what the BOARD does, with\n"
                "no network in the way. the hatched bar is\n"
                "one example link, not a specification.",
                xy=(0.60, 0.46), xycoords="axes fraction", ha="center",
                va="top", fontsize=8, color=t["muted"], linespacing=1.45)

    fig.text(0.012, -0.02, "\n".join(textwrap.wrap(data["footnote"], 118)),
             fontsize=7.2, color=t["muted"], va="top")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def main(argv):
    with open(argv[1]) as f:
        data = json.load(f)
    for theme in THEMES:
        draw(data, theme, f"docs/img/throughput-{theme}.svg")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
