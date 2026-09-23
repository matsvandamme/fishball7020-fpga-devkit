# Fabric School

A ground-up course in software-defined radio, and in the FPGA inside this one.
Thirty-nine lessons and an appendix, written against **this** board — its block
design, its clocks, its measured numbers.

It assumes you have never written a line of Verilog, never opened Vivado, and
are not sure what an FPGA is — or what a spectrum, a decibel or a constellation
is either. Every term is defined the first time it appears.

| File | What it is |
|---|---|
| [`index.html`](index.html) | The course. One self-contained file, no build step, day/night theme, ten live calculators. |
| [`Fabric-School.pdf`](Fabric-School.pdf) | The same content as a 98-page book, for reading away from a screen. |
| `fabric-school-print.html` | Generated. The print layout the PDF is rendered from. |
| `print.css` · `make_print_html.py` | The print stylesheet and the script that applies it. |

## Reading it

**[matsvandamme.github.io/fishball7020-fpga-devkit/course/](https://matsvandamme.github.io/fishball7020-fpga-devkit/course/)** — published
from this folder, so it is always what is committed here.

Or open `index.html` locally; it is self-contained and needs nothing installed.
Browsing to it on github.com shows you the source rather than the page, so
download it first:

```bash
# run from: anywhere
curl -sLO https://raw.githubusercontent.com/matsvandamme/fishball7020-fpga-devkit/main/docs/course/index.html
xdg-open index.html
```

The PDF is the same material, with the calculators removed and every "check
yourself" answer already open.

## What it covers

| Lessons | |
|---|---|
| **0–3** | What a radio is, what an FPGA is, what is on this board, what each tool does |
| **4–10** | Verilog from nothing: modules, clocks, the two assignments, widths, fixed point, testbenches |
| **11–16** | The radio's datapath: IQ samples, sampling and aliasing, the block design, clock domains, the packers, DMA into memory |
| **17–22** | Changing the fabric: a worked example, Tcl, constraints, driving Vivado, clock crossings, registers |
| **23–24** | Signals before the fabric: the frequency domain, noise and decibels |
| **25–27** | DSP in the fabric: filters, decimation, mixers and CORDIC |
| **28–32** | Building a link: modulation, pulse shaping, synchronisation, correlation, OFDM |
| **33–36** | Measuring: the six figures of merit, link budgets, IQ metadata, two coherent receivers |
| **37–38** | Projects, and the rules worth taping to the wall |
| **A** | Where to go for more, and what this course leaves out |

Every measured number in it comes from this repository's `docs/` — mostly
[`measured-performance.md`](../measured-performance.md),
[`modulation-and-throughput.md`](../modulation-and-throughput.md) and
[`both-receive-channels.md`](../both-receive-channels.md) — with the measurement
conditions attached.

## Rebuilding the PDF

Edit `index.html`; everything else is generated from it.

```bash
# run from: docs/course/
python3 make_print_html.py
google-chrome --headless=new --no-pdf-header-footer \
  --print-to-pdf=Fabric-School.pdf "file://$PWD/fabric-school-print.html"
```

`make_print_html.py` rebuilds the contents page from the course's own navigation,
so the two cannot drift apart, hides the calculators, and opens every collapsed
answer. Any Chromium will do in place of `google-chrome`.
