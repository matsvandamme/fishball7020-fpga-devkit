#!/usr/bin/env python3
"""Build the examples' .grc files from one description each.

    # run from: the repo root
    python3 examples/mkgrc.py            # rebuild all three
    python3 examples/mkgrc.py 01         # just one
    python3 examples/mkgrc.py --check    # fail if the committed files differ

WHY A GENERATOR, when a .grc is a file you are supposed to edit in GRC?

Because each of these flowgraphs carries an embedded Python block, and a
.grc stores that block's source as a single YAML scalar - a few hundred lines
of Python with every newline escaped, inside a quoted string. Hand-maintaining
that is how you get a flowgraph whose block silently reverts to a cached port
signature because one escape was wrong. The first attempt at this cost an hour
to a `window_size: (1000,1000)` whose comma YAML read as a flow separator.

So the Python lives in `examples/lib/`, where it can be imported, linted and
unit-tested by `examples/test_blocks.py`, and this script injects it. PyYAML
does the quoting, which means the quoting is right by construction.

You can still open the .grc in GRC and edit it normally - it is an ordinary
flowgraph, and GRC will rewrite it in its own formatting when you save. If you
change an embedded block that way, copy the change back into `examples/lib/`
and re-run this script; `--check` in CI is what catches you forgetting.
"""
from __future__ import annotations

import os
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "lib")
GRC_VERSION = "3.10.7.0"

# The board is found by name. tools/board_addr.py does the same lookup and can
# print an address if mDNS is not working on your network.
URI = "'ip:fishball.local'"


# --------------------------------------------------------------------------
# the little bit of .grc structure we need
# --------------------------------------------------------------------------
#: GRC draws a block's `comment` on the canvas, in full, UNWRAPPED, below the
#: block. It is not a tooltip. Long comments therefore overlap their
#: neighbours and turn the flowgraph into a wall of text - the first version of
#: these examples was unusable for exactly that reason, while still compiling
#: and running perfectly, so nothing caught it but opening the editor and
#: looking. The same is true of a chooser's option LABELS.
#:
#: So: two short lines at most, and the depth goes in the example's README,
#: which is where this repository keeps depth anyway. These limits are asserted
#: rather than documented, because the failure is invisible from the compiler.
COMMENT_MAX_LINES = 2
COMMENT_MAX_CHARS = 46
OPTIONS_MAX_LINES = 11
OPTIONS_MAX_CHARS = 50


def _check_comment(bname, comment, max_lines=COMMENT_MAX_LINES,
                   max_chars=COMMENT_MAX_CHARS):
    lines = comment.split("\n")
    if len(lines) > max_lines:
        raise AssertionError(
            f"{bname}: {len(lines)} comment lines, max {max_lines}. GRC draws "
            f"every line on the canvas - put the detail in the README.")
    for line in lines:
        if len(line) > max_chars:
            raise AssertionError(
                f"{bname}: comment line is {len(line)} chars, max {max_chars}:"
                f"\n  {line!r}\nGRC does not wrap it; it will overlap the "
                f"block to its right.")


def _states(coord, extra=None):
    s = {"bus_sink": False, "bus_source": False, "bus_structure": None,
         "coordinate": list(coord), "rotation": 0, "state": "enabled"}
    if extra:
        s.update(extra)
    return s


def blk(bname, bid, coord, comment=None, states_extra=None, **params):
    """One block. Every parameter value is stringified, as GRC writes them.

    The first argument is the block's id in the flowgraph; `name=` inside
    **params is a parameter of the block itself, which several QT sinks have.
    Keeping the two apart is why this is `bname` and not `name`.
    """
    p = {k: str(v) for k, v in params.items()}
    if comment:
        _check_comment(bname, comment)
        p["comment"] = comment
    return {"name": bname, "id": bid, "parameters": p,
            "states": _states(coord, states_extra)}


def chooser(bname, coord, label, dtype, opts, labels, value, gui_hint,
            comment=None):
    """A QT GUI Chooser.

    GRC validates the default against option0..option4 individually, not
    against the `options` list, so both have to be filled in or the flowgraph
    will not load. Five options is the hard ceiling of the block.
    """
    assert len(opts) == len(labels) <= 5, bname
    assert value in opts, f"{bname}: default {value!r} is not one of the options"
    # Option labels are drawn on the canvas too, and overflow the same way.
    for l in labels:
        if len(l) > 34:
            raise AssertionError(
                f"{bname}: option label is {len(l)} chars, max 34: {l}")
    p = dict(label=label, type=dtype, num_opts=str(len(opts)),
             options="[" + ", ".join(opts) + "]",
             labels="[" + ", ".join(labels) + "]",
             value=value, widget="combo_box", orient="Qt.QVBoxLayout",
             gui_hint=gui_hint)
    for i, (o, l) in enumerate(zip(opts, labels)):
        p["option%d" % i] = o
        p["label%d" % i] = l
    return blk(bname, "variable_qtgui_chooser", coord, comment=comment, **p)


def var(bname, value, coord, comment=None):
    return blk(bname, "variable", coord, comment=comment, value=value)


def epy(bname, module, coord, comment=None, **params):
    """An embedded Python block, with its source read from examples/lib/.

    `_io_cache` is filled in with exactly what GRC would compute, by calling
    GRC's own extractor. GRC recomputes it on load anyway; having it right in
    the file means a GRC that cannot exec the source (a missing numpy, say)
    still shows the correct ports instead of a block with none.
    """
    from gnuradio.grc.core.utils import epy_block_io

    with open(os.path.join(LIB, module + ".py")) as f:
        src = f.read()
    io = epy_block_io.extract(src)
    b = blk(bname, "epy_block", coord, comment=comment,
            states_extra={"_io_cache": repr(tuple(io))}, **params)
    b["parameters"]["_source_code"] = src
    return b


def epy_mod(bname, module, coord, comment=None):
    """A GRC "Python Module" block, holding a module from examples/lib/.

    Unlike an embedded BLOCK this processes no samples. Its contents land in
    the flowgraph's evaluation namespace as `<bname>.<something>`, so it can be
    called from any parameter expression - which is how one definition of the
    constellation reaches both the modulator and the EVM meter.
    """
    with open(os.path.join(LIB, module + ".py")) as f:
        src = f.read()
    return blk(bname, "epy_module", coord, comment=comment, source_code=src)


