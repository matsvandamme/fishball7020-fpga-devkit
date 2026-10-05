"""What the server needs from the board, behind one interface.

SysfsBackend is the real one: it runs on the board and reads and writes the
radio through sysfs and debugfs, records samples with iio_readdev, and
transmits through libiio's Python binding (python3-libiio). FakeBackend stands
in for it in the tests, so the server's rules can be checked on any machine;
it models the two kernel behaviours the transmit rules exist for.
"""
import array
import fcntl
import glob
import os
import re
import subprocess
import threading
import time

MUTED_DB = -89.75
QUIET_DB = -89.5                     # one step above the floor: "quiet", but not the state that arms the cache restore
MUTE_TOL_DB = 0.26                   # one attenuator step is 0.25 dB
AFFIRM_FLAG = "/tmp/tx-antenna-affirmed.{}"   # tools/tx-guard.sh's record that a port was looked at
PHY, RX_DEV, TX_DEV, XADC = "ad9361-phy", "cf-ad9361-lpc", "cf-ad9361-dds-core-lpc", "xadc"
BYTES_PER_SAMPLE = 4                 # one channel: int16 I, int16 Q


class Refused(Exception):
    """The driver or the board refused a request; the text says why."""


class Busy(Exception):
    """Another process holds the buffer this request needs."""

    def __init__(self, buffer, holders):
        self.buffer, self.holders = buffer, holders
        who = ", ".join(f"pid {p} ({c})" for p, c in holders) or "an unnamed process"
        super().__init__(f"the {buffer} buffer is in use by {who}")


class Backend:
    """The operations the server uses. Attribute names are the driver's own."""

    def read(self, device, attr):
        raise NotImplementedError

    def write(self, device, attr, value):
        raise NotImplementedError

    def reg(self, address):
        """One AD9361 register, through debugfs."""
        raise NotImplementedError

    def identity(self):
        """(model, firmware, kernel)."""
        raise NotImplementedError

    def buffer_enabled(self, device):
        raise NotImplementedError

    def holders(self, device):
        """[(pid, command)] of the processes that have the device file open."""
        raise NotImplementedError

    def free_memory(self, directory):
        """Bytes a capture written into `directory` (in RAM) may use."""
        raise NotImplementedError

    def record(self, channels, samples, path):
        """Write `samples` per channel to `path` (ci16, interleaved); return bytes written."""
        raise NotImplementedError

    def open_stream(self, channels, block_bytes):
        """Return (read_block, close): read_block() gives block_bytes of samples, or b'' at the end."""
        raise NotImplementedError

    def affirmed(self, index):
        """Whether a person recorded that transmit port `index` (0 = TX1A) is terminated."""
        raise NotImplementedError

    def tx_start(self, channels, data, cyclic):
        """Enable the transmit buffer for `channels` (1, 2) and push `data`
        (ci16, interleaved per sample). Returns a handle for tx_stop. The
        caller sets the attenuators before and after; this only moves samples."""
        raise NotImplementedError

    def tx_stop(self, handle):
        """Release the transmit buffer. The caller mutes first: the kernel's
        stop hook keeps whatever attenuation it finds, for the next enable."""
        raise NotImplementedError

    # ---- built on the above -------------------------------------------------

    def number(self, device, attr):
        """An attribute as a float: '71.000000 dB' and '2400000000' both parse."""
        return float(self.read(device, attr).split()[0])

    def tx_attenuation(self):
        return [self.number(PHY, f"out_voltage{ch}_hardwaregain") for ch in (0, 1)]

    def mute(self):
        """Both transmitters to the floor, read back. Both are always tried,
        whatever the first does. Raises Refused if either did not go."""
        failed = []
        for ch in (0, 1):
            try:
                self.write(PHY, f"out_voltage{ch}_hardwaregain", f"{MUTED_DB}")
            except Refused as e:
                failed.append(f"TX{ch + 1}: {e}")
        got = self.tx_attenuation()
        if failed or any(g > MUTED_DB + MUTE_TOL_DB for g in got):
            raise Refused(f"mute did not apply: the attenuators read {got[0]} and {got[1]} dB"
                          f"{' (' + '; '.join(failed) + ')' if failed else ''}. TREAT BOTH TRANSMIT PORTS AS LIVE")
        return got

    def require_free(self, device, buffer):
        if self.buffer_enabled(device):
            holders = self.holders(device)
            if not holders:
                # Flagged enabled, but no process has the device open: a reader
                # that was killed before it could switch the buffer off.
                self._clear_stale(device)
                if not self.buffer_enabled(device):
                    return
            raise Busy(buffer, holders)

    def _clear_stale(self, device):
        """Switch off a buffer that is flagged enabled but that no process holds."""


