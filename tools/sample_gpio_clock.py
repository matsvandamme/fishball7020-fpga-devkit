#!/usr/bin/env python3
"""Drive the four sample-locked GPIO pins from an authored transmit waveform.

    # run from: the repo root, on your HOST (not the board)
    pip install pyadi-iio numpy
    ./tools/sample_gpio_clock.py                      # safe: transmitter muted
    ./tools/sample_gpio_clock.py --tx-gain -40        # ...into a terminated load

This is the complete, runnable version of the example in docs/tx-gpio-bitmap.md. It
connects to the board, turns the feature on, authors a pattern into the low
nibble of each transmit sample, and streams it in a loop.

WHAT COMES OUT OF THE PINS
  sample_gpio[0]  JP5 pin 7   square wave at half the sample rate
  sample_gpio[1]  JP5 pin 9   one-sample marker every FRAME samples
  sample_gpio[2]  JP5 pin 11  held low
  sample_gpio[3]  JP5 pin 13  held high, so you can see which end is which
Ground your probe on JP5 pin 2 or 20.

SAFETY
The transmitter defaults to maximum attenuation (-89.75 dB), which is
effectively silent - the pins work regardless, because the nibble never
reaches the DAC. Raise --tx-gain only into a terminated load or an
attenuated loopback. The receive port survives +2.5 dBm and this board can
reach about +19 dBm; never transmit at power into an open connector.
"""
import argparse
import sys, pathlib as _pl
sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from board_addr import uri as _board_uri            # noqa: E402

import numpy as np

try:
    import adi
    import iio
except ImportError:
    sys.exit("needs pyadi-iio: pip install pyadi-iio numpy")

DAC_NAME = "cf-ad9361-dds-core-lpc"      # the DAC core that owns the flag


def set_feature(uri, on):
    """Turn the sample-GPIO bit-map on or off.

    pyadi-iio exposes the radio, not this attribute, so go through libiio
    directly. tx_sample_gpio_en is added by firmware patch 0007; it
    read-modify-writes bit 1 of the DAC core's GP_CONTROL register.
    """
    dac = iio.Context(uri).find_device(DAC_NAME)
    if dac is None:
        sys.exit(f"no {DAC_NAME} on {uri} - is this the devkit firmware?")
    if "tx_sample_gpio_en" not in dac.attrs:
        sys.exit("firmware has no tx_sample_gpio_en: flash a build that "
                 "includes patch 0007 (v1.3 or later)")
    dac.attrs["tx_sample_gpio_en"].value = "1" if on else "0"
    return dac.attrs["tx_sample_gpio_en"].value


def build(n_samples, frame, amplitude):
    """A carrier in the top 12 bits, a pattern in the bottom 4."""
    n = np.arange(n_samples)

    # The signal. Anything you like - here one cycle of a sine per 64 samples.
    phase = 2 * np.pi * n / 64.0
    i16 = (amplitude * np.cos(phase)).astype(np.int16)
    q16 = (amplitude * np.sin(phase)).astype(np.int16)

    # The pattern. One bit per pin, assembled into the low nibble.
    bit0 = (n % 2 == 0)                      # half the sample rate
    bit1 = (n % frame == 0)                  # one sample every `frame`
    bit2 = np.zeros(n_samples, dtype=bool)   # held low
    bit3 = np.ones(n_samples, dtype=bool)    # held high
    nibble = (bit0 | (bit1 << 1) | (bit2 << 2) | (bit3 << 3)).astype(np.int16)

    # OR it in LAST. Any scaling applied after this would overwrite the
    # bottom bits, because to that code they are noise.
    i16 = (i16 & ~np.int16(0x000F)) | nibble
    return i16, q16


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--uri", default=None,
                   help="libiio URI (default: the board, found by name)")
    p.add_argument("--rate", type=float, default=30.72e6, help="samples/s")
    p.add_argument("--lo", type=float, default=2.4e9, help="TX centre, Hz")
    p.add_argument("--tx-gain", type=float, default=-89.75,
                   help="TX hardwaregain in dB, negative is attenuation. "
                        "The default is silent.")
    p.add_argument("--samples", type=int, default=16384, help="buffer length")
    p.add_argument("--frame", type=int, default=64,
                   help="marker period on sample_gpio[1], in samples")
    p.add_argument("--amplitude", type=int, default=2 ** 13)
    p.add_argument("--off", action="store_true",
                   help="hand the pins back to Linux and exit")
    a = p.parse_args()
    # Resolved only if not given, so --help and a supplied --uri cost nothing.
    a.uri = a.uri or _board_uri()

    if a.off:
        print(f"tx_sample_gpio_en = {set_feature(a.uri, False)}")
        return 0

    sdr = adi.ad9361(uri=a.uri)
    sdr.tx_enabled_channels = [0]
    sdr.sample_rate = int(a.rate)
    sdr.tx_lo = int(a.lo)
    sdr.tx_hardwaregain_chan0 = a.tx_gain
    sdr.tx_cyclic_buffer = True              # loop it, for a continuous clock

    i16, q16 = build(a.samples, a.frame, a.amplitude)
    print(f"tx_sample_gpio_en = {set_feature(a.uri, True)}")

    # pyadi-iio takes complex samples and casts real/imag to int16, so
    # integer-valued input reaches the DAC bit for bit.
    sdr.tx(i16.astype(np.complex128) + 1j * q16.astype(np.complex128))

    # Setting the gain AFTER the buffer starts is deliberate: the TX mute in
    # patch 0004 unmutes on buffer start, and 0005 makes it keep a gain you
    # set first. Re-asserting here works whichever order the driver took.
    sdr.tx_hardwaregain_chan0 = a.tx_gain

    rate = sdr.sample_rate
    print(f"streaming {a.samples} samples, cyclic, at {rate/1e6:.6g} MSPS")
    print(f"  TX attenuation now {sdr.tx_hardwaregain_chan0} dB")
    print(f"  sample_gpio[0] (JP5 pin 7)  square wave at {rate/2/1e6:.6g} MHz")
    print(f"  sample_gpio[1] (JP5 pin 9)  marker every {a.frame} samples "
          f"= {rate/a.frame/1e3:.4g} kHz")
    print("  sample_gpio[2] (JP5 pin 11) low     "
          "sample_gpio[3] (JP5 pin 13) high")
    print("\nGround your probe on JP5 pin 2 or 20. Ctrl-C to stop.")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        sdr.tx_destroy_buffer()
        sdr.tx_hardwaregain_chan0 = -89.75
        print(f"tx_sample_gpio_en = {set_feature(a.uri, False)}, "
              "transmitter muted")
    return 0


if __name__ == "__main__":
    sys.exit(main())
