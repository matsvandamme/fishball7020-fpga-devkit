#!/usr/bin/env python3
"""Draw docs/img/automation-sweep-{light,dark}.svg from two measured runs.

Reads docs/img/data/loopback-sweep-run{1,2}.csv, written by
tools/automation/examples/loopback_sweep.py on 2026-10-05 (TX1 -> 20 dB -> RX1,
TX2 -> 30 dB -> RX2, both transmitters at -40 dB, both receivers at 20 dB
manual gain). Top panel: the tone level, a line through the mean of the runs
with a band for their spread. Bottom panel: the image, one dot per run, because
the point is that it does not repeat.

Standard library only. Colours are the same validated pair as
make_loop_gain_svg.py.

Usage:  python3 make_automation_sweep_svg.py [output_dir]
"""
import csv, math, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
RUNS = [list(csv.DictReader(open(HERE / "data" / f"loopback-sweep-run{i}.csv"))) for i in (1, 2)]
F = [float(r["lo_mhz"]) * 1e6 for r in RUNS[0]]
W, H = 760, 560
L, R, T = 62, 70, 40
PW = W - L - R
P1 = (T, 210)                       # top panel: y, height
P2 = (T + 210 + 70, 170)            # bottom panel
FMIN, FMAX = 85e6, 6800e6
LEVEL = (-55.0, -20.0)
IMAGE = (-85.0, -25.0)
TH = {"light": dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
                    muted="#8a8985", grid="#e6e5e1", s1="#2a78d6", s2="#eb6834"),
      "dark":  dict(surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7",
                    muted="#8a8985", grid="#33322f", s1="#3987e5", s2="#d95926")}
CH = (("rx1", "RX1 (20 dB pad)", "s1"), ("rx2", "RX2 (30 dB pad)", "s2"))


def x(f): return L + PW * (math.log10(f) - math.log10(FMIN)) / (math.log10(FMAX) - math.log10(FMIN))
def yy(panel, rng, v): return panel[0] + panel[1] * (1 - (v - rng[0]) / (rng[1] - rng[0]))


def axes(o, c, panel, rng, step, label):
    for v in range(int(rng[0]), int(rng[1]) + 1, step):
        o.append(f'<line x1="{L}" y1="{yy(panel, rng, v):.1f}" x2="{L + PW}" y2="{yy(panel, rng, v):.1f}" '
                 f'stroke="{c["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{L - 10}" y="{yy(panel, rng, v) + 4:.1f}" text-anchor="end" font-size="12" '
                 f'fill="{c["secondary"]}">{v}</text>')
    bottom = panel[0] + panel[1]
    for f, lab in ((100e6, "100"), (200e6, "200"), (500e6, "500"), (1000e6, "1 GHz"), (2000e6, "2"), (5000e6, "5")):
        o.append(f'<line x1="{x(f):.1f}" y1="{bottom}" x2="{x(f):.1f}" y2="{bottom + 5}" stroke="{c["grid"]}"/>')
        o.append(f'<text x="{x(f):.1f}" y="{bottom + 20}" text-anchor="middle" font-size="12" '
                 f'fill="{c["secondary"]}">{lab}</text>')
    mid = panel[0] + panel[1] / 2
    o.append(f'<text x="16" y="{mid:.0f}" text-anchor="middle" font-size="12" fill="{c["secondary"]}" '
             f'transform="rotate(-90 16 {mid:.0f})">{label}</text>')


def build(t):
    c = TH[t]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
         f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" role="img" '
         f'aria-label="Loopback tone level and image against frequency, two runs, both channels">',
         f'<rect width="{W}" height="{H}" fill="{c["surface"]}"/>']
    axes(o, c, P1, LEVEL, 5, "tone level (dBFS)")
    axes(o, c, P2, IMAGE, 10, "image (dBc)")
    o.append(f'<text x="{L}" y="{P1[0] - 14}" font-size="13" fill="{c["primary"]}" font-weight="600">'
             f'Tone level: repeats to about 1 dB</text>')
    o.append(f'<text x="{L}" y="{P2[0] - 14}" font-size="13" fill="{c["primary"]}" font-weight="600">'
             f'Image: one dot per run, and it does not repeat</text>')
    o.append(f'<text x="{L + PW / 2:.0f}" y="{H - 8}" text-anchor="middle" font-size="12" '
             f'fill="{c["secondary"]}">LO frequency (MHz, log scale)</text>')
    for key, name, slot in CH:
        v = [[float(run[i][f"{key}_dbfs"]) for run in RUNS] for i in range(len(F))]
        up = " ".join(f"{x(f):.1f},{yy(P1, LEVEL, max(p)):.1f}" for f, p in zip(F, v))
        dn = " ".join(f"{x(f):.1f},{yy(P1, LEVEL, min(p)):.1f}" for f, p in reversed(list(zip(F, v))))
        o.append(f'<polygon points="{up} {dn}" fill="{c[slot]}" opacity="0.35"/>')
        o.append(f'<polyline points="{" ".join(f"{x(f):.1f},{yy(P1, LEVEL, sum(p) / len(p)):.1f}" for f, p in zip(F, v))}" '
                 f'fill="none" stroke="{c[slot]}" stroke-width="2" stroke-linejoin="round"/>')
        last = sum(v[-1]) / len(v[-1])
        o.append(f'<text x="{x(F[-1]) + 8:.1f}" y="{yy(P1, LEVEL, last) + 4:.1f}" font-size="12" '
                 f'fill="{c["primary"]}">{name.split()[0]}</text>')
        for run in RUNS:
            for f, r in zip(F, run):
                o.append(f'<circle cx="{x(f):.1f}" cy="{yy(P2, IMAGE, float(r[f"{key}_image_dbc"])):.1f}" r="3.5" '
                         f'fill="{c[slot]}"/>')
    lx, ly = L + 10, yy(P2, IMAGE, -78.5)
    for i, (_k, name, slot) in enumerate(CH):
        o.append(f'<circle cx="{lx + 6}" cy="{ly + i * 17 - 4}" r="3.5" fill="{c[slot]}"/>')
        o.append(f'<text x="{lx + 16}" y="{ly + i * 17}" font-size="12" fill="{c["primary"]}">{name}</text>')
    o.append(f'<text x="{L + 10}" y="{yy(P1, LEVEL, -52.5):.1f}" font-size="11.5" fill="{c["muted"]}">'
             f'both TX at &#8722;40 dB, both RX at 20 dB gain; RX2 reads ~10 dB lower: its pad is 10 dB bigger</text>')
    o.append('</svg>')
    return "\n".join(o)


out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
for t in TH:
    (out / f"automation-sweep-{t}.svg").write_text(build(t))
print(f"wrote {out}/automation-sweep-{{light,dark}}.svg")
