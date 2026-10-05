#!/usr/bin/env python3
"""Draw the Building section's diagrams, each in a light and a dark variant.

    # run from: the repo root
    python3 docs/img/make_build_figures.py        # stdlib only

Writes into docs/img/:

    build-path-{light,dark}.svg           doctor -> setup -> build -> verify -> flash
    build-xsa-{light,dark}.svg            the FPGA half from Vivado, or from an XSA
    build-change-map-{light,dark}.svg     what you changed -> the file -> the flash flag
    build-kernel-loop-{light,dark}.svg    edit, build uImage, flash it, read dmesg
    build-devicetree-{light,dark}.svg     dtsi + overlay -> .dtb -> verify_dtb -> flash
    build-container-{light,dark}.svg      what runs in the container and what on the host
    build-insert-points-{light,dark}.svg  upstream's datapath and where your logic goes
    build-wbfm-datapath-{light,dark}.svg  the receive path with the FM channelizer

The look comes from make_start_figures.py (same helpers, same colours). Pages
show a diagram as `![alt](img/x-light.svg#only-light)` plus the
`-dark.svg#only-dark` twin. Every number and name drawn here comes from the
pages that show the figure.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from make_start_figures import Fig, both  # noqa: E402


def chain(f, y, stages, x0=20, bw=132, gap=22, h=74, colour="accent"):
    """A row of boxes joined by arrows. stages: (title, sub lines, fill, stroke)."""
    for i, (title, sub, fill, stroke) in enumerate(stages):
        x = x0 + i * (bw + gap)
        f.box(x, y, bw, h, title, sub, fill=fill, stroke=stroke)
        if i < len(stages) - 1:
            f.arrow(x + bw + 2, y + h / 2, x + bw + gap - 2, y + h / 2, colour=colour)


# --- doctor -> setup -> build -> verify -> flash -------------------------------

def path(t):
    f = Fig(790, 132, t)
    plain = ("surface", "line")
    chain(f, 14, (
        ("doctor", ("can this", "machine build?"), *plain),
        ("setup", ("fetch the sources,", "apply the patches"), *plain),
        ("build", ("the SD-card files,", "into output/"), "accent_soft", "accent"),
        ("verify", ("is the build sane?", "--board: is it running?"), *plain),
        ("flash", ("over the network,", "md5-verified"), "ok_soft", "ok"),
    ))
    f.text(20, 116, "Each is one ./devkit command, run from the repo root.", 12, "muted", anchor="start")
    return f


# --- with or without Vivado ----------------------------------------------------

def xsa(t):
    f = Fig(790, 250, t)
    f.text(20, 26, "The FPGA half: build it, or take it from an XSA", 14, "ink", 600, "start")
    f.box(20, 44, 230, 74, "Vivado 2022.2", ("about 50 GB installed,", "20 to 70 min of every build"))
    f.box(20, 150, 230, 74, "An XSA you already have", ("a release's system_top.xsa,", "or one saved from a full build"),
          fill="ok_soft", stroke="ok")
    f.box(330, 97, 150, 74, "The XSA", ("system_top.bit", "ps7_init.c"), fill="accent_soft", stroke="accent", mono_sub=True)
    f.arrow(250, 81, 328, 120, colour="muted")
    f.arrow(250, 187, 328, 148, colour="ok")
    f.text(292, 84, "builds", 12, "muted")
    f.text(292, 196, "--xsa", 12, "ok", mono=True)
    f.box(560, 60, 210, 148, "", ())
    f.text(665, 86, "The rest of the build", 14, "ink", 600)
    for i, s in enumerate(("FSBL", "U-Boot", "kernel", "root filesystem", "BOOT.bin")):
        f.text(665, 110 + i * 19, s, 12.5, "body")
    f.arrow(480, 134, 558, 134, colour="accent")
    f.text(665, 228, "minutes, nothing from AMD installed", 12, "muted")
    return f


# --- what you changed -> file -> flag ------------------------------------------

def change_map(t):
    f = Fig(790, 276, t)
    for x, s in ((120, "You changed"), (395, "The file that changes"), (660, "How it reaches the board")):
        f.text(x, 24, s, 13, "muted", 600)
    rows = (
        ("The FPGA", "HDL, block design", "BOOT.bin", "flash --boot-only", "accent_soft", "accent"),
        ("The kernel", "a driver, the config", "uImage", "flash --kernel-only", "accent_soft", "accent"),
        ("The device tree", "", "devicetree.dtb", "flash --dtb-only", "accent_soft", "accent"),
        ("The Debian root", "the overlay, packages", "rootfs.tar", "write-card: a new card", "surface", "line"),
    )
    for i, (what, sub, name, how, fill, stroke) in enumerate(rows):
        y = 38 + i * 58
        f.box(20, y, 200, 46, what, sub)
        f.arrow(222, y + 23, 298, y + 23, colour="muted")
        f.box(300, y, 190, 46, name, (), fill=fill, stroke=stroke)
        f.arrow(492, y + 23, 548, y + 23, colour="muted")
        f.box(550, y, 220, 46, how, (), title_fill="body")
    return f


# --- the kernel loop -----------------------------------------------------------

def kernel_loop(t):
    f = Fig(790, 170, t)
    plain = ("surface", "line")
    chain(f, 20, (
        ("Edit the driver", ("add dev_warn()",), *plain),
        ("Build uImage", ("about two minutes",), "accent_soft", "accent"),
        ("flash --kernel-only", ("back in about", "fifteen seconds"), "ok_soft", "ok"),
        ("Read dmesg", ("on the board",), *plain),
    ), bw=170, gap=23)
    # the way back: under the row, from the last box to the first
    c = t["muted"]
    f.raw(f'<path d="M 684 96 L 684 136 L 105 136 L 105 98" fill="none" stroke="{c}" stroke-width="1.6" '
          f'stroke-dasharray="5 4" marker-end="url(#a-muted)"/>')
    f.text(395, 156, "and again", 12, "muted")
    return f


# --- the modern device tree ----------------------------------------------------

def devicetree(t):
    f = Fig(790, 196, t)
    f.box(20, 20, 220, 62, "zynq-pluto-sdr.dtsi", ("ADI's: an ADALM-Pluto",))
    f.box(20, 112, 220, 62, "zynq-pluto-sdr-fishball.dts", ("the overlay: only where", "this board differs"),
          fill="accent_soft", stroke="accent")
    f.box(320, 66, 150, 62, "devicetree.dtb", ("the built tree",), fill="accent_soft", stroke="accent")
    f.arrow(240, 51, 318, 88, colour="muted")
    f.arrow(240, 143, 318, 106, colour="accent")
    f.box(540, 20, 230, 62, "verify_dtb.py", ("16 checks on the built .dtb",), fill="ok_soft", stroke="ok")
    f.box(540, 112, 230, 62, "flash --dtb-only", ("onto the running board",))
    f.arrow(470, 88, 538, 55, colour="ok")
    f.arrow(655, 82, 655, 110, colour="muted")
    return f


# --- the container -------------------------------------------------------------

def container(t):
    f = Fig(790, 262, t)
    f.box(20, 20, 750, 222, "", ())
    f.text(40, 46, "Your Linux host", 14, "ink", 600, "start")
    f.box(40, 62, 150, 68, "The repo", ("at its own", "absolute path"))
    f.box(40, 152, 150, 68, "/tools/Xilinx", ("Vivado 2022.2",), mono_sub=False)
    f.box(330, 62, 240, 158, "", (), fill="accent_soft", stroke="accent")
    f.text(450, 88, "The container", 14, "ink", 600)
    f.text(450, 107, "pinned Ubuntu 22.04, about 1.4 GB", 12, "muted")
    for i, s in enumerate(("doctor", "setup", "build", "build --hdl-only")):
        f.text(450, 134 + i * 19, s, 12.5, "body", mono=True)
    f.arrow(190, 96, 328, 96, "mounted, same path", "accent")
    f.arrow(190, 186, 328, 186, "mounted read-only", "muted")
    f.box(620, 62, 132, 158, "", ())
    f.text(686, 88, "Host only", 14, "ink", 600)
    for i, s in enumerate(("flash", "selftest", "gpio-check", "verify --board")):
        f.text(686, 118 + i * 19, s, 12.5, "body", mono=True)
    return f


# --- upstream's datapath, and where your logic goes -----------------------------

def insert_points(t):
    """This devkit's default build: both receive channels go through
    rx_fir_decimator (patch 0021); on transmit only channel 0 has a filter."""
    f = Fig(790, 440, t)
    f.text(210, 24, "Receive", 13, "muted", 600)
    f.text(580, 24, "Transmit", 13, "muted", 600)
    f.box(245, 36, 300, 46, "axi_ad9361", ("the AD9361's LVDS pins",))
    # receive, left: one column, both channels
    f.box(110, 146, 200, 62, "rx_fir_decimator", ("RX1 and RX2: ÷8, four FIRs",), fill="accent_soft", stroke="accent")
    f.box(110, 268, 200, 56, "cpack", ("util_cpack2",), mono_sub=True)
    f.box(110, 362, 200, 56, "adc_dma", ("axi_dmac",), mono_sub=True)
    f.arrow(300, 82, 222, 144, colour="accent")
    f.text(150, 104, "adc_data_i0/q0", 12, "accent", mono=True)
    f.text(150, 121, "adc_data_i1/q1", 12, "accent", mono=True)
    f.arrow(210, 208, 210, 266, colour="accent")
    f.arrow(210, 324, 210, 360, colour="muted")
    # transmit, right
    f.box(600, 146, 170, 62, "tx_fir_interpolator", ("channel 0 only: ×8",), fill="accent_soft", stroke="accent")
    f.box(480, 268, 200, 56, "tx_upack", ("util_upack2",), mono_sub=True)
    f.box(480, 362, 200, 56, "dac_dma", ("axi_dmac",), mono_sub=True)
    f.arrow(580, 360, 580, 326, colour="muted")
    f.arrow(628, 266, 676, 210, colour="accent")
    f.arrow(672, 144, 512, 84, colour="accent")
    f.text(672, 104, "dac_data_i0/q0", 12, "accent", mono=True)
    f.arrow(530, 266, 462, 84, colour="muted")
    f.text(486, 196, "dac_data_i1/q1", 12, "muted", mono=True, anchor="end")
    f.text(486, 213, "channel 1: direct", 12, "muted", anchor="end")
    # the insertion points
    ok = t["ok"]
    for cx, cy in ((261, 113), (210, 237), (496, 175), (592, 114), (652, 238)):
        f.raw(f'<circle cx="{cx}" cy="{cy}" r="7" fill="{t["ok_soft"]}" stroke="{ok}" stroke-width="2"/>')
    f.raw(f'<circle cx="352" cy="346" r="7" fill="{t["ok_soft"]}" stroke="{ok}" stroke-width="2"/>')
    f.text(366, 351, "your logic", 12.5, "ok", 600, "start")
    f.text(366, 369, "goes here", 12.5, "ok", 600, "start")
    return f


# --- the FM channelizer's receive path ------------------------------------------

def wbfm(t):
    f = Fig(790, 372, t)
    rows = (
        ("AD9361", ("LO 101.044 MHz, 4.224 MSPS",), "surface", "line",
         "wanted channel at +1.056 MHz; LO leak and DC offset at 0"),
        ("axi_ad9361", ("adc_data_i0 / adc_data_q0",), "surface", "line", ""),
        ("rx_ddc  (ad_fs4_ddc.v)", ("new: × exp(−jπn/2), 0 DSPs, 0 BRAM",), "ok_soft", "ok",
         "wanted channel now at DC; spur pushed to −1.056 MHz"),
        ("rx_fir_decimator", ("existing block, new coefficients",), "accent_soft", "accent",
         "321-tap lowpass, Fpass 100 kHz, Fstop 175 kHz, then ÷8"),
        ("cpack → adc_dma → USB", ("528 kSPS",), "surface", "line", "the channel and nothing else"),
    )
    for i, (title, sub, fill, stroke, note) in enumerate(rows):
        y = 14 + i * 72
        f.box(20, y, 300, 52, title, sub, fill=fill, stroke=stroke)
        if note:
            f.text(344, y + 31, note, 12.5, "body", anchor="start")
        if i < len(rows) - 1:
            f.arrow(170, y + 52, 170, y + 70, colour="muted")
    return f


def main():
    both("build-path", "The build path: doctor, setup, build, verify, flash", path)
    both("build-xsa", "The FPGA half of a build comes from Vivado or from an XSA", xsa)
    both("build-change-map", "Which file each kind of change rebuilds, and how it reaches the board", change_map)
    both("build-kernel-loop", "The kernel loop: edit, build uImage, flash it, read dmesg", kernel_loop)
    both("build-devicetree", "The modern device tree: ADI's dtsi plus this board's overlay", devicetree)
    both("build-container", "What runs in the build container and what stays on the host", container)
    both("build-insert-points", "Upstream's datapath, and where your own logic goes", insert_points)
    both("build-wbfm-datapath", "The receive path with the FM channelizer patch applied", wbfm)


if __name__ == "__main__":
    main()
