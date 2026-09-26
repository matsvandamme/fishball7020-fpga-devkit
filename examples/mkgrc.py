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


def options(fid, title, desc, comment, window="(1800,1100)"):
    """The flowgraph's own options block.

    No `name` or `id` key here, unlike every other block: GRC loads this one
    with `options_block.import_data(name='', **data['options'])`, so a `name`
    in the mapping arrives twice and the whole file fails to load.
    """
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
EX01_HEADER = """Dynamic range, and how to lose it - Fishball7020

Every control here is wired to a number, so you can break the measurement on
purpose and watch the cost. The readout is peak minus noise floor on the trace
you are looking at.

THE ONE TO TRY FIRST. Find any strong carrier. Set the window to Rectangular,
then to Blackman-Harris, and watch the dynamic-range figure. On a synthetic
two-tone test the difference measured here was 78 dB: 40 bins away from a
full-scale carrier, a rectangular window leaves a skirt at -42 dBFS and
Blackman-Harris leaves -120 dBFS. Anything weaker than that skirt does not
exist as far as your spectrum is concerned. The cost is about two bins of
extra width - that is the whole trade.

WHY THE FFT IS NOT THE STOCK QT SINK. GNU Radio's frequency sink takes its
window when it is built and offers no way to change it while running, so you
could never watch the thing this example is about. Doing the transform in an
embedded block also means the dynamic-range number comes from the very trace
on screen, so the picture and the number cannot disagree.

  LO offset    drags the receiver's own LO leak out of the middle of the
               span. Set it to 0 and the spike lands on whatever you were
               trying to measure. It is a FRACTION of the span, so it stays
               sensible when you change the sample rate.
  Gain mode    manual, or let the AGC decide. Switch to slow_attack and the
               vertical axis stops meaning anything: the receiver is now
               changing its own reference level while you read it.
  Averaging    a one-pole average over FFT frames, in the POWER domain.
  Floor %      which percentile counts as 'noise'. Raise it through a busy
               band and watch the floor climb into the signals, because a
               percentile cannot tell noise from traffic.

LEVELS ARE dBFS, not dBm - decibels relative to the converter's full scale.
Nothing in this repository is calibrated to absolute power."""

EX01_NOTE_RATE = """Sample rate and buffer size are a trade, not a setting.

Dynamic range is BETTER at a lower rate: the same 4096-point FFT over a
narrower span puts less noise in each bin. 5 MS/s is the default for that
reason, not to be gentle on the link.

Push the chooser to 61.44 MS/s and two things happen. The span gets 12x
wider and every bin gets 11 dB noisier - and the stream needs 245 MB/s,
which no Ethernet link carries. Samples will be dropped. Raise `buf` to
1048576 or more first: a bigger libiio buffer was measured to be worth about
3x the throughput over a network. See docs/modulation-and-throughput.md.

`buf` is fixed when the flowgraph starts, so changing it needs a re-run."""

EX01_NOTE_GAIN = """The gain slider goes to 71, and above 4 GHz that is a lie.

The AD9361's gain table depends on the band: full scale is 71 dB at 2.4 GHz
but 62 dB above 4 GHz. gr-iio only LOGS a refusal from the driver, so a value
past the end of the table leaves the gain wherever it was and nothing on
screen says so. If a level looks stuck, check the gain actually took:

    # run from: the repo root
    ./devkit status

RX2 is off in this example. Turn it on and you double the data rate for a
channel you are not looking at."""


