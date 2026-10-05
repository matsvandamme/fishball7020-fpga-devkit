#!/usr/bin/env python3
"""The automation server's rules, checked against a fake board.

    # run from: tools/automation
    .venv/bin/python tests/test_automation.py

A real gRPC server and the real client talk over localhost; only the board is
faked (FakeBackend), so the request checks, the busy refusals, the capture and
stream paths and the transmit-safety rules are all exercised as shipped.
"""
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fishball_automation import proto                                    # noqa: E402
from fishball_automation.backend import (MUTED_DB, PHY, RX_DEV, TX_DEV, FakeBackend,   # noqa: E402
                                         measure_sample_rate, stream_channels)
from fishball_automation.client import Fishball, FishballError, status_text  # noqa: E402
from fishball_automation.server import Service, serve                       # noqa: E402


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.b = FakeBackend()
        self.service = Service(self.b, os.path.join(self.tmp.name, "captures"))
        self.service.clock = lambda: self.b.sim_time          # the fake radio's clock, not the wall's
        self.server = serve(self.service, "127.0.0.1", 0)
        self.c = Fishball("127.0.0.1", self.server.port, timeout=10)

    def tearDown(self):
        self.c.close()
        self.server.stop()
        self.tmp.cleanup()

    def refused(self, code, fn, *a, **k):
        with self.assertRaises(FishballError) as cm:
            fn(*a, **k)
        self.assertEqual(cm.exception.code, code, str(cm.exception))
        return str(cm.exception)

    def tx(self):
        return self.b.tx_attenuation()


class Status(Case):
    def test_reports_the_board(self):
        s = self.c.status()
        self.assertEqual(s.model, "FISH Ball PlutoSDR Rev.A (Z7020/AD9361)")
        self.assertEqual((s.rx_lo_hz, s.tx_lo_hz, s.sample_rate_hz), (2_400_000_000, 2_450_000_000, 30_720_000))
        self.assertEqual([ch.tx_attenuation_db for ch in s.channels], [MUTED_DB, MUTED_DB])
        self.assertEqual(s.channels[0].rx_gain_mode, "slow_attack")
        self.assertAlmostEqual(s.ad9361_temp_c, 44.7)
        self.assertTrue(s.clock.bbpll_locked and s.clock.rx_synth_locked and s.clock.tx_synth_locked)
        self.assertEqual((s.clock.xo_correction_min_hz, s.clock.xo_correction_max_hz), (39_992_000, 40_008_000))
        self.assertFalse(s.rx_buffer_busy or s.tx_buffer_busy)

    def test_names_who_holds_a_buffer(self):
        self.b.enabled[RX_DEV] = True
        self.b.held[RX_DEV] = [(311, "/usr/sbin/iiod -F /dev/iio_ffs")]
        s = self.c.status()
        self.assertTrue(s.rx_buffer_busy)
        self.assertEqual([(h.pid, h.buffer) for h in s.holders], [(311, "rx")])
        self.assertIn("pid 311", status_text(s))

    def test_an_unlocked_pll_shows(self):
        self.b.registers[0x05E] = 0x00
        self.assertFalse(self.c.status().clock.bbpll_locked)
        self.assertIn("BBPLL NOT LOCKED", status_text(self.c.status()))

    def test_status_text_flags_an_unmuted_transmitter(self):
        self.b.attrs[(PHY, "out_voltage1_hardwaregain")] = "-30.000000 dB"
        self.assertIn("NOT MUTED", status_text(self.c.status()))