def options(fid, title, desc, comment, window="(1800,1100)"):  # noqa: C901
    """The flowgraph's own options block.

    No `name` or `id` key here, unlike every other block: GRC loads this one
    with `options_block.import_data(name='', **data['options'])`, so a `name`
    in the mapping arrives twice and the whole file fails to load.
    """
    _check_comment("options", comment, OPTIONS_MAX_LINES, OPTIONS_MAX_CHARS)
    return {
        "parameters": {
            "author": "Matthieu", "catch_exceptions": "True",
            "category": "[GRC Hier Blocks]", "cmake_opt": "", "comment": comment,
            "copyright": "", "description": desc, "gen_cmake": "On",
            "gen_linking": "dynamic", "generate_options": "qt_gui",
            "hier_block_src_path": ".:", "id": fid, "max_nouts": "0",
            "output_language": "python", "placement": "(0,0)",
            "qt_qss_theme": "", "realtime_scheduling": "", "run": "True",
            "run_command": "{python} -u {filename}", "run_options": "prompt",
            "sizing_mode": "fixed", "thread_safe_setters": "", "title": title,
            "window_size": window,
        },
        "states": _states((8, 8)),
    }


def write(path, opts, blocks, connections):
    doc = {"options": opts, "blocks": blocks,
           "connections": [[a, str(b), c, str(d)] for a, b, c, d in connections],
           "metadata": {"file_format": 1, "grc_version": GRC_VERSION}}
    text = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False,
                          width=88, allow_unicode=True)
    with open(path, "w") as f:
        f.write(text)
    return text


# --------------------------------------------------------------------------
# 01 - dynamic range, and how to lose it
# --------------------------------------------------------------------------
EX01_HEADER = """Dynamic range, and how to lose it

Press Execute, then switch FFT window between
rectangular and blackman-harris, and watch the
dynamic-range readout move.

Measured on a two-tone test: 40 bins from a
full-scale carrier, rectangular leaves a skirt at
-42 dBFS where blackman-harris leaves -120.

Levels are dBFS, not dBm. Detail in the README."""

EX01_NOTE_RATE = """Sample rate and buffer are a trade, not a setting.

Dynamic range is BETTER at a lower rate: the same 4096-point FFT over a
narrower span puts less noise in each bin. 5 MS/s is the default for that
reason, not to be gentle on the link.

Push the chooser to 61.44 MS/s and the span gets 12x wider, every bin gets
about 11 dB noisier, and the stream needs 245 MB/s - which no Ethernet link
carries, so samples will be dropped. Raise `buf` to 1048576 or more first: a
bigger libiio buffer was measured to be worth about 3x the throughput over a
network. See docs/modulation-and-throughput.md.

`buf` is fixed when the flowgraph starts, so changing it needs a re-run."""

EX01_NOTE_GAIN = """The gain slider goes to 71, and above 4 GHz that is a lie.

The AD9361's gain table depends on the band: full scale is 71 dB at 2.4 GHz
but 62 dB above 4 GHz. gr-iio only LOGS a refusal from the driver, so a value
past the end of the table leaves the gain wherever it was and nothing on
screen says so. If a level looks stuck, check the gain actually took with
`./devkit status`.

RX2 is off in this example. Turning it on doubles the data rate for a channel
you are not looking at.

FFT size is not a live control and no GUI could make it one: it is the width
of a vector port, and GNU Radio fixes port widths when the flowgraph is
built. Edit `nfft` and re-run."""


