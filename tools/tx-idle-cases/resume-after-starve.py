#!/usr/bin/env python3
"""Does the transmitter come back when data resumes after a starve mute?

    ./resume-after-starve.py <uri>        e.g. usb:16.69.4 or ip:192.168.2.1

Two ways a program can stop and restart a transmission inside one connection:

  A  keep the TX buffer open, stop feeding it, feed it again   (SDR Console)
  B  destroy the TX buffer, create a new one                   (most others)

In A the starve watchdog (patches/0015) mutes after tx_starve_timeout_ms. This
prints what the transmitter is doing at every stage of both, read back from the
board, so "does resumed data unmute it" is answered by the hardware.

It commands NO output: both attenuators are preset to -89.5 dB (not the -89.75
floor, which would arm the kernel's cached-gain restore), only zero samples are
sent, and every buffer enable is followed by a read of both attenuators that
aborts if either rose. So it needs no tx-guard affirmation, like
tx-gpio-bitmap-check.py. It does open TX buffers, so it follows the rules in
docs/transmitter-safety.md, and it lowers the sample rate for the run (USB
cannot feed the board's default 30.72 MSPS) and puts it back.

Exit status: 0 the transmitter resumed in A, 1 it stayed muted, 2 the run
itself went wrong (read the output).
"""
import sys
import time

import iio

QUIET_DB = -89.5        # preset: silent, but not the floor
FLOOR_DB = -89.75
RATE = 2_500_000        # 10 MB/s for one I/Q pair, inside USB's ~20 MB/s
BLOCK_S = 0.05
DATA_SEL = {0: "DDS", 1: "SED", 2: "DMA", 3: "ZERO"}
# axi_ad9361 DAC core, REG_CHAN_CNTRL_7 of channel 0: bits 3:0 select the DAC's
# data source. Bit 31 addresses the FPGA core rather than the AD9361 over SPI.
REG_DATA_SEL_CH0 = 0x80000000 | 0x418


