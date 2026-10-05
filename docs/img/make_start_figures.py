#!/usr/bin/env python3
"""Draw the Getting started figures: diagrams in a light and a dark variant,
and labelled crops of the board photographs.

    # run from: the repo root
    python3 docs/img/make_start_figures.py        # stdlib only; the photo figures need ImageMagick

Writes into docs/img/:

    start-loopback-{light,dark}.svg     TX -> 20 dB attenuator -> RX, with the levels
    start-card-{light,dark}.svg         the two partitions of the modern firmware's card
    start-connect-{light,dark}.svg      which socket goes where
    start-network-{light,dark}.svg      the board's two network interfaces
    start-bootchain-{light,dark}.svg    BootROM to root filesystem
    start-buildstages-{light,dark}.svg  build_all.sh's seven stages
    start-netconfig-{light,dark}.svg    where the Buildroot address settings live
    start-ports.svg                     the case's sockets, labelled (from plutosky-r1-ports.jpg)
    start-board.svg                     the bare board, labelled (from board.jpg)
    start-login-message.svg             the board's login message, from start-login-message.ansi

The login message is real output, captured with

    # run from: the repo root, with the board reachable
    ssh fishball 'run-parts /etc/update-motd.d' > docs/img/start-login-message.ansi

and drawn here line for line, colours included, up to its Health line.

Pages show a diagram as `![alt](img/x-light.svg#only-light)` plus the
`-dark.svg#only-dark` twin, so it follows the site's colour-scheme switch.
Every number and name drawn here comes from the pages that show the figure.
"""
import base64
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent

THEMES = {
    "light": dict(ink="#141415", body="#3c3c43", muted="#6e6e73", surface="#f8f8f8", line="#c9c9cf",
                  accent="#4069FF", accent_soft="#e9eeff", danger="#d6293e", danger_soft="#fdecee",
                  ok="#1a9e5c", ok_soft="#e6f6ee"),
    "dark": dict(ink="#f4f4f6", body="#cfcfd6", muted="#9a9aa3", surface="#1f1f23", line="#4a4a54",
                 accent="#8aa2ff", accent_soft="#232a47", danger="#ff7a8a", danger_soft="#3a1d22",
                 ok="#5fd39a", ok_soft="#17302a"),
}
FONT = "Inter, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "'JetBrains Mono', ui-monospace, 'DejaVu Sans Mono', Menlo, Consolas, monospace"


class Fig:
    def __init__(self, w, h, t):
        self.w, self.h, self.t, self.out = w, h, t, []

    def text(self, x, y, s, size=14, fill="body", weight=400, anchor="middle", mono=False):
        s = s.replace("&", "&amp;").replace("<", "&lt;")
        self.out.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{self.t[fill]}" '
                        f'text-anchor="{anchor}" font-family="{MONO if mono else FONT}">{s}</text>')

    def box(self, x, y, w, h, title, sub=(), fill="surface", stroke="line", title_fill="ink", r=8, mono_sub=False):
        self.out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{self.t[fill]}" '
                        f'stroke="{self.t[stroke]}" stroke-width="1.5"/>')
        sub = [sub] if isinstance(sub, str) else list(sub)
        top = y + h / 2 - (len(sub) * 17) / 2 + 5
        self.text(x + w / 2, top, title, 14, title_fill, 600)
        for i, s in enumerate(sub):
            self.text(x + w / 2, top + 19 + i * 17, s, 12, "muted", mono=mono_sub)

    def arrow(self, x1, y1, x2, y2, label=None, colour="muted", dash=False, label_dy=-8):
        c = self.t[colour]
        d = ' stroke-dasharray="5 4"' if dash else ""
        self.out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" stroke-width="1.6"{d} '
                        f'marker-end="url(#a-{colour})"/>')
        if label:
            self.text((x1 + x2) / 2, (y1 + y2) / 2 + label_dy, label, 12, colour)

    def line(self, x1, y1, x2, y2, colour="line", width=1.5):
        self.out.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{self.t[colour]}" stroke-width="{width}"/>')

    def raw(self, s):
        self.out.append(s)

    def svg(self, title):
        markers = "".join(
            f'<marker id="a-{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">'
            f'<path d="M0 0 L10 5 L0 10 z" fill="{self.t[k]}"/></marker>'
            for k in ("muted", "accent", "danger", "ok", "ink"))
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" '
                f'height="{self.h}" role="img"><title>{title}</title><defs>{markers}</defs>'
                + "".join(self.out) + "</svg>\n")


