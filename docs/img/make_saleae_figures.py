#!/usr/bin/env python3
"""Draw docs/img/saleae-*-{light,dark}.svg from the logic-analyser bench.

    # run from: the repo root
    python3 docs/img/make_saleae_figures.py

Reads docs/img/data/saleae-bench.json, which was reduced from Saleae Logic 8
captures and loopback spectra taken on 2026-09-18. The raw captures are
hundreds of megabytes and stay out of the repository; the JSON keeps what
each figure plots and nothing else. Dense spectra were reduced with max-hold
per pixel column, so a real spur can never be averaged away.

Colour follows the data-viz method in the reference palette: one categorical
hue (slot 1), a grey neutral for the one de-emphasised reference series, and
text always in ink tokens, never in the series colour. Slot 1 was run through
the palette validator in both modes and passes every check; the grey is not a
categorical slot (the validator fails it on chroma, correctly), but the
blue-grey pair clears the CVD and normal-vision floors in both modes.

These are static images: GitHub renders an SVG as <img>, so a hover layer
could not run there. The numbers behind every figure are in the tables of
docs/tx-gpio-bitmap.md.

Standard library only.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).parent
DATA = json.loads((HERE / "data" / "saleae-bench.json").read_text())

THEMES = {
    "light": dict(surface="#fcfcfb", ink="#0b0b0b", ink2="#52514e",
                  muted="#898781", grid="#e1e0d9", base="#c3c2b7",
                  s1="#2a78d6", ref="#898781"),
    "dark": dict(surface="#1a1a19", ink="#ffffff", ink2="#c3c2b7",
                 muted="#898781", grid="#2c2c2a", base="#383835",
                 s1="#3987e5", ref="#898781"),
}
FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class Fig:
    def __init__(self, w, h, theme):
        self.w, self.h, self.c = w, h, THEMES[theme]
        self.o = []

    def text(self, x, y, s, size=12, role="ink", anchor="start", weight=400,
             num=False):
        fv = ' font-variant-numeric="tabular-nums"' if num else ""
        self.o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" '
                      f'fill="{self.c[role]}" text-anchor="{anchor}" '
                      f'font-weight="{weight}"{fv}>{esc(s)}</text>')

    def line(self, x1, y1, x2, y2, role="grid", width=1):
        self.o.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" '
                      f'y2="{y2:.1f}" stroke="{self.c[role]}" '
                      f'stroke-width="{width}"/>')

    def path(self, pts, role="s1", width=2):
        d = "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        self.o.append(f'<path d="{d}" fill="none" stroke="{self.c[role]}" '
                      f'stroke-width="{width}" stroke-linejoin="round" '
                      f'stroke-linecap="round"/>')

    def header(self, title, subtitle, width_chars=104):
        self.text(24, 30, title, 16, "ink", weight=600)
        line, y = "", 50
        for word in subtitle.split():
            if len(line) + len(word) + 1 > width_chars:
                self.text(24, y, line, 12.5, "ink2"); line, y = word, y + 17
            else:
                line = f"{line} {word}".strip()
        self.text(24, y, line, 12.5, "ink2")

    def caption(self, y, lines):
        for i, ln in enumerate(lines):
            self.text(24, y + 16 * i, ln, 11.5, "ink2")

    def svg(self):
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" '
                f'height="{self.h}" viewBox="0 0 {self.w} {self.h}" '
                f'font-family=\'{FONT}\'>'
                f'<rect width="{self.w}" height="{self.h}" '
                f'fill="{self.c["surface"]}"/>' + "".join(self.o) + "</svg>")


def axis_x(f, x0, x1, y, lo, hi, ticks, fmt, label):
    f.line(x0, y, x1, y, "base")
    for t in ticks:
        x = x0 + (t - lo) / (hi - lo) * (x1 - x0)
        f.line(x, y, x, y + 4, "base")
        f.text(x, y + 17, fmt(t), 11, "muted", "middle", num=True)
    f.text((x0 + x1) / 2, y + 34, label, 11.5, "ink2", "middle")


def grid_y(f, x0, x1, y0, y1, lo, hi, ticks, fmt, label):
    for t in ticks:
        y = y1 - (t - lo) / (hi - lo) * (y1 - y0)
        f.line(x0, y, x1, y, "grid")
        f.text(x0 - 8, y + 4, fmt(t), 11, "muted", "end", num=True)
    f.o.append(f'<text transform="translate({x0 - 46},{(y0 + y1) / 2}) '
               f'rotate(-90)" font-size="11.5" fill="{f.c["ink2"]}" '
               f'text-anchor="middle">{esc(label)}</text>')


# ---------------------------------------------------------------------------
def fig_timing(theme):
    d = DATA["fig1"]; span = d["span_ns"]; T = d["sample_ns"]
    f = Fig(760, 356, theme)
    f.header("What the four pins carry",
             f"A 4-bit counter in the low nibble at {d['fs_msps']} MSPS, captured "
             f"by a logic analyser. Every sample is a new value, and every pin changes on "
             f"the same sample edge.")
    x0, x1, top, lane_h = 150, 736, 94, 44
    X = lambda ns: x0 + ns / span * (x1 - x0)
    # sample boundaries: the real edges of pin 0, which toggles every sample
    bounds = d["lanes"][0]["edges_ns"]
    for b in bounds:
        f.line(X(b), top - 6, X(b), top + 4 * lane_h + 28, "grid")
    names = [("sample_gpio[0]", "JP5 pin 7"), ("sample_gpio[1]", "JP5 pin 9"),
             ("sample_gpio[2]", "JP5 pin 11"), ("sample_gpio[3]", "JP5 pin 13")]
    levels_at = []
    for i, lane in enumerate(d["lanes"]):
        yh, yl = top + i * lane_h + 6, top + i * lane_h + 30
        f.text(24, top + i * lane_h + 18, names[i][0], 12, "ink", weight=600)
        f.text(24, top + i * lane_h + 33, names[i][1], 11, "ink2")
        lvl = lane["start"]; pts = [(x0, yh if lvl else yl)]
        for e in lane["edges_ns"]:
            y = yh if lvl else yl
            pts.append((X(e), y)); lvl ^= 1
            pts.append((X(e), yh if lvl else yl))
        pts.append((x1, yh if lvl else yl))
        f.path(pts, "s1", 2)
        levels_at.append(lane)
    # decoded value per sample, from the four lanes at each interval's middle
    yv = top + 4 * lane_h + 20
    f.text(24, yv + 4, "value", 12, "ink", weight=600)
    edges = [0] + bounds + [span]
    for a, b in zip(edges[:-1], edges[1:]):
        if b - a < T * 0.6:
            continue
        mid = (a + b) / 2; v = 0
        for bit, lane in enumerate(d["lanes"]):
            lvl = lane["start"] ^ (sum(1 for e in lane["edges_ns"] if e < mid) & 1)
            v |= lvl << bit
        f.text(X(mid), yv + 4, f"{v:X}", 12, "ink2", "middle", num=True)
    axis_x(f, x0, x1, top + 4 * lane_h + 40, 0, span,
           [0, 1000, 2000, 3000, 4000], lambda t: f"{t / 1000:g}",
           "time (µs) - one sample every 200 ns")
    return f


def fig_analog(theme):
    d = DATA["fig2"]; v = d["v"]; dt = d["dt_us"]
    f = Fig(760, 382, theme)
    f.header("Clean 3.3 V logic levels, at full transmit power",
             f"Pin 7 on the analyser's analog channel (5 MS/s) while TX1 transmits "
             f"at full power. With the feature off the pin idles at "
             f"{d['idle_v'] * 1000:.0f} mV.")
    x0, x1, y0, y1 = 80, 640, 88, 278
    span = len(v) * dt; lo, hi = -0.3, 3.8
    X = lambda t: x0 + t / span * (x1 - x0)
    Y = lambda u: y1 - (u - lo) / (hi - lo) * (y1 - y0)
    grid_y(f, x0, x1, y0, y1, lo, hi, [0, 1, 2, 3], lambda t: f"{t:g}",
           "volts")
    for level, name in ((d["voh"], f"high {d['voh']:.2f} V"),
                        (d["vol"], f"low {d['vol']:.2f} V")):
        f.line(x0, Y(level), x1 + 8, Y(level), "muted", 1)
        f.text(x1 + 14, Y(level) + 4, name, 12, "ink2")
    f.path([(X(i * dt), Y(u)) for i, u in enumerate(v)], "s1", 2)
    axis_x(f, x0, x1, y1 + 8, 0, span, [0, 10, 20, 30, 40, 50],
           lambda t: f"{t:g}", "time (µs)")
    f.caption(y1 + 60, [
        "The rounded edges and the small overshoot are the analyser's analog channel "
        "(5 MS/s, limited bandwidth), not the pin:",
        "its digital channels resolve the same edges to within nanoseconds. What this "
        "view does show is the levels."])
    return f


def fig_spectrum(theme):
    d = DATA["fig3"]
    f = Fig(760, 412, theme)
    f.header("The RF does not notice the pins",
             "Received spectrum at 61.44 MSPS, TX1 at full power into a 50 dB loop. "
             "Blue: pins toggling at up to 30.72 MHz. Grey: pins off.")
    x0, x1, y0, y1 = 80, 736, 116, 316
    lo, hi = -30.72, 30.72; dlo, dhi = -90, 5
    X = lambda m: x0 + (m - lo) / (hi - lo) * (x1 - x0)
    Y = lambda db: y1 - (max(min(db, dhi), dlo) - dlo) / (dhi - dlo) * (y1 - y0)
    grid_y(f, x0, x1, y0, y1, dlo, dhi, [-80, -60, -40, -20, 0],
           lambda t: f"{t:g}", "dB relative to the tone")
    # where pin switching would land, if it coupled into the RF
    for m in d["pin_mhz"]:
        for s in (-1, 1):
            f.line(X(s * m), y0 - 4, X(s * m), y1, "base", 1)
    f.text(X(-d["pin_mhz"][1]), y0 - 10, "pin frequencies", 11, "ink2", "middle")
    f.text(X(d["pin_mhz"][1]), y0 - 10, "pin frequencies", 11, "ink2", "middle")
    fm = d["f_mhz"]
    f.path([(X(a), Y(b)) for a, b in zip(fm, d["B_dbc"])], "ref", 1.5)
    f.path([(X(a), Y(b)) for a, b in zip(fm, d["C_dbc"])], "s1", 1.5)
    f.text(X(d["tone_mhz"]) + 8, Y(0) + 4, "the tone", 11.5, "ink2")
    # legend: always present for two series
    lx, ly = x0 + 4, 92
    f.line(lx, ly, lx + 22, ly, "s1", 2.5)
    f.text(lx + 28, ly + 4, "pins toggling", 12, "ink")
    f.line(lx + 130, ly, lx + 152, ly, "ref", 2.5)
    f.text(lx + 158, ly + 4, "pins off", 12, "ink")
    axis_x(f, x0, x1, y1 + 8, lo, hi, [-30, -20, -10, 0, 10, 20, 30],
           lambda t: f"{t:+g}" if t else "0", "offset from the LO (MHz)")
    f.caption(y1 + 60, [
        "The traces overlap almost everywhere, and nothing rises above the floor at "
        "the pin frequencies. The spurs beside the",
        "tone are the radio's own (its image and harmonics): they are there with the "
        "pins off too, hidden under the blue."])
    return f


def fig_interp(theme):
    d = DATA["fig4"]
    f = Fig(760, 392, theme)
    f.header("The same 1 MSPS buffer, sent two ways",
             "A 9.995 kHz tone, TX1 at -20 dB into the loop. Left: the normal way. "
             "Right: through the FPGA's ÷8 interpolator.")
    lo, hi = -50, 50; dlo, dhi = -150, -50
    panels = [("std", "AD9361's own filters", 80, 380),
              ("fpga", "FPGA ÷8 interpolator", 440, 740)]
    y0, y1 = 108, 288
    for key, title, x0, x1 in panels:
        X = lambda k, x0=x0, x1=x1: x0 + (k - lo) / (hi - lo) * (x1 - x0)
        Y = lambda db: y1 - (max(min(db, dhi), dlo) - dlo) / (dhi - dlo) * (y1 - y0)
        ticks = [-140, -120, -100, -80, -60]
        for t in ticks:
            f.line(x0, Y(t), x1, Y(t), "grid")
        if key == "std":
            for t in ticks:
                f.text(x0 - 8, Y(t) + 4, f"{t}", 11, "muted", "end", num=True)
            f.o.append(f'<text transform="translate({x0 - 50},{(y0 + y1) / 2}) '
                       f'rotate(-90)" font-size="11.5" fill="{f.c["ink2"]}" '
                       f'text-anchor="middle">dBFS per Hz</text>')
        f.text(x0, y0 - 12, title, 12.5, "ink", weight=600)
        p = d[key]
        f.path([(X(a), Y(b)) for a, b in zip(p["f_khz"], p["dbfs_hz"])], "s1", 1.5)
        axis_x(f, x0, x1, y1 + 8, lo, hi, [-50, -25, 0, 25, 50],
               lambda t: f"{t:+g}" if t else "0", "offset (kHz)")
    f.text(80 + (10 - lo) / (hi - lo) * 300 + 8, 144, "the tone, clean",
           11.5, "ink2")
    f.text(80 + (-10 - lo) / (hi - lo) * 300 - 6, 176, "its IQ image",
           11.5, "ink2", "end")
    f.text(452, 152, "no tone at all: the spectrum matches", 11.5, "ink2")
    f.text(452, 168, "the transmitter muted, within 1.2 dB", 11.5, "ink2")
    f.caption(y1 + 60, [
        "Same y-scale in both panels. The noise floors differ by a few dB only "
        "because each pixel holds the maximum of",
        "more receive bins on the left (15 Hz each) than on the right (122 Hz each). "
        "The bump at 0 Hz is LO leakage."])
    return f


if __name__ == "__main__":
    for name, fn in (("timing", fig_timing), ("analog", fig_analog),
                     ("spectrum", fig_spectrum), ("interp", fig_interp)):
        for theme in THEMES:
            p = HERE / f"saleae-{name}-{theme}.svg"
            p.write_text(fn(theme).svg(), encoding="utf8")
            print(p.name)
