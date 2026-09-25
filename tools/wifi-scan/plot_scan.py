#!/usr/bin/env python3
"""Draw the pictures for a scan recorded by wifi_scan.py.

    # run from: tools/wifi-scan/
    ./plot_scan.py scan.json                 # writes scan-2.4.png, scan-5.png

Two panels per band, because they answer two different questions.

The SPECTRUM panel answers "what is actually on the air": every 100 kHz of the
band, the loudest thing seen during the sweep (filled) and the long-term average
(line). A Wi-Fi carrier appears as a flat-topped hump about 20 MHz wide - that
shape is the giveaway, and it is why this panel is worth reading before the bars.

The OCCUPANCY panel answers "what would a device on channel N have to put up
with": the strongest thing anywhere inside that channel's own 20 MHz, measured
against the band's noise floor. In the 2.4 GHz band the channels OVERLAP - they
are spaced 5 MHz apart and each is 20 MHz wide - so one transmitter necessarily
raises four or five neighbouring bars. That is not a bug in the measurement, it
is the reason 1, 6 and 11 are the only non-overlapping choices, and the panel
shows you exactly why.

Identity never rests on colour alone here: max-hold is a filled area and the
average is a line, so the two are distinguishable in greyscale, in print and to
a reader with any form of colour blindness.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator

# Blue against orange is the pair that survives both deuteranopia and
# protanopia; the greys are text and grid, never a series.
C_MAX, C_AVG, C_BAR = "#1f6feb", "#0b3d91", "#1f6feb"
C_INK, C_MUTED, C_GRID, C_FLOOR = "#1c1e21", "#6b7280", "#e5e7eb", "#9ca3af"

UNII = [(36, 48, "U-NII-1"), (52, 64, "U-NII-2A"),
        (100, 140, "U-NII-2C"), (149, 165, "U-NII-3")]

# Occupancy is recomputed here from the stored traces rather than read out of
# the file, so there is exactly one definition of it and an older scan gets the
# current one.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wifi_scan import occupancy, CHANNELS_24, CHANNELS_5     # noqa: E402


def style():
    plt.rcParams.update({
        "font.size": 9, "axes.edgecolor": C_MUTED, "axes.labelcolor": C_INK,
        "text.color": C_INK, "xtick.color": C_MUTED, "ytick.color": C_MUTED,
        "axes.spines.top": False, "axes.spines.right": False,
        "grid.color": C_GRID, "grid.linewidth": 0.6,
        "figure.facecolor": "white", "axes.facecolor": "white",
    })


def draw_band(st, band, path):
    f = np.asarray(st["freq_mhz"])
    mx = np.asarray(st["max_dbfs"])
    av = np.asarray(st["avg_dbfs"])
    plan = CHANNELS_24 if band == "2.4" else CHANNELS_5
    chans, floor, floor_max = occupancy(st, plan)

    # height_ratios as a subplots() keyword needs matplotlib 3.6; this works on
    # 3.5 too, which is what Ubuntu 22.04 ships.
    fig, (ax, bx) = plt.subplots(
        2, 1, figsize=(13, 7.6),
        gridspec_kw={"hspace": 0.34, "height_ratios": [1.35, 1]})

    # ---- panel 1: the spectrum ------------------------------------------
    ax.fill_between(f, floor - 6, mx, color=C_MAX, alpha=0.30, linewidth=0,
                    label="loudest seen (max-hold)")
    ax.plot(f, mx, color=C_MAX, linewidth=1.0)
    ax.plot(f, av, color=C_AVG, linewidth=1.6, label="long-term average")
    # Named in the legend rather than annotated on the trace: wherever the line
    # is drawn, the average trace is sitting on it, so any inline label collides.
    ax.axhline(floor, color=C_FLOOR, linewidth=1.2, linestyle=(0, (4, 3)),
               label=f"noise floor, {floor:.0f} dBFS")

    # the channel plan, as light bands behind everything
    for ch, v in sorted(chans.items()):
        c = v["centre_mhz"]
        ax.axvspan(c - 10, c + 10, color=C_MUTED, alpha=0.035, linewidth=0)
        ax.plot([c, c], [floor - 6, floor - 3], color=C_MUTED, linewidth=0.8)

    top = float(np.nanmax(mx))
    ax.set_ylim(floor - 7, top + 7)
    ax.set_xlim(f[0], f[-1])
    ax.set_ylabel("level, dBFS")
    ax.grid(axis="y")
    ax.legend(loc="upper left", frameon=False, fontsize=8)
    ax.set_title(f"{band} GHz band as this board hears it     "
                 f"{st['rbw_hz']/1e3:.0f} kHz resolution · "
                 f"{st['gain_db']:.0f} dB gain · "
                 f"{len(st['lo_mhz'])} tunings · {st['seconds']:.0f} s",
                 loc="left", fontsize=10, color=C_INK, pad=10)

    # name the loudest few humps directly on the trace
    order = np.argsort(mx)[::-1]
    shown = []
    for i in order:
        if mx[i] < floor + 12:
            break
        if all(abs(f[i] - s) > 0.06 * (f[-1] - f[0]) for s in shown):
            shown.append(f[i])
            # keep the label inside the axes at both ends
            span = f[-1] - f[0]
            ha = ("left" if f[i] < f[0] + 0.06 * span else
                  "right" if f[i] > f[-1] - 0.06 * span else "center")
            ax.annotate(f"{f[i]:.0f} MHz", (f[i], mx[i]), xytext=(0, 7),
                        textcoords="offset points", ha=ha, fontsize=8,
                        color=C_INK)
        if len(shown) == 6:
            break

    # ---- panel 2: per-channel occupancy ---------------------------------
    chs = sorted(chans)
    burst = [max(0.0, chans[c]["burst_db"]) for c in chs]
    sust = [max(0.0, chans[c]["sustained_db"]) for c in chs]
    pos = np.arange(len(chs))
    # Two bars per channel, because "something transmitted here" and "this
    # channel is heavily used" are different findings and a single bar hides
    # the difference. Hatching carries the same distinction as the colour does,
    # so the pair survives greyscale and colour blindness.
    bx.bar(pos - 0.19, burst, width=0.36, color=C_BAR, edgecolor="white",
           linewidth=0.8, label="loudest burst")
    bx.bar(pos + 0.19, sust, width=0.36, color="white", edgecolor=C_AVG,
           linewidth=1.0, hatch="///", label="sustained average")
    bx.set_xticks(pos)
    bx.set_xticklabels([str(c) for c in chs], fontsize=8)
    bx.set_xlabel("802.11 channel")
    bx.set_ylabel("dB above an empty channel")
    bx.grid(axis="y")
    bx.legend(loc="upper center", frameon=False, fontsize=8, ncol=2)
    bx.set_ylim(0, max(burst + [1]) * 1.30)

    # label only the busiest, never every bar
    for i in np.argsort(burst)[::-1][:5]:
        bx.annotate(f"{burst[i]:.0f}", (pos[i] - 0.19, burst[i]), xytext=(0, 3),
                    textcoords="offset points", ha="center", fontsize=8,
                    color=C_INK, fontweight="bold")

    if band == "2.4":
        for c in (1, 6, 11):
            if c in chans:
                bx.get_xticklabels()[chs.index(c)].set_color(C_AVG)
                bx.get_xticklabels()[chs.index(c)].set_fontweight("bold")
        bx.set_title("Channels 1, 6 and 11 are bold: the only three that do not "
                     "overlap. A single transmitter raises its neighbours too.",
                     loc="left", fontsize=8.5, color=C_MUTED, pad=6)
    else:
        # The U-NII groupings go UNDER the axis, where a band label belongs and
        # where nothing can collide with a bar or the legend.
        for lo, hi, name in UNII:
            inside = [i for i, c in enumerate(chs) if lo <= c <= hi]
            if not inside:
                continue
            a, b = inside[0] - 0.4, inside[-1] + 0.4
            bx.plot([a, b], [-0.085, -0.085], transform=bx.get_xaxis_transform(),
                    color=C_MUTED, linewidth=0.9, clip_on=False)
            bx.annotate(name, ((a + b) / 2, -0.135),
                        xycoords=bx.get_xaxis_transform(), ha="center",
                        va="top", fontsize=8, color=C_MUTED, annotation_clip=False)
        bx.set_title("5 GHz channels do not overlap, so each bar stands alone.",
                     loc="left", fontsize=8.5, color=C_MUTED, pad=6)

    fig.text(0.008, 0.012,
             "dBFS, relative to the converter's full scale — not dBm. "
             "Levels are comparable within a band, not between the two: the "
             "board's response is only established from 200 MHz to 1 GHz, and "
             "its RF baluns carry no part number.",
             fontsize=7.2, color=C_MUTED)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("scan", help="the JSON written by wifi_scan.py")
    p.add_argument("--prefix", default=None,
                   help="output prefix (default: the scan file's own name)")
    args = p.parse_args(argv)

    with open(args.scan) as f:
        d = json.load(f)
    prefix = args.prefix or os.path.splitext(args.scan)[0]
    style()
    for band, st in d["bands"].items():
        draw_band(st, band, f"{prefix}-{band}.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
