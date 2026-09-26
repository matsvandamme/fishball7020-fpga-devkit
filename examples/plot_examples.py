#!/usr/bin/env python3
"""Draw each example's figure from the data captured off the board.

    # run from: the repo root
    python3 examples/capture_examples.py     # measure (needs the radio)
    python3 examples/plot_examples.py        # draw (needs only the JSON)

Writes docs/img/examples-0N-{light,dark}.svg. Same split as
tools/plot_throughput.py: measuring and drawing are separate programs, so a
figure can be redrawn without a radio and cannot quietly become a drawing of
nothing.

COLOURS ARE NOT A TASTE DECISION HERE. The three-series palette was checked by
simulating protanopia and deuteranopia and measuring the pairwise separation in
OKLab, because a palette that fails is not something you can see by looking at
it - the whole problem is that it looks fine to whoever picked it.

    light  #1f6feb blue  #d1690a orange  #1a7f64 teal
           worst pair: normal 22.7, protanopia 9.4, deuteranopia 16.7
    dark   #58a6ff blue  #f0883e orange  #39c5a3 teal
           worst pair: normal 18.4, protanopia 14.4, deuteranopia 12.3

The target is 8 and the normal-vision floor is 15, so both pass. A purple third
series (#8250df), which was the obvious first choice, fails badly: 2.9 against
the blue under deuteranopia, i.e. the same colour. The dark steps had to be
chosen separately rather than reused - the first attempt at them scored 7.2
under protanopia. Identity is also carried by line style and marker, so none of
this is load-bearing on its own.
"""
from __future__ import annotations

import json
import os
import sys
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "docs", "img", "data", "examples.json")
IMG = os.path.join(ROOT, "docs", "img")

THEMES = {
    "light": dict(fg="#1c1e21", muted="#5b6470", grid="#e3e6ea", bg="white",
                  series=("#1f6feb", "#d1690a", "#1a7f64"), band=0.16),
    "dark": dict(fg="#e6e6e6", muted="#9aa4b2", grid="#2b3038", bg="#0d1117",
                 series=("#58a6ff", "#f0883e", "#39c5a3"), band=0.24),
}
WINDOWS = ("rectangular", "hann", "blackman-harris")
STYLES = ("-", "--", "-")
MARKERS = ("o", "s", "^")


def style(t):
    plt.rcParams.update({
        "font.size": 9, "text.color": t["fg"], "axes.labelcolor": t["fg"],
        "axes.edgecolor": t["muted"], "xtick.color": t["muted"],
        "ytick.color": t["muted"], "axes.facecolor": t["bg"],
        "figure.facecolor": t["bg"], "savefig.facecolor": t["bg"],
        "axes.spines.top": False, "axes.spines.right": False,
        "grid.color": t["grid"], "grid.linewidth": 0.7,
    })


def caption(fig, t, text, width=150):
    fig.text(0.012, -0.05, "\n".join(textwrap.wrap(text, width)),
             fontsize=7.2, color=t["muted"], va="top")


