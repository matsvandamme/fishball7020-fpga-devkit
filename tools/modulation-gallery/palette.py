#!/usr/bin/env python3
"""Check a categorical palette instead of trusting it.

Four checks, all computed:
  * adjacent-pair separation in OKLab (dE*100), for normal vision and under
    simulated deuteranopia and protanopia. Target >= 8; 6-8 only with a second
    encoding; a NORMAL-vision value below 15 is a hard fail.
  * lightness band: the steps should sit in a similar L range so no one series
    shouts.
  * chroma floor: nothing so grey it reads as a gridline.
  * contrast against the chart surface, so a thin 2 px line stays visible.
"""
import numpy as np

def hex2rgb(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i+2], 16) / 255 for i in (0, 2, 4)])

def srgb2lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def lin2oklab(rgb):
    m1 = np.array([[0.4122214708, 0.5363325363, 0.0514459929],
                   [0.2119034982, 0.6806995451, 0.1073969566],
                   [0.0883024619, 0.2817188376, 0.6299787005]])
    lms = m1 @ rgb
    l = np.cbrt(lms)
    m2 = np.array([[0.2104542553, 0.7936177850, -0.0040720468],
                   [1.9779984951, -2.4285922050, 0.4505937099],
                   [0.0259040371, 0.7827717662, -0.8086757660]])
    return m2 @ l

def oklab(h):
    return lin2oklab(srgb2lin(hex2rgb(h)))

# Viénot-Brettel-Mollon dichromat simulation in linear RGB
def cvd(rgb, kind):
    M = np.array([[0.31399022, 0.63951294, 0.04649755],
                  [0.15537241, 0.75789446, 0.08670142],
                  [0.01775239, 0.10944209, 0.87256922]])
    Mi = np.linalg.inv(M)
    lms = M @ rgb
    if kind == "deuteranopia":
        S = np.array([[1, 0, 0], [0.49421, 0, 1.24827], [0, 0, 1]])
    else:                                       # protanopia
        S = np.array([[0, 2.02344, -2.52581], [0, 1, 0], [0, 0, 1]])
    return Mi @ (S @ lms)

def de(a, b):
    return float(np.linalg.norm(a - b) * 100)

def contrast(h, surface):
    def lum(x):
        r = srgb2lin(hex2rgb(x)); return 0.2126*r[0] + 0.7152*r[1] + 0.0722*r[2]
    a, b = lum(h), lum(surface)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)

def check(pal, surface, label):
    print(f"\n  {label}  (surface {surface})")
    labs = [oklab(h) for h in pal]
    Ls = [l[0] for l in labs]
    Cs = [float(np.hypot(l[1], l[2])) for l in labs]
    ok = True
    print(f"    lightness band  L {min(Ls):.3f}-{max(Ls):.3f}  (spread {max(Ls)-min(Ls):.3f})")
    if max(Ls) - min(Ls) > 0.32:
        print("      WARN wide lightness spread"); 
    print(f"    chroma floor    {min(Cs):.3f}  " + ("PASS" if min(Cs) > 0.045 else "FAIL"))
    ok &= min(Cs) > 0.045
    print("    adjacent pairs:")
    for i in range(len(pal) - 1):
        a, b = pal[i], pal[i+1]
        dn = de(oklab(a), oklab(b))
        dd = de(lin2oklab(cvd(srgb2lin(hex2rgb(a)), "deuteranopia")),
                lin2oklab(cvd(srgb2lin(hex2rgb(b)), "deuteranopia")))
        dp = de(lin2oklab(cvd(srgb2lin(hex2rgb(a)), "protanopia")),
                lin2oklab(cvd(srgb2lin(hex2rgb(b)), "protanopia")))
        worst = min(dd, dp)
        verdict = "PASS" if (worst >= 8 and dn >= 15) else (
                  "FAIL-normal" if dn < 15 else "FLOOR(needs 2nd encoding)" if worst >= 6 else "FAIL-cvd")
        ok &= verdict == "PASS"
        print(f"      {a} vs {b}:  normal {dn:5.1f}  deut {dd:5.1f}  prot {dp:5.1f}   {verdict}")
    print("    contrast vs surface:")
    for h in pal:
        c = contrast(h, surface)
        print(f"      {h}: {c:5.2f}:1  " + ("PASS" if c >= 3.0 else "WARN (label it)"))
        ok &= c >= 3.0
    print("    ->", "palette passes" if ok else "palette needs work")
    return ok

if __name__ == "__main__":
    import sys
    pal = sys.argv[1].split(",")
    surf = sys.argv[2] if len(sys.argv) > 2 else "#0f1218"
    raise SystemExit(0 if check(pal, surf, "categorical") else 1)
