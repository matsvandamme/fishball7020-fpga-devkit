# Examples

Three GNU Radio flowgraphs, easy to hard, each one a thing you can *watch*
rather than just run. They exist because a spectrum that looks right tells you
almost nothing, and every control here is wired to a number so you can break
the measurement on purpose and see what it cost.

**Jargon, once.** *IQ* is a complex sample: two numbers per instant, which is
what lets a radio tell a signal above the tuned frequency from one below it.
*dBFS* is decibels relative to the converter's full scale - a level, not a
power, and never dBm; nothing in this repository is calibrated to absolute
power. *EVM* is how far a received symbol lands from where it should, as a
percentage. *Coherence* is how much two receivers are hearing the same thing,
0 to 1.

| | What it teaches | Transmits? |
|---|---|---|
| [**01 - dynamic range, and how to lose it**](01-dynamic-range/) | Windows, offset tuning, AGC and averaging, each with a number attached | no |
| [**02 - a modulated link you can watch**](02-modulated-link/) | QPSK/QAM end to end: constellation, eye, live EVM | **yes** |
| [**03 - two coherent receivers**](03-coherent-receivers/) | The thing a one-channel radio cannot do: stable phase between RX1 and RX2 | no |

Start at 01 even if you know GNU Radio. It is the one that sets up the habit
the other two rely on - that a spectrum is a measurement with a definition,
and the definition is yours.

## Before you start

You need the board on the network and GNU Radio 3.10 on your host.

```bash
# run from: the repo root
./devkit status                 # is the board there, and what is it running?
python3 tools/board_addr.py     # the address the flowgraphs use, by name
gnuradio-companion --version    # 3.10.x; these were built against 3.10.7
```

Every flowgraph looks the board up as `ip:fishball.local`. If mDNS does not
work on your network, `tools/board_addr.py` prints a numeric address - put
`'ip:192.168.x.y'` in the `uri` variable instead.

## Running one

Open it in GRC, read the comment block at the top left, and press play:

```bash
# run from: the repo root
gnuradio-companion examples/01-dynamic-range/dynamic_range.grc
```

Or without the GUI editor, which is also how CI checks them:

```bash
# run from: the repo root
cd examples/01-dynamic-range && grcc -o . dynamic_range.grc && python3 fishball_dynamic_range.py
```

`grcc` writes a `fishball_*.py` beside the `.grc`, plus one module per embedded
block. Those are generated files and are gitignored; the `.grc` is the source.

## 02 transmits. Read this.

**The board reaches roughly +19 dBm at an antenna port, through a power
amplifier, anywhere from 70 MHz to 6 GHz.** Transmitting without a licence is
illegal across nearly all of that. What leaves the port is your
responsibility. The default centre frequency is 2437 MHz, inside the 2.4 GHz
ISM band, because that is the least bad default - not because it is permitted
where you are. Prefer a cable and an attenuator to an antenna.

The flowgraph is built so that the safe state is the state it starts in:

- `arm` is **unticked**, and unarmed the transmit samples are multiplied by
  exactly `0.0`.
- Attenuation starts at **89.75 dB**, the most the AD9361 offers. Higher is
  quieter; the safe end of that slider is the right-hand end.
- It is **re-asserted after the stream opens**, not only before it. Patch 0005
  restores a cached attenuation when a buffer starts, so a value written before
  streaming guarantees nothing during it. A snippet re-writes it after
  `start()`, which is the rule every tool in this repo follows.
- The attenuation on screen is **read out of the chip** four times a second by
  an IIO Attribute Source, not echoed from the slider. If the driver refuses a
  write - the thermal limit of patch 0018, the `tx_disable` latch of patch 0016
  - the slider moves and that number does not. Believe the number.

**A loopback without an attenuator destroys the receiver.** The RX input is
rated about +2.5 dBm (AD9361 Rev. G, Table 11) against about +19 dBm out. Fit
at least 20 dB of pad. See [transmitter-safety.md](../docs/transmitter-safety.md)
and `tools/tx-guard.sh`.

To exercise the whole chain with **nothing leaving the board at all**, use the
AD9361's internal digital loopback - the transmit samples are fed to the
receiver inside the chip, past the mixers and the amplifier:

```bash
# run from: the repo root - engage, then ALWAYS put it back
python3 tools/examples_loopback.py on     # digital TX -> RX inside the chip
python3 tools/examples_loopback.py off
```

With loopback on there is no frequency translation, so set the two LO offsets
in 02 equal to each other - otherwise the carrier loop sees an offset it cannot
pull in.

## What is here

```
examples/
├── 01-dynamic-range/dynamic_range.grc     spectrum, waterfall, live dynamic range
├── 02-modulated-link/modulated_link.grc   QPSK/QAM link, EVM          (TRANSMITS)
├── 03-coherent-receivers/coherent_rx.grc  RX1/RX2 phase and coherence
├── lib/                 the embedded Python, as importable modules
│   ├── spectrum_engine.py   window + FFT + power averaging + dynamic range
│   ├── evm_meter.py         EVM, two ways, and why the two differ
│   ├── phase_meter.py       cross-correlation, coherence, the phase dial
│   └── qam.py               the constellation, shared by modulator and meter
├── mkgrc.py             builds the .grc files from one description each
├── test_blocks.py       checks the blocks, with no radio attached
└── plot_examples.py     redraws the figures from measured data
```

**Why a generator.** A `.grc` stores an embedded block's source as one YAML
scalar - hundreds of lines of Python with every newline escaped inside a quoted
string. Hand-maintaining that is how you get a block that silently falls back
to a stale cached port signature. So the Python lives in `lib/`, where it can be
imported and unit-tested, and `mkgrc.py` injects it with PyYAML doing the
quoting. You can still edit the `.grc` in GRC like any other flowgraph; if you
change an embedded block that way, copy it back into `lib/` and re-run the
generator.

```bash
# run from: the repo root
python3 examples/test_blocks.py     # the DSP and the port signatures
python3 examples/mkgrc.py           # rebuild all three .grc
python3 examples/mkgrc.py --check   # CI: fail if a .grc is stale
```

`test_blocks.py` needs no radio. It checks the things that would otherwise fail
quietly: that a full-scale tone reads 0.000 dBFS through every window, that the
scalloping losses are the textbook ones, that averaging happens in power and
not in dB, that a perfect symbol stream reads 0.000% EVM at every order, that
the separable constellation decision is *exactly* the brute-force one, and that
a phase at the ±180° wrap still reads ±180° instead of zero.

## Not GNU Radio?

Several of these jobs have better tools, and one of them - a real-time
waterfall at the full 61.44 MS/s - GNU Radio on a host fundamentally cannot do,
because no link carries 245 MB/s. See
[**docs/other-sdr-tools.md**](../docs/other-sdr-tools.md) for what to reach for
instead and what it costs you.