# ------------------------------------------------------------------ 01
def fig01(d, t, path):
    style(t)
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14.0, 4.8),
                                 gridspec_kw={"width_ratios": [1.5, 1],
                                              "wspace": 0.26})
    e = d["01"]
    fs, nfft, centre = e["samp_rate"], e["nfft"], e["centre_hz"]
    # Every 2nd bin was stored, so the axis steps by 2 bins.
    n = len(e["traces"]["blackman-harris"]["db"])
    mhz = (centre - fs / 2) / 1e6 + np.arange(n) * (fs / nfft) * 2 / 1e6

    for i, w in enumerate(WINDOWS):
        tr = e["traces"][w]
        ax.plot(mhz, tr["db"], color=t["series"][i], linestyle=STYLES[i],
                linewidth=1.3, alpha=0.9,
                label=f"{w}  ({tr['sidelobes_db']:+d} dB sidelobes)")
    ax.set_xlabel("frequency, MHz")
    ax.set_ylabel("level, dBFS")
    ax.grid(axis="y")
    ax.legend(loc="upper right", frameon=False, fontsize=8)
    spread = (max(e["traces"][w]["range_db"] for w in WINDOWS)
              - min(e["traces"][w]["range_db"] for w in WINDOWS))
    ax.set_title(f"The same air, through three windows\n"
                 f"nothing loud here, so they agree within {spread:.1f} dB",
                 loc="left", fontsize=10.5, color=t["fg"], pad=8)

    # The noise floor each window leaves, labelled where it actually sits.
    for i, w in enumerate(WINDOWS):
        fl = e["traces"][w]["floor_dbfs"]
        ax.axhline(fl, color=t["series"][i], linewidth=0.8, alpha=0.45,
                   linestyle=(0, (1, 3)))
    ax.annotate("dotted: each window's own noise floor\n"
                "(10th percentile of its trace)",
                xy=(0.015, 0.03), xycoords="axes fraction", fontsize=7.5,
                color=t["muted"], linespacing=1.4)

    # ---- right: the known-answer case
    syn = e["synthetic"]
    pos = np.arange(len(WINDOWS))
    read = [syn[w]["weak_tone_read_dbfs"] for w in WINDOWS]
    truth = -60.0
    for i, w in enumerate(WINDOWS):
        bx.barh(pos[i], read[i] - truth, left=truth, height=0.55,
                color=t["series"][i], edgecolor=t["bg"], linewidth=1)
        err = read[i] - truth
        bx.annotate(f"{read[i]:.1f} dBFS   ({err:+.1f} dB)",
                    (max(read[i], truth), pos[i]), xytext=(6, 0),
                    textcoords="offset points", va="center", fontsize=8.5,
                    color=t["fg"], fontweight="bold")
    bx.axvline(truth, color=t["muted"], linewidth=1.4, linestyle=(0, (4, 3)))
    bx.annotate("the tone's TRUE level, -60 dBFS", xy=(truth, -0.72),
                xytext=(-6, 0), textcoords="offset points", ha="right",
                va="center", fontsize=8, color=t["muted"])
    bx.set_yticks(pos)
    bx.set_yticklabels(WINDOWS, fontsize=8.5)
    bx.invert_yaxis()
    bx.set_xlim(truth - 2, max(read) + 16)
    bx.set_ylim(len(WINDOWS) - 0.4, -1.1)
    bx.set_xlabel("what the spectrum reports, dBFS")
    bx.grid(axis="x")
    bx.set_title("Asked to measure a tone 60 dB down, 40 bins from a carrier",
                 loc="left", fontsize=10.5, color=t["fg"], pad=8)

    caption(fig, t,
            f"LEFT: one capture of real air at {centre/1e6:.0f} MHz "
            f"({e.get('what') or 'as tuned'}), {fs/1e6:.2f} MS/s, "
            f"{e['frames']} frames of {nfft} points, manual gain "
            f"{e['gain_db']} dB, processed three times - the window is the only "
            f"thing that differs. The three traces nearly coincide, and that is "
            f"the honest result for a band with nothing loud in it: a window's "
            f"sidelobes only cost you dynamic range when there is a strong "
            f"signal near a weak one for them to smear over. Point the example "
            f"at a strong carrier and the left panel separates. RIGHT: the same "
            f"three windows on "
            f"a synthetic two-tone, which is the only way to state an error "
            f"against a KNOWN answer: a full-scale carrier plus a tone 60 dB "
            f"below it, 40 bins away, both half a bin off centre. A rectangular "
            f"window does not blur the weak tone - it reports its loud "
            f"neighbour's skirt instead, and does so confidently. Levels are "
            f"dBFS, relative to the converter's full scale, not dBm; nothing "
            f"here is calibrated to absolute power.")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


# ------------------------------------------------------------------ 02
NAMES = {"4": "QPSK", "16": "16-QAM", "64": "64-QAM"}


