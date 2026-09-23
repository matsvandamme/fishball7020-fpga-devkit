#!/usr/bin/env python3
"""Capture a fixed number of complex samples from the HackRF to a .cf32 file.

Headless GNU Radio + SoapySDR. The first `skip` samples are thrown away because
the HackRF's front end and its filter need a moment to settle, and a capture that
starts at sample 0 begins with a transient that looks exactly like a modulation
artefact.
"""
import sys, argparse
from gnuradio import gr, blocks, soapy


class Cap(gr.top_block):
    def __init__(self, freq, rate, n, out, lna=24, vga=20, amp=0, bw=None, skip=None):
        gr.top_block.__init__(self, "cap")
        bw = bw or rate * 0.75
        skip = int(rate * 0.05) if skip is None else skip   # 50 ms of settling
        src = soapy.source('driver=hackrf', "fc32", 1, '', '', [''], [''])
        src.set_sample_rate(0, rate)
        src.set_frequency(0, freq)
        src.set_bandwidth(0, bw)
        src.set_gain(0, 'LNA', lna)
        src.set_gain(0, 'AMP', amp)
        src.set_gain(0, 'VGA', vga)
        self.connect(src, blocks.skiphead(gr.sizeof_gr_complex, skip),
                     blocks.head(gr.sizeof_gr_complex, n),
                     blocks.file_sink(gr.sizeof_gr_complex, out, False))


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--freq", type=float, required=True)
    a.add_argument("--rate", type=float, required=True)
    a.add_argument("--n", type=int, default=1 << 20)
    a.add_argument("--out", required=True)
    a.add_argument("--lna", type=int, default=24)
    a.add_argument("--vga", type=int, default=20)
    a.add_argument("--amp", type=int, default=0)
    a.add_argument("--bw", type=float, default=None)
    g = a.parse_args()
    tb = Cap(g.freq, g.rate, g.n, g.out, g.lna, g.vga, g.amp, g.bw)
    tb.start(); tb.wait()
    print(f"captured {g.n} samples @ {g.rate/1e6:.3f} MSPS, {g.freq/1e6:.4f} MHz -> {g.out}",
          file=sys.stderr)
