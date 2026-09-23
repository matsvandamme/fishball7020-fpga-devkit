#!/usr/bin/env python3
"""Every CW feature on both receivers, with the geometry fixed.

The previous attempt put the upper 1 MHz sideband at +3.6 MHz in a receiver
running 8 MSPS behind a filter set to 4 MHz - on the skirt, near Nyquist, and
therefore attenuated by an unknown amount. Here the rate is 12.288 MSPS and the
receive filter 10 MHz, so every feature listed sits comfortably inside both.

Caveat that this cannot escape: the board's TX and RX oscillators are
synthesised from one 40 MHz reference, so a phase perturbation OF THAT REFERENCE
appears on both and partly cancels here - by 20*log10(866.5/2.0) = 52.7 dB at
this 2 MHz separation. A feature missing from the board's receiver is therefore
either absent from the transmitter, or reference-borne. It cannot tell the two
apart, and with no receive antenna on the board there is no third path that can.
"""
import os, json, subprocess, sys, numpy as np, board as B, dsp
from iiod_min import mask_for

HOST = os.environ.get("BOARD", "192.168.2.1")
TXLO, BRX, HRX, CH = 866_500_000, 864_500_000, 871_300_000, 1
RATE = 12_288_000

b = B.Board(HOST)
try:
    b.mute()
    b.wr(B.PHY, "voltage0", "sampling_frequency", RATE)
    b.wr(B.PHY, "voltage0", "rf_bandwidth", 10_000_000)          # receive filter
    b.wr(B.PHY, "voltage0", "rf_bandwidth", 10_000_000, out=True)  # transmit filter
    b.wr(B.PHY, "altvoltage1", "frequency", TXLO, out=True)
    b.wr(B.PHY, "altvoltage1", "powerdown", 0, out=True)
    fs = float(b.rd(B.RX, "voltage0", "sampling_frequency"))
    nb = 4096; k = round(600e3 * nb / fs); T = k * fs / nb
    b.transmit(np.exp(2j * np.pi * k * np.arange(nb) / nb), -16, pair=CH, cyclic=True, scale=0.9)

    b.wr(B.PHY, "altvoltage0", "frequency", BRX, out=True)
    b.wr(B.PHY, "altvoltage0", "powerdown", 0, out=True)
    b.wr(B.PHY, "voltage0", "gain_control_mode", "manual")
    b.wr(B.PHY, "voltage0", "hardwaregain", 8)
    did, nch = b.dev[B.RX]
    a = np.array(b.c.read_samples(did, 1 << 19, mask_for([2, 3], nch), nchannels=2), dtype=float)
    xb = (a[0::2] + 1j * a[1::2]) / 2048.0
    clb = 100 * float(np.mean(np.abs(xb.real) > 0.98) + np.mean(np.abs(xb.imag) > 0.98))
    fb, pb, _ = dsp.hi_dr_psd(xb, fs, nfft=1 << 16)

    subprocess.run([sys.executable, "hackrf_cap.py", "--freq", str(HRX), "--rate", "16e6",
                    "--n", str(1 << 21), "--out", "/tmp/a2.cf32", "--lna", "16", "--vga", "16",
                    "--bw", "12e6"], check=True, capture_output=True)
    xh = np.fromfile("/tmp/a2.cf32", dtype=np.complex64)
    clh = 100 * float(np.mean(np.abs(xh.real) > 0.985) + np.mean(np.abs(xh.imag) > 0.985))
    fh, ph, _ = dsp.hi_dr_psd(xh, 16e6, nfft=1 << 16)

    def lv(f, p, at, w=45e3):
        return float(p[np.abs(f - at) < w].max())
    cb, ch = lv(fb, pb, TXLO + T - BRX), lv(fh, ph, TXLO + T - HRX)
    flb = float(np.median(pb[np.abs(fb - (TXLO + T - BRX)) > 1.5e6]))
    flh = float(np.median(ph[np.abs(fh - (TXLO + T - HRX)) > 1.5e6]))
    print(f"  rate {fs/1e6:.3f} MSPS, tone {T/1e3:.1f} kHz, clipping {clb:.3f}/{clh:.3f} %")
    print(f"  carrier: board {cb:.1f} dBFS (floor {flb:.1f}, so {cb-flb:.0f} dB of range), "
          f"HackRF {ch:.1f} dBFS ({ch-flh:.0f} dB)\n")
    rows = []
    print(f"  {'feature':<30} {'TX-LO rel':>11} {'board':>8} {'HackRF':>8} {'diff':>7}")
    for name, rel in (("carrier feedthrough (TX LO)", 0.0), ("I/Q image", -T),
                      ("2nd harmonic of the tone", -2 * T), ("3rd harmonic of the tone", -3 * T),
                      ("tone - 1.000 MHz", T - 1e6), ("tone + 1.000 MHz", T + 1e6)):
        vb = lv(fb, pb, TXLO + rel - BRX) - cb
        vh = lv(fh, ph, TXLO + rel - HRX) - ch
        rows.append(dict(name=name, rel_hz=rel, board_dbc=vb, hackrf_dbc=vh))
        print(f"  {name:<30} {rel/1e3:+10.1f}k {vb:8.1f} {vh:8.1f} {vh-vb:+7.1f}")
    print(f"\n  board's noise floor sits at {flb-cb:.1f} dBc, HackRF's at {flh-ch:.1f} dBc")
    json.dump(dict(rows=rows, board_floor_dbc=flb - cb, hackrf_floor_dbc=flh - ch,
                   tone_hz=T, rate_hz=fs, comb_board_dbc=-68.0),
              open("results/atlas.json", "w"), indent=1)
finally:
    print("\n  stop:", b.stop()); b.close()
