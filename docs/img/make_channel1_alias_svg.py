#!/usr/bin/env python3
"""Redraw docs/img/channel1-alias-{light,dark}.svg from measured spectra.

Reads docs/img/data/channel1-alias.json: four captures of CHANNEL 1 (RX2) with
an FPGA-generated tone at 10 MHz sent out of TX2A, through a 20 dB pad, back
into RX2A. Two builds (stock and the optional both-channels patch) x two states
of the fabric decimator (bypassed and engaged).

Left panel, decimator bypassed: the tone sits at +10 MHz in both builds, which
is where it actually is. That panel exists to prove the signal is present and
that the patch has not simply silenced channel 1.

Right panel, decimator engaged: the window is now only +-3.84 MHz, so 10 MHz is
outside it. Stock, it folds to 10 - 7.68 = +2.32 MHz at almost full strength -
an alias indistinguishable from a real signal. Patched, it is gone.

Standard library only, matching the rest of this repo. The two series colours
are slots 1 and 2 of the validated reference palette - they pass the
colour-vision and contrast checks as a pair in both light and dark. Do not
substitute them by eye.

Usage:  python3 make_channel1_alias_svg.py [output_dir]
"""
import json, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
D = json.load(open(HERE / "data" / "channel1-alias.json"))

THEMES = {
    "light": dict(bg="#FFFFFF", panel="#F7F8F9", ink="#10151A", ink2="#414D57",
                  muted="#68757F", rule="#D6DCE1", grid="#E8EBEE",
                  s1="#2a78d6", s2="#eb6834"),
    "dark":  dict(bg="#161C22", panel="#1B222A", ink="#E9EEF2", ink2="#BAC6CF",
                  muted="#8795A0", rule="#2A353D", grid="#222C34",
                  s1="#3987e5", s2="#d95926"),
}

W, H = 940, 400
PAD_L, PAD_R, PAD_T, PAD_B = 58, 18, 86, 70
GAP = 44
PW = (W - PAD_L - PAD_R - GAP) / 2          # panel width
PH = H - PAD_T - PAD_B
YLO, YHI = -80, 30                          # dBFS


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def panel(ox, xlo, xhi, series, title, sub, T, xticks, labels):
    """One spectrum panel. series = [(f_list, db_list, colour)]"""
    o = []
    X = lambda v: ox + (v - xlo) / (xhi - xlo) * PW
    Y = lambda v: PAD_T + (1 - (v - YLO) / (YHI - YLO)) * PH

    o.append(f'<rect x="{ox:.1f}" y="{PAD_T}" width="{PW:.1f}" height="{PH}" '
             f'fill="{T["panel"]}" stroke="{T["rule"]}" stroke-width="1" rx="3"/>')
    # horizontal grid every 20 dB
    v = YLO
    while v <= YHI:
        o.append(f'<line x1="{ox:.1f}" x2="{ox+PW:.1f}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" '
                 f'stroke="{T["grid"]}" stroke-width="1"/>')
        if ox == PAD_L:
            o.append(f'<text x="{ox-8:.1f}" y="{Y(v)+3.5:.1f}" text-anchor="end" '
                     f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10" '
                     f'fill="{T["muted"]}">{v:g}</text>')
        v += 20
    for t in xticks:
        o.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{PAD_T}" y2="{PAD_T+PH}" '
                 f'stroke="{T["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{X(t):.1f}" y="{PAD_T+PH+15:.1f}" text-anchor="middle" '
                 f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10" '
                 f'fill="{T["muted"]}">{t:g}</text>')

    for f, db, col in series:
        pts = []
        for i, (fx, dy) in enumerate(zip(f, db)):
            if fx < xlo or fx > xhi:
                continue
            pts.append(("M" if not pts else "L") + f"{X(fx):.1f} {Y(max(min(dy, YHI), YLO)):.1f}")
        o.append(f'<path d="{" ".join(pts)}" fill="none" stroke="{col}" '
                 f'stroke-width="1.8" stroke-linejoin="round"/>')

    o.append(f'<text x="{ox:.1f}" y="{PAD_T-26:.1f}" font-family="IBM Plex Sans, system-ui, sans-serif" '
             f'font-size="13" font-weight="600" fill="{T["ink"]}">{esc(title)}</text>')
    o.append(f'<text x="{ox:.1f}" y="{PAD_T-10:.1f}" font-family="IBM Plex Mono, ui-monospace, monospace" '
             f'font-size="10.5" fill="{T["muted"]}">{esc(sub)}</text>')
    for lx, ly, text, col, anchor in labels:
        o.append(f'<text x="{X(lx):.1f}" y="{Y(ly):.1f}" text-anchor="{anchor}" '
                 f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10.5" '
                 f'font-weight="600" fill="{col}">{esc(text)}</text>')
    return "".join(o)


