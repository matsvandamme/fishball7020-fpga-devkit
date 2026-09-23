#!/usr/bin/env python3
"""Figure 5 - what the measurements add up to."""
import json, numpy as np, matplotlib.pyplot as plt
import theme, dsp
theme.apply()

S = json.load(open("results/summary.json"))
by = {r["kind"]: r for r in S}
spur = json.load(open("results/spurs.json"))
fig, axes = plt.subplots(1, 4, figsize=(17.5, 5.6))

# --- (a) PAPR, as a CCDF ------------------------------------------------------
ax = axes[0]
show = [("cw", theme.TEAL), ("gmsk", theme.BLUE), ("css", theme.GREEN),
        ("qpsk", theme.VIOLET), ("qam64", theme.PINK), ("ofdm", theme.AMBER)]
for k, c in show:
    d = np.load(f"results/{k}.npz"); y = d["iq"]
    p = np.abs(y) ** 2; p = p / p.mean()
    pr = np.sort(10 * np.log10(p + 1e-30))
    ccdf = 1 - np.arange(len(pr)) / len(pr)
    m = ccdf > 1e-5
    ax.semilogy(pr[m], ccdf[m], color=c, lw=1.6, label=by[k]["name"])
ax.set_xlim(-1, 13); ax.set_ylim(1e-5, 1)
ax.set_xlabel("dB above average power"); ax.set_ylabel("fraction of samples above")
ax.set_title("Peak-to-average: how much\nheadroom each one demands", color=theme.INK, pad=6)
ax.legend(labelcolor=theme.INK2, fontsize=8, loc="lower left")

# --- (b) EVM, and the link's own floor ---------------------------------------
ax = axes[1]
ks = ["bpsk", "qpsk", "qam16", "qam64", "ofdm"]
names = [by[k]["name"] for k in ks]
raw = [by[k]["evm_pct"] for k in ks]
eq = [by[k].get("evm_eq_pct", np.nan) for k in ks]
yy = np.arange(len(ks))
ax.barh(yy + 0.19, raw, height=0.34, color=theme.BLUE, label="as received")
ax.barh(yy - 0.19, eq, height=0.34, color=theme.GREEN, label="after a 15-tap equaliser")
floor = by["cw"]["link_evm_equiv_pct"]
ax.axvline(floor, color=theme.AMBER, lw=1.6, ls=(0, (5, 3)), zorder=6)
ax.text(floor + 0.3, -0.62, f"the link itself: {floor:.1f} %\non an unmodulated tone",
        color=theme.AMBER, fontsize=8.2, va="top", linespacing=1.5)
ax.set_yticks(yy); ax.set_yticklabels(names)
ax.invert_yaxis(); ax.set_xlim(0, 17)
ax.set_xlabel("EVM  (%)")
ax.set_title("Error vector magnitude, and\nwhy it stops improving", color=theme.INK, pad=6)
ax.legend(labelcolor=theme.INK2, fontsize=8, loc="center right",
          bbox_to_anchor=(1.0, 0.74))
for i, v in enumerate(eq):
    if v == v:
        ax.text(v + 0.15, i - 0.19, f"{v:.2f}", color=theme.INK2, fontsize=7.8, va="center")

# --- (c) phase noise ----------------------------------------------------------
ax = axes[2]
d = np.load("results/cw_phase.npz"); ph = d["ph"].astype(float); fs = float(d["fs"])
w = np.hanning(len(ph))
P = np.abs(np.fft.rfft(ph * w)) ** 2 / (fs * (w ** 2).sum())
ff = np.fft.rfftfreq(len(ph), 1 / fs)
L = 10 * np.log10(P / 2 + 1e-30)
m = (ff > 3e2) & (ff < 3e5)
fb = np.logspace(np.log10(3e2), np.log10(3e5), 200)
idx = np.digitize(ff[m], fb)
xs = [fb[i - 1] for i in range(1, len(fb) + 1) if (idx == i).any()]
ys = [np.median(L[m][idx == i]) for i in range(1, len(fb) + 1) if (idx == i).any()]
ax.semilogx(xs, ys, color=theme.AMBER, lw=1.6)
# Stop at 300 kHz: the tone sits 606 kHz from centre, so beyond about
# half that the phase estimate folds against the DC region and the
# curve would be the measurement rather than the oscillators.
ax.set_xlim(3e2, 3e5); ax.set_ylim(-115, -70)
ax.set_xlabel("offset from the carrier  (Hz)"); ax.set_ylabel("dBc/Hz")
ax.set_title("Phase noise of the link\n(two independent oscillators)", color=theme.INK, pad=6)
ax.text(0.04, 0.10, f"{by['cw']['link_phase_rms_deg']:.2f} deg RMS integrated\n"
                    f"amplitude only {by['cw']['link_amp_rms_pct']:.2f} %",
        transform=ax.transAxes, color=theme.INK2, fontsize=8.4, family="DejaVu Sans Mono")

# --- (d) spur attribution -----------------------------------------------------
ax = axes[3]
at = [r["atten"] for r in spur]
car = [r["carrier"] for r in spur]
sp = [max(r["spur_lo"], r["spur_hi"]) for r in spur]
rxs = [r["rx_spur"] for r in spur]
ax.plot(at, car, "o-", color=theme.BLUE, lw=1.6, ms=5, label="carrier")
ax.plot(at, sp, "o-", color=theme.AMBER, lw=1.6, ms=5, label="spur at carrier +- 1 MHz")
ax.plot(at, rxs, "o-", color=theme.PINK, lw=1.6, ms=5, label="spur at 865.0 MHz")
ax.set_xlabel("transmit attenuation  (dB)"); ax.set_ylabel("level  (dBFS)")
ax.set_title("Whose spur is it?\nTurn the transmitter down and see", color=theme.INK, pad=6)
ax.set_ylim(-78, 6)
ax.legend(labelcolor=theme.INK2, fontsize=8, loc="upper left")
ax.annotate("tracks the carrier 1:1\n-> the board's own spur, -40 dBc",
            xy=(-20, sp[3]), xytext=(-35.5, -30), color=theme.AMBER, fontsize=8.2,
            linespacing=1.5, arrowprops=dict(arrowstyle="->", color=theme.AMBER, lw=1.1))
ax.annotate("never moves\n-> the receiver, not the board",
            xy=(-22, rxs[2]), xytext=(-35.5, -74), color=theme.PINK, fontsize=8.2,
            linespacing=1.5, arrowprops=dict(arrowstyle="->", color=theme.PINK, lw=1.1))

fig.text(0.008, 0.975, "What the measurements add up to", color=theme.INK,
         fontsize=17, fontweight="bold", va="top")
fig.text(0.008, 0.933,
         "Every number here is measured on this board through a HackRF One, not taken from a datasheet.\n"
         "The two panels on the right are why the EVM figures stop improving: the transmitter's own spurs sit "
         "40 dB down and track the carrier, while what dominates every\nconstellation is phase noise between "
         "two oscillators that have never met - which is a property of the measurement, not of the board.",
         color=theme.INK2, fontsize=9.3, va="top", linespacing=1.6)
theme.stamp(fig, "Fishball7020 FPGA devkit  ·  Zynq-7020 + AD9361, TX2A at 866.5 MHz",
            "receiver: HackRF One, 16 MSPS, tuned 4.8 MHz above the transmitter")
fig.tight_layout(rect=[0, 0.02, 1, 0.855])
fig.savefig("fig/05-summary.png")
print("wrote fig/05-summary.png")