def main(uri):
    ctx = iio.Context(uri)
    phy = ctx.find_device("ad9361-phy")
    dds = ctx.find_device("cf-ad9361-dds-core-lpc")
    att = [phy.find_channel("voltage%d" % c, True) for c in (0, 1)]
    lo = phy.find_channel("altvoltage1", True)
    rate_ch = phy.find_channel("voltage0", True)

    def gains():
        return [float(a.attrs["hardwaregain"].value.split()[0]) for a in att]

    def set_gain(db):
        """Write, read back, rewrite until the chip agrees."""
        for _ in range(5):
            for a in att:
                a.attrs["hardwaregain"].value = str(db)
            if all(abs(g - db) < 0.01 for g in gains()):
                return True
            time.sleep(0.02)
        return False

    def state(label):
        g = gains()
        pd = int(lo.attrs["powerdown"].value)
        try:
            sel = DATA_SEL.get(dds.reg_read(REG_DATA_SEL_CH0) & 0xF, "?")
        except OSError as e:
            sel = "unreadable (%s)" % e
        und = dds.attrs["tx_dma_underflow_count"].value
        print("  %-38s atten %7.2f / %7.2f  LO_pd=%d  source=%-4s underflows=%s"
              % (label, g[0], g[1], pd, sel, und), flush=True)
        return g, pd, sel

    def mute_or_shout():
        if not set_gain(FLOOR_DB):
            print("MUTE DID NOT LAND: %s - TREAT THE PORTS AS LIVE" % gains(),
                  file=sys.stderr)
            return False
        return True

    for ch in dds.channels:
        ch.enabled = ch.output and ch.scan_element and ch.id in ("voltage0", "voltage1")
    n = int(RATE * BLOCK_S)
    zeros = bytearray(n * 4)            # one I/Q pair, int16 each

    def open_buffer():
        if not set_gain(QUIET_DB):
            raise RuntimeError("could not preset %s dB: %s" % (QUIET_DB, gains()))
        # iiod destroys a buffer after it has answered the close, so a new one
        # straight away can be refused; say how long that lasted.
        t0 = time.monotonic()
        while True:
            try:
                buf = iio.Buffer(dds, n, False)
                break
            except OSError as e:
                if e.errno != 16 or time.monotonic() - t0 > 10:
                    print("  a new buffer was REFUSED for %.1f s: %s"
                          % (time.monotonic() - t0, e))
                    raise
                time.sleep(0.1)
        if time.monotonic() - t0 > 0.15:
            print("  (a new buffer was refused as busy for %.1f s first)"
                  % (time.monotonic() - t0))
        g = gains()                     # the enable itself can raise them
        if max(g) > QUIET_DB + 0.01:
            mute_or_shout()
            raise RuntimeError("the buffer enable raised an attenuator: %s" % g)
        return buf

    def feed(buf, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            buf.write(zeros)
            buf.push()

    print("%s: %s, firmware %s, kernel %s" % (
        uri, ctx.attrs.get("hw_model"), ctx.attrs.get("fw_version"),
        ctx.attrs.get("local,kernel")))
    starve_ms = int(dds.attrs["tx_starve_timeout_ms"].value)
    print("tx_starve_timeout_ms = %d" % starve_ms)
    old_rate = rate_ch.attrs["sampling_frequency"].value
    result = 2
    buf = None
    try:
        state("before anything")
        rate_ch.attrs["sampling_frequency"].value = str(RATE)
        print("sample rate %s -> %s for the run" % (
            old_rate, rate_ch.attrs["sampling_frequency"].value))

        print("A: one buffer, feed - pause - feed")
        buf = open_buffer()
        feed(buf, 1.0)
        _, pd_run, _ = state("feeding")
        if pd_run:
            print("  (muted while being fed: the link starved the DAC by itself)")
        pause_s = max(1.0, 4 * starve_ms / 1000)
        time.sleep(pause_s)
        state("paused %.1f s" % pause_s)
        # With the DAC on the DDS nothing drains the DMA, so on a kernel that
        # does not resume, the queue fills and the push itself times out.
        push_error = None
        try:
            feed(buf, 1.0)
        except OSError as e:
            push_error = e
            print("  pushing into the same buffer FAILED: %s" % e)
        g, pd, sel = state("feeding again, same buffer")
        resumed = (push_error is None and pd == 0
                   and min(g) > FLOOR_DB + 0.01 and sel == "DMA")
        remuted = None
        if resumed:
            # The watchdog must still be armed after a resume: stall again.
            time.sleep(pause_s)
            g2, pd2, _ = state("paused again")
            remuted = pd2 == 1 and max(g2) < FLOOR_DB + 0.01
            feed(buf, 1.0)
            g, pd, sel = state("feeding a third time")
            resumed = pd == 0 and min(g) > FLOOR_DB + 0.01 and sel == "DMA"
        mute_or_shout()                 # before the teardown, always
        del buf
        buf = None
        time.sleep(0.3)
        state("buffer destroyed")

        print("B: feed - destroy - new buffer - feed")
        buf = open_buffer()
        feed(buf, 1.0)
        state("feeding")
        del buf                         # deliberately at -89.5: what a restart restores
        buf = None
        time.sleep(1.0)
        state("buffer destroyed, 1 s")
        buf = open_buffer()
        feed(buf, 1.0)
        gb, pdb, selb = state("feeding, new buffer")
        mute_or_shout()
        del buf
        buf = None
        time.sleep(0.3)

        b_ok = pdb == 0 and min(gb) > FLOOR_DB + 0.01 and selb == "DMA"
        print("A (same buffer): %s" % ("transmitter RESUMED" if resumed
                                       else "transmitter STAYED MUTED"))
        print("B (new buffer):  %s" % ("transmitter resumed" if b_ok
                                       else "transmitter STAYED MUTED"))
        if remuted is not None:
            print("second stall:    %s" % ("muted again" if remuted
                                           else "NOT MUTED - the watchdog did not re-arm"))
        result = 0 if resumed and remuted else 1
        if remuted is False:
            result = 2
    finally:
        ok = mute_or_shout()
        buf = None
        try:
            rate_ch.attrs["sampling_frequency"].value = old_rate
        except OSError as e:
            print("could not restore the sample rate %s: %s" % (old_rate, e),
                  file=sys.stderr)
        time.sleep(0.3)
        state("at exit")
        print("sample rate back at %s" % rate_ch.attrs["sampling_frequency"].value)
        if not ok:
            result = 2
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
