#!/usr/bin/env python3
"""The Fishball7020 automation server: runs on the board, port 7020.

    # run on the board (the systemd unit does this)
    python3 -m fishball_automation.server

It is a gRPC server built on grpclib, which is pure Python: Debian's
python3-grpcio aborts on this board (a 64-bit time bug in its armhf build), and
grpclib needs nothing compiled. Any gRPC client can call it.

It answers the calls in fishball.proto for a client on the network: what the
board is, how the radio is set, the reference clock, and receive captures.

THIS VERSION NEVER TRANSMITS. No call writes a transmit attenuator except
Mute, which writes the floor. Configure reads both attenuators before and
after, and mutes and fails if either rose. A call that needs a buffer another
program holds (SDR++, zc-stream, a capture) is refused, naming that program.

There is no authentication and no encryption, like iiod on port 30431: anyone
who can reach the port can retune the radio. Keep the board on a network you
trust.
"""
import argparse
import asyncio
import json
import os
import queue
import secrets
import signal
import threading
import time
from concurrent import futures

from grpclib.const import Cardinality, Handler, Status
from grpclib.exceptions import GRPCError
from grpclib.server import Server

from . import __version__, proto
from .backend import (BYTES_PER_SAMPLE, MUTE_TOL_DB, MUTED_DB, PHY, RX_DEV, TX_DEV, XADC, Busy, Refused,
                      SysfsBackend, measure_sample_rate, parse_range)

CAPTURE_DIR = "/dev/shm/fishball-automation"   # tmpfs: a capture is recorded into RAM
FETCH_CHUNK = 1 << 20
STREAM_QUEUE = 4                                # blocks (about 50 ms each) held for a slow client before dropping
OWN_WAIT_S = 6                                  # how long a call waits for this server's previous one to let go
MEASURE_MAX_RATE = 20_000_000                   # above this a Python reader cannot keep count


class BadRequest(Exception):
    """The request itself is wrong; the text says what to change."""


def lo_attr(direction):
    return "out_altvoltage0_RX_LO_frequency" if direction == "rx" else "out_altvoltage1_TX_LO_frequency"


