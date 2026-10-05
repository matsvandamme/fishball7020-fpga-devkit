#!/usr/bin/env python3
"""Drive the four sample-locked GPIO pins from an authored transmit waveform.

    # run from: the repo root, on your HOST (not the board)
    python3 -m venv .venv && .venv/bin/pip install pyadi-iio numpy
    .venv/bin/python tools/sample_gpio_clock.py                 # safe: transmitter muted
    .venv/bin/python tools/sample_gpio_clock.py --tx-gain -40   # ...into a terminated load

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
The transmitter defaults to maximum attenuation (-89.75 dB) and the nibble never
reaches the DAC, so the pins work whatever the gain. That is NOT the same as "this
run transmits nothing": streaming needs a TX buffer, and enabling one can itself
raise an attenuator, because the kernel restores a cached gain from the last stream
when it unmutes - measured at -61.5 dB on a board reading -89.75. So every run,
including the default, checks both attenuators immediately after the enable and
aborts muted if either moved.

Any --tx-gain louder than that goes through the transmit gate and is REFUSED
unless someone has looked at the port and said so:

    ./devkit tx-guard affirm 0        # only after checking TX1A is terminated

That affirmation lives in the board's /tmp, so a reboot withdraws it. It is not
a detector: this board has no coupler and no detector on the transmit port, so
whether an antenna is attached cannot be measured by any means. A human's word
is the only evidence there is. The receive port survives +2.5 dBm and this board
can reach about +19 dBm; never transmit at power into an open connector.
"""
import argparse
import os
import subprocess
import sys, pathlib as _pl
import pathlib
sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from board_addr import uri as _board_uri            # noqa: E402
from tx_gate import (gated_set_atten, require_affirmation,       # noqa: E402
                     assert_quiet_after_enable, TxGateError, MUTE_DB)

import numpy as np

try:
    import adi
    import iio
except ImportError:
    sys.exit("needs pyadi-iio, in a venv: python3 -m venv .venv && .venv/bin/pip install pyadi-iio numpy, "
             "then run this with .venv/bin/python")

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


