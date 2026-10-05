# MATLAB

What to install for MATLAB and Simulink, where MathWorks' ADALM-Pluto support
package falls short on this board, and the `fishball` package and blocks this
repository adds to get around it. To check MATLAB and run the first example,
see [use MATLAB](radio/use-matlab.md); then the
[MATLAB examples](../examples/matlab/README.md).

`./devkit matlab` checks MATLAB and the board in a few seconds; from a MATLAB
prompt the same check is `fishball.doctor`. If MATLAB is not on `PATH`, set
`MATLAB_BIN` to the binary.

- **firmware update offer:** **never accept**: that image is for a different board, and there is no undo
- **full scale:** `int16`: **±2047**; `double`/`single`: **±1.0**; transmit: **±32767**
- **channels:** `sdrrx`/`sdrtx` see **only RX1/TX1**; RX2 and TX2 through the `fishball` package
- **changing a setting:** release and re-create: a property set on a running object does nothing
- **Simulink blocks:** must run with **Simulate using = Interpreted execution**
- **listening:** engage the FPGA ÷8 decimator, or the sound card starves

## Never let MATLAB update your firmware

!!! danger "Never accept MATLAB's offer to \"switch the firmware version\""
    The ADALM-Pluto support package is tested against Pluto firmware `v0.39`, sees
    this board's version, and makes the offer through the Hardware Setup App. That
    image is for an ADALM-Pluto (Zynq-7010, AD9363); this board is a Zynq-7020 with
    an AD9361 and, on the common variant, a power amplifier. **There is no undo.**

`fishball.connect` suppresses that offer and prints the safe half of the warning
once per session; `sdrrx` used directly shows MathWorks' original, offer and all.

## What you need

| | |
|---|---|
| MATLAB | tested with R2026a |
| **Communications Toolbox** | required |
| **ADALM-Pluto support package** | required for live radio; about 1 GB. Tested with 26.1.7 |
| DSP System Toolbox | `audioDeviceWriter` in example 02's listening mode |
| Simulink | example 06, and the `RxSource`/`TxSink` blocks |
| HDL Coder | **not used** |

Without the support package every analysis still runs on a capture file; see
[No support package](#no-support-package).

## Three things that will bite you

**1. Full scale differs by data type.** The converters are 12-bit,
sign-extended into `int16`; *full scale* is the largest representable value, and
every dBFS level is relative to it.

| what you asked for | what you get | full scale |
|---|---|---|
| `OutputDataType` `int16` | raw converter counts | **±2047** |
| `OutputDataType` `double` or `single` | counts ÷ **2048** | **±1.0** |
| transmit | MSB-aligned into a 12-bit DAC | **±32767** |

!!! warning "Dividing receive counts by 32768 makes every absolute level 24.09 dB low"
    Uniformly, so nothing looks wrong and every ratio (SNR, EVM) is unchanged.
    `fishball.spectrum` takes a `FullScale` argument and defaults to 2047.

**2. Setting a property on a running object does nothing**, without an error.
Changing `.Gain` on a locked System object is ignored; release and re-create:

```matlab
% run from: the MATLAB prompt
rx.Gain = 40;                                        % silently ignored
release(rx); rx = fishball.connect('Gain', 40);      % what you meant
```

**3. `sdrrx` and `sdrtx` see only one channel.** Both reject anything but
`ChannelMapping` = 1 (`ChannelMapping must be equal to 1`): the support package
is written for the 1R1T ADALM-Pluto. This board is 2R2T, so RX2 and TX2 exist,
only through the `fishball` package:

| | RX1 / TX1 | RX2 / TX2 |
|---|---|---|
| receive | `sdrrx` | `fishball.capture2` → `iio_readdev` |
| transmit | `sdrtx` | `fishball.safeTransmit` → `iio_writedev -c` |

Both return something `release()` stops, so your code does not branch.

## No support package

Every analysis in the examples runs on a capture file, so base MATLAB plus
Communications Toolbox is enough:

```bash
# run from: the repo root
./tools/sigmf-capture.py record air --rate 3e6 --freq 868e6 --seconds 2
```

```matlab
% run from: the MATLAB prompt, with the repo root as the current folder
addpath matlab
[x, meta] = fishball.readSigMF('air.sigmf-meta');
[db, f]   = fishball.spectrum(x, meta.SampleRate, 'FullScale', meta.FullScale);
plot((meta.CenterFrequency + f)/1e6, db); grid on
```

`readSigMF` reads exactly what `tools/sigmf-capture.py` writes, full scale
included, and matches numpy on the same file.

## Streaming, and letting the fabric help

| At 2.4 MS/s, 0.2 s frames | |
|---|---|
| reading (real-time limited) | 179.7 ms |
| DSP | 11.3 ms |
| each 200 ms of audio costs | ~212 ms: **the sound card starves indefinitely** |

The fix is the **÷8 decimating filter in the FPGA fabric** (the programmable
logic in front of the ARM cores): the host then reads 288 kHz instead of
2.304 MHz.

```
3.2 s of audio    3.39 s of wall clock  ->  2.64 s
40 s of listening    113 underruns      ->  0
```

There is no "filter on" attribute: writing the ADC device's `sampling_frequency`
to one eighth of the converter rate engages it (`GP_CONTROL` bit 0, the bypass
mux).

!!! warning "It is only safe on both receivers because of patch `0021`"
    On a `STOCK_RX_FILTER=1` build it aliases RX2 by about 70 dB. See
    [both-receive-channels.md](both-receive-channels.md).

## Transmitting

Three examples transmit: **03** (the modulated link), **04** with `TxChannel`
(`PadDb` then required), and **06**'s `fishball_qam16.slx` (`PadDb` defaults to
20).

