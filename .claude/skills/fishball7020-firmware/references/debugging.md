# Traps that have actually cost hours here

Each of these was diagnosed the slow way at least once. They are recorded so the
next one is not.

## Check /mnt/jffs2 before believing anything about the firmware

**Symptom:** the transmit attenuation reset itself to 10 dB, seconds after a
stream started, with no userspace write to cause it. Not reproducible by any
LO change, rate change or calibration. Absent from the kernel source. Survived
reflashing the kernel, the device tree and the bitstream.

**Cause:** a user script on `/mnt/jffs2`, started by `autorun.sh`, polling
`buffer/enable` and applying its own gain two seconds after a stream began.

**Why it took three kernel rebuilds:** the search was confined to the firmware,
which is exactly where it could not be. `/mnt/jffs2` is the one writable,
persistent partition; nothing in a build touches it.

**The step that would have solved it immediately:** the first stack trace said
`Comm: iio_attr` — a *userspace* process. Read the `Comm:` field.

`sdr_selftest.py --ssh` now lists `autorun.sh` and flags anything under
`/mnt/jffs2` that writes radio settings.

## An interrupted build leaves stamps that lie

**Symptom:** a resumed buildroot build fails with `install: cannot stat
.../mtd-2.1.5/flashcp`, or hash mismatches on packages that were fine before.

**Cause:** buildroot records `.stamp_downloaded` / `.stamp_extracted` /
`.stamp_built` inside each package's build directory. Kill a build mid-compile
and those claim work that was never finished. Deleting a bad download from `dl/`
without also clearing the build directory produces the mirror-image failure.

**Fix:** remove the package's build directory so it is fetched and built again.
If several are affected, `rm -rf output/build` and let it redo. If the tree has
been hand-edited as well, start from a clean clone — debugging your own damage
is not the same as debugging the repo.

## The measurement is measuring the instrument

Three findings that looked like hardware faults and were not:

- **RX gain "0.65 dB/dB"** — fitting across the AD9361's gain-table transitions.
  See `ad9361-gain-tables.md`.
- **Image rejection moving 15 dB between runs** — measured at whatever gain
  autoranging happened to stop at, on either side of the LNA transition. Pin the
  operating point.
- **A "300 dBc" spur-free figure** — an FFT bin that is literally zero, because
  the path was a digital loopback with no noise in it. Cap headline dB figures.

Ask "could this be the instrument?" before "is the board broken?".

## Verify the edit landed

Two captions shipped stale in this repo because a string replacement silently
matched nothing. `sed`/`str.replace` that finds no match is not an error.

Assert the pattern was found, and read back what you wrote. The same applies to
flashing: compare md5sums on the board against the host before rebooting.

## Do not pattern-match your own process

`pkill -f build_all.sh` matches the shell running the command that contains that
string, and kills it. This has happened three times here, twice with
`pgrep -f <path>`. Use PIDs, or a pattern that cannot match the invoking
command line.

## Background work does not always survive

A `nohup ... &` build died at a session boundary six hours in. `setsid nohup`
into its own session survived. Check with `ps -o sid=` that the session id
differs from your shell's, and write logs somewhere durable — a scratch
directory can be cleaned underneath a running process, which loses the log
while the build continues blindly.

## When something autonomous changes the radio

Every measurement in the self-test re-reads gain and attenuation and re-asserts
them if they moved, then reports how often that happened. If a number looks
wrong and that counter is non-zero, believe the counter.

## A wrong PACKAGE_PIN is not a build error

Vivado will happily place a port on a ball the board leaves unconnected, meet
timing, and write a clean bitstream that drives a pad wired to nothing. On this
board V11, W9 and V7 look like plausible header pins and are marked **no
connect** on the schematic; the real ones are V10, U9, U10, T9. Read the
schematic, do not pattern-match ball names.

Two related traps from the same episode:

- **Ball names do not tell you the bank.** Grepping for `V1x`/`U1x` suggested
  the AD9361 LVDS lines shared bank 13 with the header pins. They do not —
  `get_property IOBANK` in a routed checkpoint is the only authority.
- **An `.xdc` is a restricted Tcl dialect and rejects `if`.** A guarded
  constraint block is discarded whole, and the explanation appears in
  `pluto.runs/*/runme.log`, not the top-level build log. Check the run logs.


