#!/usr/bin/env python3
"""Turn fabric-school.html into a print-ready book, for Chrome's --print-to-pdf.

The web version and the print version share their content but not their layout:
the screen has a sticky rail, live calculators and collapsed answers, and a page
has none of those.  So this script keeps the prose and swaps everything around it.

  python3 make_print_html.py            # writes fabric-school-print.html
"""
import html, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, "index.html")
CSS  = os.path.join(HERE, "print.css")
OUT  = os.path.join(HERE, "fabric-school-print.html")

FONTS = ('https://fonts.googleapis.com/css2?family=Bitter:wght@500;700'
         '&family=Source+Serif+4:ital,opsz,wght@0,8..60,400;0,8..60,600;1,8..60,400'
         '&family=IBM+Plex+Mono:wght@400;600&display=swap')


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sections(src):
    """Every lesson, in order: (id, number, title, markup)."""
    out = []
    for mo in re.finditer(r'<section class="part" id="(l[0-9a-z]+)">', src):
        start = mo.start()
        end = src.index("</section>", start) + len("</section>")
        body = src[start:end]
        head = re.search(r'<span class="part-n">([0-9A-Z]+)</span><h2>(.*?)</h2>',
                         body, re.S)
        out.append((mo.group(1), head.group(1), head.group(2), body))
    return out


def toc(src, secs):
    """Rebuild the contents page from the nav rail, so the two cannot drift."""
    titles = {sid: title for sid, _, title, _ in secs}
    nums   = {sid: n for sid, n, _, _ in secs}
    rows   = []
    nav = src[src.index('<nav class="rail"'):src.index("</nav>")]
    for mo in re.finditer(r'<h4>(.*?)</h4>|href="#(l[0-9a-z]+)"', nav):
        if mo.group(1):
            rows.append('<li class="bd">%s</li>' % mo.group(1))
        else:
            sid = mo.group(2)
            rows.append('<li><span class="tn">%s</span><span>%s</span></li>'
                        % (nums[sid], titles[sid]))
    return '<div class="toc"><h2>Contents</h2><ol>\n' + "\n".join(rows) + "\n</ol></div>"


def cover(n_lessons):
    return f"""<div class="cover">
  <p class="kick">Fishball7020 &middot; PlutoSky &middot; 7020-SDR</p>
  <h1>Fabric School</h1>
  <p class="sub">A ground-up course in software-defined radio, and in the FPGA inside this one.
     {n_lessons} lessons, from what a radio <em>is</em> to your own signal processing running in
     the AD9361 datapath &mdash; by way of spectra, noise, filters, modulation and link budgets.</p>
  <p class="sub" style="font-size:10.5pt;color:#5C6A77">Assumes no Verilog, no Vivado, no FPGA
     experience, and no signal processing. Every term is defined the first time it appears.</p>
  <div class="spec">
    Xilinx XC7Z020-CLG400 &nbsp;&middot;&nbsp; Analog Devices AD9361, 2R2T<br>
    Vivado / Vitis 2022.2 &nbsp;&middot;&nbsp; Ubuntu 22.04 &nbsp;&middot;&nbsp; Verilog-2001<br>
    Written against the fishball7020-fpga-devkit block design
  </div>
</div>"""


FOOTER = """<footer><div class="foot-in">
  <p><strong>Fabric School</strong> &mdash; written against the Fishball7020 / PlutoSky devkit
    (Xilinx XC7Z020-CLG400 + Analog Devices AD9361), Vivado/Vitis 2022.2 on Ubuntu 22.04.</p>
  <p style="margin-bottom:0">Every trap in these pages is one that actually cost someone a build, a
    measurement, or an afternoon.</p>
</div></footer>"""


def main():
    src  = read(SRC)
    css  = read(CSS)
    secs = sections(src)
    lessons = [s for s in secs if s[1].isdigit()]

    body = []
    for _, _, _, markup in secs:
        # answers are collapsed on screen; on paper they have to be visible
        markup = markup.replace('<details class="check">', '<details class="check" open>')
        body.append(markup)

    doc = (f'<!doctype html><html><head><meta charset="utf-8">'
           f'<title>Fabric School</title>'
           f'<link rel="stylesheet" href="{FONTS}">\n'
           f'<style>\n{css}\n</style></head><body>\n'
           + cover(len(lessons)) + "\n"
           + toc(src, secs) + "\n"
           + "\n".join(body) + "\n"
           + FOOTER + "\n</body></html>\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"{OUT}: {len(lessons)} lessons + {len(secs)-len(lessons)} appendix, {len(doc):,} bytes")


if __name__ == "__main__":
    sys.exit(main())
