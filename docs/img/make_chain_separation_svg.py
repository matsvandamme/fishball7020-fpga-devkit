#!/usr/bin/env python3
"""Draw docs/img/chain-separation-{light,dark}.svg.

A straight loopback measures T+R for one channel and cannot separate the
transmit chain from the receive chain. Measuring a CROSSED loop as well makes
the differences solvable:

    L00 = T0 + R0      straight, channel 0
    L11 = T1 + R1      straight, channel 1
    L01 = T0 + R1      crossed, TX0 into RX1

    R0 - R1 = L00 - L01        T0 - T1 = L01 - L11

Absolute T and R stay unknown - three equations, four unknowns - but the
differences are fully determined, which is enough to say which chain any
asymmetry lives in.

Both crosses were measured too, so each difference has two independent
routes; the figure plots their mean. Input is docs/img/data/measured-performance.json
(the 2026-09-18 campaign): the four 20 dB single-pad configurations, median
over their passes. Standard library only. Colours are slots 1-2 of the validated reference
palette at agentskills.io; do not substitute by eye.
"""
import json, math, pathlib, statistics, sys

HERE = pathlib.Path(__file__).resolve().parent
_ds = json.load(open(HERE / "data" / "measured-performance.json"))

def _loop(tx, rx, pad=20):
    runs = [r["loop"]["path_loss_curve"] for r in _ds["runs"]
            if (r["tx_channel"], r["rx_channel"], r["pad_db"]) == (tx, rx, pad)
            and not r["stacked_pads"]]
    return {int(f): statistics.median(c[f] for c in runs) for f in runs[0]}

L00, L11, L01, L10 = _loop(0, 0), _loop(1, 1), _loop(0, 1), _loop(1, 0)
FREQS = sorted(L00)
d = {"dR": [[f, ((L00[f] - L01[f]) + (L10[f] - L11[f])) / 2] for f in FREQS],
     "dT": [[f, ((L01[f] - L11[f]) + (L00[f] - L10[f])) / 2] for f in FREQS]}

def _band(k, lo, hi):
    return statistics.median(v for f, v in d[k] if lo <= f < hi)
# The step, as the change in each difference's median level either side of
# 4 GHz. Band medians rather than the two nearest points: the sweep points
# straddling 4 GHz are 300 MHz apart, and real structure lives in that gap.
STEP_R = _band("dR", 4.0e9, 5.0e9) - _band("dR", 2.0e9, 3.95e9)
STEP_T = _band("dT", 4.0e9, 5.0e9) - _band("dT", 2.0e9, 3.95e9)
W, H = 760, 340
L, R, T, B = 62, 150, 34, 52
PW, PH = W - L - R, H - T - B
FMIN, FMAX = 63e6, 6800e6
YMIN, YMAX = -7.0, 5.0
def x(f): return L + PW*(math.log10(f)-math.log10(FMIN))/(math.log10(FMAX)-math.log10(FMIN))
def y(v): return T + PH*(1-(v-YMIN)/(YMAX-YMIN))
TH = {"light": dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
                    muted="#8a8985", grid="#e6e5e1", s1="#2a78d6", s2="#eb6834"),
      "dark":  dict(surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7",
                    muted="#8a8985", grid="#33322f", s1="#3987e5", s2="#d95926")}
SERIES = [("dR", "receive:  R0 − R1", "s1"), ("dT", "transmit: T0 − T1", "s2")]

def build(t):
    c = TH[t]; o = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" role="img" '
             f'aria-label="Difference between the two channels, split into receive and transmit contributions. '
             f'The receive difference steps by {abs(STEP_R):.1f} dB at 4 GHz while the transmit difference moves {abs(STEP_T):.1f} dB.">')
    o.append(f'<rect width="{W}" height="{H}" fill="{c["surface"]}"/>')
    for v in range(-7, 6):
        if v % 2: continue
        o.append(f'<line x1="{L}" y1="{y(v):.1f}" x2="{L+PW}" y2="{y(v):.1f}" stroke="{c["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{L-10}" y="{y(v)+4:.1f}" text-anchor="end" font-size="12" fill="{c["secondary"]}">{v:+d}</text>')
    o.append(f'<line x1="{L}" y1="{y(0):.1f}" x2="{L+PW}" y2="{y(0):.1f}" stroke="{c["muted"]}" stroke-width="1" opacity="0.5"/>')
    for f, lab in ((70e6,"70"),(100e6,"100"),(200e6,"200"),(500e6,"500"),(1000e6,"1 GHz"),(2000e6,"2"),(5000e6,"5")):
        o.append(f'<line x1="{x(f):.1f}" y1="{T+PH}" x2="{x(f):.1f}" y2="{T+PH+5}" stroke="{c["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{x(f):.1f}" y="{T+PH+21}" text-anchor="middle" font-size="12" fill="{c["secondary"]}">{lab}</text>')
    o.append(f'<text x="{L+PW/2:.0f}" y="{H-12}" text-anchor="middle" font-size="12" fill="{c["secondary"]}">Frequency (MHz, log scale)</text>')
    o.append(f'<text x="16" y="{T+PH/2:.0f}" text-anchor="middle" font-size="12" fill="{c["secondary"]}" '
             f'transform="rotate(-90 16 {T+PH/2:.0f})">Channel difference (dB)</text>')
    gx = x(3986e6)
    o.append(f'<line x1="{gx:.1f}" y1="{T+4}" x2="{gx:.1f}" y2="{T+PH}" stroke="{c["muted"]}" stroke-width="1" stroke-dasharray="3 3"/>')
    for k, name, slot in SERIES:
        rows = sorted(d[k])
        o.append(f'<polyline points="{" ".join(f"{x(f):.1f},{y(v):.1f}" for f,v in rows)}" '
                 f'fill="none" stroke="{c[slot]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        f, v = rows[-1]
        o.append(f'<text x="{x(f)+10:.1f}" y="{y(v)+4:.1f}" font-size="12.5" fill="{c["primary"]}">{name}</text>')
    o.append(f'<text x="{gx-8:.1f}" y="{T+16}" text-anchor="end" font-size="11.5" fill="{c["muted"]}">4 GHz</text>')
    # Notes sit top-left, above both traces everywhere left of 1.5 GHz.
    o.append(f'<text x="{L+14}" y="{y(4.2):.1f}" font-size="11.5" fill="{c["muted"]}">'
             f'across 4 GHz the receive difference moves {STEP_R:+.1f} dB, the transmit {STEP_T:+.1f} dB:</text>')
    o.append(f'<text x="{L+14}" y="{y(3.4):.1f}" font-size="11.5" fill="{c["muted"]}">'
             f'the step is in the receiver, as an RX gain-table change should be</text>')
    o.append('</svg>')
    return "\n".join(o)

out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
for t in TH:
    (out / f"chain-separation-{t}.svg").write_text(build(t))
print(f"wrote {out}/chain-separation-{{light,dark}}.svg")
