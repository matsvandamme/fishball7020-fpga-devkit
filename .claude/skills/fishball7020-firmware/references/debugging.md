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