def build(theme):
    T = THEMES[theme]
    o = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
         f'<rect width="{W}" height="{H}" fill="{T["bg"]}"/>']

    SW = D["sweep"]
    nyq = SW["nyquist_mhz"]

    # ---- left: measured anti-alias response, swept ----
    ox, xlo, xhi = PAD_L, 0, 20
    ylo, yhi = -80, 10
    X = lambda v: ox + (v - xlo) / (xhi - xlo) * PW
    Y = lambda v: PAD_T + (1 - (v - ylo) / (yhi - ylo)) * PH
    o.append(f'<rect x="{ox}" y="{PAD_T}" width="{PW:.1f}" height="{PH}" fill="{T["panel"]}" '
             f'stroke="{T["rule"]}" stroke-width="1" rx="3"/>')
    v = ylo
    while v <= yhi:
        o.append(f'<line x1="{ox}" x2="{ox+PW:.1f}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" '
                 f'stroke="{T["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{ox-8}" y="{Y(v)+3.5:.1f}" text-anchor="end" '
                 f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10" '
                 f'fill="{T["muted"]}">{v:g}</text>')
        v += 20
    for t in (0, 5, 10, 15, 20):
        o.append(f'<line x1="{X(t):.1f}" x2="{X(t):.1f}" y1="{PAD_T}" y2="{PAD_T+PH}" '
                 f'stroke="{T["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{X(t):.1f}" y="{PAD_T+PH+15:.1f}" text-anchor="middle" '
                 f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10" '
                 f'fill="{T["muted"]}">{t:g}</text>')
    o.append(f'<line x1="{X(nyq):.1f}" x2="{X(nyq):.1f}" y1="{PAD_T}" y2="{PAD_T+PH}" '
             f'stroke="{T["muted"]}" stroke-width="1" stroke-dasharray="3 3"/>')
    o.append(f'<text x="{X(nyq)+5:.1f}" y="{PAD_T+13:.1f}" '
             f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="9.5" '
             f'fill="{T["muted"]}">window edge, 3.84 MHz</text>')
    for key, col in (("stock", T["s1"]), ("patched", T["s2"])):
        pts = []
        for r in SW[key]:
            pts.append(("M" if not pts else "L") +
                       f"{X(r['tone']):.1f} {Y(max(min(r['resp_db'], yhi), ylo)):.1f}")
        o.append(f'<path d="{" ".join(pts)}" fill="none" stroke="{col}" stroke-width="2" '
                 f'stroke-linejoin="round"/>')
        for r in SW[key]:
            o.append(f'<circle cx="{X(r["tone"]):.1f}" cy="{Y(max(min(r["resp_db"],yhi),ylo)):.1f}" '
                     f'r="2.6" fill="{col}"/>')
    o.append(f'<text x="{X(11):.1f}" y="{Y(5):.1f}" font-family="IBM Plex Mono, ui-monospace, monospace" '
             f'font-size="10.5" font-weight="600" fill="{T["s1"]}">stock: no attenuation at all</text>')
    o.append(f'<text x="{X(11):.1f}" y="{Y(-62):.1f}" font-family="IBM Plex Mono, ui-monospace, monospace" '
             f'font-size="10.5" font-weight="600" fill="{T["s2"]}">patched: \u221270 dB stopband</text>')
    o.append(f'<text x="{ox}" y="{PAD_T-26}" font-family="IBM Plex Sans, system-ui, sans-serif" '
             f'font-size="13" font-weight="600" fill="{T["ink"]}">Measured anti-alias response, channel 1</text>')
    o.append(f'<text x="{ox}" y="{PAD_T-10}" font-family="IBM Plex Mono, ui-monospace, monospace" '
             f'font-size="10.5" fill="{T["muted"]}">tone swept 0.2\u201320 MHz \u00b7 level vs the same tone undecimated</text>')
    o.append(f'<text x="{ox+PW/2:.1f}" y="{PAD_T+PH+32:.1f}" text-anchor="middle" '
             f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10" '
             f'fill="{T["muted"]}">tone frequency \u00b7 MHz</text>')

    # ---- right: the spectrum at 10 MHz, decimator engaged ----
    sd, pd = D["stock_decimated"], D["patched_decimated"]
    ox2 = PAD_L + PW + GAP
    X2 = lambda v: ox2 + (v + 3.84) / 7.68 * PW
    Y2 = lambda v: PAD_T + (1 - (v - ylo) / (yhi - ylo)) * PH
    o.append(f'<rect x="{ox2:.1f}" y="{PAD_T}" width="{PW:.1f}" height="{PH}" fill="{T["panel"]}" '
             f'stroke="{T["rule"]}" stroke-width="1" rx="3"/>')
    v = ylo
    while v <= yhi:
        o.append(f'<line x1="{ox2:.1f}" x2="{ox2+PW:.1f}" y1="{Y2(v):.1f}" y2="{Y2(v):.1f}" '
                 f'stroke="{T["grid"]}" stroke-width="1"/>')
        v += 20
    for t in (-3, -1.5, 0, 1.5, 3):
        o.append(f'<line x1="{X2(t):.1f}" x2="{X2(t):.1f}" y1="{PAD_T}" y2="{PAD_T+PH}" '
                 f'stroke="{T["grid"]}" stroke-width="1"/>')
        o.append(f'<text x="{X2(t):.1f}" y="{PAD_T+PH+15:.1f}" text-anchor="middle" '
                 f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10" '
                 f'fill="{T["muted"]}">{t:g}</text>')
    for src, col in ((sd, T["s1"]), (pd, T["s2"])):
        pts = []
        for fx, dy in zip(src["f_mhz"], src["psd_db"]):
            if fx < -3.84 or fx > 3.84:
                continue
            pts.append(("M" if not pts else "L") + f"{X2(fx):.1f} {Y2(max(min(dy, yhi), ylo)):.1f}")
        o.append(f'<path d="{" ".join(pts)}" fill="none" stroke="{col}" stroke-width="1.6"/>')
    o.append(f'<text x="{X2(2.32)-6:.1f}" y="{Y2(4):.1f}" text-anchor="end" '
             f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10.5" '
             f'font-weight="600" fill="{T["s1"]}">alias, +2.32 MHz</text>')
    o.append(f'<text x="{ox2+8:.1f}" y="{Y2(-64):.1f}" '
             f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10.5" '
             f'font-weight="600" fill="{T["s2"]}">patched: gone</text>')
    o.append(f'<text x="{ox2:.1f}" y="{PAD_T-26}" font-family="IBM Plex Sans, system-ui, sans-serif" '
             f'font-size="13" font-weight="600" fill="{T["ink"]}">What that looks like at 10 MHz</text>')
    o.append(f'<text x="{ox2:.1f}" y="{PAD_T-10}" font-family="IBM Plex Mono, ui-monospace, monospace" '
             f'font-size="10.5" fill="{T["muted"]}">decimated to 7.68 MSPS \u00b7 4096-pt FFT \u00b7 Hann</text>')
    o.append(f'<text x="{ox2+PW/2:.1f}" y="{PAD_T+PH+32:.1f}" text-anchor="middle" '
             f'font-family="IBM Plex Mono, ui-monospace, monospace" font-size="10" '
             f'fill="{T["muted"]}">frequency offset \u00b7 MHz</text>')

    # ---- header and legend ----
    o.append(f'<text x="{PAD_L}" y="24" font-family="IBM Plex Sans, system-ui, sans-serif" '
             f'font-size="15" font-weight="600" fill="{T["ink"]}">'
             f'Channel 1 (RX2) with the FPGA decimator engaged</text>')
    o.append(f'<text x="{PAD_L}" y="42" font-family="IBM Plex Sans, system-ui, sans-serif" '
             f'font-size="11.5" fill="{T["ink2"]}">'
             f'TX2A \u2192 20 dB pad \u2192 RX2A at 900 MHz \u00b7 converter 61.44 MSPS \u00b7 measured 2026-09-23</text>')
    ly = H - 20
    x = PAD_L
    for text, col in (("stock \u2014 channel 1 has no filter", T["s1"]),
                      ("patched \u2014 both channels filtered in lockstep", T["s2"])):
        o.append(f'<rect x="{x}" y="{ly-4}" width="16" height="3" rx="1.5" fill="{col}"/>')
        o.append(f'<text x="{x+22}" y="{ly}" font-family="IBM Plex Sans, system-ui, sans-serif" '
                 f'font-size="11.5" fill="{T["ink2"]}">{text}</text>')
        x += 30 + len(text) * 6.2
    o.append(f'<text x="{PAD_L-46}" y="{PAD_T+PH/2:.1f}" transform="rotate(-90 {PAD_L-46} {PAD_T+PH/2:.1f})" '
             f'text-anchor="middle" font-family="IBM Plex Mono, ui-monospace, monospace" '
             f'font-size="10" fill="{T["muted"]}">dB</text>')
    o.append('</svg>')
    return "\n".join(o)


def main():
    out = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE
    for theme in THEMES:
        p = out / f"channel1-alias-{theme}.svg"
        p.write_text(build(theme))
        print("wrote", p)
    sd, pd = D["stock_decimated"], D["patched_decimated"]
    print(f"suppression: {sd['peak_db'] - pd['peak_db']:.1f} dB "
          f"({sd['peak_db']:.1f} dB at {sd['peak_mhz']:+.3f} MHz "
          f"-> {pd['peak_db']:.1f} dB)")


if __name__ == "__main__":
    main()
