#!/usr/bin/env python3
"""Draw docs/img/tx-rx-leak-{light,dark}.svg: how strongly each channel's
transmitter leaks into its own receiver on the board, without the cable.

The leak is expressed as an EQUIVALENT PAD: the attenuator value a cable loop
would need to be exactly as strong as the leak. That puts it on the same scale
as the pads people actually fit, so the chart answers the practical question
directly - a loopback measurement is only clean where the pad sits well below
the curve.

How the numbers are made, from docs/img/data/measured-performance.json:

  leak["tx{c}_rx{c}_rx_open"]   tone level into RX c from TX c at a fixed
                                operating point, with the cable REMOVED from
                                the receive port
  runs, 20 dB single pad        the same channel's loop gain through the cable

  equivalent pad = 20 + loop_gain_20dB(f) - (leak_tone(f) + calibration)

The calibration offset converts the fixed-point tone level into the self-test's
loop-gain scale. It was taken where the two can be compared directly: below
1 GHz, with the 50 dB loop connected, at frequencies where the leak was at
least 15 dB below the loop. It is stored with the data; its spread (about 3 dB)
is the reason to read these curves as +/-2 dB.

The receive port was open, not terminated, during the leak measurement.
Standard library only. Colours are slots 1-2 of the validated reference
palette at agentskills.io; do not substitute by eye.

Usage:  python3 make_tx_rx_leak_svg.py [output_dir]
"""
import json, math, pathlib, statistics, sys

HERE = pathlib.Path(__file__).resolve().parent
_ds = json.load(open(HERE / "data" / "measured-performance.json"))
PAD = 20
OFF = _ds["leak"]["calibration_offset_db"]

def _loop(ch):
    runs = [r["loop"]["path_loss_curve"] for r in _ds["runs"]
            if (r["tx_channel"], r["rx_channel"], r["pad_db"]) == (ch, ch, PAD)
            and not r["stacked_pads"]]
    return {int(f): statistics.median(c[f] for c in runs) for f in runs[0]}

data = {}
for ch in (0, 1):
    loop = _loop(ch)
    leak = _ds["leak"][f"tx{ch}_rx{ch}_rx_open"]
    data[f"ch{ch}"] = sorted((int(f), PAD + loop[int(f)] - (v["tone_dbfs"] + OFF))
                             for f, v in leak.items())

W, H = 760, 380
L, R, T, B = 62, 150, 34, 52
PW, PH = W - L - R, H - T - B
FMIN, FMAX = 63e6, 6800e6
YMIN, YMAX = 10.0, 100.0
def x(f): return L + PW*(math.log10(f)-math.log10(FMIN))/(math.log10(FMAX)-math.log10(FMIN))
def y(v): return T + PH*(1-(v-YMIN)/(YMAX-YMIN))
TH = {"light": dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e",
                    muted="#8a8985", grid="#e6e5e1", s1="#2a78d6", s2="#eb6834"),
      "dark":  dict(surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7",
                    muted="#8a8985", grid="#33322f", s1="#3987e5", s2="#d95926")}
NAMES = {"ch0": ("Channel 0", "s1"), "ch1": ("Channel 1", "s2")}

def build(t):
    c = TH[t]; o = []
    o.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" '
             f'font-family="-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif" role="img" '
             f'aria-label="The board&#8217;s own transmit-to-receive leak on each channel, expressed as the '
             f'attenuator a cable loop would need to be as strong. It falls with frequency, from 60-90 dB '
             f'below 1 GHz to 33-58 dB above 3 GHz, and channel 0 leaks more than channel 1.">')
    o.append(f'<rect width="{W}" height="{H}" fill="{c["surface"]}"/>')
    for v in range(20, 101, 20):
        o.append(f'<line x1="{L}" y1="{y(v):.1f}" x2="{L+PW}" y2="{y(v):.1f}" stroke="{c["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{L-10}" y="{y(v)+4:.1f}" text-anchor="end" font-size="12" fill="{c["secondary"]}">{v}</text>')
    for f, lab in ((70e6,"70"),(100e6,"100"),(200e6,"200"),(500e6,"500"),(1000e6,"1 GHz"),(2000e6,"2"),(5000e6,"5")):
        o.append(f'<line x1="{x(f):.1f}" y1="{T+PH}" x2="{x(f):.1f}" y2="{T+PH+5}" stroke="{c["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{x(f):.1f}" y="{T+PH+21}" text-anchor="middle" font-size="12" fill="{c["secondary"]}">{lab}</text>')
    o.append(f'<text x="{L+PW/2:.0f}" y="{H-12}" text-anchor="middle" font-size="12" fill="{c["secondary"]}">Frequency (MHz, log scale)</text>')
    o.append(f'<text x="16" y="{T+PH/2:.0f}" text-anchor="middle" font-size="12" fill="{c["secondary"]}" '
             f'transform="rotate(-90 16 {T+PH/2:.0f})">Leak, as an equivalent pad (dB)</text>')
    # The pads actually used, as reference lines. Labels sit at the left end,
    # where every curve is at least 55 dB and cannot reach them.
    for p in (20, 30, 50):
        o.append(f'<line x1="{L}" y1="{y(p):.1f}" x2="{L+PW}" y2="{y(p):.1f}" stroke="{c["muted"]}" '
                 f'stroke-width="1" stroke-dasharray="4 3"/>')
        o.append(f'<text x="{L+8}" y="{y(p)-5:.1f}" font-size="11.5" fill="{c["muted"]}">{p} dB pad</text>')
    for k in ("ch0", "ch1"):
        rows = data[k]; name, slot = NAMES[k]
        o.append(f'<polyline points="{" ".join(f"{x(f):.1f},{y(v):.1f}" for f,v in rows)}" '
                 f'fill="none" stroke="{c[slot]}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
    ends = sorted(((y(data[k][-1][1]) + 4, x(data[k][-1][0]) + 10, NAMES[k][0]) for k in data),
                  key=lambda e: e[0])
    placed = []
    for ly, lx, name in ends:
        if placed and ly - placed[-1][0] < 16:
            ly = placed[-1][0] + 16
        placed.append((ly, lx, name))
    for ly, lx, name in placed:
        o.append(f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="13" fill="{c["primary"]}">{name}</text>')
    lx, ly = L+PW-150, T+16
    for i, k in enumerate(("ch0", "ch1")):
        name, slot = NAMES[k]; yy = ly + i*17
        o.append(f'<line x1="{lx}" y1="{yy-4}" x2="{lx+18}" y2="{yy-4}" stroke="{c[slot]}" stroke-width="2" stroke-linecap="round"/>')
        o.append(f'<text x="{lx+25}" y="{yy}" font-size="12" fill="{c["primary"]}">{name} (own RX)</text>')
    o.append('</svg>')
    return "\n".join(o)

out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
for t in TH:
    (out / f"tx-rx-leak-{t}.svg").write_text(build(t))
print(f"wrote {out}/tx-rx-leak-{{light,dark}}.svg")
