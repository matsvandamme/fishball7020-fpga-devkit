"""Small SVG charts for the examples' figures. Standard library only.

    from svgplot import Panel, write
    p = Panel("Tone level", "LO frequency (MHz)", "dBFS", logx=True)
    p.line([100, 1000, 5800], [-30, -25, -42], "RX1", 1)
    write("sweep.svg", [p])                   # follows the viewer's light/dark setting
    write("sweep-light.svg", [p], "light")    # or one fixed theme, for a docs site

A figure is a column of panels sharing one width. Each panel has its own axes,
title and legend; the legend sits in the title row, so it never covers data.
Series are told apart by colour and by marker shape, so the figure still reads
without colour.
"""
import math

THEMES = {
    "light": dict(surface="#fcfcfb", primary="#0b0b0b", secondary="#52514e", muted="#8a8985",
                  grid="#e6e5e1", s1="#2a78d6", s2="#eb6834", s3="#1f9e6e", s4="#8a5bd6"),
    "dark": dict(surface="#1a1a19", primary="#ffffff", secondary="#c3c2b7", muted="#8a8985",
                 grid="#33322f", s1="#3987e5", s2="#d95926", s3="#2bb17f", s4="#a07de8"),
}
MARKERS = {1: "circle", 2: "square", 3: "triangle", 4: "diamond"}
DASH = ' stroke-dasharray="5 4"'
FONT = "-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif"


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _nice_ticks(lo, hi, n=6):
    span = hi - lo
    if span <= 0:
        return [lo]
    raw = span / n
    mag = 10 ** math.floor(math.log10(raw))
    step = min((m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw), default=10 * mag)
    first = math.ceil(lo / step - 1e-9) * step
    out, v = [], first
    while v <= hi + step * 1e-9:
        out.append(round(v, 10))
        v += step
    return out


def _log_ticks(lo, hi):
    out = []
    for e in range(math.floor(math.log10(lo)), math.ceil(math.log10(hi)) + 1):
        for m in (1, 2, 5):
            v = m * 10 ** e
            if lo <= v <= hi:
                out.append(v)
    return out


def _label(v):
    if abs(v) >= 1000 and v == int(v):
        return f"{v / 1000:g}k" if v % 1000 else f"{int(v / 1000)}k"
    return f"{v:g}".replace("-", "−")


class Panel:
    """One chart. Add series with line(), points() and band(), marks with
    vline(), hline() and note(); limits default to the data."""

    def __init__(self, title, xlabel, ylabel, xlim=None, ylim=None, logx=False, height=230,
                 xticks=None, yticks=None, xtick_labels=None):
        self.title, self.xlabel, self.ylabel = title, xlabel, ylabel
        self.xlim, self.ylim, self.logx, self.height = xlim, ylim, logx, height
        self.xticks, self.yticks, self.xtick_labels = xticks, yticks, xtick_labels
        self.items, self.notes = [], []

    def line(self, xs, ys, label=None, slot=1, dashed=False, markers=False):
        self.items.append(("line", list(xs), list(ys), label, slot, dashed, markers))
        return self

    def points(self, xs, ys, label=None, slot=1):
        self.items.append(("points", list(xs), list(ys), label, slot, False, True))
        return self

    def band(self, xs, lo, hi, slot=1):
        self.items.append(("band", list(xs), (list(lo), list(hi)), None, slot, False, False))
        return self

    def vline(self, x, text=""):
        self.items.append(("vline", x, None, text, 0, True, False))
        return self

    def hline(self, y, text=""):
        self.items.append(("hline", None, y, text, 0, True, False))
        return self

    def note(self, text):
        self.notes.append(text)
        return self

    def _limits(self):
        xs, ys = [], []
        for kind, x, y, *_ in self.items:
            if kind in ("line", "points"):
                xs += x
                ys += y
            elif kind == "band":
                xs += x
                ys += y[0] + y[1]
        ys = [v for v in ys if v is not None and math.isfinite(v)]
        if self.xlim:
            xlim = self.xlim
        elif self.logx:                      # a little room, so edge markers are not cut
            xlim = (min(xs) / 1.06, max(xs) * 1.06)
        else:
            pad = (max(xs) - min(xs)) * 0.02 or 1
            xlim = (min(xs) - pad, max(xs) + pad)
        if self.ylim:
            ylim = self.ylim
        else:
            lo, hi = min(ys), max(ys)
            pad = (hi - lo) * 0.08 or 1
            ylim = (lo - pad, hi + pad)
        return xlim, ylim