## Patches stack, and both obvious "already applied?" tests are wrong

0004, 0005 and 0007 all edit `cf_axi_dds.c`. Once a later one is applied,
`git apply --check --reverse` on an earlier one fails - its context is gone -
so per-patch detection reports a good tree as broken. And `git apply --check
a.patch b.patch` tests each against the CURRENT tree, not cumulatively, so a
whole-series check fails the same way. `setup.sh` therefore stamps
`src/.devkit-patches-applied` with a digest of the patch set; `build_all.sh`
refuses to build without a matching stamp. Generate a new patch to a stacked
file against a reconstructed pre-change copy, not a plain `git diff`.

## "Verified" must name the exact file

`verify_output.sh` once picked the smallest `.bit` it could find to check
compression, and a stale compressed bitstream from an earlier build vouched
for the fresh one. It now checks exactly `pluto.runs/impl_1/system_top.bit`,
the file `build_all.sh` packages. The flash script used to print "back after
7s" while the OLD firmware was still answering ssh during shutdown - it now
waits for `/proc/uptime` to reset and md5s the card. When a check can be
satisfied by the wrong artefact, it eventually will be.

## `pgrep -f` and `pkill -f` match the shell that runs them

A waiter loop `while pgrep -f build_all.sh; do sleep 30; done` never exits: its
own command line contains the pattern. `pkill -f "pattern"` kills the shell
issuing it (exit 144). Use `pgrep -x <name>` for a process name, or the bracket
trick `pgrep -f "[b]uild_all"`. A shell `for ...; do [ test ] && echo; done`
exits 1 when the LAST iteration's test is false, so a wrapper that checks exit
codes must end such loops with `; true` and judge the output instead.

## `Unable to create buffer: -16` is a stale session on the BOARD

`-16` is `EBUSY`. A libiio client that is killed rather than closed leaves its
session open on the board, holding the DMA. The board showed **three** open
connections on port 30431 while the host showed none, and every later transmit
allocation was refused indefinitely. Restarting the client, or the host, does
nothing. `killall iiod` on the board clears it; so does a reboot.

Do not read a size limit into it. A 4 MB (1048576-sample) transmit buffer
allocates fine as a fresh process's first request, and a 1 MB one is refused as
the same process's second. An hour went into a non-existent "1 MB transmit
buffer ceiling" because the large sizes happened to be tested second.

A related one: with the digital loopback engaged, allocating a large transmit
buffer returned `-104` (`ECONNRESET`) — IIOD reset the session — and *that*
left the DMA allocated, producing the `-16` cascade afterwards. Memory was not
the cause: 963 MB free, 260 MB of 262 MB CMA free.

## Transmitting over a wireless host link starves the DAC, and 0015 then mutes

Receiving tolerates a slow link: samples pile up on the board and you lose
some, which prints `O`. Transmitting does not — the converter must be fed in
real time, so a late buffer prints `U`, and **patch 0015 mutes the transmitter
after 250 ms of starvation** and switches the data source to the DDS. The
symptom is a flowgraph that looks like it is still working while nothing is on
the air, and a receiver seeing exactly zero.

Measured: transmit and receive together at 4 MS/s over WiFi produced bursts of
20–40 underflows in 45 s, each beside `Unable to push buffer: Connection timed
out`, while a transmit-only stream at the same rate and buffer produced none.
It is intermittent — the same configuration ran clean an hour later — so it is
contention, not a throughput limit. The defence is buffer DURATION,
`buf / samp_rate`, because that is the stall you can absorb. Lowering the rate
helps twice (more slack, less traffic); raising the buffer helps once.

## A receive buffer as big as the whole capture never returns

`head` for exactly 262144 samples behind a 262144-sample receive buffer hung
indefinitely; a 65536-sample buffer delivered the same 262144 samples in 1.4 s.
Long-running streams at 262144 are fine — it is the ask-for-one-bufferful-and-
stop pattern that wedges. Any one-shot capture should bound its own wait rather
than trust `tb.wait()`.

## Digital loopback exercises transmit without radiating