def fig02(d, t, path):
    style(t)
    e = d["02"]
    sps, alpha = e["sps"], e["alpha"]
    fig, axes = plt.subplots(1, 3, figsize=(15.4, 4.7),
                             gridspec_kw={"width_ratios": [1, 1, 1.45],
                                          "wspace": 0.28})

    # Two constellations: the one this receiver recovers, and the one it does
    # not. Showing the failure is the point - a QPSK receiver does not become a
    # QAM receiver by changing one number.
    for ax, order in zip(axes[:2], ("4", "16")):
        v = e["orders"][order]
        cl = np.array(v["cloud"])
        ideal = np.array(v["ideal"])
        # rasterized: a few thousand vector dots is most of the file size, and
        # a scatter cloud gains nothing from being vector.
        ax.scatter(cl[:, 0], cl[:, 1], s=3.5, color=t["series"][0], alpha=0.35,
                   linewidths=0, label="received", rasterized=True,
                   zorder=3)
        # Open circles, not filled crosses: a well-recovered QPSK cloud is
        # tighter than a marker, so a filled ideal marker HIDES the very thing
        # the panel is meant to show. The cloud sits inside the ring instead.
        ax.scatter(ideal[:, 0], ideal[:, 1], s=150, marker="o",
                   facecolors="none", edgecolors=t["series"][1],
                   linewidths=1.5, label="ideal")
        lim = float(np.abs(ideal).max()) * 1.5
        ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
        ax.set_aspect("equal"); ax.grid(True)
        ax.set_xlabel("I")
        verdict = "recovered" if order == "4" else "DOES NOT RESOLVE"
        ax.set_title(f"{NAMES[order]} — {verdict}\nEVM {v['evm_pct']:.2f}%   "
                     f"MER {v['mer_db']:.1f} dB",
                     loc="left", fontsize=10, color=t["fg"], pad=8)
        if order == "4":
            ax.set_ylabel("Q")
            ax.legend(loc="upper right", frameon=False, fontsize=7.5,
                      markerscale=2)

    # The quantitative check: EVM against SNR, with theory.
    bx = axes[2]
    sw = e.get("snr_sweep", [])
    if sw:
        snr = np.array([r["snr_db"] for r in sw], dtype=float)
        got = np.array([r["evm_pct"] for r in sw])
        plain = np.array([r["evm_theory_pct"] for r in sw])
        # The matched filter keeps the symbol bandwidth and throws the rest of
        # the noise away, so the EVM that arrives is better than the SNR at its
        # input by 10*log10(sps / (1 + alpha)) - a prediction, not a fit.
        gain_db = 10 * np.log10(sps / (1.0 + alpha))
        withmf = plain * 10 ** (-gain_db / 20.0)
        bx.plot(snr, plain, color=t["muted"], linewidth=1.3,
                linestyle=(0, (4, 3)), label="100·10^(−SNR/20), no filter")
        bx.plot(snr, withmf, color=t["series"][2], linewidth=2,
                linestyle="--", marker="^", markersize=5,
                label=f"...minus the matched filter's {gain_db:.1f} dB")
        bx.plot(snr, got, color=t["series"][0], linewidth=2, marker="o",
                markersize=5, label="measured")
        bx.set_yscale("log")
        bx.set_xlabel("SNR at the receiver input, dB")
        bx.set_ylabel("EVM, %")
        bx.grid(axis="y")
        bx.legend(loc="lower left", frameon=False, fontsize=7.5)
        ratio = float(np.mean(got / withmf))
        bx.annotate(f"measured / predicted = {ratio:.2f}\nacross "
                    f"{snr.max() - snr.min():.0f} dB",
                    xy=(0.97, 0.94), xycoords="axes fraction", ha="right",
                    va="top", fontsize=8, color=t["muted"], linespacing=1.4)
        bx.set_title("QPSK: EVM follows theory, not a fitted curve",
                     loc="left", fontsize=10.5, color=t["fg"], pad=8)

    caption(fig, t,
            f"Measured in software - the modulator's own output through added "
            f"Gaussian noise into the identical receive chain, including the "
            f"real embedded EVM block. NO RADIO is involved, so this validates "
            f"the DSP and says nothing about converters, mixers, amplifiers or "
            f"clocks. {e['samp_rate']/1e6:.0f} MS/s, {sps} samples per symbol, "
            f"root raised cosine roll-off {alpha}. LEFT AND MIDDLE at "
            f"{e['snr_db']:.0f} dB SNR. The 16-QAM panel is not a bug being "
            f"hidden: both recovery loops here are effectively "
            f"constant-modulus - decision-directed Mueller and Mueller timing, "
            f"and an order-4 Costas loop - so their error signals are "
            f"amplitude-dependent and a multilevel constellation drives them "
            f"with its own data. Gardner's detector did not lock at all on this "
            f"chain, and a decision-directed LMS equaliser made 16-QAM worse. A "
            f"QAM receiver needs joint decision-directed recovery against the "
            f"full constellation, which is a bigger thing than a showcase. "
            f"RIGHT: the dashed grey line is the textbook relation between SNR "
            f"and EVM; the teal line subtracts the matched filter's predicted "
            f"noise-bandwidth gain of 10·log10(sps/(1+alpha)); the measurement "
            f"sits on it across the whole range, which is what makes this a "
            f"check rather than a curve fit.",
            width=156)
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


