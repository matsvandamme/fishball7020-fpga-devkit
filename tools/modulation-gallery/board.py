#!/usr/bin/env python3
"""Transmit an arbitrary complex waveform from the Fishball7020, safely.

Uses the devkit's own stdlib IIOD client. The rules encoded here are the ones
that are expensive to rediscover:

  * TX attenuation is set AFTER the buffer starts and then READ BACK. Firmware
    patch 0005 restores a cached attenuation when a stream starts on a chip that
    looks muted, so anything written before OPEN is not what is on the air.
  * Channel numbering: on cf-ad9361-dds-core-lpc, voltage0/1 are TX1's I/Q and
    voltage2/3 are TX2's. On ad9361-phy the OUTPUT voltage0/voltage1 are the two
    transmit attenuators. Two different meanings for "channel 1".
  * Full scale is +-32767. The receive side is 12-bit (+-2047); mixing the two
    up is a 24.09 dB error.
  * stop() mutes first and closes the buffer second, then verifies. A cyclic
    buffer keeps playing after the process that created it exits, so closing
    without muting can leave the transmitter live.
"""
import sys, math, pathlib
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "selftest"))
from iiod_min import Iiod, mask_for                                    # noqa: E402
import sys as _s, pathlib as _pl                     # noqa: E402
_s.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
from board_addr import resolve as _board             # name first, USB last

PHY, TX, RX = "ad9361-phy", "cf-ad9361-dds-core-lpc", "cf-ad9361-lpc"
TX_LO = "altvoltage1"
MUTE = -89.75
FULLSCALE = 32767


class Board:
    def __init__(self, host):
        self.c = Iiod(host=host); self.c.connect()
        self.dev = self.c.devices()          # {name: (device_id, n_scan_channels)}
        for need in (PHY, TX):
            if need not in self.dev:
                raise SystemExit(f"device {need} not found on {host}")

    # attributes --------------------------------------------------------------
    def rd(self, dev, ch, attr, out=False):
        return self.c.read(self.dev[dev][0], ch, attr, output=out)

    def wr(self, dev, ch, attr, val, out=False):
        return self.c.write(self.dev[dev][0], ch, attr, str(val), output=out)

    # setup -------------------------------------------------------------------
    def configure_tx(self, lo_hz, fs, bw=None):
        self.mute()
        self.wr(PHY, "voltage0", "sampling_frequency", int(fs))
        self.wr(PHY, "voltage0", "rf_bandwidth", int(bw or fs * 0.8))
        self.wr(PHY, TX_LO, "frequency", int(lo_hz), out=True)
        self.wr(PHY, TX_LO, "powerdown", 0, out=True)
        return dict(fs=float(self.rd(PHY, "voltage0", "sampling_frequency")),
                    bw=float(self.rd(PHY, "voltage0", "rf_bandwidth")),
                    lo=float(self.rd(PHY, TX_LO, "frequency", out=True)))

    def mute(self):
        for v in ("voltage0", "voltage1"):
            try: self.wr(PHY, v, "hardwaregain", MUTE, out=True)
            except Exception: pass

    # transmit ----------------------------------------------------------------
    def transmit(self, iq, atten_db, pair=0, cyclic=True, scale=1.0):
        """Start a cyclic buffer, then set and verify the attenuation."""
        if np.abs(iq).max() > 1.0 + 1e-9:
            raise ValueError("iq must be normalised to |x| <= 1 before scaling")
        s = (iq * scale * FULLSCALE)
        i = np.clip(np.round(s.real), -FULLSCALE, FULLSCALE).astype(np.int16)
        q = np.clip(np.round(s.imag), -FULLSCALE, FULLSCALE).astype(np.int16)
        values = np.empty(2 * len(iq), dtype=np.int16)
        values[0::2], values[1::2] = i, q

        did, total = self.dev[TX]
        self.c.close_buffer(did)
        first = pair * 2
        self.c.write_samples(did, values.tolist(),
                             mask_for([first, first + 1], total),
                             nchannels=2, cyclic=cyclic)
        # AFTER the buffer: patch 0005 would otherwise restore a cached value.
        v = f"voltage{pair}"
        self.wr(PHY, v, "hardwaregain", round(atten_db, 2), out=True)
        got = float(self.rd(PHY, v, "hardwaregain", out=True).split()[0])
        if abs(got - atten_db) > 0.3:
            self.stop()
            raise RuntimeError(f"attenuation read back {got} dB, asked {atten_db} dB")
        return got

    def stop(self):
        """Mute first, then close. Order matters."""
        self.mute()
        self.c.close_buffer(self.dev[TX][0])
        self.mute()
        try: self.wr(PHY, TX_LO, "powerdown", 1, out=True)
        except Exception: pass
        return {v: self.rd(PHY, v, "hardwaregain", out=True) for v in ("voltage0", "voltage1")}

    def close(self):
        self.c.close()


if __name__ == "__main__":
    import os
    b = Board(sys.argv[1] if len(sys.argv) > 1 else _board())
    print("devices:", {k: v for k, v in b.dev.items()})
    print("TX atten:", b.rd(PHY, "voltage0", "hardwaregain", out=True),
          "/", b.rd(PHY, "voltage1", "hardwaregain", out=True))
    print("TX LO:", b.rd(PHY, TX_LO, "frequency", out=True),
          "powerdown:", b.rd(PHY, TX_LO, "powerdown", out=True))
    print("fs:", b.rd(PHY, "voltage0", "sampling_frequency"))
    b.close()