def duplicate_channel(data):
    """A one-channel waveform as the same samples on both channels."""
    pairs = array.array("i")
    assert pairs.itemsize == 4
    pairs.frombytes(data)
    out = array.array("i", bytes(len(data) * 2))
    out[0::2] = pairs
    out[1::2] = pairs
    return out.tobytes()


def stream_channels(channels):
    """iio_readdev's channel names for RX1 (voltage0/1) and RX2 (voltage2/3)."""
    names = []
    for ch in sorted(channels):
        names += [f"voltage{2 * (ch - 1)}", f"voltage{2 * (ch - 1) + 1}"]
    return names


class SysfsBackend(Backend):
    IIO = "/sys/bus/iio/devices"
    DEBUG = "/sys/kernel/debug/iio"

    def __init__(self):
        self._lock = threading.Lock()
        self._dirs = {}
        for d in glob.glob(f"{self.IIO}/iio:device*"):
            try:
                self._dirs[open(f"{d}/name").read().strip()] = d
            except OSError:
                pass
        if PHY not in self._dirs:
            raise Refused(f"no {PHY} device: the radio did not start (see `dmesg | grep ad9361`)")

    def _path(self, device, attr):
        if device not in self._dirs:
            raise Refused(f"no IIO device named {device}")
        return f"{self._dirs[device]}/{attr}"

    def read(self, device, attr):
        try:
            return open(self._path(device, attr)).read().strip()
        except OSError as e:
            raise Refused(f"cannot read {device} {attr}: {e.strerror}") from e

    def write(self, device, attr, value):
        try:
            with open(self._path(device, attr), "w") as f:
                f.write(str(value))
        except OSError as e:
            raise Refused(f"the driver refused {attr} = {value}: {e.strerror}") from e

    def reg(self, address):
        path = f"{self.DEBUG}/{os.path.basename(self._dirs[PHY])}/direct_reg_access"
        with self._lock:                        # write the address, then read: one at a time
            try:
                with open(path, "w") as f:
                    f.write(f"0x{address:03X}")
                return int(open(path).read().strip(), 16)
            except OSError as e:
                raise Refused(f"cannot read register 0x{address:03X}: {e.strerror}") from e

    def identity(self):
        def first(path, default=""):
            try:
                return open(path, "rb").read().rstrip(b"\0\n").decode(errors="replace")
            except OSError:
                return default
        firmware = ""
        for line in first("/opt/VERSIONS").splitlines():
            if line.startswith("device-fw "):
                firmware = line.split(None, 1)[1]
        return first("/proc/device-tree/model"), firmware, os.uname().release

    def buffer_enabled(self, device):
        try:
            return open(self._path(device, "buffer/enable")).read().strip() == "1"
        except OSError:
            return False

    def holders(self, device):
        node = "/dev/" + os.path.basename(self._dirs[device])
        found = {}
        for fd in glob.glob("/proc/[0-9]*/fd/*"):
            try:
                if os.readlink(fd) != node:
                    continue
                pid = int(fd.split("/")[2])
                cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
                found[pid] = cmd.strip()[:80]
            except (OSError, ValueError):
                continue
        return sorted(found.items())

    def free_memory(self, directory):
        available = 0
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                available = int(line.split()[1]) * 1024 * 6 // 10    # leave the system 40 %
        fs = os.statvfs(directory)                                  # the tmpfs has its own ceiling
        return min(available, fs.f_bavail * fs.f_frsize)

    def _readdev(self, channels, samples=None):
        cmd = ["iio_readdev", "-u", "local:", "-b", "1048576"]
        if samples:
            cmd += ["-s", str(samples)]
        return cmd + [RX_DEV] + stream_channels(channels)

    def record(self, channels, samples, path):
        with open(path, "wb") as out:
            r = subprocess.run(self._readdev(channels, samples), stdout=out, stderr=subprocess.PIPE)
        size = os.path.getsize(path)
        self._clear_stale(RX_DEV)
        if r.returncode or size != samples * BYTES_PER_SAMPLE * len(channels):
            os.unlink(path)
            raise Refused(f"the capture came up short ({size} bytes): "
                          f"{r.stderr.decode(errors='replace').strip()[-200:] or 'iio_readdev gave no reason'}")
        return size

    def open_stream(self, channels, block_bytes):
        p = subprocess.Popen(self._readdev(channels), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)
        fd = p.stdout.fileno()
        try:                                    # a 1 MB pipe instead of 64 kB: a block then takes
            fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, 1 << 20)   # a few reads, not dozens, and each read
        except OSError:                         # has to win Python's lock back from the sender
            pass

        def read_block():
            buf = bytearray(block_bytes)
            view, got = memoryview(buf), 0
            while got < block_bytes:
                n = os.readv(fd, [view[got:]])
                if not n:
                    return b""
                got += n
            return buf

        def close():
            # SIGTERM first: iio_readdev then switches the buffer off itself.
            # Killed outright, it leaves buffer/enable at 1 with nobody
            # holding it, and every later capture is refused as "busy".
            p.terminate()
            try:
                p.wait(3)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            p.stdout.close()
            self._clear_stale(RX_DEV)
        return read_block, close

    def affirmed(self, index):
        try:
            return os.path.getsize(AFFIRM_FLAG.format(index)) > 0       # an empty flag is not an affirmation
        except OSError:
            return False

    def tx_start(self, channels, data, cyclic):
        import iio                                  # python3-libiio; only the transmit path needs it
        ctx = iio.Context("local:")
        dev = ctx.find_device(TX_DEV)
        if dev is None:
            raise Refused(f"no {TX_DEV} device")
        want = set(stream_channels(channels))
        for i in range(4):
            dev.find_channel(f"voltage{i}", True).enabled = f"voltage{i}" in want
        samples = len(data) // (BYTES_PER_SAMPLE * len(channels))
        handle = {"ctx": ctx, "buf": None}
        try:
            handle["buf"] = iio.Buffer(dev, samples, cyclic)     # this is the enable
        except OSError as e:
            raise Refused(f"the transmit buffer could not start: {e}") from e
        written = handle["buf"].write(bytearray(data))
        if written != len(data):
            self.tx_stop(handle)
            raise Refused(f"the transmit buffer took {written} of {len(data)} bytes")
        handle["buf"].push()
        return handle

    def tx_stop(self, handle):
        handle["buf"] = None                        # the last reference: libiio destroys the buffer now
        handle["ctx"] = None

    def _clear_stale(self, device):
        """Switch off a buffer that is flagged enabled but that no process holds."""
        if self.buffer_enabled(device) and not self.holders(device):
            try:
                self.write(device, "buffer/enable", 0)
            except Refused:
                pass


