#!/usr/bin/env python3
"""Figure 1 - the whole signal set, as measured."""
import json, numpy as np, matplotlib.pyplot as plt
import theme, dsp
theme.apply()

S = json.load(open("results/summary.json"))
mut = np.load("results/_muted.npz")
order = ["cw", "ook", "fsk2", "bpsk", "qpsk", "gmsk", "qam16", "qam64", "ofdm", "css"]
by = {r["kind"]: r for r in S}
floor = float(np.median(mut["p"][np.abs(mut["f"]) < 1.8e6]))

fig, axes = plt.subplots(2, 5, figsize=(17.5, 7.0))
for ax, k in zip(axes.ravel(), order):
    r, d = by[k], np.load(f"results/{k}.npz")
    c = theme.TIER[r["tier"]]
    theme.spectrum(ax, d["f"], d["p"], c, floor=floor)
    ax.set_xlim(-2, 2); ax.set_ylim(floor - 6, 2)
    ax.set_title(r["name"], color=theme.INK, pad=6)
    ax.text(0.03, 0.955, r["tier"], transform=ax.transAxes, color=c, fontsize=8,
            fontweight="bold", va="top")
    txt = (f"occupied  {r['occ_bw_mhz']:.3f} MHz\n"
           f"PAPR      {r['papr_db']:.2f} dB\n"
           f"peak      {r['peak_dbfs']:.1f} dBFS")
    if "evm_pct" in r:
        txt += f"\nEVM       {r['evm_pct']:.2f} %"
    if "css_errors" in r:
        txt += f"\nsymbols   {r['css_nsym']-r['css_errors']}/{r['css_nsym']} ok"
    ax.text(0.97, 0.94, txt, transform=ax.transAxes, color=theme.INK2, fontsize=7.4,
            family="DejaVu Sans Mono", ha="right", va="top", linespacing=1.5)
    ax.set_xticks([-2, -1, 0, 1, 2])

for ax in axes[1]:
    ax.set_xlabel("offset from 866.5 MHz  (MHz)")
for ax in axes[:, 0]:
    ax.set_ylabel("dBFS per bin")

fig.text(0.008, 0.975, "Ten modulations from one Fishball7020, measured on a HackRF One",
         color=theme.INK, fontsize=17, fontweight="bold", va="top")
fig.text(0.008, 0.935,
         "Zynq-7020 + AD9361 transmitting at 866.5 MHz, 4 MSPS, TX2A at -16 dB attenuation.  "
         "Receiver offset-tuned 3.5 MHz low so its own DC spike falls in the filter's "
         "stopband: every trace below is genuinely DC-free.\n"
         "Dashed line is the transmitter muted - the same absolute scale, so what looks "
         "like signal is signal.  Chebyshev-windowed, 32 768-point, 62 averages.",
         color=theme.INK2, fontsize=9.3, va="top", linespacing=1.6)
hand = [plt.Line2D([], [], color=theme.TIER[t], lw=3,
        label={"simple": "simple", "moderate": "moderate", "complex": "complex"}[t])
        for t in ("simple", "moderate", "complex")]
fig.legend(handles=hand, loc="upper right", bbox_to_anchor=(0.995, 0.99), ncol=3,
           labelcolor=theme.INK2, fontsize=9)
theme.stamp(fig, "Fishball7020 FPGA devkit  ·  measured, not simulated",
            "receiver: HackRF One, 16 MSPS, 12 MHz analog filter, LNA 24 / VGA 24 dB")
fig.tight_layout(rect=[0, 0.02, 1, 0.885])
fig.savefig("fig/01-signal-set.png")
print("wrote fig/01-signal-set.png")