def _marker(o, kind, x, y, colour, r=3.6):
    if kind == "circle":
        o.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" style="fill:{colour}"/>')
    elif kind == "square":
        o.append(f'<rect x="{x - r:.1f}" y="{y - r:.1f}" width="{2 * r}" height="{2 * r}" style="fill:{colour}"/>')
    elif kind == "triangle":
        o.append(f'<polygon points="{x:.1f},{y - r * 1.2:.1f} {x - r * 1.1:.1f},{y + r * 0.8:.1f} '
                 f'{x + r * 1.1:.1f},{y + r * 0.8:.1f}" style="fill:{colour}"/>')
    else:
        o.append(f'<polygon points="{x:.1f},{y - r * 1.3:.1f} {x + r:.1f},{y:.1f} {x:.1f},{y + r * 1.3:.1f} '
                 f'{x - r:.1f},{y:.1f}" style="fill:{colour}"/>')


def render(panels, theme="auto", width=760, title=None):
    """The SVG text. theme: "auto" (follows prefers-color-scheme), "light" or "dark"."""
    L, R, gap_top, gap_bottom = 66, 24, 46, 46
    top = 34 if title else 6
    heights = [gap_top + p.height + gap_bottom for p in panels]
    H = top + sum(heights) + 4
    def var(name):
        return f"var(--{name})"
    css = ":root{" + ";".join(f"--{k}:{v}" for k, v in THEMES["light" if theme != "dark" else "dark"].items()) + "}"
    if theme == "auto":
        css += ("@media (prefers-color-scheme: dark){:root{"
                + ";".join(f"--{k}:{v}" for k, v in THEMES["dark"].items()) + "}}")
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{H}" viewBox="0 0 {width} {H}" '
         f'font-family="{FONT}" role="img" aria-label="{_esc(title or panels[0].title)}">',
         f"<style>{css}</style>",
         f'<rect width="{width}" height="{H}" style="fill:{var("surface")}"/>']
    if title:
        o.append(f'<text x="{L}" y="22" font-size="15" font-weight="600" style="fill:{var("primary")}">'
                 f"{_esc(title)}</text>")
    y0 = top
    PW = width - L - R
    for p, h in zip(panels, heights):
        (x_lo, x_hi), (y_lo, y_hi) = p._limits()
        T, PH = y0 + gap_top, p.height

        def X(v):
            if p.logx:
                return L + PW * (math.log10(v) - math.log10(x_lo)) / (math.log10(x_hi) - math.log10(x_lo))
            return L + PW * (v - x_lo) / (x_hi - x_lo)

        def Y(v):
            v = min(max(v, y_lo), y_hi)
            return T + PH * (1 - (v - y_lo) / (y_hi - y_lo))

        o.append(f'<text x="{L}" y="{T - 18}" font-size="13" font-weight="600" style="fill:{var("primary")}">'
                 f"{_esc(p.title)}</text>")
        yt = p.yticks or _nice_ticks(y_lo, y_hi)
        for v in yt:
            o.append(f'<line x1="{L}" y1="{Y(v):.1f}" x2="{L + PW}" y2="{Y(v):.1f}" '
                     f'style="stroke:{var("grid")}" stroke-width="1"/>')
            o.append(f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" font-size="11.5" '
                     f'style="fill:{var("secondary")}">{_label(v)}</text>')
        xt = p.xticks or (_log_ticks(x_lo, x_hi) if p.logx else _nice_ticks(x_lo, x_hi, 8))
        for i, v in enumerate(xt):
            lab = p.xtick_labels[i] if p.xtick_labels else _label(v)
            o.append(f'<line x1="{X(v):.1f}" y1="{T + PH}" x2="{X(v):.1f}" y2="{T + PH + 5}" '
                     f'style="stroke:{var("muted")}" stroke-width="1"/>')
            o.append(f'<text x="{X(v):.1f}" y="{T + PH + 19}" text-anchor="middle" font-size="11.5" '
                     f'style="fill:{var("secondary")}">{_esc(lab)}</text>')
        o.append(f'<line x1="{L}" y1="{T + PH}" x2="{L + PW}" y2="{T + PH}" style="stroke:{var("muted")}" stroke-width="1"/>')
        o.append(f'<text x="{L + PW / 2:.0f}" y="{T + PH + 37}" text-anchor="middle" font-size="12" '
                 f'style="fill:{var("secondary")}">{_esc(p.xlabel)}</text>')
        mid = T + PH / 2
        o.append(f'<text x="16" y="{mid:.0f}" text-anchor="middle" font-size="12" style="fill:{var("secondary")}" '
                 f'transform="rotate(-90 16 {mid:.0f})">{_esc(p.ylabel)}</text>')
        o.append(f'<clipPath id="c{y0}"><rect x="{L}" y="{T - 2}" width="{PW}" height="{PH + 4}"/></clipPath>')
        o.append(f'<g clip-path="url(#c{y0})">')
        legend = []
        for kind, xs, ys, label, slot, dashed, markers in p.items:
            c = var(f"s{slot}") if slot else var("muted")
            if kind == "band":
                lo, hi = ys
                pts = [f"{X(x):.1f},{Y(v):.1f}" for x, v in zip(xs, hi)]
                pts += [f"{X(x):.1f},{Y(v):.1f}" for x, v in reversed(list(zip(xs, lo)))]
                o.append(f'<polygon points="{" ".join(pts)}" style="fill:{c}" opacity="0.28"/>')
            elif kind == "line":
                segs, cur = [], []
                for x, v in zip(xs, ys):           # a None or NaN breaks the line
                    if v is None or not math.isfinite(v):
                        if cur:
                            segs.append(cur)
                        cur = []
                    else:
                        cur.append(f"{X(x):.1f},{Y(v):.1f}")
                if cur:
                    segs.append(cur)
                for s in segs:
                    o.append(f'<polyline points="{" ".join(s)}" fill="none" style="stroke:{c}" stroke-width="2" '
                             f'stroke-linejoin="round" stroke-linecap="round"'
                             f'{DASH if dashed else ""}/>')
                if markers:
                    for x, v in zip(xs, ys):
                        if v is not None and math.isfinite(v):
                            _marker(o, MARKERS.get(slot, "circle"), X(x), Y(v), c, 3)
            elif kind == "points":
                for x, v in zip(xs, ys):
                    if v is not None and math.isfinite(v):
                        _marker(o, MARKERS.get(slot, "circle"), X(x), Y(v), c)
            elif kind == "vline":
                o.append(f'<line x1="{X(xs):.1f}" y1="{T}" x2="{X(xs):.1f}" y2="{T + PH}" '
                         f'style="stroke:{var("muted")}" stroke-width="1" stroke-dasharray="3 3"/>')
                if label:
                    o.append(f'<text x="{X(xs) + 5:.1f}" y="{T + 13}" font-size="11" '
                             f'style="fill:{var("muted")}">{_esc(label)}</text>')
            elif kind == "hline":
                o.append(f'<line x1="{L}" y1="{Y(ys):.1f}" x2="{L + PW}" y2="{Y(ys):.1f}" '
                         f'style="stroke:{var("muted")}" stroke-width="1" stroke-dasharray="3 3"/>')
                if label:
                    o.append(f'<text x="{L + PW - 4}" y="{Y(ys) - 4:.1f}" text-anchor="end" font-size="11" '
                             f'style="fill:{var("muted")}">{_esc(label)}</text>')
            if label and kind in ("line", "points"):
                legend.append((label, slot, kind == "points" or markers, dashed))
        o.append("</g>")
        lx = L + PW
        for label, slot, marked, dashed in reversed(legend):      # right-aligned, in the title row
            w = 7 * len(label) + 30
            lx -= w
            c = var(f"s{slot}")
            if marked:
                _marker(o, MARKERS.get(slot, "circle"), lx + 9, T - 22, c)
            else:
                o.append(f'<line x1="{lx}" y1="{T - 22}" x2="{lx + 18}" y2="{T - 22}" style="stroke:{c}" '
                         f'stroke-width="2"{DASH if dashed else ""}/>')
            o.append(f'<text x="{lx + 22}" y="{T - 18}" font-size="12" style="fill:{var("primary")}">{_esc(label)}</text>')
        for i, text in enumerate(p.notes):
            o.append(f'<text x="{L + 8}" y="{T + PH - 8 - 15 * (len(p.notes) - 1 - i)}" font-size="11" '
                     f'style="fill:{var("muted")}">{_esc(text)}</text>')
        y0 += h
    o.append("</svg>")
    return "\n".join(o)


def write(path, panels, theme="auto", width=760, title=None):
    """Write the figure to path. Returns path."""
    with open(path, "w") as f:
        f.write(render(panels, theme, width, title))
    return path


def retheme(svg, theme):
    """A figure written with theme="auto", fixed to "light" or "dark": for a
    site that switches themes itself rather than following the system."""
    start = svg.index("<style>") + len("<style>")
    end = svg.index("</style>")
    css = ":root{" + ";".join(f"--{k}:{v}" for k, v in THEMES[theme].items()) + "}"
    return svg[:start] + css + svg[end:]
