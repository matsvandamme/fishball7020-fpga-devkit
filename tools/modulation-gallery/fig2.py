#!/usr/bin/env python3
"""Figure 2 - constellations, recovered from the air."""
import json, numpy as np, matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
import theme
theme.apply()

S = {r["kind"]: r for r in json.load(open("results/summary.json"))}
panels = [("bpsk", "BPSK", 2), ("qpsk", "QPSK", 4), ("qam16", "16-QAM", 16),
          ("qam64", "64-QAM", 64), ("ofdm", "OFDM  52 x QPSK", 4)]
cmap = LinearSegmentedColormap.from_list("iq", ["#0f1218", "#1d4e7a", theme.BLUE,
                                                "#9BD0FF", "#FFFFFF"])
fig, axes = plt.subplots(1, 5, figsize=(17.5, 4.5))
for ax, (k, name, order) in zip(axes, panels):
    d = np.load(f"results/{k}_sym.npz")
    y = d["syms_eq"] if "syms_eq" in d.files else d["syms"]
    ref = d["ref_eq"] if "ref_eq" in d.files else d["ref"]
    y = np.asarray(y).ravel(); ref = np.asarray(ref).ravel()
    s = np.sqrt((np.abs(ref) ** 2).mean())
    y, ref = y / s, ref / s
    lim = 1.65 if order <= 4 else 1.75
    ax.hexbin(y.real, y.imag, gridsize=190, extent=(-lim, lim, -lim, lim),
              cmap=cmap, bins="log", linewidths=0, mincnt=1, zorder=3)
    u = np.unique(np.round(ref, 6))
    ax.scatter(u.real, u.imag, s=16, facecolors="none", edgecolors=theme.AMBER,
               linewidths=0.9, zorder=5)
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim); ax.set_aspect("equal")
    ax.axhline(0, color=theme.GRID, lw=0.7, zorder=1)
    ax.axvline(0, color=theme.GRID, lw=0.7, zorder=1)
    ax.set_title(name, color=theme.INK, pad=6)
    r = S[k]
    ev = r["evm_pct"]
    sub = f"EVM {ev:.2f} %"
    if "evm_eq_pct" in r:
        sub += f"   ({r['evm_eq_pct']:.2f} % equalised)"
    ax.text(0.5, 0.045, sub, transform=ax.transAxes, color=theme.INK, ha="center",
            fontsize=9.5, family="DejaVu Sans Mono", zorder=8)
    ax.text(0.03, 0.965, f"{len(y):,} symbols", transform=ax.transAxes,
            color=theme.INK3, fontsize=7.5, va="top")
    ax.set_xticks([-1, 0, 1]); ax.set_yticks([-1, 0, 1])
axes[0].set_ylabel("Q  (normalised)")
for ax in axes:
    ax.set_xlabel("I  (normalised)")

fig.text(0.008, 0.975, "Constellations recovered over the air, 866.5 MHz -> HackRF One",
         color=theme.INK, fontsize=17, fontweight="bold", va="top")
fig.text(0.008, 0.925,
         "1 Msym/s, root-raised-cosine alpha = 0.35.  Amber rings are the transmitted symbols; the cloud is "
         "what came back after carrier and timing recovery.  Every point is measured - nothing here is a model.\n"
         "The 6.0 % that survives equalisation is the same for BPSK as for 64-QAM, which is the signature of "
         "the link rather than the transmitter: see the phase-noise panel in figure 5.",
         color=theme.INK2, fontsize=9.3, va="top", linespacing=1.6)
theme.stamp(fig, "Fishball7020 FPGA devkit  ·  Zynq-7020 + AD9361, TX2A",
            "colour is point density, log scale")
fig.tight_layout(rect=[0, 0.045, 1, 0.87])
fig.savefig("fig/02-constellations.png")
print("wrote fig/02-constellations.png")
