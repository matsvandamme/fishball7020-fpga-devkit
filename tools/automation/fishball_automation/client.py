"""The Python client for the Fishball7020 automation server.

    # run from: tools/automation on your PC, as: .venv/bin/python example.py
    from fishball_automation.client import Fishball

    with Fishball("fishball.local") as board:
        print(board.status().model)
        board.configure(rx_lo_hz=868_000_000, sample_rate_hz=20_000_000)
        rec = board.capture(samples=2_000_000, channels=[1, 2], path="loop")
        print(rec.samples, "samples per channel in", rec.data_path)

        # transmitting needs the port affirmed first: ./devkit tx-guard affirm 0
        tone = board.upload_waveform(iq)          # complex, full scale +-32767, like pyadi-iio
        with board.transmit(tone, channels=[1], attenuation_db=-40):
            ...                                   # TX1 plays until the block ends, then mutes

Every call returns the server's reply message (see fishball.proto), and raises
FishballError with the server's own explanation when the board refuses.
"""
import json
import pathlib
import threading
import time

import grpc

from . import proto


class FishballError(Exception):
    """The server refused a call. `.code` is the gRPC status code's name:
    INVALID_ARGUMENT (the request is wrong), FAILED_PRECONDITION (the board is
    busy, or the driver refused), UNAVAILABLE (no server there)."""

    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class Recording:
    """A capture fetched to disk: a SigMF pair, `<path>.sigmf-data` and `<path>.sigmf-meta`."""

    def __init__(self, info, data_path, meta_path):
        self.info, self.data_path, self.meta_path = info, data_path, meta_path
        self.samples, self.channels = info.samples, list(info.channels)
        self.sample_rate_hz, self.rx_lo_hz, self.lost_samples = info.sample_rate_hz, info.rx_lo_hz, info.lost_samples

    def read(self):
        """The samples as a complex64 array, shape (channels, samples). Needs numpy."""
        import numpy as np
        raw = np.fromfile(self.data_path, dtype="<i2").reshape(-1, len(self.channels), 2)
        return (raw[..., 0] + 1j * raw[..., 1]).astype(np.complex64).T


def _resolve(host, port):
    """host:port with the name looked up by the system resolver. gRPC's own
    resolver does not ask mDNS, so it cannot find fishball.local by itself."""
    import socket
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return f"{host}:{port}"                 # let gRPC report it as unavailable
    infos.sort(key=lambda i: i[0] != socket.AF_INET)       # IPv4 first: no scope to carry
    family, *_, addr = infos[0]
    return f"[{addr[0]}]:{port}" if family == socket.AF_INET6 else f"{addr[0]}:{port}"