def both(name, title, draw):
    for theme, t in THEMES.items():
        f = draw(t)
        (HERE / f"{name}-{theme}.svg").write_text(f.svg(title))


# --- TX -> attenuator -> RX ---------------------------------------------------

def loopback(t):
    f = Fig(760, 250, t)
    f.text(20, 28, "With the attenuator", 14, "ink", 600, "start")
    f.box(20, 44, 150, 64, "TX1A", "about +19 dBm out")
    f.arrow(170, 76, 300, 76, "+19 dBm")
    f.box(300, 44, 160, 64, "20 dB attenuator", "at least 20 dB", fill="accent_soft", stroke="accent")
    f.arrow(460, 76, 590, 76, "about −1 dBm", "ok")
    f.box(590, 44, 150, 64, "RX1A", "survives +2.5 dBm", fill="ok_soft", stroke="ok")
    f.text(20, 158, "Without it", 14, "ink", 600, "start")
    f.box(20, 174, 150, 56, "TX1A", "about +19 dBm out")
    f.arrow(170, 202, 590, 202, "+19 dBm, about 16 dB over the limit", "danger")
    f.box(590, 174, 150, 56, "RX1A", "destroyed", fill="danger_soft", stroke="danger")
    return f


# --- the card ----------------------------------------------------------------

def card(t):
    f = Fig(760, 210, t)
    f.text(20, 26, "One microSD card, two partitions", 14, "ink", 600, "start")
    f.box(20, 42, 250, 150, "", (), fill="accent_soft", stroke="accent")
    f.text(145, 68, "1 · Boot partition", 14, "ink", 600)
    f.text(145, 87, "FAT, 128 MB: the board boots from it", 12, "muted")
    for i, name in enumerate(("BOOT.bin", "uImage", "devicetree.dtb", "uEnv.txt")):
        f.text(145, 112 + i * 19, name, 12.5, "body", mono=True)
    f.box(290, 42, 450, 150, "", ())
    f.text(515, 68, "2 · Debian root", 14, "ink", 600)
    f.text(515, 87, "ext4 (ext3 when written on Windows): Debian 13, with systemd", 12, "muted")
    f.text(515, 122, "the rest of the card", 12.5, "body")
    f.text(515, 144, "unpacked from debian-rootfs.tar.gz", 12.5, "body")
    f.text(515, 172, "Windows cannot create this one: use the card writer", 12, "muted")
    return f


# --- which socket goes where --------------------------------------------------

def connect(t):
    f = Fig(760, 300, t)
    f.box(280, 30, 200, 240, "", ())
    f.text(380, 58, "The board", 14, "ink", 600)
    f.text(380, 77, "BOOT switch: SD (0 0)", 12, "muted")
    for i, (name, sub) in enumerate((("ETH", "RJ45"), ("DEBUG", "USB-C"), ("USB", "USB-C"))):
        y = 100 + i * 56
        f.box(300, y, 160, 42, name, sub, fill="accent_soft", stroke="accent")
    f.box(20, 100, 180, 42, "Your router", "optional")
    f.arrow(300, 121, 202, 121, colour="muted", dash=True)
    f.text(250, 112, "DHCP", 12, "muted")
    f.box(560, 150, 180, 54, "Mains USB charger", "not a laptop port")
    f.arrow(460, 177, 558, 177, "power")
    f.box(20, 206, 180, 54, "Your PC", "reaches it at 192.168.2.1")
    f.arrow(300, 233, 202, 233, "network", "accent")
    f.text(650, 240, "On a laptop's USB power", 12, "muted")
    f.text(650, 257, "alone the board can hang", 12, "muted")
    return f


# --- the two interfaces ------------------------------------------------------

def network(t):
    f = Fig(760, 250, t)
    f.box(290, 24, 180, 202, "", ())
    f.text(380, 52, "The board", 14, "ink", 600)
    f.text(380, 71, "fishball.local", 12.5, "accent", mono=True)
    f.box(306, 88, 148, 54, "USB cable", "192.168.2.1", fill="ok_soft", stroke="ok", mono_sub=True)
    f.box(306, 156, 148, 54, "Ethernet", "DHCP, or static", fill="accent_soft", stroke="accent")
    f.box(20, 88, 190, 54, "Your PC", "ssh root@192.168.2.1", mono_sub=True)
    f.arrow(306, 115, 212, 115, colour="ok")
    f.text(259, 106, "fixed", 12, "ok")
    f.box(550, 156, 190, 54, "Your router", "hands out the address")
    f.arrow(454, 183, 548, 183, colour="accent")
    f.text(115, 172, "never changes with", 12, "muted")
    f.text(115, 189, "devkit net: the way back in", 12, "muted")
    f.text(645, 106, "devkit net static / dhcp", 12, "muted")
    f.text(645, 123, "change this side only", 12, "muted")
    return f


