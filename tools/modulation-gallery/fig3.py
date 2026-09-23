#!/usr/bin/env python3
"""Figure 3 - the LoRa-style chirp, in time and frequency at once."""
import json, numpy as np, matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.gridspec import GridSpec
from scipy.signal import spectrogram
import theme, waveforms as W
theme.apply()

S = {r["kind"]: r for r in json.load(open("results/summary.json"))}
d = np.load("results/css.npz"); y = d["iq"]; fs = float(d["fs"])
sym = np.load("results/css_sym.npz")

# Align to the transmitted buffer exactly as the decoder does. Slicing raw
# symbol blocks out of an unaligned capture splits each chirp across two blocks,
# which puts a spurious second peak in the dechirp and mislabels the symbol -
# the spectrogram still looks perfect while the numbers beside it are wrong.
import rx
_x, _meta = W.css()
_ref = rx._upsample_ref(_x, W.FS, fs)
_cfo, _lag, y = rx.sync(y.astype(np.complex64), _ref, fs, span=40e3)

cmap = LinearSegmentedColormap.from_list("wf", ["#0b0e14", "#16304d", "#1f6f9e",
                                                theme.TEAL, "#C9FFF6", "#FFFFFF"])
nsym_show = 14
symlen = int(round((1 << 9) / 1e6 * fs))          # one CSS symbol at the work rate
seg = y[:nsym_show * symlen]

fig = plt.figure(figsize=(17.5, 7.6))
gs = GridSpec(2, 3, figure=fig, width_ratios=[2.5, 1, 1], height_ratios=[1, 1],
              hspace=0.32, wspace=0.24)

# --- the staircase -----------------------------------------------------------
ax = fig.add_subplot(gs[:, 0])
f, t, Sxx = spectrogram(seg, fs=fs, window="hann", nperseg=320, noverlap=296,
                        nfft=2048, return_onesided=False, mode="magnitude")
i = np.argsort(f); f, Sxx = f[i], Sxx[i]
Z = 20 * np.log10(Sxx + 1e-12); Z -= Z.max()
ax.grid(False)
ax.pcolormesh(t * 1e3, f / 1e6, Z, cmap=cmap, vmin=-48, vmax=0,
              shading="auto", rasterized=True)
ax.set_ylim(-0.62, 0.62)
ax.set_xlabel("time  (ms)"); ax.set_ylabel("offset from 866.5 MHz  (MHz)")
ax.set_title("Every symbol is a chirp, shifted by its own value", color=theme.INK, pad=8)
ax.grid(False)
for j in range(nsym_show):
    ax.axvline(j * symlen / fs * 1e3, color="#ffffff", lw=0.35, alpha=0.22)
ax.text(0.015, 0.965, f"decoded: {'  '.join(str(v) for v in sym['want'][:8])} ...",
        transform=ax.transAxes, color=theme.INK, fontsize=8.5,
        family="DejaVu Sans Mono", va="top")

# --- dechirp -----------------------------------------------------------------
axd = fig.add_subplot(gs[0, 1:])
nbase = 1 << 9
dec = int(round(fs / 1e6))
from scipy.signal import resample_poly
rb = resample_poly(y[:40 * symlen], 1, dec)
n = np.arange(nbase)
base = np.exp(2j * np.pi * (n ** 2 / (2 * nbase) - n / 2))
BLK = 3
blk = rb[BLK * nbase:(BLK + 1) * nbase] * np.conj(base)
Sp = 20 * np.log10(np.abs(np.fft.fft(blk)) + 1e-12)
Sp -= Sp.max()
axd.plot(np.arange(nbase), Sp, color=theme.TEAL, lw=0.9)
axd.fill_between(np.arange(nbase), -90, Sp, color=theme.TEAL, alpha=0.25, lw=0)
axd.set_ylim(-70, 4); axd.set_xlim(0, nbase)
axd.set_xlabel("dechirped FFT bin  =  the symbol"); axd.set_ylabel("dB below peak")
axd.set_title("Dechirping turns a chirp into one tone", color=theme.INK, pad=6)
k = int(np.argmax(Sp))
axd.annotate(f"symbol {k}  (sent {sym['want'][BLK]})", xy=(k, 0),
             xytext=(k + 45, -13), color=theme.AMBER,
             fontsize=9, arrowprops=dict(arrowstyle="->", color=theme.AMBER, lw=1.1))
axd.text(0.985, 0.90, f"peak {S['css']['css_peak_median_db']:.1f} dB above the median bin",
         transform=axd.transAxes, color=theme.INK2, ha="right", fontsize=8.5,
         family="DejaVu Sans Mono")

# --- symbol accuracy ---------------------------------------------------------
axs = fig.add_subplot(gs[1, 1])
got, want = sym["got"], sym["want"]
axs.scatter(want, got, s=14, color=theme.TEAL, alpha=0.85, zorder=4, linewidths=0)
axs.plot([0, 512], [0, 512], color=theme.INK3, lw=0.8, ls=(0, (4, 3)), zorder=2)
axs.set_xlim(0, 512); axs.set_ylim(0, 512); axs.set_aspect("equal")
axs.set_xlabel("symbol sent"); axs.set_ylabel("symbol decoded")
err = int((got != want).sum())
axs.set_title(f"{len(got)-err} of {len(got)} correct", color=theme.INK, pad=6)

# --- envelope ----------------------------------------------------------------
axe = fig.add_subplot(gs[1, 2])
env = np.abs(y[:3 * symlen]); env = env / env.mean()
axe.plot(np.arange(len(env)) / fs * 1e3, env, color=theme.AMBER, lw=0.7)
axe.set_ylim(0, 2.0)
axe.set_xlabel("time  (ms)"); axe.set_ylabel("envelope  (x mean)")
axe.set_title(f"PAPR {S['css']['papr_db']:.2f} dB", color=theme.INK, pad=6)

fig.text(0.008, 0.975, "LoRa-style chirp spread spectrum, transmitted and decoded",
         color=theme.INK, fontsize=17, fontweight="bold", va="top")
fig.text(0.008, 0.938,
         "Spreading factor 9, 1 MHz wide: 512 possible symbols, each the same up-chirp cyclically "
         "shifted.  All 128 symbols in the buffer came back correct.\n"
         "A chirp is nominally constant-envelope; band-limiting it to its own 1 MHz channel gives it "
         "the PAPR on the right, because the frequency wrap at each symbol boundary is a real discontinuity.",
         color=theme.INK2, fontsize=9.3, va="top", linespacing=1.6)
theme.stamp(fig, "Fishball7020 FPGA devkit  ·  measured on a HackRF One",
            "spectrogram: 320-point Hann window, 92.5 % overlap, 48 dB range")
fig.subplots_adjust(left=0.045, right=0.985, top=0.855, bottom=0.075)
fig.savefig("fig/03-chirp.png")
print("wrote fig/03-chirp.png")
