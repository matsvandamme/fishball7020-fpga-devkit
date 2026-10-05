#!/usr/bin/env python3
"""chirp_view: a sweep on TX1, watched and heard live on RX1 (or TX2 on RX2).

TX1 plays one sweep from a cyclic buffer, over and over: a linear chirp, or a
triangle, logarithmic, sine-FM, stepped, frequency-hopping or pulsed sweep.
RX1 hears it through the bench loop (TX1 -> 20 dB pad -> RX1). The window
shows, beside a panel to start, stop and change it:

  - the live spectrum, with a max-hold trace;
  - a scrolling waterfall, where each sweep is a slanted line;
  - the response curve: received level against frequency, built up sweep by
    sweep from the chirp's own peak, so it shows how flat the loop is;
and the speakers play the received chirp as a rising whistle.

    # run from: tools/chirp-view, with the packages in requirements.txt
    python chirp_view.py                    # 7 MHz in 0.8 s around 868 MHz, 20 MS/s
    python chirp_view.py --shape triangle --span 4e6
    python chirp_view.py --rate 4.8e6 --span 1e6 --period 3   # slow, 16-bit through libiio
    python chirp_view.py --check            # build the buffer, no board
    python chirp_view.py --measure 5        # measure 5 sweeps, no window
    python chirp_view.py --save             # also write chirp_response.csv

How it reaches 20 MS/s: the samples come from zc-stream on the board (8-bit,
RX1 on port 5555; tools/stream-paths/zc-stream in the devkit), and everything
that touches them runs in its own process, so neither the window nor the
sound can make it miss a block. Below 6 MS/s it can use libiio instead
(--transport libiio). The sample rate is shared by TX and RX, and one DMA
block holds 64 MB, so at 20 MS/s a sweep lasts at most 0.83 s.

Offset tuning: TX1 and RX1 are both tuned below the sweep, and the chirp is
built off-centre in TX1's band, so it runs from +guard to +guard+span above
both LOs. The TX LO leakage and the RX DC spike then sit together, outside
the sweep, instead of in the middle of it.

Board rules it follows (docs/cyclic-buffers.md, rf-safety.md in the devkit):
  - TX attenuation is set only after the buffer starts, read back, and
    rewritten until the chip agrees; TX2 stays muted.
  - On exit (Ctrl+C, closing the window, or an error) TX1 is muted and read
    back BEFORE the buffer is torn down.
  - The firmware mutes a cyclic transmit after 60 s; the chirp is re-armed
    every 55 s instead (a gap of a second or two while the buffer re-uploads).
  - --tx-atten above -10 dB is refused: with the 20 dB pad that keeps RX1
    under its +2.5 dBm rating even at the board's ~+19 dBm maximum.

--channel 2 runs the same on the second pair, TX2 -> pad -> RX2, with TX1
muted instead: the samples come from zc-stream's RX2 port (5556).

--reference makes the other receiver a timing reference for pulse
compression: both receivers are read from one libiio buffer, so their samples
are taken at the same instants, and a lost block shifts both alike. The range
is then RX1's peak minus RX2's, which no lost sample can move. 'loops' plays
the pulse on TX1 and TX2 at once, one per bench loop; 'split' plays it on TX1
only, for a splitter feeding both receivers.
"""
import argparse
import csv
import math
import multiprocessing as mp
import os
import queue
import signal
import socket
import sys
import time

import numpy as np

MUTED = -89.75
MAX_BLOCK = 64 * 1024 * 1024        # bytes per DMA block (iio_max_block_size)
REARM_S = 55.0                      # the firmware's cyclic bound is 60 s
FULL_SCALE_RX = 2048.0              # 12-bit samples
NFFT = 4096
POOL = 4                            # FFT bins per waterfall column
BLOCK = 1 << 18                     # samples per processing block
ZC_PORT = 5555                      # zc-stream -D: RX1 here, RX2 on the next port
COMP_MAX_PERIOD = 0.01              # pulse compression for pulse periods up to 10 ms
REF_MAX = 5.5e6                     # --reference: two receivers through libiio, 44 MB/s


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


# --- the plan: rate, span, period, tuning ------------------------------------

def plan(args):
    """Fill in rate, span, period and the RX offset from what was asked."""
    rate = args.rate
    guard = max(0.5e6, 0.04 * rate)                 # clear of the DC spike
    usable = 0.45 * rate                            # the RF filter rolls off near rate/2
    widest = math.floor((usable - guard) / 1e6) * 1e6
    # 7 MHz by default: at 20 MS/s that keeps the top of the sweep ~1 MHz
    # inside the RF filters' edge, so the response shows the loop, not the
    # filter. At a lower --rate, the widest sweep that fits.
    span = args.span or min(7e6, widest)
    if span + guard > usable:
        raise ValueError(f"a {span/1e6:g} MHz sweep does not fit beside DC at {rate/1e6:g} MS/s: "
                         f"at most {(usable - guard)/1e6:.1f} MHz (or a higher rate)")
    max_period = MAX_BLOCK / 4 / rate
    default = 1e-3 if args.shape == "pulsed" else math.floor(max_period * 10) / 10   # radar-like: 1 ms
    period = args.period or default
    if period > max_period:
        raise ValueError(f"{period:g} s at {rate/1e6:g} MS/s is {4*period*rate/1e6:.0f} MB: "
                         f"one DMA block holds 64 MB, so at most {max_period:.2f} s")
    shortest = 1e-4 if args.shape == "pulsed" else 0.05
    if period < shortest:
        raise ValueError(f"a {'pulse period' if args.shape == 'pulsed' else 'sweep'} shorter than "
                         f"{shortest:g} s is too fast" + ("" if args.shape == "pulsed" else " to watch"))
    transport = args.transport
    if transport == "auto":
        transport = "zc" if rate > 6e6 else "libiio"
    if args.reference:
        # both receivers in one buffer: libiio, at 16 bits, 8 bytes a sample
        if args.shape != "pulsed":
            raise ValueError("the reference is for pulse compression: pick the pulsed mode")
        if rate > REF_MAX:
            raise ValueError(f"the reference reads both receivers through libiio: at most "
                             f"{REF_MAX/1e6:g} MS/s (4.8 MS/s in the window)")
        transport = "libiio"
    offset = span / 2 + guard                       # chirp centre, above the RX LO
    return dict(rate=rate, span=span, period=period, guard=guard, offset=offset,
                rx_lo=args.freq - offset, transport=transport, shape=args.shape, taper=args.taper,
                steps=args.steps, duty=args.duty,
                comp=args.shape == "pulsed" and period <= COMP_MAX_PERIOD, ref=args.reference,
                max_span=usable - guard, max_period=max_period)


# --- the chirp --------------------------------------------------------------

SHAPES = (("up", "Sawtooth up"), ("down", "Sawtooth down"), ("triangle", "Triangle (up, then down)"),
          ("log", "Logarithmic up"), ("sine", "Sine (FM)"), ("steps", "Stepped"),
          ("hops", "Random hops"), ("pulsed", "Pulsed chirp"))
USES_STEPS, USES_DUTY = ("steps", "hops"), ("pulsed",)


def _smooth_circular(x, width):
    """Two passes of a moving average over a periodic signal: a soft step."""
    w = int(width)
    if w < 2:
        return x
    for _ in range(2):
        xp = np.concatenate([x[-w:], x, x[:w]])
        c = np.cumsum(xp)
        x = (c[2 * w:] - c[:-2 * w]) / (2 * w)
        x = x[: len(xp) - 2 * w]
    return x


def fmt_s(sec):
    return f"{sec:.2f} s" if sec >= 0.1 else f"{sec * 1e3:.3g} ms"


def fmt_mb(mb):
    return f"{mb:.0f} MB" if mb >= 1 else f"{mb * 1e3:.0f} kB"


def shape_curves(shape, n, centre, span, taper=0.05, steps=8, duty=0.25):
    """One period of a sweep mode: instantaneous frequency (Hz above the TX
    LO) and amplitude envelope (0..1), at n points.

    Every mode is described this way, so the samples, the theory chart and
    the mirror correction all come from the same curves.
    """
    u = np.arange(n) / n                              # fraction of the period
    lo, hi = centre - span / 2, centre + span / 2
    env = np.ones(n)
    if shape == "up":
        f = lo + span * u
    elif shape == "down":
        f = hi - span * u
    elif shape == "triangle":
        f = lo + span * (1 - np.abs(2 * u - 1))
    elif shape == "log":                              # equal ratios: slow at the bottom, fast at the top
        f = lo * (hi / lo) ** u
    elif shape == "sine":
        f = centre - span / 2 * np.cos(2 * np.pi * u)
    elif shape in ("steps", "hops"):
        k = np.minimum((u * steps).astype(int), steps - 1)
        order = np.arange(steps) if shape == "steps" else np.random.default_rng(7020).permutation(steps)
        f = lo + span * (order[k] + 0.5) / steps
        # smooth each jump over taper of a step, so the change does not splatter
        f = _smooth_circular(f, taper * n / steps / 2)
    elif shape == "pulsed":
        on = u < duty
        f = lo + span * np.clip(u / duty, 0, 1)
        env = on.astype(float)
        L = int(taper * duty * n / 2)
        if L > 1:                                     # raised-cosine edges on the pulse
            r = 0.5 - 0.5 * np.cos(np.pi * np.arange(L) / L)
            env[:L] *= r
            end = int(duty * n)
            env[end - L:end] *= r[::-1]
    else:
        raise ValueError(f"unknown sweep mode {shape}")
    # The sawtooth-like modes jump from top to bottom at the wrap: fade there
    if shape in ("up", "down", "log") and taper > 0:
        L = max(2, int(n * taper / 2))
        r = 0.5 - 0.5 * np.cos(np.pi * np.arange(L) / L)
        env[:L] *= r
        env[-L:] *= r[::-1]
    return f, env


def build_chirp(rate, span, period, centre=0.0, level=0.5, shape="up", taper=0.05, cal=None,
                steps=8, duty=0.25):
    """One period of the sweep, ready for TX1's cyclic buffer.

    The phase is the running sum of the instantaneous frequency, with the
    frequency nudged by under a hertz so the period holds a whole number of
    cycles: the end then meets the start without a phase jump. N is a
    multiple of 32 (the DMA rounds other lengths) and T follows N.
    """
    n = int(round(period * rate / 32)) * 32
    t_sweep = n / rate
    f, env = shape_curves(shape, n, centre, span, taper, steps, duty)
    cycles = f.sum() / rate
    f = f + (round(cycles) - cycles) * rate / n       # a whole number of cycles per period
    phase = 2 * np.pi * np.concatenate([[0.0], np.cumsum(f[:-1])]) / rate
    iq = (level * 32767) * env * np.exp(1j * phase)
    if cal is not None:
        # Mirror cancellation: the radios' IQ mismatch adds alpha*conj(x), a
        # mirror image. Sending x - alpha*conj(x) cancels it. alpha depends on
        # frequency, and the sweep is one frequency at each instant, so each
        # sample gets alpha at its own instantaneous frequency.
        fc, ac = cal
        a = np.interp(f, fc, ac.real) + 1j * np.interp(f, fc, ac.imag)
        iq = iq - a * np.conj(iq)
    end_phase = phase[-1] + 2 * np.pi * f[-1] / rate
    return iq.astype(np.complex64), {
        "samples": n, "seconds": t_sweep, "mb": 4 * n / 1e6,
        "peak_fs": float(np.abs(iq).max() / 32767),
        "wrap_phase_error": float(np.angle(np.exp(1j * end_phase))),
        "centre": centre,
    }