class Configure(Case):
    def test_round_trips_what_it_set(self):
        s = self.c.configure(rx_lo_hz=868_000_000, sample_rate_hz=20_000_000, rx1_gain_mode="manual", rx1_gain_db=30)
        self.assertEqual((s.rx_lo_hz, s.sample_rate_hz), (868_000_000, 20_000_000))
        self.assertEqual((s.channels[0].rx_gain_mode, s.channels[0].rx_gain_db), ("manual", 30.0))
        self.assertEqual(s.tx_lo_hz, 2_450_000_000)          # not asked for: left alone

    def test_leaves_unset_fields_unwritten(self):
        self.c.configure(rx_lo_hz=433_920_000)
        self.assertEqual([w[1] for w in self.b.writes], ["out_altvoltage0_RX_LO_frequency"])

    def test_the_rate_is_written_before_the_bandwidth(self):
        self.c.configure(rx_rf_bandwidth_hz=4_000_000, sample_rate_hz=4_000_000)
        self.assertEqual([w[1] for w in self.b.writes],
                         ["in_voltage_sampling_frequency", "in_voltage_rf_bandwidth"])

    def test_a_driver_refusal_is_an_error_not_success(self):
        self.b.refuse[(PHY, "in_voltage_sampling_frequency")] = "Invalid argument"
        msg = self.refused("FAILED_PRECONDITION", self.c.configure, sample_rate_hz=100)
        self.assertIn("Invalid argument", msg)

    def test_an_unknown_gain_mode_is_rejected_before_any_write(self):
        msg = self.refused("INVALID_ARGUMENT", self.c.configure, rx1_gain_mode="loud", rx_lo_hz=1_000_000_000)
        self.assertIn("slow_attack", msg)
        self.assertEqual(self.b.writes, [])

    def test_an_unknown_setting_is_rejected_by_the_client(self):
        self.refused("INVALID_ARGUMENT", self.c.configure, tx1_attenuation_db=-10)

    def test_never_writes_a_transmit_attenuator(self):
        self.c.configure(rx_lo_hz=868_000_000, tx_lo_hz=868_000_000, sample_rate_hz=20_000_000,
                         rx_rf_bandwidth_hz=18_000_000, tx_rf_bandwidth_hz=18_000_000,
                         rx1_gain_mode="manual", rx2_gain_mode="manual", rx1_gain_db=10, rx2_gain_db=10)
        self.assertFalse([w for w in self.b.writes if w[1].startswith("out_voltage") and "hardwaregain" in w[1]])
        self.assertEqual(self.tx(), [MUTED_DB, MUTED_DB])

    def test_refused_while_another_program_streams(self):
        self.b.enabled[RX_DEV] = True
        self.b.held[RX_DEV] = [(4242, "sdrpp")]
        msg = self.refused("FAILED_PRECONDITION", self.c.configure, rx_lo_hz=100_000_000)
        self.assertIn("pid 4242 (sdrpp)", msg)
        self.assertEqual(self.b.writes, [])

    def test_refused_while_another_program_transmits(self):
        self.b.enabled[TX_DEV] = True
        self.b.held[TX_DEV] = [(77, "chirp_view.py")]
        self.assertIn("transmit buffer", self.refused("FAILED_PRECONDITION", self.c.configure, tx_lo_hz=100_000_000))

    def test_if_an_attenuator_rises_it_mutes_and_fails(self):
        def raise_tx(device, attr, value):
            if attr == "in_voltage_sampling_frequency":       # as if the driver restored a cached gain
                self.b.attrs[(PHY, "out_voltage0_hardwaregain")] = "-61.500000 dB"
        self.b.on_write = raise_tx
        msg = self.refused("FAILED_PRECONDITION", self.c.configure, sample_rate_hz=20_000_000)
        self.assertIn("muted", msg)
        self.assertEqual(self.tx(), [MUTED_DB, MUTED_DB])


class Clock(Case):
    def test_reads_without_measuring(self):
        c = self.c.clock()
        self.assertEqual(c.xo_correction_hz, 40_000_000)
        self.assertFalse(c.measured)

    def test_sets_the_correction_within_its_range(self):
        self.assertEqual(self.c.set_xo_correction(40_000_123).xo_correction_hz, 40_000_123)
        msg = self.refused("INVALID_ARGUMENT", self.c.set_xo_correction, 41_000_000)
        self.assertIn("39992000 to 40008000", msg)

    def test_measuring_is_refused_above_the_rate_it_can_count(self):
        self.assertIn("20 MS/s", self.refused("INVALID_ARGUMENT", self.c.clock, True, 2))

    def test_measuring_is_refused_while_the_receiver_is_held(self):
        self.b.attrs[(PHY, "in_voltage_sampling_frequency")] = "20000000"
        self.b.enabled[RX_DEV] = True
        self.b.held[RX_DEV] = [(9, "iio_readdev")]
        self.assertIn("iio_readdev", self.refused("FAILED_PRECONDITION", self.c.clock, True, 2))

    def test_the_fit_recovers_a_known_rate(self):
        t = {"now": 0.0}

        def read_block():                                    # 1 MB every 13.1 ms: 20 MS/s plus 25 ppm
            t["now"] += (1 << 20) / (20_000_000 * 1.000025 * 4)
            return b"\0" * (1 << 20)
        rate, span = measure_sample_rate(read_block, 10, 4, clock=lambda: t["now"])
        self.assertAlmostEqual((rate / 20e6 - 1) * 1e6, 25.0, places=3)
        self.assertGreater(span, 9)