!!! danger "Read [transmitter-safety.md](transmitter-safety.md) before anything radiates"
    The board reaches about **+19 dBm** and its receive input is rated **+2.5 dBm**
    absolute maximum, so a loopback needs **at least 20 dB** of attenuation.

| `fishball.safeTransmit` | Why |
|---|---|
| will not start without `PadDb` | nothing on the board senses the transmit port, so the number has to come from you |
| reads the attenuation back **off the chip** after the buffer starts, and stops the transmitter if it disagrees by more than 0.5 dB | patch `0005` restores a cached attenuation when a buffer opens |
| releasing a transmitter waits for its `iio_writedev` to exit | without the wait the kernel's close hook mutes the transmitter *after* the next object has set its gain, and every second transmitter comes up silent at −89.75 dB |

## Simulink

Two blocks in `matlab/+fishball/` replace the stock ADALM-Pluto block, which
also enforces `ChannelMapping must be equal to 1`. Drop a **MATLAB System** block
and point it at the class:

| | |
|---|---|
| `fishball.RxSource` | receive. RX1, RX2 or both; the FPGA ÷8 decimator; a telemetry output |
| `fishball.TxSink` | transmit. TX1 or TX2; the sample-locked header pins; a pad guard |

Parameters use the usual SDR names (`BasebandSampleRate`, `RFBandwidth`,
`RFPort`, `GainSource`, `SamplesPerFrame`);
[example 06](../examples/matlab/06-simulink/README.md) lists every dialog group.

### Set "Simulate using" to Interpreted execution

!!! warning "Required"
    These blocks reach the radio through `system()`, which has no generated
    equivalent. With the default, **Code generation**, the model fails to compile
    with `An error occurred in the block '...' during compile`.