class Fishball:
    def __init__(self, host="fishball.local", port=proto.PORT, timeout=30.0):
        self.target, self.timeout = f"{host}:{port}", timeout
        self._channel = grpc.insecure_channel(_resolve(host, port),
                                              options=[("grpc.max_receive_message_length", 16 << 20)])
        self._calls = {}
        for name, (req, rep, streaming) in proto.METHODS.items():
            make = (self._channel.stream_unary if name in proto.CLIENT_STREAMING
                    else self._channel.unary_stream if streaming else self._channel.unary_unary)
            self._calls[name] = make(proto.path(name), request_serializer=req.SerializeToString,
                                     response_deserializer=rep.FromString)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._channel.close()

    def _call(self, name, request, timeout=None):
        try:
            return self._calls[name](request, timeout=timeout or self.timeout)
        except grpc.RpcError as e:
            raise self._error(e) from None

    def _error(self, e):
        code = e.code().name
        if code == "UNAVAILABLE":
            return FishballError(code, f"no automation server at {self.target}: is the board up, and "
                                       f"is the service installed (./devkit automation install)?")
        return FishballError(code, e.details() or code)

    # ---- the calls ----------------------------------------------------------

    def status(self):
        return self._call("GetStatus", proto.StatusRequest())

    def configure(self, **settings):
        """Set any of: rx_lo_hz, tx_lo_hz, sample_rate_hz, rx_rf_bandwidth_hz,
        tx_rf_bandwidth_hz, rx1_gain_mode, rx2_gain_mode, rx1_gain_db,
        rx2_gain_db. Returns the status read back afterwards."""
        try:
            request = proto.ConfigureRequest(**settings)
        except (ValueError, TypeError) as e:
            raise FishballError("INVALID_ARGUMENT", f"configure: {e}") from None
        return self._call("Configure", request)

    def clock(self, measure=False, seconds=0.0):
        """The reference clock's state. measure=True also times the sample
        clock against the board's own crystal, which takes `seconds` (30 by default)."""
        return self._call("GetClock", proto.ClockRequest(measure=measure, seconds=seconds),
                          timeout=(seconds or 30.0) + 30 if measure else None)

    def set_xo_correction(self, hz):
        return self._call("SetXoCorrection", proto.XoCorrectionRequest(hz=int(hz)))

    def mute(self):
        return self._call("Mute", proto.Empty())

    def capture(self, samples, channels=(1,), path=None, keep_on_board=False):
        """Record `samples` per channel on the board, gap-free, then fetch them.

        With `path`, writes `<path>.sigmf-data` and `<path>.sigmf-meta` and
        returns a Recording; without, returns the CaptureInfo and leaves the
        capture on the board for fetch()."""
        info = self._call("Capture", proto.CaptureRequest(channels=list(channels), samples=int(samples)),
                          timeout=self.timeout + samples / 1e5)
        if path is None:
            return info
        rec = self.fetch(info, path)
        if not keep_on_board:
            self.delete(info.id)
        return rec

    def fetch(self, info, path):
        base = str(path)
        for suffix in (".sigmf-data", ".sigmf-meta"):
            if base.endswith(suffix):
                base = base[:-len(suffix)]
        base = pathlib.Path(base)
        data, meta = base.with_name(base.name + ".sigmf-data"), base.with_name(base.name + ".sigmf-meta")
        got = 0
        try:
            with open(data, "wb") as f:
                for chunk in self._calls["Fetch"](proto.FetchRequest(id=info.id), timeout=None):
                    f.write(chunk.data)
                    got += len(chunk.data)
        except grpc.RpcError as e:
            raise self._error(e) from None
        if got != info.bytes:
            raise FishballError("DATA_LOSS", f"fetched {got} of {info.bytes} bytes of capture {info.id}")
        meta.write_text(info.sigmf_meta + "\n")
        return Recording(info, data, meta)

    def delete(self, capture_id):
        self._call("DeleteCapture", proto.FetchRequest(id=capture_id))

    def upload_waveform(self, iq, channels=None):
        """Send a waveform to the board, once. `iq` is complex samples at the
        transmit full scale (+-32767, as pyadi-iio takes them), shape (n,) or
        (channels, n), or ci16 bytes with `channels`. n must be a multiple of 32.
        Returns the WaveformInfo that transmit() and transmit_capture() take."""
        data, ch = _waveform_bytes(iq, channels)

        def chunks():
            for i in range(0, max(len(data), 1), 1 << 20):
                yield proto.WaveformChunk(data=data[i:i + (1 << 20)], channels=ch if i == 0 else 0)
        try:
            return self._calls["UploadWaveform"](chunks(), timeout=self.timeout + len(data) / 2e6)
        except grpc.RpcError as e:
            raise self._error(e) from None

    def delete_waveform(self, waveform):
        self._call("DeleteWaveform", proto.WaveformRef(id=getattr(waveform, "id", waveform)))

    def transmit(self, waveform, channels=(1,), attenuation_db=-89.75, pad_db=0.0, seconds=0.0,
                 one_shot=False, cyclic_bound_s=0.0):
        """Play an uploaded waveform. Returns a Transmission once the board
        confirms it is playing at the asked attenuation; use it in a `with`
        block, or call stop(). seconds=0 plays until stopped (the board's own
        cyclic bound, 60 s, still applies unless cyclic_bound_s raises it)."""
        req = proto.TransmitRequest(waveform_id=getattr(waveform, "id", waveform), channels=list(channels),
                                    attenuation_db=attenuation_db, pad_db=pad_db, seconds=seconds,
                                    one_shot=one_shot, cyclic_bound_s=cyclic_bound_s)
        return Transmission(self, self._calls["Transmit"](req, timeout=None))

    def transmit_capture(self, waveform, samples, tx_channels=(1,), rx_channels=(1,), attenuation_db=-89.75,
                         pad_db=0.0, settle_s=0.0, path=None, keep_on_board=False):
        """Play a waveform cyclically, record the receivers while it plays,
        mute, stop. pad_db, the attenuation fitted between the transmitter and
        the receiver, must be at least 20. Returns like capture()."""
        req = proto.TransmitCaptureRequest(waveform_id=getattr(waveform, "id", waveform),
                                           tx_channels=list(tx_channels), attenuation_db=attenuation_db,
                                           pad_db=pad_db, rx_channels=list(rx_channels), samples=int(samples),
                                           settle_s=settle_s)
        info = self._call("TransmitCapture", req, timeout=self.timeout + samples / 1e5 + settle_s)
        if path is None:
            return info
        rec = self.fetch(info, path)
        if not keep_on_board:
            self.delete(info.id)
        return rec

    def stream(self, channels=(1,), samples=0, block_samples=0):
        """Yield SampleBlock messages as the board receives them. Each block
        carries `dropped_samples`: how many the board had to drop so far because
        this client or the network was too slow. Stop by leaving the loop."""
        call = self._calls["Stream"](proto.StreamRequest(channels=list(channels), samples=int(samples),
                                                         block_samples=int(block_samples)), timeout=None)
        try:
            yield from call
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                raise self._error(e) from None
        finally:
            call.cancel()


