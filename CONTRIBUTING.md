# Contributing

A hobby-scale reverse-engineering and build-system project. Contributions are
welcome; these are the things that save everyone time.

## Where the code actually lives

**The HDL, kernel, U-Boot and Buildroot source is not in this repo.**
`firmware/src/` is cloned fresh by `./devkit setup` from the upstream fork and
patched. A fix to anything in there is a patch under `firmware/patches/`:

```bash
# from firmware/src, with the tree patched and your edit made
git diff -- path/to/file > ../patches/0010-what-it-does.patch
```

Number it after the highest existing patch. Two traps:

- **Patches stack.** 0004, 0005 and 0007 all edit `cf_axi_dds.c`. A plain
  `git diff` of such a file includes the earlier patches' changes too. Generate
  yours against a reconstructed pre-change copy (see commit `4468327` for how),
  and check the whole series still applies in order on a fresh `setup`.
- **`setup.sh` stamps the tree** with a digest of the patch set, and
  `build_all.sh` refuses to build without a matching stamp - so after adding a
  patch, re-run `./devkit setup` before building.

## Before opening a PR

1. `./devkit doctor` - the machine can build.
2. `./devkit sim --mutate` if you touched HDL - and **add a testbench** for any
   new module, next to `firmware/sim/tb_*.v`, plus at least one mutant in
   `run_sim.sh` that proves it can fail.
3. `./devkit build` end to end, `./devkit verify --board` after flashing, and
   say so in the PR. CI cannot run Vivado; "I flashed it and it works" is the bar.
4. **Add an assertion to `.github/workflows/verify-patches.yml`** that your patch
   landed (a `grep` for something it introduces). Every existing patch has one;
   it is what catches a patch that silently stops applying against upstream.
5. Measured numbers in the docs come from real builds and a real board. If your
   change moves them (LUTs, WNS, `BOOT.bin` size), update them from your own
   build rather than leaving stale figures: `docs/measured-performance.md`,
   `docs/tx-gpio-bitmap.md` and the agent skill's healthy-board table.

## What CI does and does not do

- `verify-patches.yml`: a fresh clone, `setup.sh`, and an assertion per patch.
- `host-tools.yml`: the Python tools compile and import on 3.8 and 3.12, the
  selftest's measurement maths is asserted against known signals, and the HDL
  simulation with mutation testing runs (triggered by changes under
  `firmware/sim/`, `firmware/patches/` and `tools/`).
- It does **not** build the firmware or touch hardware.

## Style

Scripts over documentation-only workarounds: fix the build in
`build_all.sh` or the relevant `.tcl` rather than telling the next person how
to work around it. Write for someone who has not built an FPGA design before -
define a term where it first appears, and say *why*, not only *what*.

Bug reports: use the issue templates (build failure vs. hardware mismatch);
they ask for the stage, tool versions and logs that actually speed things up.