def check(args, p):
    iq, info = build_chirp(p["rate"], p["span"], p["period"], p["offset"], shape=p["shape"], taper=p["taper"], steps=p["steps"], duty=p["duty"],
                           cal=cal_load(p, args) if args.mirror_fix else None)
    ok = (info["samples"] % 16 == 0 and 4 * info["samples"] <= MAX_BLOCK
          and info["peak_fs"] <= 0.51 and abs(info["wrap_phase_error"]) < 1e-4)   # the mirror correction adds ~0.1%
    print(f"rate          {p['rate']/1e6:g} MS/s, RX through {p['transport']}")
    print(f"buffer        {info['samples']} samples ({'multiple of 16' if info['samples'] % 16 == 0 else 'NOT a multiple of 16'})")
    print(f"size          {info['mb']:.1f} MB of {MAX_BLOCK/1e6:.1f} MB")
    print(f"sweep         {info['seconds']:.4f} s, {(args.freq - p['span']/2)/1e6:.3f} -> "
          f"{(args.freq + p['span']/2)/1e6:.3f} MHz")
    print(f"tuning        TX and RX LO {p['rx_lo']/1e6:.3f} MHz: the chirp sits {p['guard']/1e6:.2f} to "
          f"{(p['guard'] + p['span'])/1e6:.2f} MHz above both, clear of TX LO leakage and RX DC")
    print(f"peak level    {info['peak_fs']:.3f} of full scale")
    print(f"wrap          phase back to {info['wrap_phase_error']:+.2e} rad at the end of the sweep")
    print("check:", "OK" if ok else "FAILED")
    return 0 if ok else 1


# --- mirror calibration, remembered per tuning ---------------------------------

CAL_FILE = os.path.join(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
                        "fishball7020", "chirp_view_mirror.json")


def cal_key(p, args):
    key = f"lo={p['rx_lo']:.0f} rate={p['rate']:.0f} offset={p['offset']:.0f} span={p['span']:.0f}"
    return key if args.channel == 1 else key + f" ch={args.channel}"     # each pair has its own mirror


def cal_points(p):
    """Five points across the sweep, inside the edge taper."""
    return p["offset"] + p["span"] * np.array([-0.45, -0.225, 0.0, 0.225, 0.45])


def cal_load(p, args):
    import json
    if args.reference:
        return None                     # one pulse for both transmitters: no per-transmitter correction
    try:
        e = json.load(open(CAL_FILE))[cal_key(p, args)]
        return np.array(e["f"]), np.array(e["re"]) + 1j * np.array(e["im"])
    except Exception:
        return None


def cal_save(p, args, f, a, before, after):
    import json
    os.makedirs(os.path.dirname(CAL_FILE), exist_ok=True)
    try:
        data = json.load(open(CAL_FILE))
    except Exception:
        data = {}
    data[cal_key(p, args)] = {"f": list(map(float, f)), "re": list(map(float, a.real)),
                              "im": list(map(float, a.imag)),
                              "before_dbc": [round(10 * math.log10(x), 1) for x in before],
                              "after_dbc": [round(10 * math.log10(x), 1) for x in after],
                              "when": time.strftime("%Y-%m-%d %H:%M")}
    json.dump(data, open(CAL_FILE, "w"), indent=1)


# --- the board --------------------------------------------------------------

class Board:
    """TX and every setting, through one libiio context in the main process."""

    def __init__(self, args, p):
        import adi
        self.args, self.p = args, p
        self.dev = adi.ad9361(uri=args.uri)
        self.i = args.channel - 1                     # 0 or 1: the pair in use
        self.o = 1 - self.i                           # the other transmitter, muted unless --reference loops
        # the transmitters that play: both for --reference loops, else this pair's
        self.tx_on = [0, 1] if args.reference == "loops" else [self.i]
        self.tx_running = self.closed = self.bound_off = False
        self.bound_was = None
        self.armed_at = 0.0

    def gain(self, ch, val=None):
        """Read, or write then read, TX attenuation on channel index ch."""
        if val is not None:
            setattr(self.dev, f"tx_hardwaregain_chan{ch}", val)
        return getattr(self.dev, f"tx_hardwaregain_chan{ch}")

    LONG_BOUND_S = 3600

    def lift_cyclic_bound(self):
        """Stretch the firmware's 60 s cyclic bound to an hour while this app runs.

        The bound stops a forgotten cyclic transmit. An hour means one re-arm
        (a 1-2 s gap) per hour instead of one a minute, and if this program
        ever dies without cleaning up, the board still mutes the chirp within
        the hour by itself. close() restores the old value; so does a reboot.
        """
        try:
            a = self.dev._txdac.attrs["tx_cyclic_timeout_ms"]
            self.bound_was = a.value
            a.value = str(self.LONG_BOUND_S * 1000)
            self.args.rearm = self.LONG_BOUND_S - 60
            log(f"cyclic bound: {self.bound_was} ms -> {a.value} ms for this session (re-arm once an hour); "
                f"restored on exit")
            return True
        except Exception as e:
            log(f"could not lift the cyclic bound ({e}); re-arming every {self.args.rearm:g} s instead")
            return False

    def restore_cyclic_bound(self):
        if getattr(self, "bound_was", None) is not None:
            self.dev._txdac.attrs["tx_cyclic_timeout_ms"].value = self.bound_was
            log(f"cyclic bound restored to {self.dev._txdac.attrs['tx_cyclic_timeout_ms'].value} ms")
            self.bound_was = None

    def configure(self):
        a, d, p = self.args, self.dev, self.p
        self._mute_both("before starting")
        if getattr(self, "quad_was", None) is not None:
            self.freeze_rx_quad(False)                # RX quadrature tracking stays on
        d.sample_rate = int(p["rate"])              # shared by RX and TX
        # Offset tuning on both sides: TX and RX LOs below the sweep, so the TX
        # LO leakage and the RX DC spike both land outside it.
        d.tx_lo = int(p["rx_lo"])
        d.rx_lo = int(p["rx_lo"])
        bw = int(min(0.9 * p["rate"], 56e6))
        d.rx_rf_bandwidth = bw
        d.tx_rf_bandwidth = bw
        for ch in ([0, 1] if a.reference else [self.i]):  # the reference receiver gets the same gain
            setattr(d, f"gain_control_mode_chan{ch}", "manual")
            setattr(d, f"rx_hardwaregain_chan{ch}", a.rx_gain)
        log(f"radio: {p['rate']/1e6:g} MS/s, TX and RX LO {p['rx_lo']/1e6:.3f} MHz "
            f"(chirp {p['guard']/1e6:.2f}-{(p['guard']+p['span'])/1e6:.2f} MHz above both), "
            f"RF bandwidth {bw/1e6:.1f} MHz, RX{a.channel} manual {a.rx_gain:g} dB")

    def _mute_both(self, why):
        for ch in (0, 1):
            setattr(self.dev, f"tx_hardwaregain_chan{ch}", MUTED)
        g = (self.dev.tx_hardwaregain_chan0, self.dev.tx_hardwaregain_chan1)
        if any(x > MUTED + 0.26 for x in g):
            raise RuntimeError(f"transmitters not muted {why}: {g}")
        return g

    def start_tx(self, iq):
        """Start the cyclic chirp, then set the attenuation and make the chip agree."""
        d, want = self.dev, self.args.tx_atten
        c = self.args.channel
        d.tx_enabled_channels = self.tx_on
        d.tx_cyclic_buffer = True
        t0 = time.time()
        d.tx(iq if len(self.tx_on) == 1 else [iq, iq])
        self.tx_running = True
        self.armed_at = time.time()
        for _ in range(10):                         # AFTER the start: write, read back
            g = [self.gain(ch, want if ch in self.tx_on else MUTED) for ch in (0, 1)]
            if all(abs(g[ch] - want) <= 0.5 if ch in self.tx_on else g[ch] <= MUTED + 0.26 for ch in (0, 1)):
                break
            time.sleep(0.05)
        else:
            self.stop_tx()
            raise RuntimeError(f"TX attenuation did not apply: asked {want}, chip reads TX1 {g[0]}, TX2 {g[1]}")
        log(f"{' and '.join(f'TX{ch + 1}' for ch in self.tx_on)} cyclic {'pulse' if self.args.reference else 'chirp'} "
            f"started ({time.time() - t0:.1f} s upload), attenuation TX1 {g[0]:.2f} dB, TX2 {g[1]:.2f} dB "
            f"(asked {want:g} on TX{c}{' and TX' + str(3 - c) if len(self.tx_on) == 2 else ''})")

    def set_tx_atten(self, want):
        """Live: write and read back until the chip agrees (only while running)."""
        self.args.tx_atten = want
        if not self.tx_running:
            return None
        for _ in range(10):
            got = [self.gain(ch, want) for ch in self.tx_on]
            if all(abs(x - want) <= 0.5 for x in got):
                return got[0]
            time.sleep(0.05)
        self.stop_tx()
        raise RuntimeError(f"TX{self.args.channel} attenuation did not apply: asked {want}, "
                           f"chip reads {got}; transmitter stopped")

    def set_rx_gain(self, gain):
        self.args.rx_gain = gain
        for ch in ([0, 1] if self.args.reference else [self.i]):
            setattr(self.dev, f"rx_hardwaregain_chan{ch}", gain)
        return getattr(self.dev, f"rx_hardwaregain_chan{self.i}")

    CAL_SHIFT = 300_000                               # TX LO above RX LO while calibrating

    def measure_image(self, bb, alpha):
        """Play a tone at bb (Hz above the TX LO), corrected by alpha; return
        the TX mirror's power over the tone's (linear).

        The transmitter is tuned CAL_SHIFT above the receiver meanwhile, so
        its mirror (at shift - bb in the receiver's band) lands apart from the
        receiver's own (at -(shift + bb)), which RX quadrature tracking handles."""
        d, rate = self.dev, self.p["rate"]
        n = int(rate / 250)                           # 4 ms; bb on a 250 Hz grid fits whole cycles
        bb = round(bb / 250) * 250
        x = 0.5 * 32767 * np.exp(2j * np.pi * bb * np.arange(n) / rate)
        x = x - alpha * np.conj(x)
        d.tx_enabled_channels = [self.i]
        d.tx_cyclic_buffer = True
        d.tx(x.astype(np.complex64))
        self.tx_running = True
        try:
            for _ in range(10):                       # AFTER the start: set, read back
                got = self.gain(self.i, self.args.tx_atten)
                if abs(got - self.args.tx_atten) <= 0.5 and self.gain(self.o, MUTED) <= MUTED + 0.26:
                    break
            else:
                raise RuntimeError(f"TX{self.args.channel} attenuation did not apply")
            d.rx_destroy_buffer()
            d.rx()                                    # samples from after the start
            spec = np.zeros(1 << 16)
            win = np.blackman(1 << 16)
            for _ in range(4):
                spec += np.abs(np.fft.fft(d.rx() * win)) ** 2
            f = np.fft.fftfreq(1 << 16, 1 / rate)
            bin_ = lambda at: spec[np.abs(f - at) < 4 * rate / (1 << 16)].sum()
            sh = self.CAL_SHIFT
            return bin_(sh - bb) / bin_(sh + bb)
        finally:
            self.stop_tx()
            # close the RX buffer too: left open, it keeps zc-stream (which then
            # refuses: the buffer is in use) from serving the window afterwards
            d.rx_destroy_buffer()

    def freeze_rx_quad(self, frozen):
        """RX quadrature tracking keeps adapting to whatever image it sees,
        so while the mirror is cancelled on the TX side it must hold still.
        close() puts the original setting back."""
        q = self.dev._ctrl.find_channel(f"voltage{self.i}", False).attrs["quadrature_tracking_en"]
        if getattr(self, "quad_was", None) is None:
            self.quad_was = q.value
        q.value = "0" if frozen else self.quad_was

    def calibrate_mirror(self, freqs, progress=lambda msg: None):
        """Find, at each frequency, the alpha that cancels the mirror.

        The mirror's power with a correction alpha is K*|c - alpha|^2, where c
        is the alpha that cancels it. Five measurements (alpha0, alpha0 +- d,
        alpha0 +- jd) give K and c; a second, finer round refines c.
        """
        d = self.dev
        if self.args.reference:
            raise RuntimeError("no mirror calibration with --reference: both transmitters play one pulse")
        d.rx_enabled_channels = [self.i]
        d.rx_buffer_size = 1 << 16
        d.tx_lo = int(self.p["rx_lo"] + self.CAL_SHIFT)
        time.sleep(0.2)
        alphas, before, after = [], [], []
        for i, bb in enumerate(freqs):
            c = 0j
            for rnd, delta in enumerate((2e-3, 5e-4)):
                progress(f"calibrating mirror: point {i + 1} of {len(freqs)}, round {rnd + 1}")
                p0 = self.measure_image(bb, c)
                if rnd == 0:
                    before.append(p0)
                pr, pl = self.measure_image(bb, c + delta), self.measure_image(bb, c - delta)
                pu, pd = self.measure_image(bb, c + 1j * delta), self.measure_image(bb, c - 1j * delta)
                K = (pr + pl - 2 * p0) / (2 * delta ** 2)
                if K <= 0:
                    continue                              # too noisy to fit: keep c
                c = c + (pl - pr) / (4 * K * delta) + 1j * (pd - pu) / (4 * K * delta)
            after.append(self.measure_image(bb, c))
            alphas.append(c)
        d.tx_lo = int(self.p["rx_lo"])                # back to the app's tuning
        return np.array(alphas), np.array(before), np.array(after)

    def stop_tx(self):
        """Mute first, confirm, THEN tear the buffer down."""
        if not self.tx_running:
            return
        g = self._mute_both("before teardown")
        log(f"TX muted before teardown: TX1 {g[0]:.2f} dB, TX2 {g[1]:.2f} dB")
        self.dev.tx_destroy_buffer()
        self.tx_running = False

    def rearm(self, iq):
        log(f"re-arming the cyclic buffer ({time.time() - self.armed_at:.1f} s since the last start, bound 60 s)")
        self.stop_tx()
        self.start_tx(iq)

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.stop_tx()
        finally:
            self.restore_cyclic_bound()
            if getattr(self, "quad_was", None) is not None:
                self.freeze_rx_quad(False)
                log(f"RX quadrature tracking restored to {self.quad_was}")
        g = (self.dev.tx_hardwaregain_chan0, self.dev.tx_hardwaregain_chan1)
        log(f"closed: TX1 {g[0]:.2f} dB, TX2 {g[1]:.2f} dB")