# --- rows of stages ----------------------------------------------------------

def row(title, stages, width=760, box_w=None, h=110):
    def draw(t):
        n = len(stages)
        gap = 22
        bw = box_w or (width - 40 - gap * (n - 1)) / n
        f = Fig(width, h, t)
        if title:
            f.text(20, 24, title, 14, "ink", 600, "start")
        y = 38 if title else 14
        for i, (name, sub) in enumerate(stages):
            x = 20 + i * (bw + gap)
            f.box(x, y, bw, 58, name, sub)
            if i < n - 1:
                f.arrow(x + bw + 2, y + 29, x + bw + gap - 2, y + 29, colour="accent")
        return f
    return draw


def netconfig(t):
    f = Fig(760, 220, t)
    f.box(20, 70, 210, 80, "U-Boot environment", ("128 KB in QSPI flash", "/dev/mtd1"), fill="accent_soft", stroke="accent")
    f.arrow(230, 110, 318, 110, colour="accent")
    f.text(274, 100, "every boot", 12, "muted")
    f.box(320, 76, 170, 68, "S40network", "reads it with fw_printenv")
    for i, name in enumerate(("/etc/network/interfaces", "/etc/udhcpd.conf", "/opt/config.txt")):
        y = 22 + i * 66
        f.arrow(490, 110, 548, y + 22, colour="muted")
        f.box(550, y, 190, 44, name, (), title_fill="body")
    f.text(645, 214, "generated: edits here are lost at reboot", 12, "muted")
    return f


# --- labelled photographs ----------------------------------------------------

def photo_figure(name, title, src, crop, size, labels, t=THEMES["light"]):
    """crop: WxH+X+Y of the source photo; size: the photo's drawn (w, h).
    labels: (text, sub, side, y, (px, py)) with the point in drawn-photo pixels."""
    jpg = subprocess.run(["magick", str(HERE / src), "-crop", crop, "+repage", "-resize", f"{size[0]}x{size[1]}!",
                          "-quality", "82", "jpg:-"], check=True, capture_output=True).stdout
    pw, ph = size
    margin = 215
    f = Fig(pw + 2 * margin, ph + 20, t)
    f.raw(f'<rect width="{f.w}" height="{f.h}" rx="10" fill="#ffffff" stroke="#e3e3e6"/>')
    f.raw(f'<image x="{margin}" y="10" width="{pw}" height="{ph}" '
          f'href="data:image/jpeg;base64,{base64.b64encode(jpg).decode()}"/>')
    for text, sub, side, y, (px, py) in labels:
        px, py = px + margin, py + 10
        lx = margin - 14 if side == "left" else pw + margin + 14
        f.raw(f'<line x1="{lx}" y1="{y - 4}" x2="{px}" y2="{py}" stroke="#4069FF" stroke-width="1.6"/>')
        f.raw(f'<circle cx="{px}" cy="{py}" r="5" fill="#ffffff" stroke="#4069FF" stroke-width="2"/>')
        anchor = "end" if side == "left" else "start"
        tx = lx - 6 if side == "left" else lx + 6
        f.text(tx, y, text, 14, "ink", 600, anchor)
        if sub:
            f.text(tx, y + 17, sub, 12, "muted", 400, anchor)
    (HERE / f"{name}.svg").write_text(f.svg(title))


