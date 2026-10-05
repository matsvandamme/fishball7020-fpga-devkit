# The automation server

A gRPC server on the board, on port 7020, and a Python client for your PC:
status, settings, the reference clock and receive captures, for measurement
scripts. To use it, see [automate a measurement](radio/automate-measurements.md).

!!! danger "No authentication, like `iiod`"
    Anyone who can reach port 7020 can retune the radio and read what it
    receives. Keep the board on a network you trust
    ([networking](networking.md#what-dhcp-exposes)).

!!! note "This version never transmits"
    No call can raise a transmitter. `Configure` reads both transmit
    attenuators before and after, and mutes and fails if either rose. `Mute` is
    always allowed.

## Commands

```bash
# run from: the repo root on your PC
./devkit automation install      # put the server on the board, as a service
./devkit automation status       # the board, the radio, the clock, who holds the buffers
./devkit automation clock --measure          # time the reference against the board's crystal
./devkit automation capture loop --samples 2e6 --channels 1,2
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
| `Mute` | `mute()` | both transmitters to −89.75 dB, read back |

## What it refuses

| Request | Answer |
|---|---|
| a value the driver rejects | `FAILED_PRECONDITION`, with the driver's own error: never reported as success |
| an unknown gain mode, channel or setting | `INVALID_ARGUMENT`, before anything is written |
| `Configure`, `Capture`, `Stream` or a clock measurement while another program holds the buffer | `FAILED_PRECONDITION`, naming the process (for example `pid 311 (/usr/sbin/iiod …)`) |
| a capture larger than the board's free RAM | `INVALID_ARGUMENT`, with both sizes |
| a clock measurement above 20 MS/s | `INVALID_ARGUMENT`: lower `sample_rate_hz` first |

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
| Board packages | `python3-grpclib` and `python3-protobuf`, from apt. No pip on the board |
| Radio access | sysfs and debugfs for settings; `iio_readdev -u local:` for samples |
| Message types | loaded at run time from `fishball.desc`, the compiled `.proto`: generated code is tied to one protobuf version, and the board (3.21) and a PC differ |
| Service | `fishball-automation.service`; like `iiod`, it `Requires=fishball-rf-quiesce`, so it starts only if the boot-time transmitter mute was confirmed |
| Captures | in `/dev/shm/fishball-automation` (RAM); removed when fetched, and when the server stops |
| Tests | 40, with the real server and client over localhost and only the board faked; run by the Host tools workflow. The Hardware workflow runs `smoke` on the board |

Not in this version: transmitting, and transmit plus capture in one call.