def ex01():
    o = options("fishball_dynamic_range",
                "Fishball7020 - dynamic range, and how to lose it",
                "Spectrum, waterfall and a live dynamic-range readout",
                EX01_HEADER)
    b = [
        blk("import_math", "import", (180, 580), imports="import math"),
        blk("note_rate", "note", (8, 690), note=EX01_NOTE_RATE),
        blk("note_gain", "note", (8, 790), note=EX01_NOTE_GAIN),

        # ---- plain variables. No comments: GRC draws them on the canvas and
        # they would overlap. The why is in the README.
        var("uri", URI, (8, 360)),
        var("nfft", 4096, (180, 360)),
        var("buf", 262144, (8, 470)),
        var("center_hz", "int(center_mhz * 1e6)", (180, 470)),
        var("lo_off_hz", "lo_frac * samp_rate", (8, 580)),

        # ---- controls, row 1
        chooser("samp_rate", (520, 640), "'Sample rate'", "real",
                ["2560000", "5000000", "10000000", "20000000", "61440000"],
                ["'2.56 MS/s  (10 MB/s)'", "'5 MS/s  (20 MB/s)'",
                 "'10 MS/s  (40 MB/s)'", "'20 MS/s  (80 MB/s)'",
                 "'61.44 MS/s  (245 MB/s)'"],
                "5000000", "0,0,1,2",
                comment="Lower is better for dynamic range."),
        blk("center_mhz", "variable_qtgui_range", (840, 640),
            comment="70 MHz to 6 GHz.",
            label="'Centre frequency (MHz)'", rangeType="float", value="2437",
            start="70", stop="6000", step="0.5", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="1,0,1,2"),
        blk("lo_frac", "variable_qtgui_range", (1090, 640),
            comment="0 puts the LO leak on your signal.",
            label="'LO offset (fraction of span)'", rangeType="float",
            value="0.25", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="2,0,1,2"),
        chooser("gain_mode", (1340, 640), "'Gain mode (RX1)'", "string",
                ["'manual'", "'slow_attack'", "'fast_attack'"],
                ["'manual'", "'slow_attack (AGC)'", "'fast_attack (AGC)'"],
                "'manual'", "3,0,1,2",
                comment="An AGC moves your reference level."),
        blk("rx_gain", "variable_qtgui_range", (1620, 640),
            comment="Ignored unless the mode is manual.",
            label="'RX1 gain (dB)'", rangeType="float", value="55",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="4,0,1,2"),

        # ---- controls, row 2
        # NOT named `window`: GRC blacklists any id an import has bound, and
        # the waterfall sink pulls in gnuradio.fft.window.
        chooser("fft_win", (520, 960), "'FFT window'", "string",
                ["'rectangular'", "'hann'", "'blackman-harris'"],
                ["'rectangular  (-13 dB)'", "'hann  (-31 dB)'",
                 "'blackman-harris  (-92 dB)'"],
                "'blackman-harris'", "5,0,1,2",
                comment="The control this example exists for."),
        blk("avg", "variable_qtgui_range", (840, 960),
            comment="Frames averaged, in the POWER domain.",
            label="'Averaging (frames)'", rangeType="float", value="16",
            start="1", stop="64", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="6,0,1,2"),
        blk("floor_pct", "variable_qtgui_range", (1090, 960),
            comment="What counts as noise. It is a choice.",
            label="'Noise floor percentile'", rangeType="float", value="10",
            start="1", stop="50", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="7,0,1,2"),
        blk("hold", "variable_qtgui_check_box", (1340, 960),
            comment="Unticking is also the reset.",
            label="'Max hold'", type="bool", value="True", true="True",
            false="False", gui_hint="8,0,1,1"),
        blk("frames", "variable_qtgui_range", (1620, 960),
            comment="FFTs per second. The rest are dropped.",
            label="'Display rate (FFT/s)'", rangeType="float", value="12",
            start="1", stop="30", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="8,1,1,1"),

        # ---- signal path
        blk("rx", "iio_fmcomms2_source", (520, 8),
            comment="RX1 only. LO sits below what you asked\nfor; the rotator shifts it back.",
            type="fc32", uri="uri", frequency="int(center_hz - lo_off_hz)",
            samplerate="samp_rate", buffer_size="buf", rx1_en="True",
            rx2_en="False", quadrature="True", rfdc="True", bbdc="True",
            gain1="gain_mode", manual_gain1="rx_gain", gain2="'manual'",
            manual_gain2="20", rf_port_select="'A_BALANCED'",
            filter_source="'Auto'", filter="", fpass="0", fstop="0",
            bandwidth="int(samp_rate)", len_tag_key="packet_len"),
        blk("shift_back", "blocks_rotator_cc", (840, 48),
            comment="Undo the LO offset, so the axis reads\ntrue frequency.",
            phase_inc="-2 * math.pi * lo_frac", tag_inc_update="False"),
        blk("to_frames", "blocks_stream_to_vector", (1090, 48),
            comment="One FFT frame per item from here.",
            type="complex", num_items="nfft", vlen="1"),
        blk("drop_frames", "blocks_keep_one_in_n", (1340, 48),
            comment="Drop frames ON PURPOSE - see the README.",
            type="complex", n="max(1, int(samp_rate / (nfft * frames)))",
            vlen="nfft"),
        epy("dr", "spectrum_engine", (1610, 8),
            comment="examples/lib/spectrum_engine.py",
            nfft="nfft", window="fft_win", avg="avg", hold="hold",
            floor_pct="floor_pct"),

        # ---- displays
        blk("spectrum", "qtgui_vector_sink_f", (520, 330),
            comment="Average and max hold, one engine.",
            name="'Spectrum - average and max hold'", vlen="nfft",
            x_start="center_mhz - samp_rate / 2e6",
            x_step="samp_rate / nfft / 1e6",
            x_axis_label="'frequency'", y_axis_label="'level'",
            x_units="'MHz'", y_units="'dBFS'", ref_level="0", grid="True",
            autoscale="False", average="1.0", ymin="-140", ymax="0",
            nconnections="2", update_time="0.10", showports="False",
            legend="True", label1="'average'", width1="1", color1="'blue'",
            alpha1="1.0", label2="'max hold'", width2="1", color2="'red'",
            alpha2="0.6", gui_hint="0,2,6,10"),
        blk("waterfall", "qtgui_waterfall_sink_x", (860, 330),
            comment="Its own window is fixed; it is here for\nthe time axis, not the levels.",
            type="complex", name="'Waterfall'", fftsize="1024",
            freqhalf="True", wintype="window.WIN_BLACKMAN_hARRIS",
            fc="center_hz", bw="samp_rate", int_min="-130", int_max="-20",
            grid="False", nconnections="1", update_time="0.10",
            showports="False", legend="True", axislabels="True",
            gui_hint="6,2,4,10"),
        blk("range_num", "qtgui_number_sink", (1200, 330),
            comment="Peak minus floor, on the average trace.",
            name="'Dynamic range'", type="float", autoscale="False",
            avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="1",
            min="0", max="140", update_time="0.10", label1="'peak - floor'",
            unit1="'dB'", color1="'black'", factor1="1", gui_hint="9,0,1,2"),
        blk("level_num", "qtgui_number_sink", (1500, 330),
            comment="The two numbers the range is made of,\nplus what the window allows.",
            name="'Levels, and what the window allows'", type="float",
            autoscale="False", avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ",
            nconnections="3", min="-140", max="10", update_time="0.10",
            label1="'peak'", unit1="'dBFS'", color1="'black'", factor1="1",
            label2="'noise floor'", unit2="'dBFS'", color2="'black'",
            factor2="1", label3="'window sidelobes'", unit3="'dB'",
            color3="'black'", factor3="1", gui_hint="10,0,2,2"),
    ]
    c = [
        ("rx", 0, "shift_back", 0),
        ("shift_back", 0, "to_frames", 0),
        ("shift_back", 0, "waterfall", 0),
        ("to_frames", 0, "drop_frames", 0),
        ("drop_frames", 0, "dr", 0),
        ("dr", 0, "spectrum", 0),
        ("dr", 1, "spectrum", 1),
        ("dr", 2, "range_num", 0),
        ("dr", 3, "level_num", 0),
        ("dr", 4, "level_num", 1),
        ("dr", 5, "level_num", 2),
    ]
    return "01-dynamic-range/dynamic_range.grc", o, b, c