# --- pulse compression ---------------------------------------------------------

def pulse_reference(p):
    """The transmitted pulse at baseband, and the period in samples.

    RX1 and TX1 share one LO, so an echo arrives at the same baseband
    frequencies it was sent at: the matched filter is the pulse itself.
    """
    n = int(round(p["period"] * p["rate"] / 32)) * 32
    f, env = shape_curves("pulsed", n, p["offset"], p["span"], p["taper"], p["steps"], p["duty"])
    L = int(np.nonzero(env > 0)[0].max()) + 1
    phase = 2 * np.pi * np.concatenate([[0.0], np.cumsum(f[:L - 1])]) / p["rate"]
    return (env[:L] * np.exp(1j * phase)).astype(np.complex64), n


# --- the receiver: its own process -------------------------------------------

class Source:
    """Blocks of RX samples (RX1 or RX2) as complex64 on the 12-bit scale, from either path."""

    def __init__(self, args, p):
        self.kind = p["transport"]
        if self.kind == "zc":
            host = args.uri.split(":", 1)[1]
            self.sock = socket.create_connection((host, ZC_PORT + args.channel - 1), timeout=10)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
            self.buf = bytearray(2 * BLOCK)
        else:
            import adi
            self.dev = adi.ad9361(uri=args.uri)
            # --reference: both receivers in one buffer, sampled at the same instants
            self.ref = bool(args.reference)
            self.i = args.channel - 1
            self.dev.rx_enabled_channels = [0, 1] if self.ref else [self.i]
            self.dev.rx_buffer_size = BLOCK
            try:
                self.dev._rxadc.set_kernel_buffers_count(8)
            except Exception:
                pass

    def read(self):
        if self.kind == "zc":
            view, got = memoryview(self.buf), 0
            while got < len(self.buf):
                n = self.sock.recv_into(view[got:])
                if n == 0:
                    raise ConnectionError("zc-stream closed the stream (is another program receiving?)")
                got += n
            x = np.frombuffer(self.buf, np.int8).astype(np.float32) * 16    # back to 12-bit counts
            return x[0::2] + 1j * x[1::2]
        if self.ref:                                # (measured, reference)
            x = self.dev.rx()
            return x[self.i].astype(np.complex64), x[1 - self.i].astype(np.complex64)
        return self.dev.rx().astype(np.complex64)

    def close(self):
        try:
            self.sock.close() if self.kind == "zc" else self.dev.rx_destroy_buffer()
        except Exception:
            pass


class Ctl:
    """Small shared integers between the window and the receiver process,
    without a separate manager process (which outlived a crashed parent)."""

    KEYS = ("pause", "clear_resp", "frames_per_row", "hamming")

    def __init__(self, ctx):
        self.v = {k: ctx.Value("i", 20 if k == "frames_per_row" else 0, lock=False) for k in self.KEYS}

    def __getitem__(self, k):
        return self.v[k].value

    def __setitem__(self, k, val):
        self.v[k].value = int(val)

    def get(self, k, default=None):
        return self.v[k].value if k in self.v else default