# ------------------------------------------------------------------ 03
def fig03(d, t, path):
    style(t)
    e = d["03"]
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(14.0, 4.8),
                                 gridspec_kw={"width_ratios": [1, 1.15],
                                              "wspace": 0.24})
    sw = e["sweep"]
    w = [p["width_khz"] for p in sw]
    coh = [p["coherence"] for p in sw]
    dc_at = e["dc_enters_at_khz"]

    clean = [(x, y) for x, y in zip(w, coh) if x < dc_at]
    dirty = [(x, y) for x, y in zip(w, coh) if x >= dc_at]
    ax.plot([x for x, _ in clean], [y for _, y in clean], color=t["series"][0],
            marker="o", markersize=5, linewidth=2, label="LO leak excluded")
    if dirty:
        ax.plot([x for x, _ in dirty], [y for _, y in dirty],
                color=t["series"][1], marker="s", markersize=5, linewidth=2,
                linestyle="--", label="LO leak inside the filter")
    ax.axvline(dc_at, color=t["muted"], linewidth=1.4, linestyle=(0, (4, 3)))
    ax.annotate(f"the LO leak gets in\nbeyond {dc_at:.0f} kHz",
                xy=(dc_at, 0.5), xytext=(8, 0), textcoords="offset points",
                fontsize=8, color=t["muted"], va="center", linespacing=1.4)
    ax.set_xlabel("band-select width, kHz")
    ax.set_ylabel("coherence, 0 to 1")
    ax.set_ylim(0, 1.05)
    ax.grid(axis="y")
    ax.legend(loc="lower right", frameon=False, fontsize=8)
    ax.set_title("Widen the filter and the receiver hears itself",
                 loc="left", fontsize=10.5, color=t["fg"], pad=8)

    st = e["stability"]
    ph = np.array(st["phase_deg"])
    tt = np.arange(len(ph)) * e["chunk"] / e["samp_rate"] * 1e3
    bx.plot(tt, ph, color=t["series"][0], linewidth=1.6)
    bx.set_xlabel("time, ms")
    bx.set_ylabel("RX1 - RX2 phase, degrees")
    bx.grid(axis="y")
    spread = float(ph.max() - ph.min())
    bx.annotate(f"mean {ph.mean():+.1f}°, spread {spread:.1f}° over "
                f"{tt[-1]:.0f} ms\nmean coherence {np.mean(st['coherence']):.3f}",
                xy=(0.015, 0.05), xycoords="axes fraction", fontsize=8,
                color=t["muted"], linespacing=1.5)
    bx.set_title(f"Phase between the two receivers, {st['width_khz']} kHz band",
                 loc="left", fontsize=10.5, color=t["fg"], pad=8)

    caption(fig, t,
            f"One two-channel capture at {e['centre_hz']/1e6:.0f} MHz, "
            f"{e['samp_rate']/1e6:.0f} MS/s, manual gain "
            f"{e['gain_db'][0]}/{e['gain_db'][1]} dB, with the local oscillator "
            f"offset by {e['lo_offset_hz']/1e3:.0f} kHz. The band-select filter "
            f"is then swept IN SOFTWARE over those same samples, so the curve "
            f"is a property of the filter rather than of what happened to be on "
            f"the air a minute later. LEFT: once the filter is wide enough to "
            f"include DC it admits the receiver's own LO leak, which is "
            f"perfectly correlated with itself, and coherence climbs toward 1 "
            f"while meaning nothing about the signal. This is the failure "
            f"example 03 is arranged to avoid. RIGHT: the phase is repeatable, "
            f"not calibrated - each receive path has its own fixed delay "
            f"through its own balun, so the angle is not a direction of "
            f"arrival. See docs/measured-performance.md.")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}")


def main(argv):
    with open(DATA) as f:
        d = json.load(f)
    want = [a for a in argv[1:] if not a.startswith("-")] or ["01", "02", "03"]
    fns = {"01": fig01, "02": fig02, "03": fig03}
    os.makedirs(IMG, exist_ok=True)
    for key in want:
        if key not in d:
            print(f"no data for {key} in {DATA} - run capture_examples.py {key}",
                  file=sys.stderr)
            continue
        for theme, t in THEMES.items():
            fns[key](d, t, os.path.join(IMG, f"examples-{key}-{theme}.svg"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