#: Runs in main() AFTER tb.start(). See patch 0005: starting a buffer can
#: restore a CACHED transmit attenuation when the chip looks muted, so a value
#: written before the stream - which is when GRC's constructor writes it -
#: guarantees nothing during it. Every tool in this repository writes after the
#: stream opens and then reads back, and so does this.
SNIPPET_REASSERT = """import time

# Let the first buffer actually open before touching the attenuator; writing
# into the gap is the thing this is here to avoid.
time.sleep(0.5)

# Goes through the generated setter, so it re-evaluates `tx_atten if arm else
# 89.75` with whatever the GUI currently says.
self.set_tx_atten(self.tx_atten)

print('[02] armed=%s, attenuation re-asserted as %.2f dB after the stream '
      'opened.' % (self.arm, self.tx_atten if self.arm else 89.75))
print('[02] the number beside ARM is read back out of the chip - if it '
      'disagrees with the slider, believe the chip.')
"""
# --------------------------------------------------------------------------
# 02 - a modulated link you can watch  (THIS ONE TRANSMITS)
# --------------------------------------------------------------------------
EX02_HEADER = """A modulated link you can watch - IT TRANSMITS

+19 dBm through a power amplifier, 70 MHz-6 GHz.
Transmitting unlicensed is illegal in most of it.

arm starts OFF. Attenuation starts at 89.75 dB,
the most there is - HIGHER IS QUIETER. The number
beside arm is read from the CHIP, not the slider.

A loopback with no pad destroys the receiver: RX
is rated +2.5 dBm. Fit 20 dB. Read the README."""

EX02_NOTE_LEVEL = """Why the transmit scale defaults to 0.20 and not 1.0.

The modulator produces symbols with an RMS of 1.0 - and PEAKS well above it,
because a root raised cosine overshoots between symbols. Measured here, over
400k samples:

    QPSK    roll-off 0.35   peak 1.57   PAPR 3.9 dB
    16-QAM  roll-off 0.35   peak 2.03   PAPR 6.2 dB
    64-QAM  roll-off 0.20   peak 2.37   PAPR 7.5 dB

gr-iio's sink takes +/-1.0 as the converter's full scale, so feeding it the
modulator's output unscaled clips the peaks by up to 7.5 dB. Clipping is
broadband: it puts your signal where you did not put it, which is a licensing
problem as well as a quality one.

0.20 keeps the worst case at 0.474, about -6.5 dBFS, which is the same
headroom tools/selftest/sdr_selftest.py transmits at. The ceiling on the
slider is 0.45 for the same reason. If you raise it, watch the spectrum: the
shoulders coming up is clipping, not power."""

EX02_NOTE_BUFFER = """Why the buffer is big, and what a stream of U means.

Receiving tolerates a slow link: samples pile up on the board and you lose
some, which prints O for overflow. TRANSMITTING DOES NOT. The converter has to
be fed in real time, so if a buffer arrives late the DAC runs dry and prints U
for underflow - and on this firmware that is worse than untidy. Patch 0015
mutes the transmitter after 250 ms of starvation and switches the data source
to the internal DDS, so a link hiccup takes your signal off the air and leaves
the flowgraph looking like it is still working.

That was measured here, not imagined. Driving transmit and receive together at
4 MS/s over a wireless host link produced bursts of 20 to 40 underflows in 45
seconds, each next to a 'Unable to push buffer: Connection timed out' - while
a transmit-only stream at the same rate and buffer produced none. It is
intermittent: the same configuration ran clean later the same hour, which is
what you would expect of contention on a shared radio channel rather than a
throughput limit.

The defence is buffer DURATION - buf / sample_rate - because that is the length
of stall you can absorb:

    buf = 1048576     slack      vs the 250 ms watchdog
    at 4 MS/s          262 ms    about equal to it
    at 2 MS/s          524 ms    twice
    at 1 MS/s         1050 ms    four times - the default here

which is why this example is modest about the rate. Lowering it buys slack AND
lowers the traffic, so it helps twice; raising the buffer only helps once. A
wired link makes all of this go away, and
docs/modulation-and-throughput.md has the throughput side of the same story.

ONE MORE TRAP, if you stop and immediately restart this flowgraph:

    RuntimeError: Unable to create buffer: -16

-16 is EBUSY. The board holds the transmit DMA for a moment after a client
disconnects, so a new transmit buffer requested straight away is refused. It is
nothing to do with the buffer's SIZE - a 1048576-sample buffer allocates fine
as the first request of a fresh process, and a 262144-sample one is refused as
the second request of the same process. Wait two seconds and start it again."""


EX02_NOTE_QAM = """Set `order` to 16 and watch the constellation fail. That is real.

The transmitter is fine at any order - it is a table of points and a filter.
The RECEIVER is a QPSK receiver, and a QPSK receiver does not become a QAM
receiver by changing one number. This one recovers QPSK at about 0.65% EVM at
40 dB SNR, measured; at 16-QAM the same chain reads about 21% and the cloud
never resolves into sixteen points.

WHY, concretely. Both recovery loops here lean on the constellation being
effectively constant-modulus:

  * The timing detector is decision-directed Mueller and Mueller, which is
    built around two-level decisions. On a multilevel constellation its error
    signal is dominated by which AMPLITUDE a symbol had rather than by the
    timing error, so the loop is being driven by the data.
  * A Costas loop of order 4 recovers a carrier from four-fold symmetry. A
    16-QAM constellation has that symmetry, but its phase error estimate is
    also amplitude-dependent, so the same problem appears again.

Gardner's detector, which needs no decisions, does not rescue it: measured on
this chain it did not lock at ALL - a magnitude spread of 0.30 against 0.002
for Mueller and Mueller, and about 45% EVM on a noiseless signal. A
decision-directed LMS equaliser after the carrier loop made 16-QAM worse, not
better (21% to 35%).

What a QAM receiver actually needs is joint decision-directed timing and
carrier recovery against the full constellation - in GNU Radio, something built
around `constellation_receiver_cb`, or an equaliser that is properly trained
rather than blind. That is a bigger piece of work than a showcase, and it is
the honest reason this example stops at QPSK rather than pretending.

If you want to SEE the higher orders transmitted properly, look at the
spectrum and the eye, which are receiver-independent. Both are correct at any
order."""


EX02_NOTE_RERUN = """Which knobs are live, and which need a re-run.

LIVE, because the block exposes a setter: attenuation, centre frequency,
receive gain, both loop bandwidths, the RX matched filter's roll-off, both LO
offsets, arm, transmit scale.

RE-RUN, because the value is fixed when a block is constructed: `order`
(the modulator is built from its constellation), `sps`, `tx_alpha` (the
transmit filter's taps are baked into the modulator) and the buffer sizes.

That is why there are TWO roll-off controls. `tx_alpha` is what the
transmitter shapes with and it cannot change while running. `rrc_alpha` is
the receiver's matched filter, which can. Leave them equal and the filter is
matched; drag `rrc_alpha` away from 0.35 and watch EVM climb. A matched
filter is only matched if somebody keeps it that way."""


