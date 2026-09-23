#!/usr/bin/env python3
"""Figure 4 - what each modulation looks like in time, and its eye."""
import json, numpy as np, matplotlib.pyplot as plt
import theme, waveforms as W, rx
theme.apply()

S = {r["kind"]: r for r in json.load(open("results/summary.json"))}
fig, axes = plt.subplots(2, 4, figsize=(17.5, 7.8))

def load(k):
    d = np.load(f"results/{k}.npz"); return d["iq"], float(d["fs"])

# --- row 1: the character of each signal -------------------------------------
y, fs = load("cw")
n = 120; t = np.arange(n) / fs * 1e6
ax = axes[0, 0]
ax.plot(t, y[:n].real, color=theme.TEAL, lw=1.4)
ax.plot(t, y[:n].imag, color=theme.AMBER, lw=1.4)
# Direct labels rather than a legend box: two series, and the box sat on the title.
ax.text(t[-1] * 0.995, y[:n].real[-1], " I", color=theme.TEAL, fontsize=10,
        fontweight="bold", va="center")
ax.text(t[-1] * 0.995, y[:n].imag[-1], " Q", color=theme.AMBER, fontsize=10,
        fontweight="bold", va="center")
ax.set_title("CW tone - two sinusoids, 90 deg apart", color=theme.INK, pad=6)
ax.set_xlabel("time  (us)"); ax.set_ylabel("amplitude")
ax.set_ylim(-0.78, 0.78); ax.set_xlim(0, t[-1] * 1.06)

y, fs = load("ook")
ax = axes[0, 1]
n = int(fs / 250e3 * 22); env = np.abs(y[:n]); env /= env.max()
ax.plot(np.arange(n) / fs * 1e6, env, color=theme.TEAL, lw=1.2)
ax.fill_between(np.arange(n) / fs * 1e6, 0, env, color=theme.TEAL, alpha=0.22, lw=0)
ax.set_ylim(0, 1.15)
ax.set_title("OOK - the message is the envelope", color=theme.INK, pad=6)
ax.set_xlabel("time  (us)"); ax.set_ylabel("envelope")

def inst_freq(y, fs, npts, smooth=5):
    """Instantaneous frequency, lightly smoothed for legibility.

    The derivative of a noisy phase is noisier still, so a raw trace of a
    band-limited FSK signal is mostly differentiation noise. A 5-sample moving
    average (0.6 us, well under a 4 us symbol) leaves the transitions intact.
    """
    ph = np.unwrap(np.angle(y[:npts + 1]))
    f = np.diff(ph) / (2 * np.pi) * fs
    if smooth > 1:
        f = np.convolve(f, np.ones(smooth) / smooth, mode="same")
    return f

for col, (k, title) in enumerate((("fsk2", "2-FSK - frequency hops between two values"),
                                  ("gmsk", "GMSK - the same idea, smoothed")), start=2):
    y, fs = load(k)
    n = int(fs / (250e3 if k == "fsk2" else 1e6) * (18 if k == "fsk2" else 30))
    f = inst_freq(y, fs, n) / 1e3
    ax = axes[0, col]
    ax.plot(np.arange(len(f)) / fs * 1e6, f, color=theme.BLUE, lw=1.1)
    ax.axhline(0, color=theme.GRID, lw=0.8)
    ax.set_title(title, color=theme.INK, pad=6)
    ax.set_xlabel("time  (us)"); ax.set_ylabel("instantaneous freq  (kHz)")

# --- row 2: eye diagrams ------------------------------------------------------
for ax, k, name in zip(axes[1], ("bpsk", "qpsk", "qam16", "qam64"),
                       ("BPSK", "QPSK", "16-QAM", "64-QAM")):
    gen = {"bpsk": 2, "qpsk": 4, "qam16": 16, "qam64": 64}[k]
    x, meta = W.linear(gen)
    y, fs = load(k)
    tr, off, sps = rx.mf_trace(y[:1 << 17], meta, fs, W.FS, x)
    s = np.sqrt((np.abs(meta["sym"]) ** 2).mean())
    tr = tr.real / s
    span = 2 * sps
    start = off % sps
    seg = tr[start:start + (len(tr) - start) // span * span].reshape(-1, span)
    seg = seg[:700]
    tt = (np.arange(span) / sps) - 1.0
    ax.plot(tt, seg.T, color=theme.BLUE, lw=0.35, alpha=0.10)
    ax.set_xlim(-1, 1); ax.set_ylim(-1.9, 1.9)
    ax.axvline(0, color=theme.AMBER, lw=0.9, ls=(0, (4, 3)))
    ax.set_title(f"{name} eye", color=theme.INK, pad=6)
    ax.set_xlabel("symbol periods"); ax.set_ylabel("I  (normalised)")
    ax.text(0.03, 0.955, f"{len(seg)} traces", transform=ax.transAxes,
            color=theme.INK3, fontsize=7.5, va="top")

fig.text(0.008, 0.975, "The same ten signals in the time domain",
         color=theme.INK, fontsize=17, fontweight="bold", va="top")
fig.text(0.008, 0.938,
         "Top row: what distinguishes each modulation - a steady pair of sinusoids, an envelope that "
         "switches, a frequency that hops, a frequency that glides.\n"
         "Bottom row: eye diagrams from the matched-filter output, the same signal the EVM was measured "
         "on.  The amber line marks the instant the symbol is read; the wider the opening there, the more "
         "timing error the link can absorb.",
         color=theme.INK2, fontsize=9.3, va="top", linespacing=1.6)
theme.stamp(fig, "Fishball7020 FPGA devkit  ·  measured on a HackRF One",
            "1 Msym/s, RRC alpha = 0.35, 8 samples per symbol  ·  instantaneous frequency lightly smoothed")
fig.tight_layout(rect=[0, 0.02, 1, 0.885])
fig.savefig("fig/04-time-domain.png")
print("wrote fig/04-time-domain.png")
