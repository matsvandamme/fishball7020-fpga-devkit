#!/usr/bin/env python3
"""Transmit a CW tone from the HackRF, so the board can listen to IT for once."""
import sys, argparse, numpy as np
from gnuradio import gr, blocks, soapy

class Tx(gr.top_block):
    def __init__(self, freq, rate, tone, secs, vga=20, amp=0, amp_scale=0.5):
        gr.top_block.__init__(self, "tx")
        n = int(rate * secs)
        k = round(tone * 4096 / rate)
        buf = (amp_scale * np.exp(2j * np.pi * k * np.arange(4096) / 4096)).astype(np.complex64)
        src = blocks.vector_source_c(buf.tolist(), True)
        snk = soapy.sink('driver=hackrf', "fc32", 1, '', '', [''], [''])
        snk.set_sample_rate(0, rate)
        snk.set_frequency(0, freq)
        snk.set_bandwidth(0, rate * 0.75)
        snk.set_gain(0, 'VGA', vga)
        snk.set_gain(0, 'AMP', amp)
        self.connect(src, blocks.head(gr.sizeof_gr_complex, n), snk)

if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--freq", type=float, required=True)
    a.add_argument("--rate", type=float, default=8e6)
    a.add_argument("--tone", type=float, default=1e6)
    a.add_argument("--secs", type=float, default=4.0)
    a.add_argument("--vga", type=int, default=20)
    a.add_argument("--amp", type=int, default=0)
    g = a.parse_args()
    tb = Tx(g.freq, g.rate, g.tone, g.secs, g.vga, g.amp)
    tb.start(); tb.wait()
    print("hackrf tx done", file=sys.stderr)