def ex02():
    o = options("fishball_modulated_link",
                "Fishball7020 - a modulated link you can watch  (TRANSMITS)",
                "QPSK/QAM over the air, with constellation, eye and live EVM",
                EX02_HEADER)
    b = [
        blk("import_math", "import", (190, 830), imports="import math"),
        epy_mod("qam", "qam", (180, 860),
                "One definition of the constellation, used by\nBOTH the modulator and the EVM meter."),
        var("uri", URI, (8, 390)),
        var("samp_rate", 2000000, (190, 390)),
        var("sps", 4, (8, 500)),
        var("order", 4, (190, 500)),
        var("tx_alpha", 0.35, (8, 610)),
        var("buf", 1048576, (190, 610)),
        var("center_hz", "int(center_mhz * 1e6)", (8, 720)),
        var("cnst", "qam.points(order)", (190, 720)),

        # ---- the constellation both ends share
        blk("cnst_obj", "variable_constellation", (8, 830),
            comment="From qam.points(order) - the same function\nthe EVM meter measures against.",
            type="calcdist", sym_map="list(range(order))",
            const_points="qam.points(order)", rot_sym="4", dims="1",
            normalization="digital.constellation.POWER_NORMALIZATION",
            precision="8", soft_dec_lut="None"),

        # ---- controls
        blk("arm", "variable_qtgui_check_box", (520, 1280),
            comment="Gates the samples AND forces maximum\nattenuation. Either alone would do.",
            label="'ARM TRANSMITTER'", type="bool", value="False",
            true="True", false="False", gui_hint="0,0,1,1"),
        blk("tx_atten", "variable_qtgui_range", (780, 1280),
            comment="HIGHER IS QUIETER. 89.75 dB is the most\nthe AD9361 offers.",
            label="'TX1 attenuation (dB) - higher is quieter'",
            rangeType="float", value="89.75", start="0", stop="89.75",
            step="0.25", widget="counter_slider", orient="Qt.Horizontal",
            min_len="200", gui_hint="1,0,1,2"),
        blk("tx_scale", "variable_qtgui_range", (1040, 1280),
            comment="0.20 keeps the worst peak near -6 dBFS.\nA root raised cosine overshoots.",
            label="'TX digital scale (peak, not RMS)'", rangeType="float",
            value="0.20", start="0.02", stop="0.45", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="2,0,1,2"),
        blk("center_mhz", "variable_qtgui_range", (1300, 1280),
            comment="2437 MHz is ISM. A least-bad default,\nnot a permission.",
            label="'Centre frequency (MHz)'", rangeType="float", value="2437",
            start="70", stop="6000", step="0.5", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="3,0,1,2"),
        blk("rx_gain", "variable_qtgui_range", (1560, 1280),
            comment="Manual only. An AGC would move the\nreference level under your measurement.",
            label="'RX1 gain (dB)'", rangeType="float", value="20",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="4,0,1,2"),
        blk("rrc_alpha", "variable_qtgui_range", (520, 1490),
            comment="Live. Leave it at tx_alpha to stay\nmatched; move it to see what that costs.",
            label="'RX matched-filter roll-off (TX is fixed)'",
            rangeType="float", value="0.35", start="0.05", stop="0.90",
            step="0.01", widget="counter_slider", orient="Qt.Horizontal",
            min_len="200", gui_hint="5,0,1,2"),
        blk("sync_bw", "variable_qtgui_range", (780, 1490),
            comment="Too low never acquires; too high tracks\nnoise into the constellation.",
            label="'Timing loop bandwidth'", rangeType="float", value="0.045",
            start="0.002", stop="0.200", step="0.001", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="6,0,1,2"),
        blk("costas_bw", "variable_qtgui_range", (1040, 1490),
            comment="The one that moves the two EVM figures\napart.",
            label="'Carrier loop bandwidth'", rangeType="float", value="0.030",
            start="0.001", stop="0.200", step="0.001", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="7,0,1,2"),
        blk("tx_off_frac", "variable_qtgui_range", (1300, 1490),
            comment="Pushes the TRANSMITTER's carrier leak off\nthe signal. Set both offsets to 0 to see.",
            label="'TX LO offset (fraction of span)'", rangeType="float",
            value="0.20", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="8,0,1,2"),
        blk("rx_off_frac", "variable_qtgui_range", (1560, 1490),
            comment="Same trick at the RECEIVER.",
            label="'RX LO offset (fraction of span)'", rangeType="float",
            value="0.25", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="9,0,1,2"),

        blk("note_level", "note", (8, 1070), note=EX02_NOTE_LEVEL),
        blk("note_buffer", "note", (8, 1170), note=EX02_NOTE_BUFFER),
        blk("note_qam", "note", (8, 1270), note=EX02_NOTE_QAM),
        blk("note_rerun", "note", (8, 1370), note=EX02_NOTE_RERUN),

        # ---- transmit chain
        blk("bits", "analog_random_source_x", (520, 8),
            comment="Random bytes. The point is the modulation,\nnot the payload.",
            type="byte", min="0", max="255", num_samps="100000", repeat="True"),
        blk("mod", "digital_constellation_modulator", (820, 8),
            comment="Bits to shaped symbols. Nothing here\ndecodes, so no differential coding.",
            constellation="cnst_obj", differential="False",
            samples_per_symbol="sps", excess_bw="tx_alpha", verbose="False",
            log="False", truncate="False"),
        blk("tx_shift", "blocks_rotator_cc", (1120, 48),
            comment="Baseband UP by the TX offset; the LO goes\nDOWN by the same amount.",
            phase_inc="2 * math.pi * tx_off_frac", tag_inc_update="False"),
        blk("tx_gate", "blocks_multiply_const_vxx", (1400, 48),
            comment="Unarmed this is exactly 0.0 - nothing to\ntransmit even if attenuation were wrong.",
            type="complex", const="tx_scale if arm else 0.0", vlen="1"),
        blk("tx", "iio_fmcomms2_sink", (1680, 8),
            comment="TX1 only. Attenuation re-asserted AFTER\nthe stream opens - see patch 0005.",
            type="fc32", uri="uri", frequency="int(center_hz - tx_off_frac * samp_rate)",
            samplerate="samp_rate", bandwidth="int(samp_rate)",
            buffer_size="buf", tx1_en="True", tx2_en="False", cyclic="False",
            rf_port_select="'A'", attenuation1="tx_atten if arm else 89.75",
            attenuation2="89.75", len_tag_key="''", filter_source="'Auto'",
            filter="", fpass="0", fstop="0"),

        # ---- receive chain
        blk("rx", "iio_fmcomms2_source", (520, 400),
            comment="RX1 only. The LO sits below the signal;\nthe rotator brings it back.",
            type="fc32", uri="uri",
            frequency="int(center_hz - rx_off_frac * samp_rate)",
            samplerate="samp_rate", buffer_size="buf", rx1_en="True",
            rx2_en="False", quadrature="True", rfdc="True", bbdc="True",
            gain1="'manual'", manual_gain1="rx_gain", gain2="'manual'",
            manual_gain2="20", rf_port_select="'A_BALANCED'",
            filter_source="'Auto'", filter="", fpass="0", fstop="0",
            bandwidth="int(samp_rate)", len_tag_key="packet_len"),
        blk("rx_shift", "blocks_rotator_cc", (840, 440),
            comment="Signal to baseband zero; the receiver's\nown leak goes off to one side.",
            phase_inc="-2 * math.pi * rx_off_frac", tag_inc_update="False"),
        blk("mf", "root_raised_cosine_filter", (1080, 400),
            comment="Matched filter. Its taps are live, which\nmakes rrc_alpha a control.",
            type="fir_filter_ccf", decim="1", interp="1", gain="sps",
            samp_rate="samp_rate", sym_rate="samp_rate / sps",
            alpha="rrc_alpha", ntaps="11 * sps + 1"),
        blk("sync", "digital_symbol_sync_xx", (1340, 400),
            comment="Mueller and Mueller, chosen by measurement:\nGardner did not lock at all here.",
            type="cc", ted_type="digital.TED_MOD_MUELLER_AND_MULLER",
            constellation="cnst_obj",
            sps="sps", ted_gain="1.0", loop_bw="sync_bw", damping="1.0",
            max_dev="1.5", osps="1", resamp_type="digital.IR_MMSE_8TAP",
            nfilters="128", pfb_mf_taps="[]"),
        blk("costas", "digital_costas_loop_cc", (1660, 440),
            comment="Order 4 locks to the 90-degree symmetry\nQPSK already has.",
            w="costas_bw", order="4", use_snr="False"),
        epy("evm", "evm_meter", (1920, 400),
            comment="examples/lib/evm_meter.py - port 0 is\n"
                    "rescaled, so picture and numbers agree.",
            order="order", chunk="2048"),

        # ---- the read-back that is not an echo
        blk("atten_rb", "iio_attr_source", (520, 760),
            comment="Read out of the CHIP four times a second,\nnot echoed from the slider.",
            # attr_type/output/type are enums whose option VALUES are bare
            # 0/1/True, not quoted strings. Quoting them matches no option and
            # the block silently falls back to the first - which is a float64
            # output, and the connection then fails on item size.
            #   attr_type 0 = Channel   output True = an output channel
            #   type 1 = float (cast from double), which is what a sink wants
            uri="uri", device="'ad9361-phy'", attr_type="0", output="True",
            channel="'voltage0'", attribute="'hardwaregain'",
            address='int("0x123",0)', type="1", update_interval_ms="250",
            samples_per_update="8"),

        # ---- displays
        blk("spectrum", "qtgui_freq_sink_x", (520, 980),
            comment="True frequency. Both carrier leaks show\nhere, and so does clipping.",
            type="complex", name="'Received spectrum'", fftsize="4096",
            freqhalf="True", wintype="window.WIN_BLACKMAN_hARRIS",
            norm_window="False", fc="center_hz", bw="samp_rate", grid="True",
            autoscale="False", average="0.2", ymin="-130", ymax="0",
            label="'level'", units="'dBFS'", nconnections="1",
            update_time="0.10", showports="False", tr_mode="qtgui.TRIG_MODE_FREE",
            tr_level="0.0", tr_chan="0", tr_tag="''", ctrlpanel="False",
            legend="True", axislabels="True", label1="'RX1'", width1="1",
            color1='"blue"', alpha1="1.0", gui_hint="0,2,5,10"),
        blk("constellation", "qtgui_const_sink_x", (900, 980),
            comment="The recovered symbols, at the reference's\nscale.",
            type="complex", name="'Constellation - recovered symbols'",
            size="2048", grid="True", autoscale="False", ymin="-2", ymax="2",
            xmin="-2", xmax="2", nconnections="1", update_time="0.10",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_slope="qtgui.TRIG_SLOPE_POS",
            tr_level="0.0", tr_chan="0", tr_tag="''", legend="False",
            axislabels="True", label1="'symbols'", width1="1",
            color1='"blue"', style1="0", marker1="0", alpha1="0.4",
            gui_hint="5,2,7,5"),
        blk("eye", "qtgui_eye_sink_x", (1260, 980),
            comment="Before timing recovery, so an open eye\nmeans the SHAPING is right.",
            type="complex", name="'Eye diagram - matched filter output'",
            ylabel="'amplitude'", yunit="''", size="1024",
            samp_per_symbol="sps", srate="samp_rate", grid="True",
            autoscale="True", ymin="-1", ymax="1", nconnections="1",
            update_time="0.10", entags="True",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_slope="qtgui.TRIG_SLOPE_POS",
            tr_level="0.0", tr_delay="0", tr_chan="0", tr_tag="''",
            ctrlpanel="False", legend="False", axislabels="True",
            label1="'I'", width1="1", color1='"blue"', style1="1", marker1="-1",
            alpha1="0.3", gui_hint="5,7,7,5"),
        blk("atten_num", "qtgui_number_sink", (880, 760),
            comment="Read from the chip, not the slider.",
            name="'TX1 hardwaregain, READ BACK FROM THE CHIP'", type="float",
            autoscale="False", avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ",
            nconnections="1", min="-90", max="0", update_time="0.10",
            label1="'chip says'", unit1="'dB'", color1="'black'", factor1="1",
            gui_hint="0,1,1,1"),
        blk("evm_num", "qtgui_number_sink", (1620, 980),
            comment="Their difference is the static rotation.",
            name="'EVM'", type="float", autoscale="False", avg="0",
            graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="2", min="0",
            max="60", update_time="0.10", label1="'as received'", unit1="'%'",
            color1="'black'", factor1="1",
            label2="'after one complex gain'", unit2="'%'", color2="'black'",
            factor2="1", gui_hint="10,0,1,2"),
        blk("mer_num", "qtgui_number_sink", (1900, 980),
            comment="The same thing in dB.",
            name="'MER'", type="float", autoscale="False", avg="0",
            graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="1", min="0",
            max="45", update_time="0.10", label1="'modulation error ratio'",
            unit1="'dB'", color1="'black'", factor1="1", gui_hint="11,0,1,2"),

        # ---- the rule this repository keeps learning
        blk("reassert_atten", "snippet", (8, 970), section="main_after_start",
            priority="0", code=SNIPPET_REASSERT),
    ]
    c = [
        ("bits", 0, "mod", 0),
        ("mod", 0, "tx_shift", 0),
        ("tx_shift", 0, "tx_gate", 0),
        ("tx_gate", 0, "tx", 0),
        ("rx", 0, "rx_shift", 0),
        ("rx_shift", 0, "mf", 0),
        ("rx_shift", 0, "spectrum", 0),
        ("mf", 0, "sync", 0),
        ("mf", 0, "eye", 0),
        ("sync", 0, "costas", 0),
        ("costas", 0, "evm", 0),
        ("evm", 0, "constellation", 0),
        ("evm", 1, "evm_num", 0),
        ("evm", 2, "evm_num", 1),
        ("evm", 3, "mer_num", 0),
        ("atten_rb", 0, "atten_num", 0),
    ]
    return "02-modulated-link/modulated_link.grc", o, b, c