class Capture(Case):
    def test_records_fetches_and_describes(self):
        out = os.path.join(self.tmp.name, "loop")
        rec = self.c.capture(samples=50_000, channels=[1, 2], path=out)
        self.assertEqual((rec.samples, rec.channels, rec.lost_samples), (50_000, [1, 2], 0))
        self.assertEqual(os.path.getsize(rec.data_path), 50_000 * 4 * 2)
        import json
        meta = json.loads(pathlib.Path(rec.meta_path).read_text())
        self.assertEqual(meta["global"]["core:datatype"], "ci16_le")
        self.assertEqual(meta["global"]["core:sample_rate"], 30_720_000)
        self.assertEqual(meta["global"]["core:num_channels"], 2)
        self.assertEqual(meta["captures"][0]["core:frequency"], 2_400_000_000)
        x = rec.read()
        self.assertEqual(x.shape, (2, 50_000))
        self.assertEqual((x[0, 1234].real, x[0, 1234].imag, x[1, 1234].real), (1234.0, -1234.0, 1234.0))

    def test_fetching_deletes_it_from_the_board(self):
        self.c.capture(samples=1000, path=os.path.join(self.tmp.name, "a"))
        self.assertEqual(self.service.captures, {})
        self.assertEqual(os.listdir(self.service.dir), [])

    def test_refused_while_another_program_holds_the_receiver(self):
        self.b.enabled[RX_DEV] = True
        self.b.held[RX_DEV] = [(555, "iio_readdev -u local: cf-ad9361-lpc")]
        msg = self.refused("FAILED_PRECONDITION", self.c.capture, 1000)
        self.assertIn("pid 555 (iio_readdev -u local: cf-ad9361-lpc)", msg)

    def test_a_stale_busy_flag_with_no_holder_is_cleared_not_obeyed(self):
        self.b.enabled[RX_DEV] = True                         # as left by a reader that was killed
        self.b._clear_stale = lambda device: self.b.enabled.__setitem__(device, False)
        self.assertEqual(self.c.capture(samples=100).samples, 100)

    def test_bad_requests(self):
        self.assertIn("channels are 1", self.refused("INVALID_ARGUMENT", self.c.capture, 1000, [3]))
        self.assertIn("greater than 0", self.refused("INVALID_ARGUMENT", self.c.capture, 0))

    def test_too_large_for_memory_is_refused_with_the_numbers(self):
        self.b.memory = 1 << 20
        msg = self.refused("INVALID_ARGUMENT", self.c.capture, 10_000_000)
        self.assertIn("40 MB", msg)
        self.assertIn("1 MB", msg)

    def test_an_unknown_capture_cannot_be_fetched(self):
        info = self.c.capture(samples=100)
        self.c.delete(info.id)
        self.refused("INVALID_ARGUMENT", self.c.fetch, info, os.path.join(self.tmp.name, "gone"))

    def test_never_touches_the_transmitter(self):
        self.c.capture(samples=1000)
        self.assertEqual(self.b.writes, [])
        self.assertEqual(self.tx(), [MUTED_DB, MUTED_DB])