def _cyclic_bound_ms(uri):
    """How long this board lets an unattended CYCLIC transmit run, in ms.

    0 means unbounded; None means it could not be read - an unpatched kernel, or
    no ssh to the board. Read over ssh rather than libiio because the attribute
    lives on the DMA device whose buffer this tool is holding.

    Host resolution follows the SAME rule as ./devkit: the ssh alias when one is
    configured, because that carries the user and the key, otherwise root@ the
    address board_addr.py resolves. Inventing a third rule here is how a tool ends
    up talking to a different board than the gate does.
    """
    alias = os.environ.get("FISHBALL_SSH_ALIAS", "fishball")
    target = None
    try:
        cfg = pathlib.Path.home() / ".ssh" / "config"
        if cfg.is_file():
            for line in cfg.read_text(errors="replace").splitlines():
                if line.strip().lower() == f"host {alias}".lower():
                    target = alias
                    break
    except Exception:                                     # noqa: BLE001
        pass
    if target is None:
        try:
            target = "root@" + _board_uri().split(":", 1)[1]
        except Exception:                                 # noqa: BLE001
            return None
    try:
        out = subprocess.run(
            ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", target,
             "cat /sys/bus/iio/devices/iio:device2/tx_cyclic_timeout_ms"],
            capture_output=True, text=True, timeout=15)
    except Exception:                                     # noqa: BLE001
        return None
    if out.returncode != 0:
        return None
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


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
    # MUTED before the buffer, always - never a.tx_gain. A write here is an
    # ungated raise, and patch 0005 would restore it from the cache on the next
    # buffer enable anyway. The requested gain is applied AFTER the buffer starts,
    # through the gate, below.
    sdr.tx_hardwaregain_chan0 = MUTE_DB
    sdr.tx_cyclic_buffer = True              # loop it, for a continuous clock

    i16, q16 = build(a.samples, a.frame, a.amplitude)

    # Ask the gate BEFORE the buffer exists. Opening a TX DMA buffer is itself a
    # raise: the kernel's preenable hook powers the TX LO up and restores a
    # cached attenuation from the last stream - measured at -61.5 dB on a board
    # reading -89.75. Gating only our own attenuation write let the transmitter
    # sit at that cached gain for the ~0.8 s the gate takes to answer.
    if a.tx_gain > MUTE_DB:
        try:
            require_affirmation(0)
        except TxGateError as exc:
            print(f"\n{exc}\n", file=sys.stderr)
            print("continuing MUTED, and WITHOUT opening a transmit buffer. The "
                  "sample-GPIO pins need one, so they are not running either - "
                  "rerun without --tx-gain for the pins alone.", file=sys.stderr)
            return 1

    print(f"tx_sample_gpio_en = {set_feature(a.uri, True)}")

    try:
        # THE ENABLE IS INSIDE THE try. sdr.tx() is what creates and enables the cyclic
        # TX DMA buffer, and the kernel's preenable hook can restore a cached
        # attenuation on it - measured at -61.5 dB on a board idling at -89.75. It used
        # to sit one line ABOVE the try, under a comment claiming "the buffer is live
        # from here", which was false by exactly one statement: if sdr.tx() raised
        # after the enable (EBUSY from a stale DMA, Ctrl-C landing in the ioctl) the
        # port radiated at the cached gain with no mute, no post-enable check, and no
        # teardown - and the eventual destroy cached THAT gain for the next program.
        #
        # Everything below runs inside the try/finally that mutes and tears down,
        # because a CYCLIC stream is exempt from the starve watchdog. This board bounds
        # it at 60 s (fishball-rf-quiesce arms tx_cyclic_timeout_ms), but the driver
        # default is still 0 and no tool should rely on the rootfs for its own cleanup.

        # pyadi-iio takes complex samples and casts real/imag to int16, so
        # integer-valued input reaches the DAC bit for bit.
        sdr.tx(i16.astype(np.complex128) + 1j * q16.astype(np.complex128))

        # The enable just happened, and it is not neutral even at the default gain: the
        # kernel's cache restore can raise an attenuator on it. Checked EVERY run,
        # including the default --tx-gain of -89.75 which asks the gate nothing - the
        # docstring used to call that run "safe: transmitter muted", which is the claim
        # this file's own 28.25 dB measurement refutes.
        try:
            assert_quiet_after_enable(
                lambda ch: float(getattr(sdr, f"tx_hardwaregain_chan{ch}")),
                "sample-GPIO buffer enable")
        except TxGateError as exc:
            # Mute both, then let the finally: below do the teardown in its documented
            # order. Tearing down here as well meant two destroy calls and a second
            # copy of an ordering that only has to be right in one place.
            sdr.tx_hardwaregain_chan0 = MUTE_DB
            sdr.tx_hardwaregain_chan1 = MUTE_DB
            sys.exit(f"{exc}\n\nBoth channels muted and the buffer torn down.")

        # Setting the gain AFTER the buffer starts is deliberate: the TX mute in
        # patch 0004 unmutes on buffer start, and 0005 restores a CACHED gain when it
        # does, so anything written before the buffer is not what is on the air.
        #
        # Raising goes through the gate; muting does not, and must not - a mute has to
        # work when ssh is down and when no affirmation exists.
        if a.tx_gain > MUTE_DB:
            try:
                got = gated_set_atten(0, a.tx_gain)
            except TxGateError as exc:
                # Leave the port quiet and the pins running: the GPIO nibble does not
                # need the DAC, so there is no reason to raise output to refuse.
                sdr.tx_hardwaregain_chan0 = MUTE_DB
                print(f"\n{exc}\n", file=sys.stderr)
                print("continuing MUTED - the sample-GPIO pins work regardless, "
                      "because the nibble never reaches the DAC.", file=sys.stderr)
            else:
                # Cross-check over THIS tool's own connection, not the gate's. The gate
                # reaches the board over ssh and this tool over libiio; if those two
                # ever resolved to different boards, the read-back here would still
                # show the mute.
                rb = sdr.tx_hardwaregain_chan0
                if abs(rb - a.tx_gain) > 0.3:
                    # MUTE FIRST. This path used to destroy the buffer and then mute,
                    # which is the one ordering the finally: below exists to forbid:
                    # the stop hook caches whatever attenuation it finds at destroy
                    # time and restores it on the next enable by any program. So the
                    # mismatch path was arming this run's raised gain for the next
                    # run. Both channels, and the teardown is left to the finally:.
                    for _ch in (0, 1):
                        setattr(sdr, f"tx_hardwaregain_chan{_ch}", MUTE_DB)
                    sys.exit(f"the gate reported {got} dB but this connection reads "
                             f"{rb} dB - muted and stopped; are they the same board?")
        else:
            sdr.tx_hardwaregain_chan0 = MUTE_DB

        rate = sdr.sample_rate
        print(f"streaming {a.samples} samples, cyclic, at {rate/1e6:.6g} MSPS")
        print(f"  TX attenuation now {sdr.tx_hardwaregain_chan0} dB")
        # The board arms a cyclic backstop at boot (fishball-rf-quiesce, 60 s by
        # default), and this is the one tool here that holds a cyclic stream open
        # indefinitely - so it is the one tool where that bound is visible. It does
        # NOT stop the pins: the sample_gpio nibble never reaches the DAC, so the
        # nibble keeps toggling after the attenuator mutes. Say so, because a carrier
        # vanishing after a minute with the pins still running looks like a fault.
        if a.tx_gain > MUTE_DB:
            _bound = _cyclic_bound_ms(a.uri)
            if _bound:
                print(f"  NOTE: this board bounds an unattended cyclic transmit at "
                      f"{_bound} ms ({_bound/1000:.0f} s).")
                print("        RF goes quiet then; the sample_gpio pins keep running, "
                      "because")
                print("        the nibble never reaches the DAC. Re-run to restart the "
                      "carrier.")
            elif _bound == 0:
                print("  NOTE: cyclic transmits are NOT bounded on this board "
                      "(tx_cyclic_timeout_ms = 0),")
                print("        so this carrier stays up until the process ends or "
                      "power is cut.")
        print(f"  sample_gpio[0] (JP5 pin 7)  square wave at {rate/2/1e6:.6g} MHz")
        print(f"  sample_gpio[1] (JP5 pin 9)  marker every {a.frame} samples "
              f"= {rate/a.frame/1e3:.4g} kHz")
        print("  sample_gpio[2] (JP5 pin 11) low     "
              "sample_gpio[3] (JP5 pin 13) high")
        print("\nGround your probe on JP5 pin 2 or 20. Ctrl-C to stop.")
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        # MUTE FIRST, then tear the buffer down. The kernel's stream-stop hook
        # snapshots whatever attenuation it finds into a cache and restores it on
        # the NEXT buffer enable, by any program, with no affirmation asked for.
        # Destroying first therefore leaves this run's gain armed for whoever
        # streams next - measured: a bare buffer enable came up at -61.5 dB from a
        # -89.75 dB idle board. tools/tx-guard.sh's reap documents the same
        # ordering for the same reason.
        # BOTH channels. The stop hook snapshots both attenuators into the cache,
        # so muting only channel 0 leaves channel 1's value there for the next
        # buffer enable to restore - and channel 1 is the port that may have an
        # antenna on it. Harmless as this tool stands, since the post-enable check
        # proves ch1 was already quiet, but the rule is written for both.
        # Per-step try/except: the first failing write used to abort the rest of this
        # block, skipping the buffer teardown AND the feature disable, and replacing
        # the original exception with its own.
        def _mute_both(where):
            for _ch in (0, 1):
                try:
                    setattr(sdr, f"tx_hardwaregain_chan{_ch}", MUTE_DB)
                except Exception as exc:                       # noqa: BLE001
                    print(f"*** MUTE WRITE FAILED on chan{_ch} at {where} ({exc}) - "
                          f"TREAT THAT PORT AS LIVE ***", file=sys.stderr)

        _mute_both("pre-teardown")
        try: sdr.tx_destroy_buffer()
        except Exception as exc:                               # noqa: BLE001
            print(f"*** tx_destroy_buffer FAILED ({exc}) ***", file=sys.stderr)
        _mute_both("post-teardown")

        # READ IT BACK. This was the only mute in the repo that wrote four times and
        # then printed "transmitter muted" as fact - in the one tool that holds an
        # INDEFINITE cyclic stream, and whose own docstring is built on the measured
        # -61.5 dB cache restore it would fail to notice here.
        _quiet = True
        for _ch in (0, 1):
            try:
                _rb = float(getattr(sdr, f"tx_hardwaregain_chan{_ch}"))
            except Exception as exc:                           # noqa: BLE001
                print(f"*** chan{_ch} UNREADABLE after mute ({exc}) - TREAT THAT PORT "
                      f"AS LIVE ***", file=sys.stderr)
                _quiet = False
                continue
            if _rb > MUTE_DB + 0.26:
                print(f"*** MUTE DID NOT LAND on chan{_ch}: reads {_rb} dB - TREAT "
                      f"THAT PORT AS LIVE ***", file=sys.stderr)
                _quiet = False
        try: _feat = set_feature(a.uri, False)
        except Exception as exc:                               # noqa: BLE001
            _feat = f"UNKNOWN ({exc})"
        print(f"tx_sample_gpio_en = {_feat}, "
              + ("transmitter verified muted" if _quiet
                 else "*** TRANSMITTER NOT VERIFIED MUTED - see above ***"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