class Transmission:
    """A running transmit. The board plays while this object's call is open:
    stop() (or leaving a `with` block) ends the call, and the server mutes,
    reads back and releases the buffer. stop() then confirms both
    transmitters read the floor."""

    def __init__(self, board, call):
        self._board, self._call = board, call
        self.state, self.error, self.final = None, None, None
        self._first, self._done = threading.Event(), threading.Event()
        threading.Thread(target=self._follow, daemon=True).start()
        self._first.wait(30)
        if self.error:
            raise self.error
        if self.state is None:
            self.stop()
            raise FishballError("DEADLINE_EXCEEDED", "the transmit did not confirm within 30 s; stopped")

    def _follow(self):
        try:
            for st in self._call:
                if st.transmitting:
                    self.state = st
                else:
                    self.final = st
                self._first.set()
        except grpc.RpcError as e:
            if e.code() != grpc.StatusCode.CANCELLED:
                self.error = self._board._error(e)
        finally:
            self._first.set()
            self._done.set()

    @property
    def running(self):
        return not self._done.is_set()

    def wait(self, timeout=None):
        """Until the server ends it (its `seconds`, a one-shot, Mute). Returns the final TxState."""
        self._done.wait(timeout)
        if self.error:
            raise self.error
        return self.final

    def stop(self):
        """End it, and confirm both transmitters read the floor. Returns the status read back."""
        self._call.cancel()
        self._done.wait(5)
        deadline = time.monotonic() + 3
        while True:
            s = self._board.status()
            quiet = all(ch.tx_attenuation_db <= -89.5 for ch in s.channels)
            if (quiet and not s.transmitting) or time.monotonic() > deadline:
                break
            time.sleep(0.05)
        if not quiet:
            raise FishballError("UNKNOWN", f"after stopping, the transmitters read "
                                           f"{[ch.tx_attenuation_db for ch in s.channels]} dB: "
                                           f"TREAT THEM AS LIVE and run ./devkit automation mute")
        return s

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.stop()


def _waveform_bytes(iq, channels):
    """Complex samples (full scale +-32767, as pyadi-iio takes them) as ci16
    bytes, interleaved per sample. Raw bytes pass through."""
    if isinstance(iq, (bytes, bytearray, memoryview)):
        return bytes(iq), channels or 1
    import numpy as np
    a = np.asarray(iq)
    if a.ndim == 1:
        a = a[None, :]
    out = np.empty((a.shape[1], a.shape[0], 2), dtype="<i2")
    out[..., 0] = np.clip(np.round(a.real.T), -32768, 32767)
    out[..., 1] = np.clip(np.round(a.imag.T), -32768, 32767)
    return out.tobytes(), a.shape[0]


def status_text(s):
    """A Status message as the lines `./devkit automation status` prints."""
    c = s.clock
    lock = lambda ok: "locked" if ok else "NOT LOCKED"
    lines = [
        f"Board         {s.model}",
        f"Firmware      {s.firmware or 'unknown'}, kernel {s.kernel}, server {s.server_version}",
        f"RX LO         {s.rx_lo_hz / 1e6:.6f} MHz",
        f"TX LO         {s.tx_lo_hz / 1e6:.6f} MHz",
        f"Sample rate   {s.sample_rate_hz / 1e6:g} MS/s, RF bandwidth RX {s.rx_rf_bandwidth_hz / 1e6:g} MHz, "
        f"TX {s.tx_rf_bandwidth_hz / 1e6:g} MHz",
    ]
    for i, ch in enumerate(s.channels, 1):
        muted = " (muted)" if ch.tx_attenuation_db <= -89.5 else "  <-- NOT MUTED"
        lines.append(f"Channel {i}     RX gain {ch.rx_gain_db:g} dB ({ch.rx_gain_mode}), RSSI {ch.rssi_db:g} dB, "
                     f"TX attenuation {ch.tx_attenuation_db:g} dB{muted}")
    lines += [
        f"Temperature   AD9361 {s.ad9361_temp_c:.1f} C, FPGA {s.fpga_temp_c:.1f} C",
        f"Clock         xo_correction {c.xo_correction_hz} Hz "
        f"(range {c.xo_correction_min_hz} to {c.xo_correction_max_hz}); "
        f"BBPLL {lock(c.bbpll_locked)}, RX synthesizer {lock(c.rx_synth_locked)}, "
        f"TX synthesizer {lock(c.tx_synth_locked)}",
    ]
    if c.measured:
        lines.append(f"Reference     measured {c.measured_reference_hz / 1e6:.5f} MHz, {c.measured_ppm:+.1f} ppm "
                     f"against the board's own crystal, over {c.measured_seconds:.0f} s")
    if s.transmitting:
        lines.append("Transmit      running (./devkit automation mute stops it)")
    busy = [n for n, on in (("receive", s.rx_buffer_busy), ("transmit", s.tx_buffer_busy)) if on]
    if busy:
        who = "; ".join(f"{h.buffer}: pid {h.pid} {h.command}" for h in s.holders) or "holder unknown"
        lines.append(f"Busy          {' and '.join(busy)} buffer in use ({who})")
    else:
        lines.append("Busy          no: both buffers are free")
    return "\n".join(lines)


def meta_of(recording):
    """A Recording's SigMF metadata as a dict."""
    return json.loads(pathlib.Path(recording.meta_path).read_text())