def ex01():
    o = options("fishball_dynamic_range",
                "Fishball7020 - dynamic range, and how to lose it",
                "Spectrum, waterfall and a live dynamic-range readout",
                EX01_HEADER)
    b = [
        # `import`, not `import_`: the block definition file declares
        # `id: import_`, and GRC strips trailing underscores when it registers
        # a block (core/platform.py), so the flowgraph must use the stripped
        # form. Get it wrong and the import silently contributes nothing,
        # which shows up as "name 'math' is not defined" on an unrelated block.
        blk("import_math", "import", (8, 180), imports="import math"),
        var("uri", URI, (176, 12),
            "Found by name. `python3 tools/board_addr.py` prints an address if\n"
            "mDNS is not working on your network; put 'ip:<address>' here."),
        var("nfft", 4096, (256, 12),
            "FFT size. NOT a live control, and no GUI could make it one: it is\n"
            "the width of a vector port, and GNU Radio fixes port widths when\n"
            "the flowgraph is built. Edit it here and re-run.\n"
            "4096 bins over 5 MS/s is 1.2 kHz per bin."),
        var("buf", 262144, (352, 12),
            "libiio buffer, in samples. 262144 is 1 MB - about 52 ms at the\n"
            "default rate, which keeps the controls feeling immediate. Raise it\n"
            "to 1048576+ before selecting a high sample rate; see the note."),
        var("center_hz", "int(center_mhz * 1e6)", (464, 12)),
        var("lo_off_hz", "lo_frac * samp_rate", (584, 12),
            "The LO offset in Hz, derived from the fraction so that it can\n"
            "never fall outside the span when the sample rate changes."),

        # ---- controls
        chooser("samp_rate", (176, 100), "'Sample rate'", "real",
                ["2560000", "5000000", "10000000", "20000000", "61440000"],
                ["'2.56 MS/s  (10 MB/s)'", "'5 MS/s  (20 MB/s)'",
                 "'10 MS/s  (40 MB/s)'", "'20 MS/s  (80 MB/s)'",
                 "'61.44 MS/s  (245 MB/s - raise buf first)'"],
                "5000000", "0,0,1,2",
                comment="Span. Lower is better for dynamic range - see the note."),
        blk("center_mhz", "variable_qtgui_range", (352, 100),
            comment="Where to look. The AD9361 covers 70 MHz to 6 GHz.",
            label="'Centre frequency (MHz)'", rangeType="float", value="2437",
            start="70", stop="6000", step="0.5", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="1,0,1,2"),
        blk("lo_frac", "variable_qtgui_range", (528, 100),
            comment="LO offset as a fraction of the span. 0 puts the\n"
                    "receiver's own LO leak in the middle of your measurement.",
            label="'LO offset (fraction of span)'", rangeType="float",
            value="0.25", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="2,0,1,2"),
        chooser("gain_mode", (704, 100), "'Gain mode (RX1)'", "string",
                ["'manual'", "'slow_attack'", "'fast_attack'"],
                ["'manual - levels mean something'",
                 "'slow_attack - AGC, levels drift'",
                 "'fast_attack - AGC, levels drift fast'"],
                "'manual'", "3,0,1,2",
                comment="Manual, or let the AGC move your reference level."),
        blk("rx_gain", "variable_qtgui_range", (880, 100),
            comment="Ignored unless the gain mode is manual.",
            label="'RX1 gain (dB)'", rangeType="float", value="55",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="4,0,1,2"),
        # NOT named `window`: GRC blacklists any id that an import has already
        # bound, and the waterfall sink pulls in gnuradio.fft.window.
        chooser("fft_win", (176, 220), "'FFT window'", "string",
                ["'rectangular'", "'hann'", "'blackman-harris'"],
                ["'rectangular  (sidelobes -13 dB)'", "'hann  (-31 dB)'",
                 "'blackman-harris  (-92 dB)'"],
                "'blackman-harris'", "5,0,1,2",
                comment="The control this example exists for."),
        blk("avg", "variable_qtgui_range", (352, 220),
            comment="Frames in the power-domain average. 1 disables it.",
            label="'Averaging (frames)'", rangeType="float", value="16",
            start="1", stop="64", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="6,0,1,2"),
        blk("floor_pct", "variable_qtgui_range", (528, 220),
            comment="Which percentile of the trace counts as noise.",
            label="'Noise floor percentile'", rangeType="float", value="10",
            start="1", stop="50", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="7,0,1,2"),
        blk("hold", "variable_qtgui_check_box", (704, 220),
            comment="Unticking is also the reset.",
            label="'Max hold'", type="bool", value="True", true="True",
            false="False", gui_hint="8,0,1,1"),
        blk("frames", "variable_qtgui_range", (880, 220),
            comment="Display frames per second. Frames in between are dropped\n"
                    "on purpose - see the keep-one-in-n block.",
            label="'Display rate (FFT/s)'", rangeType="float", value="12",
            start="1", stop="30", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="8,1,1,1"),

        blk("note_rate", "note", (176, 340), note=EX01_NOTE_RATE),
        blk("note_gain", "note", (176, 420), note=EX01_NOTE_GAIN),

        # ---- signal path
        blk("rx", "iio_fmcomms2_source", (400, 400),
            comment="RX1 only. The LO sits lo_off_hz BELOW the frequency you\n"
                    "asked for; the rotator downstream shifts it back, which\n"
                    "leaves the LO leak off to one side instead of on top of\n"
                    "your signal. Quadrature and both DC loops on: they are\n"
                    "what keeps the image and the leak from growing.",
            type="fc32", uri="uri", frequency="int(center_hz - lo_off_hz)",
            samplerate="samp_rate", buffer_size="buf", rx1_en="True",
            rx2_en="False", quadrature="True", rfdc="True", bbdc="True",
            gain1="gain_mode", manual_gain1="rx_gain", gain2="'manual'",
            manual_gain2="20", rf_port_select="'A_BALANCED'",
            filter_source="'Auto'", filter="", fpass="0", fstop="0",
            bandwidth="int(samp_rate)", len_tag_key="packet_len"),
        blk("shift_back", "blocks_rotator_cc", (672, 424),
            comment="Undo the LO offset digitally, so the x-axis reads true\n"
                    "frequency. phase_inc is just -2*pi*lo_frac: the offset in\n"
                    "cycles per sample IS the fraction of the span.",
            phase_inc="-2 * math.pi * lo_frac", tag_inc_update="False"),
        blk("to_frames", "blocks_stream_to_vector", (872, 424),
            comment="One FFT frame per item from here on.",
            type="complex", num_items="nfft", vlen="1"),
        blk("drop_frames", "blocks_keep_one_in_n", (1048, 424),
            comment="Keep a dozen frames a second and DROP the rest.\n"
                    "Deliberate: a Python FFT cannot keep up with 1200\n"
                    "frames/s, and a block that cannot keep up applies\n"
                    "backpressure all the way to the radio, which turns into\n"
                    "dropped buffers you did not ask for. Dropping on purpose\n"
                    "is cheaper and visible.",
            type="complex", n="max(1, int(samp_rate / (nfft * frames)))",
            vlen="nfft"),
        epy("dr", "spectrum_engine", (1240, 396),
            comment="Window, FFT, power averaging, max hold and the\n"
                    "dynamic-range metric. examples/lib/spectrum_engine.py -\n"
                    "edit it there and re-run examples/mkgrc.py.",
            nfft="nfft", window="fft_win", avg="avg", hold="hold",
            floor_pct="floor_pct"),

        # ---- displays
        blk("spectrum", "qtgui_vector_sink_f", (1512, 300),
            comment="Two traces from one engine: the average and the max hold.",
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
        blk("waterfall", "qtgui_waterfall_sink_x", (872, 552),
            comment="On the shifted stream, so the axis reads true frequency.\n"
                    "Its own window is fixed; it is here for the time axis,\n"
                    "not for the levels.",
            type="complex", name="'Waterfall'", fftsize="1024",
            freqhalf="True", wintype="window.WIN_BLACKMAN_hARRIS",
            fc="center_hz", bw="samp_rate", int_min="-130", int_max="-20",
            grid="False", nconnections="1", update_time="0.10",
            showports="False", legend="True", axislabels="True",
            gui_hint="6,2,4,10"),
        blk("range_num", "qtgui_number_sink", (1512, 452),
            comment="Peak minus floor, on the averaged trace.",
            name="'Dynamic range'", type="float", autoscale="False",
            avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="1",
            min="0", max="140", update_time="0.10", label1="'peak - floor'",
            unit1="'dB'", color1="'black'", factor1="1", gui_hint="9,0,1,2"),
        blk("level_num", "qtgui_number_sink", (1512, 580),
            comment="The two numbers the dynamic range is the difference of,\n"
                    "plus what the chosen window is capable of.",
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
EX02_HEADER = """A modulated link you can watch - Fishball7020

THIS FLOWGRAPH TRANSMITS. Read this part before you run it.

The board reaches roughly +19 dBm at an antenna port, through a power
amplifier. What leaves that port is your responsibility and nobody else's:
transmitting without a licence is illegal in most of the spectrum, and this
radio tunes 70 MHz to 6 GHz, which is nearly all of it. The default centre is
2437 MHz, inside the 2.4 GHz ISM band, because that is the least bad default -
not because it is automatically permitted where you are. Check your own
regulations, and prefer a cable and an attenuator to an antenna.

  * `arm` starts UNTICKED and nothing is transmitted until you tick it.
  * `TX1 attenuation` starts at 89.75 dB, the most the AD9361 offers.
    HIGHER IS QUIETER. The safe end of that slider is the right-hand end.
  * The attenuation shown beside `arm` is not an echo of the slider. It is
    read back out of the chip by an IIO Attribute Source, four times a
    second. If the driver refuses a write - the thermal limit of patch 0018,
    the transmit latch of patch 0016 - the slider will move and that number
    will not. Believe the number.
  * A LOOPBACK WITHOUT AN ATTENUATOR DESTROYS THE RECEIVER. The RX input is
    rated about +2.5 dBm (AD9361 Rev. G, Table 11) and this board transmits
    about +19. Fit at least 20 dB of pad. See docs/rf-safety notes and
    tools/tx-guard.sh.

WHAT IT DOES. Random bytes become QPSK (or 16-/64-QAM), get shaped by a root
raised cosine, transmitted, received, matched-filtered, timing-recovered,
carrier-recovered, and measured. The constellation, the eye and a live EVM
figure all come from the same recovered symbols.

TWO EVM NUMBERS, and the gap between them is the interesting one. The first is
the error as it arrives. The second is the error after dividing out a single
complex gain - one fixed amplitude and one fixed rotation, fitted across the
block, which is what a real vector analyser does before quoting a figure. The
difference is the share of your error that is a static rotation you could have
calibrated away rather than noise you could not. Mistune the carrier loop and
watch the two separate.

THE CAVEAT THAT MATTERS. This board is listening to itself, so the
transmitter and the receiver share one reference clock. There is no frequency
offset to track and no independent phase noise, and the EVM is therefore
better than the same modulation would achieve between two radios. It is a real
measurement of a link that is easier than any real link.
docs/modulation-gallery.md measured this path with a separate radio and is the
honest comparison.

OFFSET TUNING, AT BOTH ENDS. The transmitter's own carrier leak sits at its
LO, and the receiver's at its own. Both offsets default to a fraction of the
span so that neither leak lands on the signal. Set them both to 0 and watch
two spikes appear in the middle of your own transmission."""

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
        blk("import_math", "import", (8, 180), imports="import math"),
        epy_mod("qam", "qam", (8, 260),
                "Square QAM points. Feeds BOTH the constellation the modulator\n"
                "is built from and the reference the EVM meter measures\n"
                "against, so the two cannot drift apart."),
        var("uri", URI, (176, 12),
            "`python3 tools/board_addr.py` prints an address if mDNS is not\n"
            "working on your network."),
        var("samp_rate", 2000000, (256, 12),
            "2 MS/s each way, so 500 ksym/s at 4 samples per symbol. Modest on\n"
            "purpose: 8 MB/s in each direction, and with the buffer below it\n"
            "gives the transmitter 524 ms of slack against a link stall -\n"
            "twice what patch 0015's mute watchdog needs. Raise it once you\n"
            "have watched the thing work, and read the buffer note first:\n"
            "transmitting is latency-critical in a way receiving is not."),
        var("sps", 4, (336, 12),
            "Samples per symbol, so 1 Msym/s at the default rate. Fixed when\n"
            "the modulator is built."),
        var("order", 4, (416, 12),
            "4 = QPSK, and QPSK is what this receiver actually recovers.\n"
            "16 and 64 will transmit correctly and will NOT resolve at the\n"
            "receiver - which is worth seeing once, and is explained in the\n"
            "note. A re-run parameter either way: the modulator takes its\n"
            "constellation object at construction, and the number of bits\n"
            "packed per symbol is fixed with it."),
        var("tx_alpha", 0.35, (496, 12),
            "The TRANSMIT root-raised-cosine roll-off. Baked into the\n"
            "modulator's taps, so changing it needs a re-run. The receive\n"
            "side has its own, live, control - see the note."),
        var("buf", 1048576, (576, 12),
            "libiio buffer, in samples, both directions. At 2 MS/s this is\n"
            "524 ms of samples, and the transmit buffer's DURATION is how long\n"
            "a link stall the DAC can ride out. Patch 0015 mutes the\n"
            "transmitter after 250 ms of starvation, so this is twice the\n"
            "margin that needs. Disarming is still immediate - the attenuator\n"
            "is analogue and unbuffered, so it does not wait for the buffer to\n"
            "drain. See the note."),
        var("center_hz", "int(center_mhz * 1e6)", (664, 12)),
        var("cnst", "qam.points(order)", (744, 12),
            "Just the points; the Constellation Object block turns them into\n"
            "the object the modulator needs."),

        # ---- the constellation both ends share
        blk("cnst_obj", "variable_constellation", (176, 560),
            comment="Built from qam.points(order), the same function the EVM\n"
                    "meter uses. Power normalisation makes the transmit level\n"
                    "independent of the order.",
            type="calcdist", sym_map="list(range(order))",
            const_points="qam.points(order)", rot_sym="4", dims="1",
            normalization="digital.constellation.POWER_NORMALIZATION",
            precision="8", soft_dec_lut="None"),

        # ---- controls
        blk("arm", "variable_qtgui_check_box", (176, 100),
            comment="Nothing is transmitted until this is ticked. It gates the\n"
                    "samples AND forces maximum attenuation - either alone\n"
                    "would do; both is cheap.",
            label="'ARM TRANSMITTER'", type="bool", value="False",
            true="True", false="False", gui_hint="0,0,1,1"),
        blk("tx_atten", "variable_qtgui_range", (256, 100),
            comment="Attenuation, so HIGHER IS QUIETER. 89.75 dB is the most\n"
                    "the AD9361 offers and is where this starts.",
            label="'TX1 attenuation (dB) - higher is quieter'",
            rangeType="float", value="89.75", start="0", stop="89.75",
            step="0.25", widget="counter_slider", orient="Qt.Horizontal",
            min_len="200", gui_hint="1,0,1,2"),
        blk("tx_scale", "variable_qtgui_range", (416, 100),
            comment="Digital amplitude before the converter. 0.20 keeps the\n"
                    "worst-case peak near -6 dBFS; see the note.",
            label="'TX digital scale (peak, not RMS)'", rangeType="float",
            value="0.20", start="0.02", stop="0.45", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="2,0,1,2"),
        blk("center_mhz", "variable_qtgui_range", (576, 100),
            comment="2437 MHz is in the 2.4 GHz ISM band. That is a least-bad\n"
                    "default, not a permission.",
            label="'Centre frequency (MHz)'", rangeType="float", value="2437",
            start="70", stop="6000", step="0.5", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="3,0,1,2"),
        blk("rx_gain", "variable_qtgui_range", (736, 100),
            comment="Manual only. An AGC would hide the thing you are\n"
                    "measuring by moving the reference level under it.",
            label="'RX1 gain (dB)'", rangeType="float", value="20",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="4,0,1,2"),
        blk("rrc_alpha", "variable_qtgui_range", (176, 200),
            comment="The RECEIVE matched filter's roll-off, and it IS live.\n"
                    "Leave it at tx_alpha to stay matched; move it to watch\n"
                    "what a mismatched matched filter costs.",
            label="'RX matched-filter roll-off (TX is fixed)'",
            rangeType="float", value="0.35", start="0.05", stop="0.90",
            step="0.01", widget="counter_slider", orient="Qt.Horizontal",
            min_len="200", gui_hint="5,0,1,2"),
        blk("sync_bw", "variable_qtgui_range", (336, 200),
            comment="Timing loop bandwidth. Too low and it never acquires;\n"
                    "too high and it tracks noise into the constellation.",
            label="'Timing loop bandwidth'", rangeType="float", value="0.045",
            start="0.002", stop="0.200", step="0.001", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="6,0,1,2"),
        blk("costas_bw", "variable_qtgui_range", (496, 200),
            comment="Carrier loop bandwidth. This is the one that moves the\n"
                    "two EVM figures apart.",
            label="'Carrier loop bandwidth'", rangeType="float", value="0.030",
            start="0.001", stop="0.200", step="0.001", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="7,0,1,2"),
        blk("tx_off_frac", "variable_qtgui_range", (656, 200),
            comment="Pushes the TRANSMITTER's carrier leak off the signal, by\n"
                    "shifting baseband up and the LO down by the same amount.",
            label="'TX LO offset (fraction of span)'", rangeType="float",
            value="0.20", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="8,0,1,2"),
        blk("rx_off_frac", "variable_qtgui_range", (816, 200),
            comment="Same trick at the RECEIVER. Set both to 0 and two leaks\n"
                    "land on top of your own transmission.",
            label="'RX LO offset (fraction of span)'", rangeType="float",
            value="0.25", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="9,0,1,2"),

        blk("note_level", "note", (176, 300), note=EX02_NOTE_LEVEL),
        blk("note_buffer", "note", (176, 380), note=EX02_NOTE_BUFFER),
        blk("note_qam", "note", (176, 460), note=EX02_NOTE_QAM),
        blk("note_rerun", "note", (176, 540), note=EX02_NOTE_RERUN),

        # ---- transmit chain
        blk("bits", "analog_random_source_x", (176, 660),
            comment="Random bytes. Nothing here is a real protocol - the point\n"
                    "is the modulation, not the payload.",
            type="byte", min="0", max="255", num_samps="100000", repeat="True"),
        blk("mod", "digital_constellation_modulator", (360, 644),
            comment="Bits to shaped symbols. differential=False: the carrier\n"
                    "loop's 90-degree ambiguity would scramble the bits, but\n"
                    "nothing here decodes bits, and EVM does not care.",
            constellation="cnst_obj", differential="False",
            samples_per_symbol="sps", excess_bw="tx_alpha", verbose="False",
            log="False", truncate="False"),
        blk("tx_shift", "blocks_rotator_cc", (608, 668),
            comment="Move baseband UP by the TX offset, so that with the LO\n"
                    "moved DOWN by the same amount the signal lands where you\n"
                    "asked and the carrier leak does not.",
            phase_inc="2 * math.pi * tx_off_frac", tag_inc_update="False"),
        blk("tx_gate", "blocks_multiply_const_vxx", (784, 668),
            comment="Amplitude and the arm gate in one block. Unarmed this is\n"
                    "exactly 0.0, so there is no modulation to transmit even\n"
                    "if the attenuation were wrong.",
            type="complex", const="tx_scale if arm else 0.0", vlen="1"),
        blk("tx", "iio_fmcomms2_sink", (968, 636),
            comment="TX1 only. Attenuation is the ARMED value or 89.75 dB, and\n"
                    "it is re-asserted after the stream opens - see the\n"
                    "snippet, and patch 0005 for why that is necessary.",
            type="fc32", uri="uri", frequency="int(center_hz - tx_off_frac * samp_rate)",
            samplerate="samp_rate", bandwidth="int(samp_rate)",
            buffer_size="buf", tx1_en="True", tx2_en="False", cyclic="False",
            rf_port_select="'A'", attenuation1="tx_atten if arm else 89.75",
            attenuation2="89.75", len_tag_key="''", filter_source="'Auto'",
            filter="", fpass="0", fstop="0"),

        # ---- receive chain
        blk("rx", "iio_fmcomms2_source", (176, 820),
            comment="RX1 only, manual gain. The LO sits below the signal by the\n"
                    "RX offset; the rotator downstream brings it back.",
            type="fc32", uri="uri",
            frequency="int(center_hz - rx_off_frac * samp_rate)",
            samplerate="samp_rate", buffer_size="buf", rx1_en="True",
            rx2_en="False", quadrature="True", rfdc="True", bbdc="True",
            gain1="'manual'", manual_gain1="rx_gain", gain2="'manual'",
            manual_gain2="20", rf_port_select="'A_BALANCED'",
            filter_source="'Auto'", filter="", fpass="0", fstop="0",
            bandwidth="int(samp_rate)", len_tag_key="packet_len"),
        blk("rx_shift", "blocks_rotator_cc", (448, 844),
            comment="Undo the RX offset, so the signal sits at baseband zero\n"
                    "and the receiver's own leak sits off to one side.",
            phase_inc="-2 * math.pi * rx_off_frac", tag_inc_update="False"),
        blk("mf", "root_raised_cosine_filter", (624, 812),
            comment="The matched filter. Its taps ARE live (set_taps), which is\n"
                    "what makes rrc_alpha a control rather than a constant.\n"
                    "Gain sps so the symbol amplitude survives the filter.",
            type="fir_filter_ccf", decim="1", interp="1", gain="sps",
            samp_rate="samp_rate", sym_rate="samp_rate / sps",
            alpha="rrc_alpha", ntaps="11 * sps + 1"),
        blk("sync", "digital_symbol_sync_xx", (872, 796),
            comment="Timing recovery, decision-directed (modified Mueller and\n"
                    "Mueller). Chosen by measurement, not by preference: with\n"
                    "Gardner's detector this chain did not lock at all - the\n"
                    "recovered magnitudes had a spread of 0.30 against 0.002\n"
                    "for this one, and EVM sat near 45% on a noiseless signal.\n"
                    "The cost is that it IS decision-directed, which is why\n"
                    "this receiver is a QPSK receiver - see the note.",
            type="cc", ted_type="digital.TED_MOD_MUELLER_AND_MULLER",
            constellation="cnst_obj",
            sps="sps", ted_gain="1.0", loop_bw="sync_bw", damping="1.0",
            max_dev="1.5", osps="1", resamp_type="digital.IR_MMSE_8TAP",
            nfilters="128", pfb_mf_taps="[]"),
        blk("costas", "digital_costas_loop_cc", (1128, 812),
            comment="Carrier recovery. Order 4 for every square QAM: it locks\n"
                    "to the 90-degree symmetry the constellation already has.",
            w="costas_bw", order="4", use_snr="False"),
        epy("evm", "evm_meter", (1304, 788),
            comment="examples/lib/evm_meter.py. Port 0 is the symbols rescaled\n"
                    "to the reference, so the picture and the numbers agree.",
            order="order", chunk="2048"),

        # ---- the read-back that is not an echo
        blk("atten_rb", "iio_attr_source", (968, 460),
            comment="TX1's hardwaregain, read out of ad9361-phy four times a\n"
                    "second. This is the attenuation the CHIP has, negated -\n"
                    "not the number the slider is showing. If the driver\n"
                    "refuses a write, only this tells you.",
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
        blk("spectrum", "qtgui_freq_sink_x", (448, 940),
            comment="The received spectrum, after the shift, so the axis reads\n"
                    "true frequency. Both carrier leaks are visible here, and\n"
                    "so is clipping if you raise the transmit scale too far.",
            type="complex", name="'Received spectrum'", fftsize="4096",
            freqhalf="True", wintype="window.WIN_BLACKMAN_hARRIS",
            norm_window="False", fc="center_hz", bw="samp_rate", grid="True",
            autoscale="False", average="0.2", ymin="-130", ymax="0",
            label="'level'", units="'dBFS'", nconnections="1",
            update_time="0.10", showports="False", tr_mode="qtgui.TRIG_MODE_FREE",
            tr_level="0.0", tr_chan="0", tr_tag="''", ctrlpanel="False",
            legend="True", axislabels="True", label1="'RX1'", width1="1",
            color1='"blue"', alpha1="1.0", gui_hint="0,2,5,10"),
        blk("constellation", "qtgui_const_sink_x", (1528, 740),
            comment="The recovered symbols, at the reference's scale.",
            type="complex", name="'Constellation - recovered symbols'",
            size="2048", grid="True", autoscale="False", ymin="-2", ymax="2",
            xmin="-2", xmax="2", nconnections="1", update_time="0.10",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_slope="qtgui.TRIG_SLOPE_POS",
            tr_level="0.0", tr_chan="0", tr_tag="''", legend="False",
            axislabels="True", label1="'symbols'", width1="1",
            color1='"blue"', style1="0", marker1="0", alpha1="0.4",
            gui_hint="5,2,7,5"),
        blk("eye", "qtgui_eye_sink_x", (872, 964),
            comment="The eye, on the matched filter's output - before timing\n"
                    "recovery, so an open eye means the SHAPING is right.",
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
        blk("atten_num", "qtgui_number_sink", (1200, 452),
            comment="Read from the chip, not from the slider.",
            name="'TX1 hardwaregain, READ BACK FROM THE CHIP'", type="float",
            autoscale="False", avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ",
            nconnections="1", min="-90", max="0", update_time="0.10",
            label1="'chip says'", unit1="'dB'", color1="'black'", factor1="1",
            gui_hint="0,1,1,1"),
        blk("evm_num", "qtgui_number_sink", (1528, 900),
            comment="The pair. Their difference is the static rotation.",
            name="'EVM'", type="float", autoscale="False", avg="0",
            graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="2", min="0",
            max="60", update_time="0.10", label1="'as received'", unit1="'%'",
            color1="'black'", factor1="1",
            label2="'after one complex gain'", unit2="'%'", color2="'black'",
            factor2="1", gui_hint="10,0,1,2"),
        blk("mer_num", "qtgui_number_sink", (1528, 1030),
            comment="The same thing in dB, because that is how link budgets\n"
                    "are written.",
            name="'MER'", type="float", autoscale="False", avg="0",
            graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="1", min="0",
            max="45", update_time="0.10", label1="'modulation error ratio'",
            unit1="'dB'", color1="'black'", factor1="1", gui_hint="11,0,1,2"),

        # ---- the rule this repository keeps learning
        blk("reassert_atten", "snippet", (1200, 320), section="main_after_start",
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
EX03_HEADER = """Two coherent receivers - Fishball7020

This is the measurement a one-channel radio cannot make. RX1 and RX2 live in
one AD9361, behind one local oscillator and one sample clock, so the phase
between them is a property of the signal and the cabling rather than of two
clocks wandering apart. Nothing else in this repository demonstrates it.

WHAT YOU GET. The angle of the cross-correlation between the two channels,
averaged as a COMPLEX NUMBER and only then turned into an angle. Averaging
angles instead is a mistake that hides itself: angles wrap at +/-180 degrees,
so a true phase near 180 has samples landing at +179 and -179 which average to
roughly zero, and a signal hard against the wrap reads as no phase shift at
all. Summing complex numbers has no wrap to fall foul of.

COHERENCE IS THE NUMBER THAT SAYS WHETHER TO BELIEVE THE ANGLE. It is the
magnitude of the normalised correlation, 0 to 1. Two independent noise streams
correlate to something that random-walks toward zero, so their angle is a
random number that the display shows just as confidently as a real one. Watch
coherence first. Near 1, the angle means something. Near 0, you are reading
noise with a decimal point on it.

THE DIAL, bottom middle, is a constellation sink used as a polar meter: the
point's ANGLE is the phase and its RADIUS is the coherence. A dot pinned to
the rim is a measurement. A dot wandering near the origin is noise.

THE TRAP THIS EXAMPLE IS BUILT TO AVOID. The receiver's own LO leak sits at
DC in both channels, it is the same leak, and it is almost perfectly
correlated with itself. Correlate the raw channels and you measure the leak:
coherence pins to 1 and the angle is a property of the board, not of anything
in the air. So the LO is offset, and each channel is band-selected around the
signal with an IDENTICAL filter - identical, so that whatever phase the filter
adds, it adds twice and cancels out of the difference. Widen the band-select
until DC is inside it and watch a convincing, meaningless coherence appear.

REPEATABLE IS NOT CALIBRATED. Each path has its own fixed delay through its
own balun and its own traces, so there is an offset that has nothing to do
with the signal. `zero` latches the current reading and subtracts it, which
makes later readings relative to that moment. It does NOT turn the angle into
a direction of arrival: that needs a splitter, matched cables and a known
geometry. The offset also changes with frequency, so zeroing at 2.4 GHz does
not hold at 5 GHz. docs/measured-performance.md has the measured asymmetry
between these two channels - about 1.5 dB in receive gain, which is normal.

Receive only. Nothing here transmits."""

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
        blk("import_math", "import", (8, 180), imports="import math"),
        var("uri", URI, (176, 12),
            "`python3 tools/board_addr.py` prints an address if mDNS is not\n"
            "working on your network."),
        var("buf", 262144, (264, 12),
            "libiio buffer, in samples. BOTH receivers are on, so the data rate\n"
            "is twice a single channel - 8 bytes per sample pair, not 4."),
        var("chunk", 4096, (344, 12),
            "Samples per phase estimate. The phase block decimates by this, so\n"
            "it is a port rate and fixed when the flowgraph is built.\n"
            "4096 at 5 MS/s is 1220 estimates a second."),
        var("center_hz", "int(center_mhz * 1e6)", (424, 12)),
        var("lo_off_hz", "lo_frac * samp_rate", (528, 12)),
        var("sel_taps", "firdes.low_pass(1.0, samp_rate, sel_bw_khz * 500.0, "
                        "sel_bw_khz * 200.0)", (648, 12),
            "One set of taps, used by BOTH band-select filters. Sharing the\n"
            "expression is the point: two filters with different taps would add\n"
            "different phases and the difference between the channels would be\n"
            "partly the filters. sel_bw_khz*500 is half the width in Hz."),

        # ---- controls
        chooser("samp_rate", (176, 100), "'Sample rate'", "real",
                ["2560000", "5000000", "10000000"],
                ["'2.56 MS/s  (20 MB/s for two channels)'",
                 "'5 MS/s  (40 MB/s)'", "'10 MS/s  (80 MB/s)'"],
                "5000000", "0,0,1,2",
                comment="Two channels, so twice the bytes of one."),
        blk("center_mhz", "variable_qtgui_range", (352, 100),
            comment="Where to look.",
            label="'Centre frequency (MHz)'", rangeType="float", value="2437",
            start="70", stop="6000", step="0.5", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="1,0,1,2"),
        blk("lo_frac", "variable_qtgui_range", (528, 100),
            comment="Offset tuning, as a fraction of the span. This is what\n"
                    "keeps the LO leak out of the correlation. Set it to 0 and\n"
                    "the leak lands inside the band-select.",
            label="'LO offset (fraction of span)'", rangeType="float",
            value="0.25", start="-0.4", stop="0.4", step="0.01",
            widget="counter_slider", orient="Qt.Horizontal", min_len="200",
            gui_hint="2,0,1,2"),
        blk("sel_bw_khz", "variable_qtgui_range", (704, 100),
            comment="Band-select width in kHz. Widen it past the LO offset and\n"
                    "the leak gets in - which is the lesson, once.",
            label="'Band-select width (kHz)'", rangeType="float", value="400",
            start="20", stop="3000", step="10", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="3,0,1,2"),
        blk("rx1_gain", "variable_qtgui_range", (176, 200),
            comment="Separate per channel on purpose: these two receivers are\n"
                    "not identical. About 1.5 dB apart on the measured board.",
            label="'RX1 gain (dB)'", rangeType="float", value="40",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="4,0,1,2"),
        blk("rx2_gain", "variable_qtgui_range", (352, 200),
            comment="Unequal gains change the amplitudes but NOT the phase -\n"
                    "worth proving to yourself with the dial.",
            label="'RX2 gain (dB)'", rangeType="float", value="40",
            start="0", stop="71", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="5,0,1,2"),
        blk("avg", "variable_qtgui_range", (528, 200),
            comment="Frames in the complex-domain average. Steadier, slower.",
            label="'Averaging (estimates)'", rangeType="float", value="8",
            start="1", stop="200", step="1", widget="counter_slider",
            orient="Qt.Horizontal", min_len="200", gui_hint="6,0,1,2"),
        blk("zero", "variable_qtgui_check_box", (704, 200),
            comment="Latches the CURRENT phase as zero, on the rising edge\n"
                    "only. Holding it ticked would re-zero forever and the\n"
                    "reading would sit at zero whatever the antennas did.",
            label="'zero (latch this phase as the reference)'", type="bool",
            value="False", true="True", false="False", gui_hint="7,0,1,2"),

        blk("note_try", "note", (176, 300), note=EX03_NOTE_TRY),

        # ---- signal path
        blk("rx", "iio_fmcomms2_source", (176, 460),
            comment="BOTH receivers, one LO, one sample clock. That shared\n"
                    "oscillator is the whole reason this example exists.\n"
                    "The LO sits lo_off_hz below the frequency you asked for.",
            type="fc32", uri="uri", frequency="int(center_hz - lo_off_hz)",
            samplerate="samp_rate", buffer_size="buf", rx1_en="True",
            rx2_en="True", quadrature="True", rfdc="True", bbdc="True",
            gain1="'manual'", manual_gain1="rx1_gain", gain2="'manual'",
            manual_gain2="rx2_gain", rf_port_select="'A_BALANCED'",
            filter_source="'Auto'", filter="", fpass="0", fstop="0",
            bandwidth="int(samp_rate)", len_tag_key="packet_len"),
        blk("sel1", "freq_xlating_fft_filter_ccc", (528, 420),
            comment="Band-select RX1 around the signal, which also throws away\n"
                    "DC and the LO leak with it. center_freq brings the offset\n"
                    "signal down to baseband.",
            decim="1", taps="sel_taps", center_freq="lo_off_hz",
            samp_rate="samp_rate", samp_delay="0", nthreads="1"),
        blk("sel2", "freq_xlating_fft_filter_ccc", (528, 540),
            comment="IDENTICAL to sel1 - same taps, same centre. Any phase the\n"
                    "filter adds, it adds to both, so it cancels out of the\n"
                    "difference. Two different filters here would make the\n"
                    "measurement partly a measurement of the filters.",
            decim="1", taps="sel_taps", center_freq="lo_off_hz",
            samp_rate="samp_rate", samp_delay="0", nthreads="1"),
        epy("phase", "phase_meter", (816, 468),
            comment="examples/lib/phase_meter.py. Averages the correlation as a\n"
                    "complex number, then takes the angle - never the other way\n"
                    "round. Decimates by chunk.",
            chunk="chunk", avg="avg", zero="zero"),

        # ---- displays
        blk("spectrum", "qtgui_freq_sink_x", (528, 680),
            comment="Both receivers, UNfiltered, so you can see where the LO\n"
                    "leak is and where the band-select sits relative to it.\n"
                    "The axis is centred on the LO, not on center_mhz - the\n"
                    "spike in the middle is the receiver looking at itself.",
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
        blk("dial", "qtgui_const_sink_x", (1088, 396),
            comment="A constellation sink used as a polar meter. Angle is the\n"
                    "phase, radius is the coherence. The unit circle is the\n"
                    "edge of the plot, so a point on the rim is a measurement\n"
                    "you can trust and one near the middle is not.",
            type="complex",
            name="'Phase dial - angle is phase, radius is coherence'",
            size="64", grid="True", autoscale="False", ymin="-1.1", ymax="1.1",
            xmin="-1.1", xmax="1.1", nconnections="1", update_time="0.10",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_slope="qtgui.TRIG_SLOPE_POS",
            tr_level="0.0", tr_chan="0", tr_tag="''", legend="False",
            axislabels="True", label1="'coherence * exp(j phase)'", width1="1",
            color1='"blue"', style1="0", marker1="0", alpha1="0.8",
            gui_hint="5,2,6,5"),
        blk("phase_time", "qtgui_time_sink_x", (1088, 556),
            comment="Phase against time. A coherent pair drifts slowly or not\n"
                    "at all; two independent radios would not hold still here.",
            type="float", name="'Phase over time'", ylabel="'phase'",
            yunit="'degrees'", size="1024", srate="samp_rate / chunk",
            grid="True", autoscale="False", ymin="-180", ymax="180",
            nconnections="1", update_time="0.10", entags="False",
            tr_mode="qtgui.TRIG_MODE_FREE", tr_slope="qtgui.TRIG_SLOPE_POS",
            tr_level="0.0", tr_delay="0", tr_chan="0", tr_tag="''",
            ctrlpanel="False", legend="False", axislabels="True",
            stemplot="False", label1="'phase'", width1="1", color1='"blue"',
            style1="1", marker1="-1", alpha1="1.0", gui_hint="5,7,6,5"),
        blk("phase_num", "qtgui_number_sink", (1088, 700),
            comment="Both the zeroed reading and the raw one, so zeroing can\n"
                    "never hide what the board is actually doing.",
            name="'Phase RX1 - RX2'", type="float", autoscale="False",
            avg="0", graph_type="qtgui.NUM_GRAPH_HORIZ", nconnections="2",
            min="-180", max="180", update_time="0.10",
            label1="'zeroed'", unit1="'deg'", color1="'black'", factor1="1",
            label2="'raw'", unit2="'deg'", color2="'black'", factor2="1",
            gui_hint="8,0,1,2"),
        blk("coh_num", "qtgui_number_sink", (1088, 828),
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
