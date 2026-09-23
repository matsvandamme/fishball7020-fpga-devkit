#!/usr/bin/env python3
"""Transmit each waveform from the Fishball7020 and measure it on a HackRF One.

Board: TX2A (the port with the antenna), LO 866.5 MHz, 4 MSPS, cyclic DMA buffer.
HackRF: 16 MSPS, 12 MHz analog filter, tuned 3.5 MHz BELOW the board so its own
DC spike lands in the digital filter's stopband instead of on the signal.

A muted reference is captured first and every level is reported against it in
absolute dBFS, because a normalised spectrum makes silence look like structure.
"""
import os, subprocess, sys, json, time, numpy as np
import board as B, chain, dsp, rx, waveforms as W

HOST  = os.environ.get("BOARD", "192.168.2.1")
BLO   = 866_500_000
ATTEN = -16.0
SCALE = 0.9
CH    = 1
LNA, VGA = 24, 24
NCAP  = 1 << 21
OUT   = "results"
os.makedirs(OUT, exist_ok=True)


def capture(n=NCAP, tag="x"):
    f = f"/tmp/cap_{tag}.cf32"
    subprocess.run([sys.executable, "hackrf_cap.py",
                    "--freq", str(BLO - chain.OFFSET), "--rate", str(chain.HACK_FS),
                    "--n", str(n), "--out", f, "--lna", str(LNA), "--vga", str(VGA),
                    "--bw", str(chain.HACK_BW)], check=True, capture_output=True)
    return np.fromfile(f, dtype=np.complex64)