In the Block Parameters dialog, set the **Simulate using** dropdown at the bottom
to `Interpreted execution`; it saves with the model. The generators in example 06
set it for you. From the command line, with the block selected (`gcb` is "get
current block"):

```matlab
% run from: the MATLAB prompt, with the model open and the block selected
set_param(gcb, 'SimulateUsing', 'Interpreted execution')
```

### The model can drive the radio

`ControlPorts` turns settings into **input ports**:

| `ControlPorts` | inputs |
|---|---|
| `'none'` | none; dialog values are fixed |
| `'tune'` | `Fc`, centre frequency in Hz |
| `'full'` | `Fc`, `gain` (dB), `BW` (Hz) |
| `'all'` | `Fc`, `gain1`, `gain2`, `BW`, `gainMode`, `RFport` |

```
gainMode   0 manual   1 AGC slow attack   2 AGC fast attack   3 hybrid
RFport     1 A Balanced ... 9 C_P, 10 TX Monitor 1, 11 TX Monitor 2
           (this firmware accepts only 1; see below)
```

- `gain1` and `gain2` are separate because the receivers differ by ~1.5 dB.
- **`NaN` on a port means "leave this alone".**
- **A value is pushed only when it changes**, at 10–30 ms per `iio_attr` round
  trip plus a stream rebuild. Drive these from something slow (a slider, a
  staircase), not a per-frame signal.
- **`BasebandSampleRate` and `FabricDecimation` are not inputs**; `release` and
  re-create the block to change them.
- **A change rebuilds the stream, and must:** samples taken at the old setting
  sit in `iio_readdev`, the FIFO, the socket and the DMA ring. Without a rebuild a
  500 kHz retune shows the old offset for 34 more frames.

`examples/matlab/06-simulink/fishball_scanner.slx` walks the oscillator across
88–108 MHz in 70 looks of 288 kHz.

### Two levers this firmware refuses

Both are offered in the dialog; the firmware rejects both with
`Invalid argument (22)`:

- **`RFPort`**: only `A_BALANCED`, although `rf_port_select_available` lists
  twelve.
- **`EnableRxFIR`**: nothing to enable until coefficients are loaded through
  `filter_fir_config`; design taps with `firmware/scripts/gen_fir_coe.m`.

The quadrature, RF DC and baseband DC tracking settings do apply. A refused write
**warns once per attribute** with the chip's own message.

### Rules for System objects that touch the radio

- **Do not open the radio in `setupImpl`.** Simulink also calls it at compile, so
  a transmitter set up there starts, stops and starts again. Open lazily on the
  first step; keep argument checks in setup (`TxSink` checks `PadDb` there, so a
  bad pad fails before anything radiates).
- **Write the transmit gain until the chip agrees.** Patch `0005` restores a
  cached attenuation when the hardware buffer starts. `TxSink` rewrites until the
  read-back matches, up to twelve attempts, then stops with
  `Asked for ... dB, chip reports ... dB after 12 attempts`.
- **Measure a constellation the way it is drawn.** Normalising symbols before
  comparing measures tightness, not position: a constellation at 1.42× the
  reference reads 6.3 % normalised and 42.3 % as plotted. Check the amplitude
  ratio too.

`examples/matlab/06-simulink/fishball_qam16.slx` is a worked 16-QAM link (TX1 →
20 dB pad → RX1, 900 MHz, 144 ksym/s): **6.7 % EVM as plotted**, amplitude ratio
1.003, peak 324 of 2047. It relies on the ÷8 decimator; at 2.304 MSPS MATLAB
falls ~34 frames behind and the constellation is a blob.

## The firmware version string

On any version other than `v0.39` the support package raises
`plutoradio:sysobj:FirmwareIncompatible`, a warning whose construction throws
for some version strings and aborts the connection, even with
`warning('off','all')`:

```
In 'plutoradio:sysobj:FirmwareIncompatible', data type supplied is incorrect
for parameter {1}.
```

It depends on the shape of `fw_version` in `/etc/libiio.ini`:

| `fw_version` | result |
|---|---|
| `v2.0`, `2.0`, `v2.0.1`, `v2.0-dirty`, `v0.39`, `v0.39-9-gdeadbeef` | **connects** |
| `v2.0-9-g5ae29d94-dirty`, `v2.0-9-g5ae29d94`, `v2.0-9-gabcdef` | **fails** |

So `fishball-identity` on the board publishes the release in `fw_version` and the
full `git describe` in `fw_build` (e.g. `fw_version=v2.0`,
`fw_build=v2.0-9-g5ae29d94-dirty`). If a board still reports a describe string,
fix it on the board:

```bash
# run from: the board (Debian root, v2.x)
/usr/local/sbin/fishball-identity   # rewrites /etc/libiio.ini
systemctl restart iiod              # iiod reads it when it starts
```

v1.x (Buildroot) is untested with MATLAB; the fix is the same if it breaks.

## Troubleshooting

| | |
|---|---|
| `No board answered on fishball.local…` | Not on the network. `BOARD=192.168.2.1 matlab` on the USB cable, or `./devkit status` |
| MATLAB offers to update the firmware | **Refuse.** See [above](#never-let-matlab-update-your-firmware) |
| `data type supplied is incorrect for parameter {1}` | The [`fw_version` shape](#the-firmware-version-string) |
| `already owned by a block, block dialog, or System object` | Left over from an earlier failed setup. `clear all` |
| `-16 EBUSY` | A killed client holds the DMA on the board; `killall iiod` over ssh |
| Everything reads near zero | Antenna on the other port? `'RxChannel', 2` |
| Audio underruns while listening | See [streaming](#streaming-and-letting-the-fabric-help) |
| Simulink: `An error occurred in the block '...' during compile` | [Interpreted execution](#set-simulate-using-to-interpreted-execution) |
| A licence error naming a toolbox | The examples say which; the SigMF path needs only Communications Toolbox |

## Where things are

| | |
|---|---|
| [`matlab/+fishball/`](../matlab/+fishball/) | `connect`, `capture2`, `spectrum`, `phase`, `evm`, `qam`, `safeTransmit`, `readSigMF`, `doctor`, and the blocks `RxSource` and `TxSink` |
| [`examples/matlab/`](../examples/matlab/) | six examples, receive-first; 06 is Simulink |
| [`tools/matlab.sh`](../tools/matlab.sh) | what `./devkit matlab` runs |
