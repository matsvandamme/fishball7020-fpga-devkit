# The automation server

A gRPC server on the board, on port 7020, and a Python client for your PC:
status, settings, the reference clock, receive captures, transmit, and
transmit plus capture in one call, for measurement scripts. To use it, see
[automate a measurement](radio/automate-measurements.md); for a complete
script to copy, [sweep both loopbacks](radio/sweep-a-loopback.md).

!!! danger "No authentication, like `iiod`"
    Anyone who can reach port 7020 can retune the radio and read what it
    receives. Keep the board on a network you trust
    ([networking](networking.md#what-dhcp-exposes)).

!!! warning "It transmits only what a person has vouched for"
    `Transmit` and `TransmitCapture` are the only calls that can raise a
    transmitter, and only on a channel with an affirmation on record
    (`./devkit tx-guard affirm 0` or `1`, after looking at the port). No other
    call can: `Configure` reads both attenuators before and after, and mutes
    and fails if either rose. `Mute` is always allowed. The rules are under
    [Transmitting](#transmitting).

## Commands

```bash
# run from: the repo root on your PC
./devkit automation install      # put the server on the board, as a service
./devkit automation status       # the board, the radio, the clock, who holds the buffers
./devkit automation clock --measure          # time the reference against the board's crystal
./devkit automation capture loop --samples 2e6 --channels 1,2   # loop.sigmf-data and loop.sigmf-meta, here
./devkit automation smoke        # an end-to-end check; receive only
./devkit automation mute         # both transmitters to the floor, read back
./devkit automation test         # the unit tests, against a fake board (no board needed)
./devkit automation uninstall
```

`BOARD` overrides the address (default `fishball.local`). The client runs in
its own venv, `tools/automation/.venv`, created on first use.

## The calls

Defined in [`tools/automation/fishball.proto`](../tools/automation/fishball.proto);
any gRPC client can use them. The Python client's method is in the second column.

| Call | Python | What it does |
|---|---|---|
| `GetStatus` | `status()` | model, firmware, kernel, both LOs, sample rate, bandwidths, each channel's gain, gain mode, RSSI and transmit attenuation, chip temperatures, whether a buffer is held and by which process, the clock |
| `Configure` | `configure(...)` | sets any of `rx_lo_hz`, `tx_lo_hz`, `sample_rate_hz`, `rx_rf_bandwidth_hz`, `tx_rf_bandwidth_hz`, `rx1_gain_mode`, `rx2_gain_mode`, `rx1_gain_db`, `rx2_gain_db`; returns the status read back afterwards |
| `GetClock` | `clock(measure, seconds)` | `xo_correction` and its range, the three PLL lock bits, and on request the measured reference |
| `SetXoCorrection` | `set_xo_correction(hz)` | tells the driver what the 40 MHz reference really runs at |
| `Capture` | `capture(samples, channels, path)` | records on the board, gap-free, into RAM; with `path` also fetches it as a SigMF pair and deletes it from the board |
| `Fetch`, `DeleteCapture` | `fetch(info, path)`, `delete(id)` | download or remove a capture left on the board |
| `Stream` | `stream(channels, samples)` | samples as they are received; each block carries `first_sample` and `dropped_samples` |
| `UploadWaveform` | `upload_waveform(iq)` | sends a waveform to the board once, into RAM; complex samples at ±32767 full scale, one channel or one per transmitter, a multiple of 32 samples, at most 64 MB. Returns its id |
| `DeleteWaveform` | `delete_waveform(w)` | removes it |
| `Transmit` | `transmit(w, channels, attenuation_db, pad_db, seconds, one_shot, cyclic_bound_s)` | plays a waveform, repeating, or once with `one_shot`. The board plays while the call is open; the reply is a stream of the read-back state every 0.25 s. The Python method returns once the board confirms it is playing at the asked attenuation |
| `TransmitCapture` | `transmit_capture(w, samples, tx_channels, rx_channels, attenuation_db, pad_db, settle_s, path)` | plays a waveform, records the receivers while it plays, then mutes and stops. Returns a capture like `Capture`; its SigMF metadata records what was transmitted |
| `Mute` | `mute()` | stops a running transmit; both transmitters to −89.75 dB, read back |

## Transmitting

```python
# run from: tools/automation, as: .venv/bin/python example.py
with board.transmit(w, channels=[1], attenuation_db=-40, pad_db=20) as tx:
    print(tx.state.tx1_attenuation_db)          # -40.0, read back from the chip
    rec = board.capture(samples=1_000_000, channels=[1], path="tone")
# here both transmitters read -89.75 dB, or stop() raised
```

**How a transmit starts.** Both attenuators are preset to −89.5 dB and read
back, the buffer is started, both are read again, and only then is the asked
attenuation written, and rewritten until the chip reads it. A channel not
playing is held at −89.75 dB. Starting with both at exactly −89.75 dB would let
the kernel restore the last stream's gain ([why](transmitter-safety.md#opening-a-transmit-buffer-is-not-a-neutral-act)),
and a value written before the start is not trusted after it. A one-shot has
finished before anything could be written after the start, so its own
attenuation is set first; it must therefore be above −89.5 dB.

**How it ends.** Both transmitters are muted and read back first, then the
buffer is released: the other order hands the next program your gain. It ends
when the client calls `stop()` or leaves the `with` block, when the client
disappears (a crash, a `kill -9`, a lost network), when `seconds` have passed,
when a one-shot has played, on `Mute`, and when the service stops; the systemd
unit also mutes after the server exits, whatever way it exited. `stop()` returns
only once the board reads both transmitters at the floor, and raises if it
does not.

**While it plays**, the server reads both attenuators every 0.25 s. A value
louder than asked mutes and fails the call. A playing channel found at the floor
ends the call with the note "the board muted TXn by itself": the kernel's own
bounds (the 60 s cyclic bound, the starve watchdog) do that.

**One transmit at a time**, and none while another program holds the transmit
buffer. `Configure` is refused while one runs.

**The repeating transmit is bounded by the board** to
`tx_cyclic_timeout_ms`, 60 s by default. A longer `seconds` is refused unless
the request also sets `cyclic_bound_s` (1 to 3600 s); the server restores the
board's own bound afterwards.

**Transmit and capture are not started together by the hardware.** The design
has no shared start for the transmit and receive DMA, so where the waveform
lands in a capture changes from one call to the next. For timing, capture a
reference: loop the second transmitter into the second receiver and measure
against that channel. Both see the same start, so their difference holds to a
fraction of a sample (measured below).

## What it refuses

| Request | Answer |
|---|---|
| a value the driver rejects | `FAILED_PRECONDITION`, with the driver's own error: never reported as success |
| an unknown gain mode, channel or setting | `INVALID_ARGUMENT`, before anything is written |
| `Configure`, `Capture`, `Stream` or a clock measurement while another program holds the buffer | `FAILED_PRECONDITION`, naming the process (for example `pid 311 (/usr/sbin/iiod …)`) |
| a capture larger than the board's free RAM | `INVALID_ARGUMENT`, with both sizes |
| a clock measurement above 20 MS/s | `INVALID_ARGUMENT`: lower `sample_rate_hz` first |
| a transmit on a channel with no affirmation | `FAILED_PRECONDITION`: "TX1 has no affirmation on record. Look at TX1A: is it terminated, or going through an attenuator? Then run ./devkit tx-guard affirm 0" |
| an attenuation louder than −10 dB with `pad_db` under 20 | `INVALID_ARGUMENT`. `pad_db` is the attenuator you have fitted between the transmitter and whatever it drives |
| `TransmitCapture` with `pad_db` under 20 | `INVALID_ARGUMENT`: it loops a transmitter into a receiver, at any attenuation |
| a one-shot at −89.5 dB or quieter | `INVALID_ARGUMENT` |
| a repeating transmit longer than the board's cyclic bound, without `cyclic_bound_s` | `INVALID_ARGUMENT`, naming the bound |
| a second transmit, or `Configure` during one | `FAILED_PRECONDITION`, "a transmit is running (Mute stops it)" |
| a waveform that is not a whole number of samples, not a multiple of 32, over 64 MB, or with more channels than transmitters named | `INVALID_ARGUMENT` |
| an attenuation the chip does not take, or a transmitter that rises on its own | `FAILED_PRECONDITION`; both muted and the buffer released before the answer |

## Measured on one board

Over Wi-Fi, board on gigabit Ethernet, 2026-10-05.

| | |
|---|---|
| Capture, RX1 + RX2 at 20 MS/s | 40 000 000 samples per channel (2 s, 320 MB) recorded in 2.2 s, 0 lost |
| Fetch | 320 MB in 19.5 s: **16.4 MB/s** |
| Live stream at 3 MS/s, one channel | 2.20 MS/s delivered, 77 %; the rest counted as dropped |
| Live stream at 20 MS/s, one channel | 3.33 MS/s delivered, 18 %; the rest counted as dropped |
| Reference clock, 30 s at 20 MS/s | 40.00030 MHz, +7.5 ppm against the Zynq's own crystal |
| After a reboot | the service is active again; both transmitters at −89.75 dB |
| Tone, 1 MHz from the LO at 868 MHz, TX1 at −40 dB → 20 dB → RX1, recorded by a separate `Capture` while `Transmit` ran | at +0.118 Hz from 1 MHz; noise floor −86.8 dBc |
| The client killed with `kill -9` while TX1 and TX2 played at −40 dB | both read −89.75 dB **46 ms** later, transmit buffer released |
| Pulsed chirp on TX1 and TX2, `TransmitCapture` on RX1 and RX2, three calls at 15.36 MS/s | the pulse landed at samples 4295, 7372 and 4439; RX1 − RX2 was −0.002 samples each time |
| [`examples/loopback_sweep.py`](../tools/automation/examples/loopback_sweep.py), TX1 → 20 dB → RX1 and TX2 → 30 dB → RX2 | 14 frequencies, 100 MHz to 5.8 GHz, in 15 s; between two runs the tone level moved at most 1.2 dB, the image up to 14.5 dB ([the result](radio/sweep-a-loopback.md#reading-the-result)) |
| [`examples/clock_stress.py`](../tools/automation/examples/clock_stress.py) | PASS in 66 s: 48 rate changes, 200 retunes, tones within 0.12 Hz at 433.92, 868 and 2400 MHz with the worst spur at −58.3 dBc, reference +5.5 ppm |

- **A capture is the way to get every sample.** It is recorded into RAM on the
  board at the radio's full rate, then fetched; its size is bounded by free RAM.
- **The live stream is for watching, at a few MS/s.** The server is pure Python
  and sends about 13 MB/s. Whatever it cannot send, it drops and counts:
  `dropped_samples` is measured against the radio's own clock, so a loss
  anywhere between the radio and your script shows.
- **The clock measurement** times the sample clock against
  `CLOCK_MONOTONIC_RAW`, the Zynq's own 33.333 MHz crystal. It tells a 40 MHz
  reference from a wrong one; over 30 s it resolves a few ppm.

## How it is built

| | |
|---|---|
| Server library | `python3-grpclib`, which is pure Python. Debian's `python3-grpcio` aborts on this board (`time_posix.cc: assertion failed: ts.tv_nsec`), a 64-bit-time fault in its armhf build |
| Board packages | `python3-grpclib`, `python3-protobuf` and `python3-libiio`, from apt. No pip on the board |
| Radio access | sysfs and debugfs for settings; `iio_readdev -u local:` for samples; libiio in the server's own process for transmit, so the buffer dies with it |
| Message types | loaded at run time from `fishball.desc`, the compiled `.proto`: generated code is tied to one protobuf version, and the board (3.21) and a PC differ |
| Service | `fishball-automation.service`; like `iiod`, it `Requires=fishball-rf-quiesce`, so it starts only if the boot-time transmitter mute was confirmed. `ExecStopPost` writes −89.75 dB to both attenuators after the server exits, however it exited |
| Captures and waveforms | in `/dev/shm/fishball-automation` (RAM); captures removed when fetched, and all of it when the server stops |
| Tests | 64, with the real server and client over localhost and only the board faked. The fake board copies the kernel's cached-gain restore, so a test fails if any transmit starts with both attenuators at the floor or is torn down before the mute. Run by the Host tools workflow; the Hardware workflow runs `smoke` on the board, which does not transmit |