b = B.Board(HOST)
summary = []
try:
    cfg = b.configure_tx(BLO, W.FS, bw=4_000_000)
    print(f"board: LO {cfg['lo']/1e6:.4f} MHz  fs {cfg['fs']/1e6:.3f} MSPS  "
          f"rf_bw {cfg['bw']/1e6:.3f} MHz")
    print(f"hackrf: {chain.HACK_FS/1e6:.0f} MSPS  analog {chain.HACK_BW/1e6:.0f} MHz  "
          f"tuned {(BLO-chain.OFFSET)/1e6:.4f} MHz  LNA{LNA} VGA{VGA}")
    print(f"link: TX2A at {ATTEN:.1f} dB attenuation, DAC scale {SCALE}\n")

    print("capturing the muted reference ...")
    raw0 = capture(tag="mute")
    y0, fsw = chain.receive(raw0)
    f0, p0, nseg = dsp.hi_dr_psd(y0, fsw, nfft=32768)
    floor_db = float(np.median(p0[np.abs(f0) < 1.8e6]))
    np.savez_compressed(f"{OUT}/_muted.npz", f=f0, p=p0, iq=y0[:1 << 18], fs=fsw)
    print(f"  muted floor {floor_db:.1f} dBFS/bin over {nseg} averages\n")

    print(f"  {'waveform':17s} {'tier':9s} {'rms dBFS':>9} {'pk dBFS':>8} {'clip%':>6} "
          f"{'PAPR':>6} {'occBW MHz':>10} {'CFO Hz':>9} {'EVM':>8}")
    for name, tier, fn in W.SET:
        x, meta = fn()
        b.transmit(x, ATTEN, pair=CH, cyclic=True, scale=SCALE)
        time.sleep(0.25)
        raw = capture(tag=meta["kind"])
        clip = 100 * float(np.mean(np.abs(raw.real) > 0.985) + np.mean(np.abs(raw.imag) > 0.985))
        y, fsw = chain.receive(raw)
        f, p, nseg = dsp.hi_dr_psd(y, fsw, nfft=32768)
        fd, pd = dsp.psd_density(y, fsw, nfft=8192)
        rms = 10 * np.log10(float((np.abs(y) ** 2).mean()) + 1e-30)
        pkd = 20 * np.log10(float(np.abs(y).max()) + 1e-30)
        obw = dsp.occupied_bw(fd, pd) / 1e6
        papr = dsp.papr_db(y)

        res = dict(name=name, tier=tier, kind=meta["kind"], rms_dbfs=rms, peak_dbfs=pkd,
                   clip_pct=clip, papr_db=float(papr), occ_bw_mhz=float(obw),
                   floor_dbfs=floor_db, nseg=int(nseg))
        ev = ""
        try:
            if meta["kind"] in ("bpsk", "qpsk", "qam16", "qam64"):
                m = rx.measure_linear(y[:1 << 17], meta, fsw, W.FS, x)
                res.update(cfo_hz=m["cfo_hz"], evm_pct=m["evm_pct"],
                           evm_eq_pct=m["evm_eq_pct"], evm_wl_pct=m["evm_wl"],
                           image_rej_db=m["image_rej_db"], timing_mu=m["timing_mu"],
                           cfo_resid_hz=m["cfo_resid_hz"])
                np.savez_compressed(f"{OUT}/{meta['kind']}_sym.npz",
                                    syms=m["syms"], ref=m["ref"], syms_eq=m["syms_eq"],
                                    ref_eq=m["ref_eq"])
                ev = f"{m['evm_pct']:.2f}%"
            elif meta["kind"] == "css":
                m = rx.measure_css(y, meta, fsw, W.FS, x)
                np.savez_compressed(f"{OUT}/css_sym.npz", got=m["got"], want=m["want"])
                res.update(cfo_hz=m["cfo_hz"], css_errors=m["errors"],
                           css_nsym=m["nsym"], css_ser=m["ser"],
                           css_peak_median_db=m["peak_to_median_db"])
                ev = f"{m['errors']}/{m['nsym']} err"
            elif meta["kind"] == "ofdm":
                m = rx.measure_ofdm(y[:1 << 17], meta, fsw, W.FS, x)
                res.update(cfo_hz=m["cfo_hz"], evm_pct=m["evm_pct"])
                np.savez_compressed(f"{OUT}/ofdm_sym.npz", syms=m["syms"], ref=m["ref"],
                                    per_carrier=m["per_carrier_evm"], idx=m["idx"],
                                    H=m["H"])
                ev = f"{m['evm_pct']:.2f}%"
        except Exception as e:
            res["error"] = str(e)[:90]
            ev = "err"
        np.savez_compressed(f"{OUT}/{meta['kind']}.npz", f=f, p=p, fd=fd, pd=pd,
                            iq=y[:1 << 19], fs=fsw, ref=x[:1 << 16], fs_tx=W.FS)
        if meta["kind"] == "cw":
            yy = y.astype(np.complex128)
            fq, pq = dsp.psd_tone(yy, fsw, nfft=1 << 16)
            ftone = fq[np.argmax(pq)]
            nn = np.arange(len(yy))
            for st in (100., 10., 1., 0.1):
                cand = np.arange(ftone - 10 * st, ftone + 10 * st + st, st)
                ftone = cand[int(np.argmax([abs(np.sum(yy * np.exp(-2j * np.pi * c * nn / fsw)))
                                            for c in cand]))]
            yd = yy * np.exp(-2j * np.pi * ftone * nn / fsw)
            ph = np.unwrap(np.angle(yd)); ph = ph - np.polyval(np.polyfit(nn, ph, 1), nn)
            am = np.abs(yd) / np.abs(yd).mean()
            res.update(link_phase_rms_deg=float(np.degrees(ph.std())),
                       link_amp_rms_pct=float(100 * am.std()),
                       link_evm_equiv_pct=float(100 * np.sqrt(ph.std() ** 2 + am.std() ** 2)))
            np.savez_compressed(f"{OUT}/cw_phase.npz", ph=ph.astype(np.float32),
                                am=am.astype(np.float32), fs=fsw)
        summary.append(res)
        print(f"  {name:17s} {tier:9s} {rms:9.1f} {pkd:8.1f} {clip:6.2f} {papr:6.2f} "
              f"{obw:10.3f} {res.get('cfo_hz', float('nan')):9.0f} {ev:>8}")
        b.stop()
finally:
    print("\nstopping:", b.stop()); b.close()

json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=1)
print(f"\nwrote {OUT}/summary.json")