def rx_process(args, p, out, ctl, stop, parent):
    """Read, transform and summarise RX1; send small results to the window.

    Runs in its own process so the window and the sound can never stall it.
    Messages: ("rows", array), ("live", spectrum, peak_dBFS, f_now, snr),
    ("pitch", offsets, present), ("resp", sum, n), ("stats", dict).
    """
    signal.signal(signal.SIGINT, signal.SIG_IGN)    # the parent decides when to stop
    try:                                            # and if the parent dies, the kernel ends us too
        import ctypes
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
    except Exception:
        pass
    import scipy.fft as sfft
    rate = p["rate"]
    win = np.blackman(NFFT).astype(np.float32)
    norm2 = (win.sum() * FULL_SCALE_RX) ** 2
    bb = np.fft.fftshift(np.fft.fftfreq(NFFT, 1 / rate))
    lo_b, hi_b = np.searchsorted(bb, p["guard"] - 2 * rate / NFFT), np.searchsorted(bb, p["guard"] + p["span"] + 2 * rate / NFFT)
    resp_sum, resp_n = np.zeros(NFFT), np.zeros(NFFT)
    acc, acc_n = np.zeros(NFFT // POOL, np.float32), 0
    stats = {"samples": 0, "gaps": 0, "gap_ms": 0.0, "t0": time.time()}
    f_last, slope, ref = None, p["span"] / p["period_built"], None
    # Pulse compression: correlate RX1 with the sent pulse (overlap-save FFT
    # convolution), and fold the result onto one pulse period, averaging.
    comp = p.get("comp")
    if comp:
        pulse, N = pulse_reference(p)
        Lp = len(pulse)
        tail = np.zeros(Lp - 1, np.complex64)
        prof, prof_have, pos, R, R_ham, comp_n = np.zeros(N), False, 0, None, None, 0
        refd, tail_r, prof_r, ref_ph = p.get("ref"), tail.copy(), np.zeros(N), None
    try:
        src = Source(args, p)
    except Exception as e:
        out.put(("error", f"RX: {e}")); return
    last_resp = time.time()
    while not stop.is_set():
        try:
            os.kill(parent, 0)                  # the window's process is gone: never outlive it
        except ProcessLookupError:
            break
        if ctl.get("pause"):
            time.sleep(0.02); continue
        if ctl.get("clear_resp"):
            resp_sum[:] = 0; resp_n[:] = 0; ctl["clear_resp"] = False
        try:
            x = src.read()
        except Exception as e:
            out.put(("error", f"RX stopped: {e}")); break
        if p.get("ref"):
            x, xr = x                               # (measured, reference)
        stats["samples"] += len(x)
        if comp:
            if R is None or R_ham != ctl.get("hamming"):  # the matched filter, weighted or not
                R_ham = ctl.get("hamming")
                w = np.hamming(Lp).astype(np.float32) if R_ham else np.ones(Lp, np.float32)
                M = sfft.next_fast_len(len(x) + Lp - 1)
                R = np.conj(sfft.fft(pulse * w, M))
                prof[:] = 0; prof_have = False
            z = np.concatenate([tail, x.astype(np.complex64)])
            if comp_n % 4 == 0:                      # one block in four: ~13 pulses each, plenty
                c = sfft.ifft(sfft.fft(z, M) * R, workers=2)[:len(x)]
                pw_c = c.real ** 2 + c.imag ** 2
                # fold onto one period: pad the front so index 0 is the period's start
                start = (pos - (Lp - 1)) % N
                rows = -(-(start + len(pw_c)) // N)
                fold = lambda v: np.concatenate([np.zeros(start), v, np.zeros(rows * N - start - len(v))]
                                                ).reshape(rows, N).sum(axis=0)
                new = fold(pw_c) / np.maximum(fold(np.ones(len(pw_c))), 1)   # mean per position
                if refd:
                    # The reference receiver, compressed the same way, sets time
                    # zero: both folds are rolled so its peak sits mid-period. A
                    # lost block moves both peaks alike, so the roll absorbs it.
                    zr = np.concatenate([tail_r, xr])
                    cr = sfft.ifft(sfft.fft(zr, M) * R, workers=2)[:len(xr)]
                    new_r = fold(cr.real ** 2 + cr.imag ** 2) / np.maximum(fold(np.ones(len(cr))), 1)
                    ph = int(np.argmax(new_r))
                    if ref_ph is not None and min((ph - ref_ph) % N, (ref_ph - ph) % N) > 3:
                        stats["realign"] = stats.get("realign", 0) + 1     # counted, and absorbed
                    ref_ph = ph
                    new, new_r = np.roll(new, N // 2 - ph), np.roll(new_r, N // 2 - ph)
                    prof[:] = 0.7 * prof + 0.3 * new if prof_have else new
                    prof_r[:] = 0.7 * prof_r + 0.3 * new_r if prof_have else new_r
                else:
                    # The fold counts samples since the start: if RX1 lost samples
                    # meanwhile, the peak lands elsewhere. Never average across that:
                    # start afresh, and count it (a zero set before no longer holds).
                    d = (int(np.argmax(new)) - int(np.argmax(prof))) % N
                    if prof_have and min(d, N - d) > 3:
                        prof[:] = new
                        stats["realign"] = stats.get("realign", 0) + 1
                    else:
                        prof[:] = 0.7 * prof + 0.3 * new if prof_have else new
                prof_have = True
            comp_n += 1
            tail = z[-(Lp - 1):] if Lp > 1 else tail
            if refd:
                tail_r = np.concatenate([tail_r, xr])[-(Lp - 1):] if Lp > 1 else tail_r
            pos += len(x)
        m = len(x) // NFFT
        X = sfft.fft(x[: m * NFFT].reshape(m, NFFT) * win, axis=1, workers=2)
        pw = np.fft.fftshift((X.real ** 2 + X.imag ** 2), axes=1) / norm2      # linear, full scale = 1
        # the chirp's bin in each frame, searched only where the chirp can be
        band = pw[:, lo_b:hi_b]
        k = band.argmax(axis=1)
        idx = k + lo_b
        lvl = 10 * np.log10(band[np.arange(m), k] + 1e-20)
        floor = 10 * np.log10(np.median(pw, axis=1) + 1e-20)
        good = lvl > floor + 20
        # continuity: the first frame should follow the previous block's last
        if f_last is not None and good[0] and p["shape"] == "up":
            jump = bb[idx[0]] - (f_last + slope * NFFT / rate)
            if 5 * rate / NFFT < abs(jump) < p["span"] / 2:                     # not a wrap
                stats["gaps"] += 1
                stats["gap_ms"] += jump / slope * 1e3
        f_last = bb[idx[-1]]
        # the mirror: whatever sits at -f when the chirp is at +f (both LOs are equal)
        if good.any():
            mi = (NFFT - idx[good]) % NFFT
            ch = pw[np.nonzero(good)[0], idx[good]]
            mr = np.maximum.reduce([pw[np.nonzero(good)[0], (mi + o) % NFFT] for o in (-1, 0, 1)])
            stats["mirror_db"] = 0.9 * stats.get("mirror_db", 10 * np.log10(np.median(mr / ch) + 1e-20)) \
                + 0.1 * 10 * np.log10(np.median(mr / ch) + 1e-20)
        # response: parabolic interpolation over the peak and its neighbours
        if good.any():                                 # not the faded edges of a tapered sweep:
            top = np.percentile(lvl[good], 90)         # a level kept across blocks, since a whole
            ref = top if ref is None else max(top, ref - 0.05)   # block can lie inside a fade
            good &= lvl > ref - 1.0
        r = np.nonzero(good)[0]
        i = np.clip(idx[r], 1, NFFT - 2)
        db = lambda j: 10 * np.log10(pw[r, j] + 1e-20)
        a, b, c = db(i - 1), db(i), db(i + 1)
        den = a - 2 * b + c
        with np.errstate(divide="ignore", invalid="ignore"):
            d = np.clip(np.where(den < 0, 0.5 * (a - c) / den, 0.0), -0.5, 0.5)
        np.add.at(resp_sum, np.rint(i + d).astype(int), 10 ** ((b - 0.25 * (a - c) * d) / 10))
        np.add.at(resp_n, np.rint(i + d).astype(int), 1)
        # waterfall rows: max over the frames in each row, pooled to columns
        per = max(1, int(ctl.get("frames_per_row", 20)))
        cols = pw.reshape(m, NFFT // POOL, POOL).max(axis=2)
        rows = []
        for fr in cols:
            np.maximum(acc, fr, out=acc); acc_n += 1
            if acc_n >= per:
                rows.append(10 * np.log10(acc + 1e-20)); acc[:] = 0; acc_n = 0
        try:
            if rows:
                out.put_nowait(("rows", np.array(rows, np.float32)))
            peak = 20 * math.log10(float(np.abs(x).max()) / FULL_SCALE_RX + 1e-12)
            out.put_nowait(("live", (10 * np.log10(pw[-1] + 1e-20)).astype(np.float32), peak,
                            float(bb[idx[-1]]), float(np.median(lvl - floor))))
            out.put_nowait(("pitch", (bb[idx] - p["guard"]) / p["span"], good))   # sound and --measure
            if time.time() - last_resp > 0.3:
                out.put_nowait(("resp", resp_sum.copy(), resp_n.copy()))
                if comp and prof_have:
                    out.put_nowait(("comp", prof.astype(np.float32), stats.get("realign", 0),
                                    prof_r.astype(np.float32) if refd else None))
                out.put_nowait(("stats", dict(stats)))
                last_resp = time.time()
        except queue.Full:
            pass                                    # the window is behind: drop a picture, never samples
    src.close()
    out.put(("resp", resp_sum.copy(), resp_n.copy()))
    out.put(("stats", dict(stats)))
    out.put(("done",))


# --- the sound -----------------------------------------------------------------

class Sonifier:
    """The received chirp as a whistle on the PC's speakers.

    The chirp sweeps MHz, far outside hearing, so its position in the sweep
    is mapped to pitch: bottom 300 Hz, top 2400 Hz, three octaves on a log
    scale. The receiver sends one position per FFT frame; the audio callback
    plays that track back in real time, about 0.1 s behind, as one
    phase-continuous tone, in whole-array maths. No chirp on RX1, no sound.
    """

    def __init__(self, frame_s, volume):
        import collections
        import sounddevice as sd
        self.volume, self.sr = volume, 44100
        self.per_frame = frame_s * self.sr          # audio samples per FFT frame
        self.track = collections.deque()
        self.phase, self.f, self.a, self.a_target, self.pos = 0.0, 300.0, 0.0, 0.0, 0.0
        self.stream = sd.OutputStream(samplerate=self.sr, channels=1, dtype="float32",
                                      blocksize=1024, callback=self._play)
        self.stream.start()

    def push(self, x, present):
        pitch = 300.0 * 2 ** (3 * np.clip(x, 0, 1))
        self.track.extend(zip(pitch, np.where(present, self.volume, 0.0)))
        keep = int(0.35 * self.sr / self.per_frame)
        while len(self.track) > keep:               # never more than ~0.35 s behind
            self.track.popleft()

    def _play(self, out, frames, _t, _status):
        need = self.pos + frames / self.per_frame
        n = int(need)
        if len(self.track) < int(0.1 * self.sr / self.per_frame):
            n = 0                                   # keep ~0.1 s in hand
        pts = [self.track.popleft() for _ in range(min(n, len(self.track)))]
        self.pos = need - n if n else 0.0
        if not pts:
            self.a_target = 0.0                       # no chirp data (applying, stopped): fade out, never hold a note
        fp = np.array([self.f] + [q[0] for q in pts])
        ap = np.array([self.a_target] + [q[1] for q in pts])
        xs = np.linspace(0, len(fp) - 1, frames)
        f = np.interp(xs, np.arange(len(fp)), fp)
        a_t = np.interp(xs, np.arange(len(ap)), ap)
        self.f, self.a_target = float(fp[-1]), float(ap[-1])
        alpha = 0.005                               # ~5 ms fades: no clicks
        w = (1 - alpha) ** np.arange(frames)
        a = self.a * (1 - alpha) * w + np.convolve(a_t * alpha, w)[:frames]
        self.a = float(a[-1])
        ph = self.phase + 2 * np.pi * np.cumsum(f) / self.sr
        self.phase = float(ph[-1] % (2 * np.pi))
        out[:, 0] = (a * np.sin(ph)).astype(np.float32)
        self.rms = float(np.sqrt(np.mean(out[:, 0] ** 2)))
        self.calls = getattr(self, "calls", 0) + 1

    def silence(self):
        """Drop what is queued and fade out; sound returns with new data."""
        self.track.clear()
        self.a_target = 0.0

    def close(self):
        self.stream.stop(); self.stream.close()


# --- the shared driver: receiver process + re-arm ------------------------------

class Session:
    def __init__(self, args, p, board, iq):
        self.args, self.p, self.board, self.iq = args, p, board, iq
        ctx = mp.get_context("spawn")           # a direct child, no fork server left behind
        self.ctl = Ctl(ctx)
        self.q = ctx.Queue(maxsize=400)
        self.stop = ctx.Event()
        self.proc = ctx.Process(target=rx_process, daemon=True,
                                args=(args, p, self.q, self.ctl, self.stop, os.getpid()))
        self.proc.start()

    def maybe_rearm(self):
        """Re-arm with the receiver paused: an upload under a busy receiver
        once stalled past the board's first-block allowance."""
        if self.board.tx_running and time.time() - self.board.armed_at > self.args.rearm:
            self.ctl["pause"] = True
            time.sleep(0.1)
            try:
                self.board.rearm(self.iq)
            finally:
                self.ctl["pause"] = False

    def close(self):
        self.stop.set()
        self.proc.join(5)
        if self.proc.is_alive():
            self.proc.terminate()
        self.q.close()
        self.q.cancel_join_thread()


# --- headless measurement ----------------------------------------------------

def measure(args, p, info, s):
    """Track the chirp's position on RX1 for N sweeps; print span, period, gaps."""
    rate = p["rate"]
    frame_s = NFFT / rate
    t, f, need = [], [], int((args.measure + 1.3) * info["seconds"] / frame_s)
    stats, resp = {}, None
    t_end = time.time() + (args.measure + 3) * info["seconds"] + 10
    while len(f) < need and time.time() < t_end:
        try:
            msg = s.q.get(timeout=1)
        except queue.Empty:
            continue
        if msg[0] == "pitch":
            pos, good = msg[1], msg[2]
            base = len(f)
            t.extend((base + np.arange(len(pos))) * frame_s)
            f.extend(np.where(good, pos * p["span"], np.nan))
        elif msg[0] == "stats":
            stats = msg[1]
        elif msg[0] == "error":
            print(msg[1]); return 1
    t, f = np.array(t), np.array(f)
    ok = ~np.isnan(f)
    # wraps only between frames where the chirp was seen: a tapered sweep's
    # faded edges are not detected, and must not count as a wrap
    tt, ff = t[ok], f[ok]
    wraps = tt[1:][np.diff(ff) < -p["span"] / 2]
    periods = np.diff(wraps)
    span = np.percentile(f[ok], 99.5) - np.percentile(f[ok], 0.5)
    print(f"transport     {p['transport']}, {rate/1e6:g} MS/s")
    print(f"continuity    {stats.get('gaps', 0)} gaps ({stats.get('gap_ms', 0):.0f} ms) in "
          f"{stats.get('samples', 0)/rate:.1f} s of samples")
    print(f"sweeps seen   {len(periods)} complete")
    print(f"span          {span/1e6:.3f} MHz measured, {p['span']/1e6:.3f} asked ({(span/p['span'] - 1)*100:+.1f}%)")
    if len(periods):
        pm = periods.mean()
        print(f"period        {pm:.4f} s measured, {info['seconds']:.4f} built "
              f"({(pm/info['seconds'] - 1)*100:+.2f}%), spread {periods.std()*1e3:.1f} ms")
    return 0


# --- the window --------------------------------------------------------------

RATES = (4.8e6, 7.68e6, 10e6, 15.36e6, 20e6)


def run_window(args, st):
    """The window: plots on the left, controls on the right.

    st holds what a re-plan replaces: p, iq, info, session (and board).
    """
    import pyqtgraph as pg
    from PyQt6 import QtCore, QtWidgets
    from PyQt6.QtGui import QKeySequence, QShortcut

    board = st["board"]
    CH = args.channel                                # 1 or 2: the labels follow the pair in use
    sound = None
    try:
        sound = Sonifier(NFFT / st["p"]["rate"], args.volume)
    except Exception as e:
        log(f"no sound ({e}); the window runs without it")

    pg.setConfigOptions(antialias=True, imageAxisOrder="row-major")
    app = QtWidgets.QApplication(sys.argv)
    timers = []

    def make_safe():
        """Mute, tear down and restore the bound BEFORE Qt shuts down: a crash
        in Qt's teardown (seen: a Wayland repaint during quit) must not be able
        to skip this."""
        for tm in timers:
            tm.stop()
        try:
            board.close()
        except Exception as e:
            log(f"while closing the board: {e}")

    class Top(QtWidgets.QWidget):
        def closeEvent(self, ev):                    # Esc, Q, the close button, --duration, Ctrl+C
            make_safe()
            ev.accept()

    top = Top()
    top.setWindowTitle(f"chirp_view: TX{CH} chirp on RX{CH}")
    top.setStyleSheet("""
        QWidget { background: black; color: #ddd; font-size: 11pt; }
        QGroupBox { border: 1px solid #444; border-radius: 6px; margin-top: 10px; padding: 3px; }
        QSlider::groove:horizontal { height: 6px; background: #444; border-radius: 3px; }
        QSlider::sub-page:horizontal { background: #4fc3f7; border-radius: 3px; }
        QSlider::handle:horizontal { background: #ddd; width: 14px; margin: -5px 0; border-radius: 7px; }
        QGroupBox::title { subcontrol-origin: margin; left: 8px; color: #aaa; }
        QDoubleSpinBox, QComboBox { background: #1b1b1b; border: 1px solid #555; padding: 3px; }
        QPushButton { background: #263238; border: 1px solid #555; border-radius: 4px; padding: 6px; }
        QPushButton:hover { background: #37474f; }
    """)
    top.resize(1500, 950)
    outer = QtWidgets.QHBoxLayout(top)
    left = QtWidgets.QVBoxLayout(); outer.addLayout(left, 1)
    status = QtWidgets.QLabel(); status.setWordWrap(True)
    status.setStyleSheet("font-size: 12pt; padding: 4px;")
    win = pg.GraphicsLayoutWidget()
    win.setMinimumSize(300, 300)                      # the plots shrink; they never push under the panel
    win.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Ignored)
    status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Preferred)
    left.addWidget(status); left.addWidget(win, 1)

    # --- plots -------------------------------------------------------------
    p_spec = win.addPlot(row=1, col=0, title="Live spectrum: blue now, orange max hold")
    p_spec.setLabel("left", "dBFS"); p_spec.setLabel("bottom", "MHz")
    p_spec.setYRange(-120, -10); p_spec.showGrid(x=True, y=True, alpha=0.3)
    region = pg.LinearRegionItem((0, 1), movable=False, brush=(80, 80, 160, 40)); p_spec.addItem(region)
    c_live = p_spec.plot(pen=pg.mkPen("#4fc3f7", width=1))
    c_hold = p_spec.plot(pen=pg.mkPen("#ffb74d", width=1))
    p_wf = win.addPlot(row=2, col=0, title="Waterfall: one slanted line per sweep")
    p_wf.setLabel("bottom", "MHz"); p_wf.setLabel("left", "seconds ago")
    img = pg.ImageItem(); p_wf.addItem(img); img.setColorMap(pg.colormap.get("inferno"))
    p_wf.setXLink(p_spec)
    p_resp = win.addPlot(row=3, col=0, title="Response: chirp level vs frequency")
    p_resp.setLabel("left", "dBFS"); p_resp.setLabel("bottom", "MHz"); p_resp.showGrid(x=True, y=True, alpha=0.3)
    c_resp = p_resp.plot(pen=pg.mkPen("#81c784", width=2), connect="finite")
    p_comp = pg.PlotItem(title=f"Pulse compression: RX{CH} matched to the sent pulse, one pulse period"
                         + (f", timed against RX{3 - CH} (grey, mid-period)" if args.reference else ""))
    p_comp.setLabel("left", "dB from the peak"); p_comp.setLabel("bottom", "delay within the period (µs)")
    p_comp.showGrid(x=True, y=True, alpha=0.3); p_comp.setYRange(-60, 3, padding=0)
    c_ref = p_comp.plot(pen=pg.mkPen("#9e9e9e", width=1))         # --reference: the reference receiver
    c_comp = p_comp.plot(pen=pg.mkPen("#ce93d8", width=2))
    comp_zero = pg.InfiniteLine(angle=90, pen=pg.mkPen("#e0e0e0", width=1, style=QtCore.Qt.PenStyle.DashLine),
                                label="zero", labelOpts={"position": 0.9, "color": "#e0e0e0"})
    comp_txt = pg.TextItem(anchor=(1, 0), color="#e0e0e0", fill=(0, 0, 0, 170))
    p_comp.addItem(comp_txt, ignoreBounds=True)
    ROW3 = {"item": p_resp}

    def use_row3(item):
        """The response chart, or the compression chart in its place."""
        if ROW3["item"] is item:
            return
        win.removeItem(ROW3["item"])
        win.addItem(item, row=3, col=0)
        ROW3["item"] = item
    # the transmitted sweep, from the plan: frequency over one period, and the
    # amplitude envelope (the edge taper) on a second axis
    p_th = win.addPlot(row=4, col=0, title="Sent: frequency (blue), envelope (orange)")
    p_th.setLabel("left", "MHz", color="#4fc3f7"); p_th.setLabel("bottom", "ms into the sweep")
    p_th.showGrid(x=True, y=True, alpha=0.3)
    c_thf = p_th.plot(pen=pg.mkPen("#4fc3f7", width=2))
    vb_env = pg.ViewBox(); p_th.showAxis("right"); p_th.scene().addItem(vb_env)
    p_th.getAxis("right").linkToView(vb_env); vb_env.setXLink(p_th)
    p_th.getAxis("right").setLabel("envelope", color="#ffb74d"); vb_env.setYRange(0, 1.05, padding=0)
    c_the = pg.PlotCurveItem(pen=pg.mkPen("#ffb74d", width=2)); vb_env.addItem(c_the)
    p_th.vb.sigResized.connect(lambda: vb_env.setGeometry(p_th.vb.sceneBoundingRect()))
    for r, sf in ((1, 2), (2, 5), (3, 2), (4, 2)):
        win.ci.layout.setRowStretchFactor(r, sf)
    # pyqtgraph sizes a plot at least as wide as its title, which pushed the
    # plots under the panel in a narrow window: let titles clip instead
    for pl in (p_spec, p_wf, p_resp, p_th, p_comp):
        pl.titleLabel.updateMin = lambda *a: None
        pl.titleLabel.setMinimumWidth(10)
        pl.titleLabel.setMinimumHeight(20)
    marks = []                                        # dashed start / centre / stop lines

    def theory(p, info):
        """Frequency and envelope of one transmitted period: the same curves the samples come from."""
        f, env = shape_curves(p["shape"], 2000, p["offset"], p["span"], p["taper"], p["steps"], p["duty"])
        t = np.arange(2000) / 2000 * info["seconds"]
        return t, (f - p["offset"] + args.freq) / 1e6, env

    # --- controls ----------------------------------------------------------
    panel = QtWidgets.QWidget()
    scroll = QtWidgets.QScrollArea(); scroll.setWidget(panel); scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setFixedWidth(345); scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
    outer.addWidget(scroll)
    pv = QtWidgets.QVBoxLayout(panel)
    pv.setSpacing(4); pv.setContentsMargins(4, 4, 4, 4)

    def spin(lo, hi, step, val, dec, suffix):
        w = QtWidgets.QDoubleSpinBox(); w.setRange(lo, hi); w.setSingleStep(step)
        w.setDecimals(dec); w.setValue(val); w.setSuffix(suffix); w.setKeyboardTracking(False)
        return w

    b_tx = QtWidgets.QPushButton(); b_tx.setMinimumHeight(48)
    pv.addWidget(b_tx)

    g_sweep = QtWidgets.QGroupBox("Sweep  (Apply to use)"); fs = QtWidgets.QFormLayout(g_sweep)
    p0 = st["p"]
    w_freq = spin(70, 6000, 0.1, args.freq / 1e6, 3, " MHz")
    w_span = spin(0.1, 25, 0.5, p0["span"] / 1e6, 2, " MHz")
    w_period = spin(0.0001, 30, 0.1, p0["period"], 4, " s")
    w_rate = QtWidgets.QComboBox()
    for r in RATES:
        w_rate.addItem(f"{r/1e6:g} MS/s", r)
    w_rate.setCurrentIndex(min(range(len(RATES)), key=lambda i: abs(RATES[i] - p0["rate"])))
    w_shape = QtWidgets.QComboBox()
    for key, name in SHAPES:
        w_shape.addItem(name, key)
    w_shape.setCurrentIndex([k for k, _ in SHAPES].index(p0["shape"]))
    fs.addRow("Centre", w_freq); fs.addRow("Span", w_span); fs.addRow("Sweep time", w_period)
    w_taper = spin(0, 20, 1, args.taper * 100, 0, " %")
    w_taper.setToolTip("Fade each sweep in and out by this much, so the jump at the wrap does not splatter")
    w_steps = spin(2, 64, 1, args.steps, 0, ""); w_steps.setToolTip("Frequencies in Stepped and Random hops")
    w_duty = spin(5, 95, 5, args.duty * 100, 0, " %"); w_duty.setToolTip("On-time of a Pulsed chirp")

    def mode_fields():
        k = w_shape.currentData()
        w_steps.setEnabled(k in USES_STEPS); w_duty.setEnabled(k in USES_DUTY)
        if k == "pulsed" and w_period.value() > COMP_MAX_PERIOD:
            w_period.setValue(0.001); w_duty.setValue(10)   # radar-like, and short enough to compress
        elif k != "pulsed" and w_period.value() < 0.05:
            w_period.setValue(min(0.8, MAX_BLOCK / 4 / w_rate.currentData()))
    w_shape.currentIndexChanged.connect(lambda _: mode_fields())
    fs.addRow("Sample rate", w_rate); fs.addRow("Mode", w_shape); fs.addRow("Steps", w_steps)
    fs.addRow("Duty", w_duty); fs.addRow("Edge taper", w_taper)
    mode_fields()
    limits = QtWidgets.QLabel(); limits.setWordWrap(True); limits.setStyleSheet("color: #999; font-size: 10pt;")
    fs.addRow(limits)
    b_apply = QtWidgets.QPushButton("Apply"); fs.addRow(b_apply)
    pv.addWidget(g_sweep)

    g_live = QtWidgets.QGroupBox("Live"); fl = QtWidgets.QFormLayout(g_live)
    w_att = spin(MUTED, -10, 1, args.tx_atten, 2, " dB")
    w_gain = spin(-3, 71, 1, args.rx_gain, 0, " dB")
    w_vol = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal); w_vol.setRange(0, 100); w_vol.setValue(int(args.volume * 100))
    w_vol.setMinimumWidth(160)
    b_auto = QtWidgets.QPushButton(f"Auto level RX{CH} (peak to -10 dBFS)")
    fl.addRow(f"TX{CH} attenuation", w_att); fl.addRow(f"RX{CH} gain", w_gain); fl.addRow(b_auto); fl.addRow("Volume", w_vol)
    pv.addWidget(g_live)

    g_mir = QtWidgets.QGroupBox("Mirror (IQ image)"); fm = QtWidgets.QVBoxLayout(g_mir)
    b_cal = QtWidgets.QPushButton("Calibrate mirror (about 10 s)")
    w_fix = QtWidgets.QCheckBox("Cancel the mirror"); w_fix.setChecked(args.mirror_fix)
    l_cal = QtWidgets.QLabel(); l_cal.setWordWrap(True); l_cal.setStyleSheet("color: #999; font-size: 10pt;")
    fm.addWidget(b_cal); fm.addWidget(w_fix); fm.addWidget(l_cal); pv.addWidget(g_mir)
    if args.reference:                                 # one pulse on both transmitters: no per-TX correction
        g_mir.setEnabled(False); g_mir.setToolTip("not with --reference")

    g_comp = QtWidgets.QGroupBox("Pulse compression"); fc = QtWidgets.QVBoxLayout(g_comp)
    w_ham = QtWidgets.QCheckBox("Hamming weighting")
    w_ham.setToolTip("Weight the matched filter: sidelobes fall from about -13 dB to about -40 dB, the peak gets ~1.5x wider")
    w_zoom = QtWidgets.QCheckBox("Zoom on the peak"); w_zoom.setChecked(True)
    b_zero = QtWidgets.QPushButton("Set zero here")
    b_zero.setToolTip("Mark the peak; then add a cable to the loop: the peak's shift is the cable's delay")
    fc.addWidget(w_ham); fc.addWidget(w_zoom); fc.addWidget(b_zero)
    pv.addWidget(g_comp)
    w_ham.toggled.connect(lambda on: st["session"].ctl.__setitem__("hamming", on))

    g_resp = QtWidgets.QGroupBox("Response"); fr = QtWidgets.QHBoxLayout(g_resp)
    b_clear = QtWidgets.QPushButton("Clear"); b_save = QtWidgets.QPushButton("Save CSV")
    fr.addWidget(b_clear); fr.addWidget(b_save); pv.addWidget(g_resp)
    msg = QtWidgets.QLabel(); msg.setWordWrap(True); msg.setStyleSheet("font-size: 10pt;")
    pv.addWidget(msg); pv.addStretch(1)
    help_ = QtWidgets.QLabel(f"Esc or Q: quit (mutes TX{CH} first)"); help_.setStyleSheet("color: #777; font-size: 9pt;")
    pv.addWidget(help_)

    def say(text, colour="#9ccc65"):
        msg.setText(text); msg.setStyleSheet(f"font-size: 10pt; color: {colour};")
        log(text)

    # --- state that follows the plan ----------------------------------------
    V = {"wf": None}
    CP = {"prof": None, "zero": None}
    hold = {"a": None}
    resp = {"sum": None, "n": None, "offset_sum": None, "offset_n": None}
    S = {"peak": -99.0, "f_now": 0.0, "snr": 0.0, "t0": time.time(), "shot": False, "logged": 0, "stats": {}}

    def geometry():
        p = st["p"]
        rate = p["rate"]
        V["frame_s"] = NFFT / rate
        V["f_rf"] = (np.fft.fftshift(np.fft.fftfreq(NFFT, 1 / rate)) + p["rx_lo"]) / 1e6
        V["span_s"] = max(2.5 * st["info"]["seconds"], 6.0)
        lo, hi = V["f_rf"][0], V["f_rf"][-1]
        V["lo"], V["hi"] = lo, hi
        sw_lo, sw_hi = (args.freq - p["span"] / 2) / 1e6, (args.freq + p["span"] / 2) / 1e6
        V["sw"] = (sw_lo, sw_hi)
        region.setRegion((sw_lo, sw_hi))
        for plot, item in marks:
            plot.removeItem(item)
        marks.clear()
        for plot in (p_spec, p_wf, p_resp):
            for f_m, name, pos in ((sw_lo, "start", 0.9), (args.freq / 1e6, "centre", 0.65), (sw_hi, "stop", 0.9)):
                ln = pg.InfiniteLine(f_m, angle=90, pen=pg.mkPen("#e0e0e0", width=1, style=QtCore.Qt.PenStyle.DashLine),
                                     label=name if plot is p_spec else None,
                                     labelOpts={"position": pos, "color": "#e0e0e0", "fill": (0, 0, 0, 160),
                                                "anchors": [(0.5, 0), (0.5, 0)]})
                plot.addItem(ln); marks.append((plot, ln))
        t, f_th, env = theory(p, st["info"])
        c_thf.setData(t * 1e3, f_th); c_the.setData(t * 1e3, env)
        p_th.setXRange(0, st["info"]["seconds"] * 1e3, padding=0)
        p_th.setYRange(sw_lo - 0.05 * p["span"] / 1e6, sw_hi + 0.05 * p["span"] / 1e6, padding=0)
        vb_env.setGeometry(p_th.vb.sceneBoundingRect())
        p_spec.setXRange(lo, hi, padding=0)
        p_wf.setXRange(lo, hi, padding=0); p_wf.setYRange(0, V["span_s"], padding=0)
        p_resp.setXRange(sw_lo - 0.05 * p["span"] / 1e6, sw_hi + 0.05 * p["span"] / 1e6, padding=0)
        use_row3(p_comp if p.get("comp") else p_resp)
        for r, sf in ((1, 2), (2, 4 if p.get("comp") else 5), (3, 3 if p.get("comp") else 2), (4, 2)):
            win.ci.layout.setRowStretchFactor(r, sf)    # the compression chart needs the room
        g_comp.setVisible(bool(p.get("comp")))
        CP.update(prof=None, zero=None)
        p_comp.removeItem(comp_zero) if comp_zero in p_comp.items else None
        c_comp.setData([], []); c_ref.setData([], [])
        st["session"].ctl["hamming"] = w_ham.isChecked()
        hold["a"] = np.full(NFFT, -200.0)
        resp.update(sum=None, n=None)
        c_resp.setData([], [])
        size_waterfall(max(100, int(0.8 * p_wf.vb.height())))
        if sound:
            sound.per_frame = V["frame_s"] * sound.sr
            sound.track.clear()
        top.setWindowTitle(f"chirp_view: {p['span']/1e6:g} MHz around {args.freq/1e6:g} MHz, TX{CH} -> RX{CH}")

    def size_waterfall(rows):
        per = max(1, round(V["span_s"] / rows / V["frame_s"]))
        st["session"].ctl["frames_per_row"] = per
        V["wf"] = np.full((rows, NFFT // POOL), -130.0, np.float32)
        img.setImage(V["wf"], autoLevels=False, levels=(-120, -30))   # data first: setRect scales by it
        img.setRect(QtCore.QRectF(V["lo"], 0, V["hi"] - V["lo"], rows * per * V["frame_s"]))

    def update_limits():
        r = w_rate.currentData()
        guard = max(0.5e6, 0.04 * r)
        limits.setText(f"At {r/1e6:g} MS/s: span up to {(0.45*r - guard)/1e6:.1f} MHz, sweep time up to "
                       f"{MAX_BLOCK/4/r:.2f} s (one 64 MB buffer). RX through "
                       f"{'zc-stream' if r > 6e6 else 'libiio'}.")

    def show_tx():
        on = board.tx_running
        b_tx.setText("■  Stop transmitting" if on else "▶  Start transmitting")
        b_tx.setStyleSheet(f"font-size: 13pt; font-weight: bold; background: {'#7f1d1d' if on else '#1b5e20'};")

    # --- actions -------------------------------------------------------------
    def toggle_tx():
        try:
            if board.tx_running:
                board.stop_tx(); say("transmitter stopped and muted")
            else:
                st["session"].ctl["pause"] = True
                try:
                    board.start_tx(st["iq"])
                finally:
                    st["session"].ctl["pause"] = False
                say("transmitting")
        except Exception as e:
            say(f"transmitter: {e}", "#ef5350")
        show_tx()

    def apply():
        args.freq = w_freq.value() * 1e6
        args.span = w_span.value() * 1e6
        args.period = w_period.value()
        args.rate = w_rate.currentData()
        args.shape = w_shape.currentData()
        args.taper = w_taper.value() / 100
        args.steps = int(w_steps.value())
        args.duty = w_duty.value() / 100
        args.transport = "auto"
        try:
            p = plan(args)
        except ValueError as e:
            say(str(e), "#ef5350"); return
        if sound:
            sound.silence()
        say("applying: re-tuning and uploading the new chirp...", "#ffca28")
        app.processEvents()
        was_on = board.tx_running
        try:
            st["session"].close()
            board.stop_tx()
            info = rebuild(p, was_on)
            say(f"{p['span']/1e6:g} MHz {dict(SHAPES)[p['shape']].lower()} in {info['seconds']:.2f} s "
                f"around {args.freq/1e6:.3f} MHz at {p['rate']/1e6:g} MS/s")
        except Exception as e:
            say(f"apply failed: {e}", "#ef5350")
        show_tx()

    def show_cal():
        import json
        if args.reference:
            l_cal.setText("off with --reference: one pulse plays on both transmitters"); return
        try:
            e = json.load(open(CAL_FILE))[cal_key(st["p"], args)]
            l_cal.setText(f"calibrated {e['when']}: mirror {max(e['before_dbc']):.0f} -> "
                          f"{max(e['after_dbc']):.0f} dBc (worst of 5 points)"
                          + ("" if args.mirror_fix else "; cancelling is OFF"))
        except Exception:
            l_cal.setText("not calibrated for these settings: press Calibrate")

    def rebuild(p, was_on):
        """Close the receiver, rebuild the chirp, restart: shared by Apply and the mirror."""
        iq, info = build_chirp(p["rate"], p["span"], p["period"], p["offset"], shape=p["shape"], taper=p["taper"], steps=p["steps"], duty=p["duty"],
                               cal=cal_load(p, args) if args.mirror_fix else None)
        p["period_built"] = info["seconds"]
        board.p = p
        board.configure()
        if was_on:
            board.start_tx(iq)
        st.update(p=p, iq=iq, info=info, session=Session(args, p, board, iq))
        geometry(); show_cal()
        return info

    def calibrate():
        if args.reference:
            say("no mirror calibration with --reference: both transmitters play one pulse", "#ffca28"); return
        was_on = board.tx_running
        if sound:
            sound.silence()
        say("calibrating the mirror: the chirp stops for about 10 s", "#ffca28"); app.processEvents()
        try:
            st["session"].close()
            board.stop_tx()
            board.configure()
            f = cal_points(st["p"])
            a, before, after = board.calibrate_mirror(
                f, progress=lambda m: (msg.setText(m), app.processEvents()))
            cal_save(st["p"], args, f, a, before, after)
            args.mirror_fix = True
            w_fix.blockSignals(True); w_fix.setChecked(True); w_fix.blockSignals(False)
            rebuild(st["p"], was_on)
            say("mirror: " + ", ".join(f"{10*math.log10(b):.0f}->{10*math.log10(x):.0f}"
                                       for b, x in zip(before, after)) + " dBc at 5 points")
        except Exception as e:
            say(f"calibration failed: {e}", "#ef5350")
            try:
                rebuild(st["p"], was_on)
            except Exception as e2:
                say(f"and restarting failed: {e2}", "#ef5350")
        show_tx()

    def toggle_fix(on):
        args.mirror_fix = bool(on)
        if sound:
            sound.silence()
        say("mirror cancelling " + ("on" if on else "off") + ": re-uploading the chirp", "#ffca28"); app.processEvents()
        try:
            st["session"].close()
            was_on = board.tx_running
            board.stop_tx()
            rebuild(st["p"], was_on)
            say("mirror cancelling " + ("on" if on else "off"))
        except Exception as e:
            say(f"mirror: {e}", "#ef5350")
        show_tx()

    b_cal.clicked.connect(calibrate); w_fix.toggled.connect(toggle_fix)

    RX = {"restarts": 0}

    def restart_rx():
        """A new receiver process with the same settings: the transmitter is untouched."""
        if RX["restarts"] >= 5:
            say("the receiver keeps stopping: check that no other program is receiving", "#ef5350"); return
        RX["restarts"] += 1
        try:
            st["session"].close()
            st["session"] = Session(args, st["p"], board, st["iq"])
            size_waterfall(len(V["wf"]))
            say("receiver restarted")
        except Exception as e:
            say(f"receiver restart failed: {e}", "#ef5350")

    def set_att(v):
        try:
            got = board.set_tx_atten(v)
            if got is not None:
                say(f"TX{CH} attenuation {got:.2f} dB (read back)")
        except Exception as e:
            say(str(e), "#ef5350"); show_tx()

    def set_gain(v):
        try:
            say(f"RX{CH} gain {board.set_rx_gain(v):.0f} dB")
            clear_resp(quiet=True)                     # levels at another gain do not mix
        except Exception as e:
            say(f"RX{CH} gain: {e}", "#ef5350")

    def set_vol(v):
        args.volume = v / 100
        if sound:
            sound.volume = args.volume

    def clear_resp(quiet=False):
        st["session"].ctl["clear_resp"] = True
        resp.update(sum=None, n=None); c_resp.setData([], []); hold["a"][:] = -200
        if not quiet:
            say("response cleared")

    def save_resp():
        name = args.save or "chirp_response.csv"
        if resp["n"] is None:
            say("nothing to save yet", "#ffca28"); return
        write_response(name, resp, st["p"]); say(f"response saved to {name}")

    b_tx.clicked.connect(toggle_tx); b_apply.clicked.connect(apply)
    w_att.valueChanged.connect(set_att); w_gain.valueChanged.connect(set_gain); w_vol.valueChanged.connect(set_vol)
    w_rate.currentIndexChanged.connect(lambda _: update_limits())
    b_clear.clicked.connect(lambda: clear_resp()); b_save.clicked.connect(save_resp)

    # Auto level: the 8-bit stream keeps the top 8 of 12 bits, so a weak peak
    # uses only a few of its steps and quantisation sets the floor. Raise the
    # gain until the chirp peaks near -10 dBFS (it is a constant-envelope tone,
    # so that leaves ~10 dB to full scale).
    AL = {"steps": 0}

    def autolevel_start():
        if not board.tx_running:
            say("auto level needs the chirp: start transmitting first", "#ffca28"); return
        AL["steps"] = 8; S["peak"] = -99.0; say(f"auto level: adjusting RX{CH} gain...", "#ffca28")

    def autolevel_tick():
        if AL["steps"] <= 0 or S["peak"] < -98:
            return
        AL["steps"] -= 1
        err = -10.0 - S["peak"]
        if abs(err) < 1.5:
            AL["steps"] = 0; say(f"auto level: RX{CH} {args.rx_gain:g} dB, chirp peak {S['peak']:.1f} dBFS"); return
        g = float(np.clip(round(args.rx_gain + err), -3, 71))
        if g == args.rx_gain:
            AL["steps"] = 0; say(f"auto level: RX{CH} at its limit, {g:g} dB, peak {S['peak']:.1f} dBFS", "#ffca28"); return
        w_gain.blockSignals(True); w_gain.setValue(g); w_gain.blockSignals(False)
        board.set_rx_gain(g); S["peak"] = -99.0           # measure afresh at the new gain
        clear_resp(quiet=True)

    b_auto.clicked.connect(autolevel_start)

    # --- the loop ----------------------------------------------------------
    def drain():
        for _ in range(300):
            try:
                m = st["session"].q.get_nowait()
            except (queue.Empty, OSError, ValueError):
                break
            kind = m[0]
            if kind == "rows":
                wf, rows = V["wf"], m[1]
                n = min(len(rows), len(wf))
                wf[:-n] = wf[n:]; wf[-n:] = rows[-n:]
            elif kind == "live":
                c_live.setData(V["f_rf"], m[1]); np.maximum(hold["a"], m[1], out=hold["a"])
                S.update(peak=max(m[2], S["peak"] - 0.3), f_now=m[3], snr=m[4])
            elif kind == "pitch" and sound:
                sound.push(m[1], m[2])
            elif kind == "comp":
                CP["prof"], CP["realign"], CP["ref"] = m[1], m[2], m[3]
            elif kind == "resp":
                resp["sum"], resp["n"] = m[1], m[2]
            elif kind == "stats":
                S["stats"] = m[1]
            elif kind == "error":
                say(m[1] + " - restarting the receiver in 2 s", "#ef5350")
                QtCore.QTimer.singleShot(2000, restart_rx)

    def refresh():
        drain()
        p, info = st["p"], st["info"]
        rows = max(100, int(0.8 * p_wf.vb.height()))  # fewer rows than pixels: Qt scales up, never drops a row
        if abs(rows - len(V["wf"])) > 0.1 * len(V["wf"]):
            size_waterfall(rows)
        wf = V["wf"]
        floor = float(np.median(wf[-8:]))
        img.setImage(wf[::-1], autoLevels=False, levels=(floor - 3, floor + 65))
        c_hold.setData(V["f_rf"], hold["a"])
        if p.get("comp") and CP["prof"] is not None:
            draw_compression(p, info)
        cover = 0.0
        if resp["n"] is not None:
            with np.errstate(divide="ignore", invalid="ignore"):
                r = 10 * np.log10(resp["sum"] / resp["n"])
            r[resp["n"] == 0] = np.nan
            c_resp.setData(V["f_rf"], r)
            inside = (V["f_rf"] >= V["sw"][0]) & (V["f_rf"] <= V["sw"][1])
            cover = np.count_nonzero(~np.isnan(r[inside])) / max(1, np.count_nonzero(inside))
        up = time.time() - S["t0"]
        x = S["stats"]
        real = x.get("samples", 0) / p["rate"] / max(1e-9, time.time() - x.get("t0", time.time()))
        clip = "  <span style='color:#ef5350'>CLIPPING - lower RX gain</span>" if S["peak"] > -3 else ""
        tx_names = "+".join(f"TX{ch + 1}" for ch in board.tx_on)
        tx = (f"{tx_names} on, {args.tx_atten:g} dB" if board.tx_running else f"<span style='color:#ffca28'>{tx_names} off</span>")
        left = max(0, args.rearm - (time.time() - board.armed_at))
        rearm = ("" if not board.tx_running else
                 f" &nbsp;|&nbsp; bound 1 h, re-arm in {left/60:.0f} min" if board.bound_off else
                 f" &nbsp;|&nbsp; re-arm in {left:.0f} s")
        status.setText(
            f"<b>{(p['rx_lo'] + S['f_now'])/1e6:8.3f} MHz</b> &nbsp;|&nbsp; {p['span']/1e6:g} MHz "
            f"{p['shape']} in {fmt_s(info['seconds'])} at {p['rate']/1e6:g} MS/s ({p['transport']}), "
            f"{fmt_mb(info['mb'])} buffer &nbsp;|&nbsp; {tx}, RX{CH} {args.rx_gain:g} dB, peak {S['peak']:.1f} dBFS{clip}"
            f" &nbsp;|&nbsp; mirror {x.get('mirror_db', float('nan')):.0f} dBc"
            f" &nbsp;|&nbsp; RX {real*100:.1f}% of real time, {x.get('gaps', 0)} gaps &nbsp;|&nbsp; response "
            f"{cover*100:.0f}%{rearm}")
        if up >= S["logged"] + 10:
            S["logged"] = int(up // 10) * 10
            log(f"{S['logged']:4d} s: {'TX on' if board.tx_running else 'TX off'}, chirp at "
                f"{(p['rx_lo'] + S['f_now'])/1e6:.3f} MHz, {S['snr']:.0f} dB over the floor, "
                f"peak {S['peak']:.1f} dBFS, mirror {x.get('mirror_db', float('nan')):.1f} dBc, "
                f"RX {real*100:.1f}% of real time, {x.get('gaps', 0)} gaps")
        if args.frames and up > args.screenshot_at and S.get("nframes", 0) < 60 \
                and time.time() - S.get("last_frame", 0) >= 0.1:
            os.makedirs(args.frames, exist_ok=True)
            top.grab().save(os.path.join(args.frames, f"f{S.get('nframes', 0):03d}.png"))
            S["nframes"] = S.get("nframes", 0) + 1; S["last_frame"] = time.time()
        if args.screenshot and not S["shot"] and up > args.screenshot_at:
            top.grab().save(args.screenshot); S["shot"] = True
            log(f"screenshot saved: {args.screenshot}")
        if args.duration and up > args.duration:
            log(f"--duration {args.duration:g} s reached"); top.close()

    def comp_metrics(prof, rate):
        """Peak position (samples, interpolated), -3 dB width (samples), worst sidelobe (dB)."""
        db = 10 * np.log10(prof / prof.max() + 1e-15)
        n = len(db); i = int(np.argmax(db))
        a, b, c = db[(i - 1) % n], db[i], db[(i + 1) % n]
        den = a - 2 * b + c
        frac = 0.5 * (a - c) / den if den < 0 else 0.0
        # -3 dB width by linear interpolation either side
        def edge(step):
            j = i
            for _ in range(n // 2):
                k = (j + step) % n
                if db[k] < -3:
                    return abs(j - i) + (db[j] + 3) / (db[j] - db[k])
                j = k
            return float("nan")
        width = edge(1) + edge(-1)
        guard = int(max(3, 2.5 * width))
        mask = np.ones(n, bool); mask[[(i + d) % n for d in range(-guard, guard + 1)]] = False
        side = float(db[mask].max()) if mask.any() else float("nan")
        return i + frac, width, side, db

    def draw_compression(p, info):
        rate = p["rate"]
        peak, width, side, db = comp_metrics(CP["prof"], rate)
        pk_us = peak / rate * 1e6
        B, Tp = p["span"], p["period"] * p["duty"]
        # draw only what is visible: a 20 000-point antialiased curve 25 times
        # a second was heavy enough to slow the receiver down
        refp = CP.get("ref")
        if refp is not None:
            # both peaks are drawn against the same scale: dB from the stronger one
            rpeak, _, _, _ = comp_metrics(refp, rate)
            top = max(CP["prof"].max(), refp.max())
            db = 10 * np.log10(CP["prof"] / top + 1e-15)
            db_r = 10 * np.log10(refp / top + 1e-15)
        curves = [(c_comp, db)] + ([(c_ref, db_r)] if refp is not None else [])
        if w_zoom.isChecked():
            half = max(40 / B * 1e6, 3 * width / rate * 1e6)   # +-40 resolution cells
            if refp is not None:                               # keep the reference in view too
                half = max(half, abs(peak - rpeak) / rate * 1e6 + 10 / B * 1e6)
            mid = pk_us if refp is None else (peak + rpeak) / 2 / rate * 1e6
            hs = int(half * 1e-6 * rate) + 2
            k = np.arange(int(mid * 1e-6 * rate) - hs, int(mid * 1e-6 * rate) + hs + 1)
            for cv, d in curves:
                cv.setData(k / rate * 1e6, d[k % len(d)])
            p_comp.setXRange(mid - half, mid + half, padding=0)
        else:
            step = max(1, len(db) // 4000)
            m = len(db) // step * step
            for cv, d in curves:
                cv.setData(np.arange(0, m, step) / rate * 1e6, d[:m].reshape(-1, step).max(axis=1))
            p_comp.setXRange(0, len(db) / rate * 1e6, padding=0)
        lines = [f"peak at {pk_us:.4f} µs in the period",
                 f"width (-3 dB) {width / rate * 1e9:.0f} ns; theory {0.886 / B * 1e9 * (1.47 if w_ham.isChecked() else 1):.0f} ns",
                 f"highest sidelobe {side:.1f} dB",
                 f"compression gain B·T = {10 * math.log10(B * Tp):.1f} dB ({B / 1e6:g} MHz x {Tp * 1e6:g} µs)"]
        if refp is not None:
            P = len(db)
            dd = (peak - rpeak + P / 2) % P - P / 2
            lines.insert(0, f"RX{CH} - RX{3 - CH}: {dd / rate * 1e9:+.2f} ns")
            lines.append(f"lost samples {CP.get('realign', 0)} times, absorbed by the RX{3 - CH} reference")
        else:
            lines.append(f"re-aligned {CP.get('realign', 0)} times (RX{CH} lost samples)")
        if refp is None and CP["zero"] is not None and CP.get("realign", 0) != CP.get("zero_realign"):
            lines.append("zero no longer holds: samples were lost since. Set zero again")
        elif CP["zero"] is not None:
            d_ns = (pk_us - CP["zero"]) * 1e3
            P = info["seconds"] * 1e9
            d_ns = (d_ns + P / 2) % P - P / 2        # the shortest way round the period
            lines.append(f"from zero: {d_ns:+.2f} ns = {d_ns * 1e-9 * 0.66 * 299792458:+.3f} m of coax "
                         f"(0.66 c), or a radar target {d_ns * 1e-9 * 299792458 / 2:+.3f} m further")
        comp_txt.setHtml("<span style='font-size: 9pt'>" + "<br>".join(lines) + "</span>")
        vr = p_comp.vb.viewRange()
        comp_txt.setPos(vr[0][1], vr[1][1])
        CP["peak_us"] = pk_us
        if S.get("comp_logged", 0) + 10 <= time.time() - S["t0"]:
            S["comp_logged"] = time.time() - S["t0"]
            log("compression: " + "; ".join(lines))

    def set_zero():
        if CP.get("peak_us") is None:
            say("no compression peak yet", "#ffca28"); return
        CP["zero"] = CP["peak_us"]
        CP["zero_realign"] = CP.get("realign", 0)
        comp_zero.setValue(CP["zero"])
        if comp_zero not in p_comp.items:
            p_comp.addItem(comp_zero)
        say(f"zero set at {CP['zero']:.4f} µs: add a cable to the loop and read the shift")

    b_zero.clicked.connect(set_zero)

    def rearm_tick():
        try:
            st["session"].maybe_rearm()
        except Exception as e:
            say(f"re-arm failed: {e}", "#ef5350")
        show_tx()

    update_limits(); show_tx(); show_cal()
    if args.calibrate_at:                              # for testing: press Calibrate after N s
        QtCore.QTimer.singleShot(int(args.calibrate_at * 1000), calibrate)
    if args.size:
        top.resize(*map(int, args.size.lower().split("x")))
    top.show() if not args.fullscreen else top.showFullScreen()
    app.processEvents()
    geometry()
    say("transmitting" if board.tx_running else "ready: press Start")
    if board.tx_running and not args.no_autolevel:
        QtCore.QTimer.singleShot(1500, autolevel_start)
    for ms, fn in ((40, refresh), (1000, rearm_tick), (700, autolevel_tick)):
        tm = QtCore.QTimer(); tm.timeout.connect(fn); tm.start(ms); timers.append(tm)
    for key in ("Escape", "Q"):
        QShortcut(QKeySequence(key), top, activated=top.close)

    def shutdown():
        make_safe()
        if sound:
            sound.close()

    app.aboutToQuit.connect(shutdown)
    signal.signal(signal.SIGINT, lambda *_: QtCore.QTimer.singleShot(0, top.close))
    tick = QtCore.QTimer(); tick.timeout.connect(lambda: None); tick.start(200)   # let Python see Ctrl+C
    rc = app.exec()
    drain()
    return rc, resp


def write_response(name, resp, p):
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 10 * np.log10(resp["sum"] / resp["n"])
    f = np.fft.fftshift(np.fft.fftfreq(NFFT, 1 / p["rate"])) + p["rx_lo"]
    ok = resp["n"] > 0
    with open(name, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["frequency_hz", "level_dbfs"])
        w.writerows(zip(f[ok].round(1), r[ok].round(2)))
    return int(ok.sum())


# --- main --------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g_sweep = ap.add_argument_group("the sweep (all can be changed in the window too)")
    g_radio = ap.add_argument_group("the radio")
    g_win = ap.add_argument_group("the window")
    g_head = ap.add_argument_group("without a window")
    g_radio.add_argument("--uri", default="ip:fishball.local", help="the board (default: %(default)s)")
    g_radio.add_argument("--channel", type=int, choices=(1, 2), default=1,
                    help="the pair to use: 1 = TX1 -> pad -> RX1, 2 = TX2 -> pad -> RX2; the other "
                         "transmitter stays muted (default: 1)")
    g_sweep.add_argument("--freq", type=float, default=868e6, help="centre of the sweep in Hz (default: 868e6)")
    g_sweep.add_argument("--rate", type=float, default=20e6,
                    help="sample rate in S/s, shared by TX and RX (default: 20e6, the fastest one receiver can stream live)")
    g_sweep.add_argument("--span", type=float, default=0,
                    help="sweep width in Hz (default: 7e6, or the widest that fits beside DC at a lower --rate)")
    g_sweep.add_argument("--period", type=float, default=0,
                    help="seconds per sweep (default: the longest one 64 MB DMA block holds)")
    g_sweep.add_argument("--shape", choices=[k for k, _ in SHAPES], default="up",
                    help="sweep mode (default: up). up/down: sawtooth; triangle; log: logarithmic up; "
                         "sine: sine FM; steps: a staircase; hops: random hops; pulsed: a chirp, then silence "
                         "(1 ms period, pulse compression shown)")
    g_sweep.add_argument("--steps", type=int, default=8, help="frequencies in the steps and hops modes (default: 8)")
    g_sweep.add_argument("--duty", type=float, default=0.1, help="on-time fraction of the pulsed mode (default: 0.1)")
    g_sweep.add_argument("--taper", type=float, default=0.05,
                    help="against splatter: fade sawtooth and log sweeps at the wrap, smooth the jumps of "
                         "steps and hops, soften the pulse edges, over this fraction (default: 0.05)")
    g_radio.add_argument("--reference", choices=("loops", "split"),
                    help="time pulse compression against the other receiver, so lost samples cannot move "
                         "the range: 'loops' plays the pulse on both transmitters (one per bench loop), "
                         "'split' on this pair's only (a splitter feeds both receivers). Pulsed mode, "
                         "libiio, at most 5.5 MS/s; defaults to 4.8 MS/s and a 1.6 MHz chirp")
    g_radio.add_argument("--calibrate-mirror", action="store_true",
                    help="measure the mirror correction for these settings, save it, and exit (~10 s)")
    g_radio.add_argument("--no-mirror-fix", dest="mirror_fix", action="store_false",
                    help="do not apply a saved mirror calibration")
    g_win.add_argument("--stopped", action="store_true", help="open the window with the transmitter off")
    g_win.add_argument("--no-autolevel", action="store_true", help="keep --rx-gain; do not auto-level at start")
    g_radio.add_argument("--transport", choices=("auto", "zc", "libiio"), default="auto",
                    help="RX path: zc-stream (8-bit, up to 20 MS/s) or libiio; auto picks zc above 6 MS/s")
    g_radio.add_argument("--tx-atten", type=float, default=-40.0, help="TX attenuation in dB, -89.75 to -10 (default: -40)")
    g_radio.add_argument("--rx-gain", type=float, default=20.0, help="RX manual gain in dB (default: 20, then auto level sets it)")
    g_win.add_argument("--volume", type=float, default=0.2, help="the chirp as a whistle, 0 to 1; 0 for silence (default: %(default)g)")
    g_radio.add_argument("--keep-bound", action="store_true",
                    help="keep the firmware's 60 s cyclic bound and re-arm instead (a 1-2 s gap each time)")
    g_radio.add_argument("--rearm", type=float, default=REARM_S, help="seconds between re-arms, under the 60 s bound (default: %(default)g)")
    g_head.add_argument("--check", action="store_true", help="build and check the buffer, touch no board")
    g_head.add_argument("--measure", type=int, metavar="SWEEPS", help="measure this many sweeps, no window")
    g_head.add_argument("--save", nargs="?", const="chirp_response.csv", metavar="CSV",
                    help="write the response curve to CSV on exit (default name: chirp_response.csv)")
    g_win.add_argument("--fullscreen", action="store_true", help="fill the screen; Esc or Q closes")
    g_win.add_argument("--size", help=argparse.SUPPRESS)
    g_win.add_argument("--calibrate-at", type=float, default=0, help=argparse.SUPPRESS)
    g_win.add_argument("--frames", help=argparse.SUPPRESS)  # DIR: 60 frames at 10/s, for the docs clip  # WxH, for checking the layout off-screen
    g_win.add_argument("--duration", type=float, default=0, help="close after this many seconds")
    g_win.add_argument("--screenshot", metavar="PNG", help="save a picture of the window once")
    g_win.add_argument("--screenshot-at", type=float, default=12, help="...this many seconds in (default: 12)")
    args = ap.parse_args()

    if args.tx_atten > -10 or args.tx_atten < MUTED:
        ap.error("--tx-atten must be between -89.75 and -10 dB (a 20 dB pad keeps the receiver safe only up to -10)")
    if not 5 <= args.rearm <= 58:
        ap.error("--rearm must be 5 to 58 s: the firmware mutes a cyclic transmit at 60 s")
    if not 2 <= args.steps <= 64:
        ap.error("--steps must be 2 to 64")
    if not 0.05 <= args.duty <= 0.95:
        ap.error("--duty must be 0.05 to 0.95")
    if not 0 <= args.taper <= 0.5:
        ap.error("--taper must be 0 to 0.5")
    if not 2.1e6 <= args.rate <= 61.44e6:
        ap.error("--rate must be 2.1 to 61.44 MS/s")
    if args.reference:
        if "--rate" not in " ".join(sys.argv):
            args.rate = 4.8e6
        if not args.span:
            args.span = 1.6e6
        if "--shape" not in " ".join(sys.argv):
            args.shape = "pulsed"
        if args.calibrate_mirror:
            ap.error("--calibrate-mirror does not apply with --reference")
    try:
        p = plan(args)
    except ValueError as e:
        ap.error(str(e))
    if p["transport"] == "libiio" and p["rate"] > 10e6:
        ap.error("libiio carries about 10 MS/s at most; use --transport zc above that")
    if p["transport"] == "zc" and p["rate"] > 20e6:
        log(f"warning: zc-stream sustains about 20 MS/s; at {p['rate']/1e6:g} MS/s expect gaps")
    if args.check:
        return check(args, p)

    iq, info = build_chirp(p["rate"], p["span"], p["period"], p["offset"], shape=p["shape"], taper=p["taper"], steps=p["steps"], duty=p["duty"],
                           cal=cal_load(p, args) if args.mirror_fix else None)
    p["period_built"] = info["seconds"]
    log(f"chirp: {p['span']/1e6:g} MHz in {info['seconds']:.3f} s around {args.freq/1e6:.3f} MHz, "
        f"{p['rate']/1e6:g} MS/s, {info['samples']} samples, {info['mb']:.1f} MB")

    board = Board(args, p)
    board.configure()
    if not args.keep_bound:
        board.bound_off = board.lift_cyclic_bound()
    if args.calibrate_mirror:
        try:
            f = cal_points(p)
            a, before, after = board.calibrate_mirror(f, progress=log)
            cal_save(p, args, f, a, before, after)
            print(f"{'offset':>12} {'before':>9} {'after':>9}   alpha")
            for fb, b, x, al in zip(f, before, after, a):
                print(f"{fb/1e6:9.3f} MHz {10*math.log10(b):7.1f} dBc {10*math.log10(x):7.1f} dBc   {al:.2e}")
            print(f"saved to {CAL_FILE}")
            return 0
        finally:
            board.close()
    st = {"board": board, "p": p, "iq": iq, "info": info, "session": None}
    resp, rc = None, 1
    try:
        if not (args.stopped and not args.measure):
            board.start_tx(iq)
        st["session"] = Session(args, p, board, iq)
        if args.measure:
            rc = measure(args, p, info, st["session"])
        else:
            rc, resp = run_window(args, st)
    except KeyboardInterrupt:
        rc = 130
    finally:
        board.close()                                 # mute, confirm, then tear down
        if st["session"]:
            st["session"].close()
        if args.save and resp and resp["n"] is not None:
            n = write_response(args.save, resp, st["p"])
            log(f"response curve: {n} points written to {args.save}")
    return rc


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush(); sys.stderr.flush()
    # Everything that matters (mute, restore the bound, save) is done by now.
    # Leave without Python's teardown: Qt and pyqtgraph objects destroyed in
    # the wrong order at interpreter exit can crash, which is noise, not a fault.
    os._exit(rc or 0)