class Service:
    """One method per call. Each takes the request and returns the reply (or
    yields replies); errors are raised as BadRequest, Busy or Refused, and
    serve() turns them into gRPC status codes."""

    def __init__(self, backend, capture_dir=CAPTURE_DIR):
        self.b, self.dir = backend, capture_dir
        self.captures = {}                      # id -> CaptureInfo
        self.clock = time.monotonic             # replaced in tests
        self.rx_lock = threading.Lock()         # one capture or stream at a time
        os.makedirs(capture_dir, exist_ok=True)

    # ---- status ---------------------------------------------------------

    def _clock(self):
        lo, step, hi = parse_range(self.b.read(PHY, "xo_correction_available"))
        return proto.ClockState(
            xo_correction_hz=int(self.b.number(PHY, "xo_correction")),
            xo_correction_min_hz=lo, xo_correction_max_hz=hi, xo_correction_step_hz=step,
            bbpll_locked=bool(self.b.reg(0x05E) & 0x80),
            rx_synth_locked=bool(self.b.reg(0x247) & 0x02),
            tx_synth_locked=bool(self.b.reg(0x287) & 0x02))

    def _fpga_temp(self):
        try:
            raw, off, scale = (self.b.number(XADC, f"in_temp0_{k}") for k in ("raw", "offset", "scale"))
            return (raw + off) * scale / 1000
        except Refused:
            return 0.0

    def GetStatus(self, _request=None):
        b = self.b
        model, firmware, kernel = b.identity()
        s = proto.Status(
            model=model, firmware=firmware, kernel=kernel, server_version=__version__,
            rx_lo_hz=int(b.number(PHY, lo_attr("rx"))), tx_lo_hz=int(b.number(PHY, lo_attr("tx"))),
            sample_rate_hz=int(b.number(PHY, "in_voltage_sampling_frequency")),
            rx_rf_bandwidth_hz=int(b.number(PHY, "in_voltage_rf_bandwidth")),
            tx_rf_bandwidth_hz=int(b.number(PHY, "out_voltage_rf_bandwidth")),
            ad9361_temp_c=b.number(PHY, "in_temp0_input") / 1000, fpga_temp_c=self._fpga_temp(),
            rx_buffer_busy=b.buffer_enabled(RX_DEV), tx_buffer_busy=b.buffer_enabled(TX_DEV),
            clock=self._clock())
        for ch in (0, 1):
            s.channels.add(rx_gain_db=b.number(PHY, f"in_voltage{ch}_hardwaregain"),
                           rx_gain_mode=b.read(PHY, f"in_voltage{ch}_gain_control_mode"),
                           tx_attenuation_db=b.number(PHY, f"out_voltage{ch}_hardwaregain"),
                           rssi_db=b.number(PHY, f"in_voltage{ch}_rssi"))
        for dev, name in ((RX_DEV, "rx"), (TX_DEV, "tx")):
            if b.buffer_enabled(dev):
                for pid, cmd in b.holders(dev):
                    s.holders.add(pid=pid, command=cmd, buffer=name)
        return s

    # ---- configure --------------------------------------------------------

    def Configure(self, r):
        b = self.b
        # Retuning under a program that is streaming changes its radio: refuse.
        with self._rx():
            b.require_free(TX_DEV, "transmit")
            return self._configure(r)

    def _configure(self, r):
        b = self.b
        modes = b.read(PHY, "in_voltage_gain_control_mode_available").split()
        for ch, field in ((0, "rx1_gain_mode"), (1, "rx2_gain_mode")):
            if r.HasField(field) and getattr(r, field) not in modes:
                raise BadRequest(f"{field} must be one of {', '.join(modes)}; got {getattr(r, field)!r}")
        before = b.tx_attenuation()
        plan = [("sample_rate_hz", "in_voltage_sampling_frequency"),      # the rate first: it bounds the bandwidths
                ("rx_rf_bandwidth_hz", "in_voltage_rf_bandwidth"), ("tx_rf_bandwidth_hz", "out_voltage_rf_bandwidth"),
                ("rx_lo_hz", lo_attr("rx")), ("tx_lo_hz", lo_attr("tx")),
                ("rx1_gain_mode", "in_voltage0_gain_control_mode"), ("rx2_gain_mode", "in_voltage1_gain_control_mode"),
                ("rx1_gain_db", "in_voltage0_hardwaregain"), ("rx2_gain_db", "in_voltage1_hardwaregain")]
        try:
            for field, attr in plan:
                if r.HasField(field):
                    b.write(PHY, attr, getattr(r, field))
        finally:
            after = b.tx_attenuation()
            if any(a > x + MUTE_TOL_DB for a, x in zip(after, before)):
                b.mute()
                raise Refused(f"a transmit attenuator rose during Configure ({before} -> {after} dB); "
                              f"both transmitters were muted")
        return self.GetStatus()

    # ---- the reference clock ---------------------------------------------

    def GetClock(self, r):
        state = self._clock()
        if not r.measure:
            return state
        rate = int(self.b.number(PHY, "in_voltage_sampling_frequency"))
        if rate > MEASURE_MAX_RATE:
            raise BadRequest(f"the measurement counts samples as they arrive, which works up to "
                             f"{MEASURE_MAX_RATE / 1e6:g} MS/s; the radio is at {rate / 1e6:g} MS/s. "
                             f"Configure a lower sample_rate_hz first")
        seconds = r.seconds or 30.0
        if not 2 <= seconds <= 600:
            raise BadRequest("seconds must be 2 to 600")
        with self._rx():
            read_block, close = self.b.open_stream([1], 1 << 20)
            try:
                measured, span = measure_sample_rate(read_block, seconds, BYTES_PER_SAMPLE)
            finally:
                close()
        ratio = measured / rate
        state.measured = True
        state.measured_reference_hz = state.xo_correction_hz * ratio
        state.measured_ppm = (ratio - 1) * 1e6
        state.measured_seconds = span
        return state

    def SetXoCorrection(self, r):
        lo, step, hi = parse_range(self.b.read(PHY, "xo_correction_available"))
        if not lo <= r.hz <= hi:
            raise BadRequest(f"xo_correction must be {lo} to {hi} Hz; got {r.hz}")
        self.b.write(PHY, "xo_correction", r.hz)
        return self._clock()

    # ---- receive ------------------------------------------------------------

    def _rx(self):
        """Hold the receive buffer for one capture, stream or measurement."""
        service = self

        class Held:
            def __enter__(self):
                # Wait out the server's own previous call: a stream the client
                # just left is still letting go of the receiver.
                if not service.rx_lock.acquire(timeout=OWN_WAIT_S):
                    raise Busy("receive", [(os.getpid(), "this server: another capture or stream")])
                try:
                    service.b.require_free(RX_DEV, "receive")
                except Exception:
                    service.rx_lock.release()
                    raise

            def __exit__(self, *exc):
                service.rx_lock.release()
        return Held()

    @staticmethod
    def _channels(requested):
        channels = sorted(set(requested)) or [1]
        if not set(channels) <= {1, 2}:
            raise BadRequest(f"channels are 1 (RX1) and 2 (RX2); got {list(requested)}")
        return channels

    def Capture(self, r):
        channels = self._channels(r.channels)
        if r.samples <= 0:
            raise BadRequest("samples must be greater than 0")
        size = r.samples * BYTES_PER_SAMPLE * len(channels)
        room = self.b.free_memory(self.dir)        # what is free now: earlier captures already count
        if size > room:
            raise BadRequest(f"this capture needs {size / 1e6:.0f} MB and the board has {max(room, 0) / 1e6:.0f} MB "
                             f"for captures (they are recorded into RAM): ask for fewer samples, "
                             f"or delete earlier captures")
        cid = secrets.token_hex(6)
        path = os.path.join(self.dir, cid + ".sigmf-data")
        with self._rx():
            rate = int(self.b.number(PHY, "in_voltage_sampling_frequency"))
            lo = int(self.b.number(PHY, lo_attr("rx")))
            written = self.b.record(channels, r.samples, path)
        model, firmware, _ = self.b.identity()
        meta = {"global": {"core:datatype": "ci16_le", "core:sample_rate": rate, "core:version": "1.0.0",
                           "core:num_channels": len(channels), "core:hw": model,
                           "core:recorder": f"fishball-automation {__version__}",
                           "fishball:firmware": firmware, "fishball:channels": [f"RX{c}" for c in channels]},
                "captures": [{"core:sample_start": 0, "core:frequency": lo,
                              "core:datetime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}],
                "annotations": []}
        info = proto.CaptureInfo(id=cid, channels=channels, samples=r.samples, sample_rate_hz=rate, rx_lo_hz=lo,
                                 bytes=written, datatype="ci16_le", sigmf_meta=json.dumps(meta, indent=1),
                                 lost_samples=0)
        self.captures[cid] = info
        return info

    def _capture_path(self, cid):
        if cid not in self.captures:
            raise BadRequest(f"no capture with id {cid!r} (it may have been deleted, or the server restarted)")
        return os.path.join(self.dir, cid + ".sigmf-data")

    def Fetch(self, r):
        with open(self._capture_path(r.id), "rb") as f:
            while True:
                data = f.read(FETCH_CHUNK)
                if not data:
                    return
                yield proto.Chunk(data=data)

    def DeleteCapture(self, r):
        path = self._capture_path(r.id)
        del self.captures[r.id]
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        return proto.Empty()

    def Stream(self, r, cancelled=lambda: False):
        channels = self._channels(r.channels)
        if r.samples < 0 or r.block_samples < 0:
            raise BadRequest("samples and block_samples cannot be negative")
        with self._rx():
            rate = int(self.b.number(PHY, "in_voltage_sampling_frequency"))
            per_block = r.block_samples or max(1024, rate // 20)          # about 50 ms
            block_bytes = per_block * BYTES_PER_SAMPLE * len(channels)
            read_block, close = self.b.open_stream(channels, block_bytes)
            q, done = queue.Queue(STREAM_QUEUE), threading.Event()
            state = {"dropped": 0}

            def reader():
                """Read at the radio's pace whatever the client does. Samples are
                lost in two places, and both are counted: here, when the client
                is too slow and the queue is full; and before here, in the
                kernel, when this thread cannot keep up with the radio. The
                second kind is found by the clock: the radio made rate x time
                samples, so whatever is missing beyond a block or two of
                slack was lost on the way in."""
                first = skipped = 0
                t0 = None
                while not done.is_set():
                    data = read_block()
                    if not data:
                        break
                    now = self.clock()
                    if t0 is None:
                        t0 = now - per_block / rate         # the first block took one block to fill
                    made = int((now - t0) * rate)           # samples the radio has produced by now
                    behind = made - (first + per_block) - 2 * per_block
                    if behind > skipped:                    # lost before they reached us
                        state["dropped"] += behind - skipped
                        skipped = behind
                    try:
                        q.put_nowait((first + skipped, data))
                    except queue.Full:
                        state["dropped"] += per_block
                    first += per_block
                q.put(None)

            t = threading.Thread(target=reader, daemon=True)
            t.start()
            try:
                seq = sent = 0
                while not cancelled():
                    item = q.get()
                    if item is None:
                        break
                    first, data = item
                    yield proto.SampleBlock(sequence=seq, data=bytes(data), first_sample=first,
                                            dropped_samples=state["dropped"])
                    seq += 1
                    sent += per_block
                    if r.samples and sent >= r.samples:
                        break
            finally:
                done.set()
                close()
                while True:                     # let the reader's final put through
                    try:
                        q.get_nowait()
                    except queue.Empty:
                        break
                t.join(2)

    # ---- transmit: only ever down -------------------------------------------

    def Mute(self, _request=None):
        got = self.b.mute()
        return proto.TxState(tx1_attenuation_db=got[0], tx2_attenuation_db=got[1],
                             muted=all(g <= MUTED_DB + MUTE_TOL_DB for g in got))


def _status(e):
    """A Service error as the gRPC status the client sees."""
    if isinstance(e, GRPCError):
        return e
    if isinstance(e, BadRequest):
        return GRPCError(Status.INVALID_ARGUMENT, str(e))
    if isinstance(e, (Busy, Refused)):
        return GRPCError(Status.FAILED_PRECONDITION, str(e))
    return GRPCError(Status.INTERNAL, f"{type(e).__name__}: {e}")


class _Handlers:
    """The Service's methods as grpclib handlers. The methods block (sysfs,
    iio_readdev), so each runs in a worker thread; replies cross back to the
    event loop through a small queue."""

    def __init__(self, service, workers=8):
        self.service, self.pool = service, futures.ThreadPoolExecutor(max_workers=workers)

    def __mapping__(self):
        return {proto.path(name): Handler(self._stream(name) if streaming else self._unary(name),
                                          Cardinality.UNARY_STREAM if streaming else Cardinality.UNARY_UNARY, req, rep)
                for name, (req, rep, streaming) in proto.METHODS.items()}

    def _unary(self, name):
        method = getattr(self.service, name)

        async def handler(stream):
            request = await stream.recv_message()
            try:
                reply = await asyncio.get_running_loop().run_in_executor(self.pool, method, request)
            except Exception as e:              # noqa: BLE001 - every failure becomes a status
                raise _status(e) from None
            await stream.send_message(reply)
        return handler

    def _stream(self, name):
        method = getattr(self.service, name)

        async def handler(stream):
            request = await stream.recv_message()
            loop, q, gone = asyncio.get_running_loop(), asyncio.Queue(4), threading.Event()

            def put(item):
                asyncio.run_coroutine_threadsafe(q.put(item), loop).result()

            def pump():
                gen = method(request, gone.is_set) if name == "Stream" else method(request)
                try:
                    for reply in gen:
                        put(("reply", reply))
                        if gone.is_set():
                            break
                    put(("end", None))
                except Exception as e:          # noqa: BLE001
                    put(("error", e))
                finally:
                    gen.close()                 # runs the method's own cleanup: frees the receiver

            task = loop.run_in_executor(self.pool, pump)
            try:
                while True:
                    kind, value = await q.get()
                    if kind == "reply":
                        await stream.send_message(value)
                    elif kind == "end":
                        return
                    else:
                        raise _status(value) from None
            finally:
                gone.set()                      # the client left, or we are done: let the pump finish
                while not task.done():
                    try:
                        q.get_nowait()
                    except asyncio.QueueEmpty:
                        await asyncio.sleep(0.01)
        return handler


class Running:
    """A started server: `.port`, and `.stop()`."""

    def __init__(self, service, host, port):
        self._loop = asyncio.new_event_loop()
        started = threading.Event()

        def run():
            asyncio.set_event_loop(self._loop)      # grpclib's Server picks up the thread's loop
            self._server = Server([_Handlers(service)])
            self._loop.run_until_complete(self._server.start(host, port))
            started.set()
            self._loop.run_forever()
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        started.wait(10)
        self.port = self._server._server.sockets[0].getsockname()[1]

    def stop(self):
        async def close():
            self._server.close()
            await self._server.wait_closed()
        asyncio.run_coroutine_threadsafe(close(), self._loop).result(5)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(5)


def serve(service, host="::", port=proto.PORT):
    """Start a gRPC server for `service`; returns a Running (see .port, .stop())."""
    return Running(service, host, port)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=proto.PORT, help="TCP port (default: %(default)s)")
    ap.add_argument("--capture-dir", default=CAPTURE_DIR, help="where captures are recorded (default: %(default)s, in RAM)")
    args = ap.parse_args()
    service = Service(SysfsBackend(), args.capture_dir)
    server = serve(service, None, args.port)        # None: every interface, IPv4 and IPv6
    print(f"fishball-automation {__version__} on port {server.port}; captures in {args.capture_dir}", flush=True)
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    stop.wait()
    server.stop()
    for cid in list(service.captures):          # a capture does not outlive the server
        try:
            os.unlink(os.path.join(args.capture_dir, cid + ".sigmf-data"))
        except OSError:
            pass


if __name__ == "__main__":
    main()