# --------------------------------------------------------------------------
# 03 - two coherent receivers
# --------------------------------------------------------------------------
EX03_HEADER = """Two coherent receivers

RX1 and RX2 share one oscillator and one clock, so
the phase between them means something. Nothing
else in this repository shows it.

READ COHERENCE BEFORE THE ANGLE. Near 1 the angle
is a measurement; near 0 it is noise wearing the
same clothes. The dial's radius IS the coherence.

Repeatable is not calibrated. Receive only."""

EX03_NOTE_TRY = """Three things to try, in order.

1. WITH TWO ANTENNAS, find any steady carrier and watch coherence. Move one
   antenna a few centimetres and the angle moves; put it back and the angle
   comes back. That repeatability IS the coherent-receiver property.

2. TICK `zero`, then move an antenna. The reading is now relative to where you
   zeroed. Untick it to see the raw angle again - the raw number is on its own
   readout precisely so that zeroing can never hide it.

3. WIDEN `band-select` past the LO offset, so that DC falls inside the filter.
   Coherence will climb toward 1 and stay there, steady and convincing, and it
   will be measuring the receiver's own LO leak talking to itself. This is the
   failure this example is arranged to avoid, and it is worth seeing once so
   you recognise it elsewhere.

The averaging control is a trade: more frames is a steadier angle and a slower
response to a real change. At the default chunk of 4096 samples and 8 frames,
the estimate settles in a few tenths of a second."""