class FakeBackend(Backend):
    """An in-memory board, for the tests. Its sample stream counts up, so a
    test can tell exactly which samples arrived."""

    def __init__(self):
        self.attrs = {
            (PHY, "out_altvoltage0_RX_LO_frequency"): "2400000000",
            (PHY, "out_altvoltage1_TX_LO_frequency"): "2450000000",
            (PHY, "in_voltage_sampling_frequency"): "30720000",
            (PHY, "in_voltage_rf_bandwidth"): "18000000",
            (PHY, "out_voltage_rf_bandwidth"): "18000000",
            (PHY, "in_voltage_gain_control_mode_available"): "manual fast_attack slow_attack hybrid",
            (PHY, "xo_correction"): "40000000",
            (PHY, "xo_correction_available"): "[39992000 1 40008000]",
            (TX_DEV, "tx_cyclic_timeout_ms"): "60000",
            (PHY, "in_temp0_input"): "44700",
            (XADC, "in_temp0_raw"): "2600", (XADC, "in_temp0_scale"): "123.040771484",
            (XADC, "in_temp0_offset"): "-2219",
        }
        for ch in (0, 1):
            self.attrs[(PHY, f"in_voltage{ch}_hardwaregain")] = "71.000000 dB"
            self.attrs[(PHY, f"in_voltage{ch}_gain_control_mode")] = "slow_attack"
            self.attrs[(PHY, f"in_voltage{ch}_rssi")] = "115.50 dB"
            self.attrs[(PHY, f"out_voltage{ch}_hardwaregain")] = f"{MUTED_DB:.6f} dB"
        self.registers = {0x05E: 0x81, 0x247: 0x02, 0x287: 0x02}
        self.enabled = {RX_DEV: False, TX_DEV: False}
        self.held = {RX_DEV: [], TX_DEV: []}
        self.memory = 512 << 20
        self.refuse = {}                 # (device, attr) -> error text
        self.writes = []                 # every write, in order
        self.on_write = None             # a hook: called after each write
        self.stream_blocks = None        # limit the stream to this many blocks
        # The transmit side, and the kernel behaviours the rules are for:
        self.affirmations = set()        # port indexes a person has affirmed
        self.cached = [-61.5, -61.5]     # what the last stream's teardown kept
        self.floor_enables = 0           # enables with both attenuators at the exact floor
        self.teardown_attenuation = []   # what each teardown found: must always be the floor
        self.tx_writes = []              # (channel, value, buffer enabled at the time)
        self.loudest = [MUTED_DB, MUTED_DB]   # the loudest each channel ever read while enabled
        self.stuck = {}                  # channel -> where its attenuator stays while transmitting, whatever is written
        self.tx_pushed = None            # (channels, bytes, cyclic) of the last start
        self.stream_pace = 0.001         # seconds per block: a radio delivers at its own rate
        self.sim_time = 0.0              # the radio's own clock: advances one block per block read

    def read(self, device, attr):
        if (device, attr) not in self.attrs:
            raise Refused(f"cannot read {device} {attr}: No such file or directory")
        return self.attrs[(device, attr)]

    def write(self, device, attr, value):
        self.writes.append((device, attr, str(value)))
        if (device, attr) in self.refuse:
            raise Refused(f"the driver refused {attr} = {value}: {self.refuse[(device, attr)]}")
        if (device, attr) not in self.attrs:
            raise Refused(f"the driver refused {attr} = {value}: No such file or directory")
        unit = " dB" if attr.endswith("hardwaregain") else ""
        m = re.fullmatch(r"out_voltage(\d)_hardwaregain", attr)
        if m:
            ch = int(m.group(1))
            self.tx_writes.append((ch, float(value), self.enabled[TX_DEV]))
            if ch in self.stuck and self.enabled[TX_DEV] and float(value) > MUTED_DB:
                value = self.stuck[ch]                # a mute still lands
        self.attrs[(device, attr)] = (f"{float(value):.6f}" if unit else str(value)) + unit
        if m:
            self._note_loudest()
        if self.on_write:
            self.on_write(device, attr, value)

    def set_tx(self, ch, value):
        """The board changing an attenuator by itself (a test's doing)."""
        self.attrs[(PHY, f"out_voltage{ch}_hardwaregain")] = f"{float(value):.6f} dB"
        self._note_loudest()

    def _note_loudest(self):
        if self.enabled[TX_DEV]:
            for ch, a in enumerate(self.tx_attenuation()):
                self.loudest[ch] = max(self.loudest[ch], a)

    def affirmed(self, index):
        return index in self.affirmations

    def tx_start(self, channels, data, cyclic):
        if self.enabled[TX_DEV]:
            raise Busy("transmit", self.held[TX_DEV])
        if all(a == MUTED_DB for a in self.tx_attenuation()):
            # The kernel: both at the exact floor reads as "muted", and the
            # enable restores the gain the last stream's teardown kept.
            self.floor_enables += 1
            for ch in (0, 1):
                self.attrs[(PHY, f"out_voltage{ch}_hardwaregain")] = f"{self.cached[ch]:.6f} dB"
        self.enabled[TX_DEV] = True
        self._note_loudest()
        self.tx_pushed = (list(channels), len(data), cyclic)
        return object()

    def tx_stop(self, handle):
        # The kernel's stop hook: keep what it finds, then apply the floor.
        found = self.tx_attenuation()
        self.teardown_attenuation.append(found)
        self.cached = found
        for ch in (0, 1):
            self.attrs[(PHY, f"out_voltage{ch}_hardwaregain")] = f"{MUTED_DB:.6f} dB"
        self.enabled[TX_DEV] = False

    def reg(self, address):
        return self.registers.get(address, 0)

    def identity(self):
        return "FISH Ball PlutoSDR Rev.A (Z7020/AD9361)", "v0-test", "6.12.0-test"

    def buffer_enabled(self, device):
        return self.enabled[device]

    def holders(self, device):
        return list(self.held[device])

    def free_memory(self, directory):
        return self.memory

    @staticmethod
    def _samples(first, count, n_channels):
        import array
        a = array.array("h")
        for i in range(first, first + count):
            for _ in range(n_channels):
                a.append(i % 32768)          # I counts the sample index
                a.append(-(i % 32768))       # Q is its negative
        return a.tobytes()

    def record(self, channels, samples, path):
        with open(path, "wb") as f:
            f.write(self._samples(0, samples, len(channels)))
        return samples * BYTES_PER_SAMPLE * len(channels)

    def open_stream(self, channels, block_bytes):
        state = {"n": 0, "blocks": 0}
        per = block_bytes // (BYTES_PER_SAMPLE * len(channels))

        def read_block():
            if self.stream_blocks is not None and state["blocks"] >= self.stream_blocks:
                return b""
            time.sleep(self.stream_pace)
            self.sim_time += per / float(self.attrs[(PHY, "in_voltage_sampling_frequency")])
            data = self._samples(state["n"], per, len(channels))
            state["n"] += per
            state["blocks"] += 1
            return data
        return read_block, lambda: None


def measure_sample_rate(read_block, seconds, bytes_per_sample, clock=None, skip=2.0):
    """The delivered sample rate, from a straight-line fit of samples against
    the raw monotonic clock (the Zynq's own crystal, which network time does
    not slew). The first `skip` seconds are left out while the stream settles."""
    clock = clock or (lambda: time.clock_gettime(time.CLOCK_MONOTONIC_RAW))
    points, total, t0 = [], 0, clock()
    while clock() < t0 + skip + seconds:
        block = read_block()
        if not block:
            break
        total += len(block)
        now = clock()
        if now >= t0 + skip:
            points.append((now, total))
    if len(points) < 3:
        raise Refused("the reference measurement got too few samples to fit")
    n = len(points)
    mt, mb = sum(t for t, _ in points) / n, sum(b for _, b in points) / n
    slope = sum((t - mt) * (b - mb) for t, b in points) / sum((t - mt) ** 2 for t, _ in points)
    return slope / bytes_per_sample, points[-1][0] - points[0][0]


def parse_range(text):
    """'[39992000 1 40008000]' -> (min, step, max)."""
    lo, step, hi = (int(x) for x in re.findall(r"-?\d+", text)[:3])
    return lo, step, hi