class Stream(Case):
    def test_delivers_the_samples_in_order(self):
        blocks = list(self.c.stream(channels=[1], samples=8192, block_samples=1024))
        self.assertEqual([b.sequence for b in blocks], list(range(8)))
        self.assertEqual([b.first_sample for b in blocks], [1024 * i for i in range(8)])
        self.assertEqual({len(b.data) for b in blocks}, {1024 * 4})
        self.assertEqual(blocks[-1].dropped_samples, 0)

    def test_a_slow_client_is_told_how_much_was_dropped(self):
        import time
        # Blocks big enough (256 kB) that the transport cannot hide a slow
        # client by buffering: the server has to drop, and must say so.
        self.b.stream_blocks, per = 120, 65536
        seen = dropped = 0
        for blk in self.c.stream(channels=[1], block_samples=per):
            if seen < 3:
                time.sleep(0.5)                              # fall behind: the board keeps reading
            seen += 1
            dropped = blk.dropped_samples
        self.assertGreater(dropped, 0)
        self.assertEqual(dropped % per, 0)
        self.assertLessEqual(seen * per + dropped, 120 * per)   # nothing is counted twice
        self.assertGreaterEqual(seen * per + dropped, (120 - 16) * per)   # all but what was still queued is accounted for

    def test_first_sample_skips_what_was_dropped(self):
        import time
        # Paced like a radio, so blocks keep coming after the client catches
        # up: the drops then sit in the middle of the stream, as a jump in
        # first_sample.
        self.b.stream_blocks, self.b.stream_pace, per = 250, 0.01, 65536
        prev_end, gaps, last = 0, 0, None
        for i, blk in enumerate(self.c.stream(channels=[1], block_samples=per)):
            if i < 3:
                time.sleep(0.5)
            gaps += blk.first_sample - prev_end
            prev_end = blk.first_sample + per
            last = blk
        self.assertGreater(gaps, 0)
        self.assertLessEqual(gaps, last.dropped_samples)      # every gap in the numbering was counted as dropped

    def test_samples_lost_before_the_server_are_counted_by_the_clock(self):
        # The fake radio hands over blocks at a tenth of the rate its clock
        # says it produces them: nine tenths were lost on the way in.
        per, rate = 1024, 30_720_000
        real = self.b.open_stream

        def slow(channels, block_bytes):
            read_block, close = real(channels, block_bytes)

            def read():
                self.b.sim_time += 9 * per / rate             # nine more blocks went by unread
                return read_block()
            return read, close
        self.b.open_stream = slow
        blocks = list(self.c.stream(channels=[1], samples=50 * per, block_samples=per))
        last = blocks[-1]
        self.assertGreater(last.dropped_samples, 9 * 40 * per)
        self.assertEqual(last.first_sample, 49 * per + last.dropped_samples)   # numbering skips what was lost

    def test_refused_while_busy_and_releases_the_receiver_after(self):
        self.b.enabled[RX_DEV] = True
        self.b.held[RX_DEV] = [(1, "zc-stream -D -8")]
        with self.assertRaises(FishballError) as cm:
            list(self.c.stream(samples=1024))
        self.assertIn("zc-stream", str(cm.exception))
        self.b.enabled[RX_DEV] = False
        self.assertEqual(len(list(self.c.stream(samples=2048, block_samples=1024))), 2)
        self.assertEqual(len(list(self.c.stream(samples=1024, block_samples=1024))), 1)   # and again


class Mute(Case):
    def test_mutes_both_and_reads_back(self):
        self.b.attrs[(PHY, "out_voltage0_hardwaregain")] = "-20.000000 dB"
        m = self.c.mute()
        self.assertTrue(m.muted)
        self.assertEqual((m.tx1_attenuation_db, m.tx2_attenuation_db), (MUTED_DB, MUTED_DB))

    def test_a_mute_that_does_not_take_is_an_error(self):
        self.b.refuse[(PHY, "out_voltage1_hardwaregain")] = "Input/output error"
        self.refused("FAILED_PRECONDITION", self.c.mute)

    def test_muting_is_allowed_while_everything_is_busy(self):
        self.b.enabled[RX_DEV] = self.b.enabled[TX_DEV] = True
        self.assertTrue(self.c.mute().muted)


class Protocol(unittest.TestCase):
    def test_every_method_has_a_handler_and_a_client_call(self):
        self.assertEqual(sorted(proto.METHODS), ["Capture", "Configure", "DeleteCapture", "Fetch", "GetClock",
                                                 "GetStatus", "Mute", "SetXoCorrection", "Stream"])
        for name in proto.METHODS:
            self.assertTrue(callable(getattr(Service, name)), name)

    def test_one_class_per_message_type(self):
        self.assertIs(proto.METHODS["GetStatus"][1], proto.Status)
        self.assertIs(proto.METHODS["Configure"][1], proto.Status)
        self.assertIs(proto.METHODS["Fetch"][0], proto.METHODS["DeleteCapture"][0])

    def test_no_call_can_raise_a_transmitter(self):
        fields = [f.name for req, _, _ in proto.METHODS.values() for f in req.DESCRIPTOR.fields]
        self.assertFalse([f for f in fields if "atten" in f or "tx_gain" in f or "power" in f], fields)

    def test_channel_names(self):
        self.assertEqual(stream_channels([2, 1]), ["voltage0", "voltage1", "voltage2", "voltage3"])
        self.assertEqual(stream_channels([2]), ["voltage2", "voltage3"])

    def test_no_server_gives_a_useful_error(self):
        c = Fishball("127.0.0.1", 1, timeout=2)
        with self.assertRaises(FishballError) as cm:
            c.status()
        self.assertIn("./devkit automation install", str(cm.exception))
        c.close()


if __name__ == "__main__":
    unittest.main(verbosity=1)