def login_message():
    """The captured login message as an SVG: one <text> per line, one <tspan>
    per colour run. Handles the escapes the message uses: reset, bold, dim and
    24-bit foreground colour."""
    import re
    raw = (HERE / "start-login-message.ansi").read_text()
    lines = raw.split("\n")
    last = max(i for i, l in enumerate(lines) if "Health" in l)
    lines = lines[: last + 1]
    cw, lh, pad = 7.83, 17, 16
    width = max(len(re.sub(r"\x1b\[[0-9;]*m", "", l)) for l in lines)
    w, h = int(width * cw + 2 * pad), len(lines) * lh + 2 * pad
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">'
           f'<title>The board\'s login message</title><rect width="{w}" height="{h}" rx="8" fill="#16161a"/>'
           f'<g font-family="{MONO}" font-size="13" xml:space="preserve" style="white-space:pre">']
    colour, bold, dim = "#e6e6ea", False, False
    for n, line in enumerate(lines):
        x, spans = 0, []
        for part in re.split(r"(\x1b\[[0-9;]*m)", line):
            m = re.fullmatch(r"\x1b\[([0-9;]*)m", part)
            if m:
                codes = [int(c) for c in m.group(1).split(";") if c] or [0]
                if codes[:2] == [38, 2]:
                    colour = "#%02x%02x%02x" % tuple(codes[2:5])
                for c in ([] if codes[:2] == [38, 2] else codes):
                    if c == 0:
                        colour, bold, dim = "#e6e6ea", False, False
                    elif c == 1:
                        bold = True
                    elif c == 2:
                        dim = True
                continue
            if not part:
                continue
            fill = "#8f8f99" if dim else colour
            # one <tspan> per run of non-space characters, each at its own
            # column: SVG collapses runs of spaces, and a fallback font's
            # glyphs are not exactly one column wide
            for run in re.finditer(r"\S+", part):
                text = run.group(0).replace("&", "&amp;").replace("<", "&lt;")
                spans.append(f'<tspan x="{pad + (x + run.start()) * cw:.1f}" '
                             f'textLength="{len(run.group(0)) * cw:.1f}" lengthAdjust="spacingAndGlyphs" '
                             f'fill="{fill}"{" font-weight=\"700\"" if bold else ""}>{text}</tspan>')
            x += len(part)
        out.append(f'<text y="{pad + 12 + n * lh}">{"".join(spans)}</text>')
    out.append("</g></svg>\n")
    (HERE / "start-login-message.svg").write_text("".join(out))


def main():
    login_message()
    both("start-loopback", "A transmit port joined to a receive port through a 20 dB attenuator", loopback)
    both("start-card", "The two partitions of the modern firmware's microSD card", card)
    both("start-connect", "Which of the board's sockets goes where", connect)
    both("start-network", "The board's USB and Ethernet interfaces and their addresses", network)
    both("start-bootchain", "The boot chain, from BootROM to the root filesystem",
         row("", (("BootROM", "in silicon"), ("FSBL", "on-chip RAM"), ("bitstream", "into the FPGA"),
                  ("U-Boot", "in DDR"), ("kernel + DTB", "in DDR"), ("root filesystem", "RAM or ext4")), width=900, h=86))
    both("start-buildstages", "The seven build stages, in dependency order",
         row("", (("HDL", ""), ("bitstream", ""), ("FSBL", "needs the bitstream"), ("U-Boot", ""), ("kernel", ""),
                  ("root filesystem", ""), ("BOOT.bin", "the package")), width=1080, h=86))
    both("start-netconfig", "On Buildroot the address settings live in the U-Boot environment", netconfig)
    # The case, from the front: plutosky-r1-ports.jpg is 1228x1104.
    photo_figure("start-ports", "The case's sockets", "plutosky-r1-ports.jpg", "1010x770+150+318", (505, 385), (
        ("ETH", "Ethernet, to your router", "left", 200, (70, 148)),
        ("DEBUG", "USB-C: console, JTAG, power", "left", 265, (132, 206)),
        ("microSD slot", "under the DEBUG socket", "left", 330, (140, 233)),
        ("USB", "USB-C: to your PC, 192.168.2.1", "right", 290, (188, 243)),
        ("GPIO header (JP5)", "2 × 10 pins", "right", 40, (186, 24)),
    ))
    # The bare board: board.jpg is 800x800.
    photo_figure("start-board", "The bare board", "board.jpg", "330x600+238+118", (275, 500), (
        ("4 × SMA", "read the silkscreen for which", "left", 40, (70, 40)),
        ("AD9361", "the radio chip", "left", 150, (128, 156)),
        ("Zynq XC7Z020", "ARM processor + FPGA", "right", 260, (124, 268)),
        ("JP5 header", "", "left", 250, (28, 232)),
        ("Ethernet", "", "left", 420, (58, 420)),
        ("2 × USB-C", "USB and DEBUG", "right", 440, (182, 452)),
        ("microSD card", "", "right", 500, (150, 480)),
    ))


if __name__ == "__main__":
    main()