`./devkit loopback on` sets the AD9361's `loopback` debugfs attribute to 1, so
transmit samples reach the receiver inside the chip — past the mixers and the
amplifier. Nothing is radiated, which makes it the right way to test a
transmit-and-receive flowgraph before making a licensing decision. Three
things to know: it does **not** translate frequency, so a transmit LO offset and
a receive LO offset do not cancel and must be set equal; the analogue
attenuator does not apply, so level is set by the digital scale alone; and a
board left in loopback is deaf to its antennas and looks broken for no visible
reason. It survives everything short of a reboot.

## A slow Python block gets your transmitter muted

An embedded block that pegs a core starves the GNU Radio scheduler's other
threads, and on this firmware a starved DAC is a muted transmitter (patch
0015). `examples/lib/evm_meter.py` decided symbols with an `n x order` distance
matrix on every call to `work()`; at a megasymbol a second that produced 40
underflows in 45 s where a bare transmit stream produced none. Two habits fix
it: decide separably where the constellation allows it (O(n), same answer), and
recompute statistics once per bufferful.

Throttle that recomputation by **samples, not by wall time**. A 40 ms clock was
correct in the live flowgraph and silently wrong everywhere else: an offline run
finishes inside 40 ms, so the meter measured once — on the acquisition
transient — and reported that number for every symbol after it. It read 23% on
a stream that was measurably 0.3%, and held flat against changing SNR. The unit
of "recent" for a sample stream is samples.

## A .grc that compiles can still be unusable. Open it and LOOK

`grcc` and the editor are different paths, and only one of them draws. The
first version of `examples/` compiled cleanly, generated correct Python, ran
against the board - and opened in GNU Radio Companion as a wall of overlapping
text with the signal chain pushed off screen. Nothing automated caught it
because nothing automated renders.

The cause: **GRC draws a block's `comment` on the canvas, in full and
unwrapped.** It is not a tooltip. A five-line comment is five lines painted
over whatever is to the right of it, and with a comment on every block the
canvas becomes unreadable. A chooser's option LABELS behave the same way, and
so does the `options` block's comment, which is usually the longest of all.

`examples/mkgrc.py` now asserts the limits rather than documenting them - two
lines of 46 characters per block, eleven of 50 for the flowgraph header, 34 per
option label - because the failure is invisible from the compiler and obvious
only from a screenshot. Depth goes in the example's README.

Two layout rules worth keeping: put the signal path at the TOP, since GRC opens
scrolled to the top-left and that is what someone wants to see first; and keep
variable blocks in a left-hand column with no comments at all, or their
comments overlap each other.

To look at one without a screen, run it against a virtual display and grab the
root window - but unset `WAYLAND_DISPLAY` first, or GTK ignores `DISPLAY` and
opens on the real session instead:

```bash
# run from: anywhere
Xvfb :99 -screen 0 1920x1200x24 &
env -u WAYLAND_DISPLAY DISPLAY=:99 GDK_BACKEND=x11 gnuradio-companion x.grc &
sleep 45 && DISPLAY=:99 xwd -root -silent > shot.xwd
```

## GRC block ids are not file names, and trailing underscores are stripped

`qtgui_chooser.block.yml` declares `id: variable_qtgui_chooser`;
`import.block.yml` declares `id: import_`, and GRC strips the trailing
underscore when it registers the block, so a flowgraph must say `import`. Get
it wrong and the block contributes nothing — a missing `import math` surfaced as
"name 'math' is not defined" on an unrelated block's parameter. Three more
traps while hand-writing a `.grc`: the `options` mapping must carry no `name`
key (GRC loads it with `name=''` and the duplicate kills the whole file); a QT
Chooser validates its default against `option0..option4` individually, not
against the `options` list; and an id that any import has already bound is
blacklisted, which is why a window-selection variable cannot be called
`window` — the waterfall sink imports `gnuradio.fft.window`.

## Sample-rate transitions can fail the AD9361's interface tuning

`ad9361_dig_tune_delay: Tuning TX FAILED!` with every one of 16x16 delay
positions marked `#` appeared after repeated sample-rate changes, and left
transmit unusable until a reboot. A healthy board passes 157–181 of 256
positions. It is a transition effect rather than a property of a particular
rate — 2.5 MS/s provoked it once and ran clean other times — so treat it as a
reason to check `dmesg` when transmit goes strange, not as a rate to avoid.