def ex03():
    o = options("fishball_coherent_rx",
                "Fishball7020 - two coherent receivers",
                "RX1/RX2 phase and coherence from one shared oscillator",
                EX03_HEADER)
    b = [
        blk("import_math", "import", (190, 720), imports="import math"),
        var("uri", URI, (8, 390)),
        var("buf", 262144, (190, 390)),
        var("chunk", 4096, (8, 500)),
        var("center_hz", "int(center_mhz * 1e6)", (190, 500)),
        var("lo_off_hz", "lo_frac * samp_rate", (8, 610)),
        var("sel_taps", "firdes.low_pass(1.0, samp_rate, sel_bw_khz * 500.0, "
                "sel_bw_khz * 200.0)", (190, 610)),

        # ---- controls
        chooser("samp_rate", (520, 800), "'Sample rate'", "real",
                ["2560000", "5000000", "10000000"],
                ["'2.56 MS/s  (20 MB/s, 2ch)'",
                 "'5 MS/s  (40 MB/s, 2ch)'", "'10 MS/s  (80 MB/s, 2ch)'"],
                "5000000", "0,0,1,2",
                comment="Two channels, so twice the bytes of one."),
        blk("center_mhz", "variable_qtgui_range", (780, 800),
            comment="Where to look.",
            label="'Centre frequency (MHz)'", rangeType="float", value="2437",
            start="70", stop="6000", step="0.5", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="1,0,1,2"),
        blk("lo_frac", "variable_qtgui_range", (1040, 800),
            comment="Keeps the LO leak out of the correlation.\nSet it to 0 to see what that costs.",
            label="'LO offset (fraction of span)'", rangeType="float",
            value="0.25", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="2,0,1,2"),
        blk("sel_bw_khz", "variable_qtgui_range", (1300, 800),
            comment="Widen it past the LO offset and the leak\ngets in. Worth seeing once.",
            label="'Band-select width (kHz)'", rangeType="float", value="400",
            start="20", stop="3000", step="10", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="3,0,1,2"),
        blk("rx1_gain", "variable_qtgui_range", (520, 1030),
            comment="Separate on purpose: the two receivers\ndiffer by about 1.5 dB.",
            label="'RX1 gain (dB)'", rangeType="float", value="40",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="4,0,1,2"),
        blk("rx2_gain", "variable_qtgui_range", (780, 1030),
            comment="Unequal gains change amplitude but NOT\nphase. Prove it on the dial.",
            label="'RX2 gain (dB)'", rangeType="float", value="40",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="5,0,1,2"),
        blk("avg", "variable_qtgui_range", (1040, 1030),
            comment="Complex-domain average. Steadier, slower.",
            label="'Averaging (estimates)'", rangeType="float", value="8",
            start="1", stop="200", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="6,0,1,2"),
        blk("zero", "variable_qtgui_check_box", (1300, 1030),
            comment="Latches on the RISING EDGE only, or it\nwould re-zero forever.",
            label="'zero (latch this phase as the reference)'", type="bool",
            value="False", true="True", false="False", gui_hint="7,0,1,2"),

        blk("note_try", "note", (8, 720), note=EX03_NOTE_TRY),

        # ---- signal path
        blk("rx", "iio_fmcomms2_source", (520, 8),
            comment="BOTH receivers, one LO, one clock. That\nshared oscillator is the whole point.",
            type="fc32", uri="uri", frequency="int(center_hz - lo_off_hz)",
            samplerate="samp_rate", buffer_size="buf", rx1_en="True",
            rx2_en="True", quadrature="True", rfdc="True", bbdc="True",
            gain1="'manual'", manual_gain1="rx1_gain", gain2="'manual'",
            manual_gain2="rx2_gain", rf_port_select="'A_BALANCED'",
            filter_source="'Auto'", filter="", fpass="0", fstop="0",
            bandwidth="int(samp_rate)", len_tag_key="packet_len"),
        blk("sel1", "freq_xlating_fft_filter_ccc", (860, 8),
            comment="Band-select RX1, which throws DC and the\nLO leak away with it.",
            decim="1", taps="sel_taps", center_freq="lo_off_hz",
            samp_rate="samp_rate", samp_delay="0", nthreads="1"),
        blk("sel2", "freq_xlating_fft_filter_ccc", (860, 210),
            comment="IDENTICAL to sel1, so whatever phase it\nadds cancels out of the difference.",
            decim="1", taps="sel_taps", center_freq="lo_off_hz",
            samp_rate="samp_rate", samp_delay="0", nthreads="1"),
        epy("phase", "phase_meter", (1180, 8),
            comment="Averages the correlation as a COMPLEX\nnumber, then takes the angle.",
            chunk="chunk", avg="avg", zero="zero"),

        # ---- displays
        blk("spectrum", "qtgui_freq_sink_x", (520, 470),
            comment="UNfiltered, centred on the LO. The spike\nin the middle is the receiver itself.",
            type="complex", name="'Both receivers, as tuned (centre = the LO)'",
            fftsize="4096", freqhalf="True",
            wintype="window.WIN_BLACKMAN_hARRIS", norm_window="False",
            fc="int(center_hz - lo_off_hz)", bw="samp_rate", grid="True",
            autoscale="False", average="0.2", ymin="-130", ymax="-10",
            label="'level'", units="'dBFS'", nconnections="2",
            update_time="0.10", showports="False",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_level="0.0", tr_chan="0",
            tr_tag="''", ctrlpanel="False", legend="True", axislabels="True",
            label1="'RX1'", width1="1", color1='"blue"', alpha1="1.0",
            label2="'RX2'", width2="1", color2='"red"', alpha2="1.0",
            gui_hint="0,2,5,10"),
        blk("dial", "qtgui_const_sink_x", (900, 470),
            comment="A polar meter: angle is phase, radius is\ncoherence. The rim is coherence 1.",
            type="complex",
            name="'Phase dial - angle is phase, radius is coherence'",
            size="64", grid="True", autoscale="False", ymin="-1.1", ymax="1.1",
            xmin="-1.1", xmax="1.1", nconnections="1", update_time="0.10",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_slope="qtgui.TRIG_SLOPE_POS",
            tr_level="0.0", tr_chan="0", tr_tag="''", legend="False",
            axislabels="True", label1="'coherence * exp(j phase)'", width1="1",
            color1='"blue"', style1="0", marker1="0", alpha1="0.8",
            gui_hint="5,2,6,5"),
        blk("phase_time", "qtgui_time_sink_x", (1260, 470),
            comment="A coherent pair holds still here. Two\nindependent radios would not.",
            type="float", name="'Phase over time'", ylabel="'phase'",
            yunit="'degrees'", size="1024", srate="samp_rate / chunk",
            grid="True", autoscale="False", ymin="-180", ymax="180",
            nconnections="1", update_time="0.10", entags="False",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_slope="qtgui.TRIG_SLOPE_POS",
            tr_level="0.0", tr_delay="0", tr_chan="0", tr_tag="''",
            ctrlpanel="False", legend="False", axislabels="True",
            stemplot="False", label1="'phase'", width1="1", color1='"blue"',
            style1="1", marker1="-1", alpha1="1.0", gui_hint="5,7,6,5"),
        blk("phase_num", "qtgui_number_sink", (1620, 470),
            comment="Zeroed AND raw, so zeroing can never hide\nwhat the board is doing.",
            name="'Phase RX1 - RX2'", type="float", autoscale="False",
            avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="2",
            min="-180", max="180", update_time="0.10",
            label1="'zeroed'", unit1="'deg'", color1="'black'", factor1="1",
            label2="'raw'", unit2="'deg'", color2="'black'", factor2="1",
            gui_hint="8,0,1,2"),
        blk("coh_num", "qtgui_number_sink", (1900, 470),
            comment="Read this BEFORE the angle.",
            name="'Coherence - read this first'", type="float",
            autoscale="False", avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ",
            nconnections="1", min="0", max="1", update_time="0.10",
            label1="'|correlation|'", unit1="''", color1="'black'",
            factor1="1", gui_hint="9,0,1,2"),
    ]
    c = [
        ("rx", 0, "sel1", 0),
        ("rx", 1, "sel2", 0),
        ("rx", 0, "spectrum", 0),
        ("rx", 1, "spectrum", 1),
        ("sel1", 0, "phase", 0),
        ("sel2", 0, "phase", 1),
        ("phase", 0, "phase_num", 0),
        ("phase", 2, "phase_num", 1),
        ("phase", 0, "phase_time", 0),
        ("phase", 1, "coh_num", 0),
        ("phase", 3, "dial", 0),
    ]
    return "03-coherent-receivers/coherent_rx.grc", o, b, c


BUILDERS = {"01": ex01, "02": ex02, "03": ex03}


def main(argv):
    check = "--check" in argv
    which = [a for a in argv[1:] if not a.startswith("-")] or list(BUILDERS)
    bad = []
    for key in which:
        rel, o, b, c = BUILDERS[key]()
        path = os.path.join(HERE, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if check:
            with open(path) as f:
                have = f.read()
            import tempfile
            tmp = os.path.join(tempfile.mkdtemp(), "x.grc")
            want = write(tmp, o, b, c)
            if have != want:
                bad.append(rel)
                print(f"STALE  {rel} - re-run examples/mkgrc.py")
            else:
                print(f"ok     {rel}")
        else:
            write(path, o, b, c)
            print(f"wrote  {rel}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
