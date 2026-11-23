# Contributing

A hobby-scale reverse-engineering and build-system project. Contributions are
welcome. This page covers where the source lives, how to add a patch, what to
check before a pull request (PR), and what CI does.

Credit for ideas as well as commits lives in [CONTRIBUTORS.md](CONTRIBUTORS.md).
A suggestion that changed the firmware counts, and GitHub's contributors graph
cannot record one.

## Where the code lives

**The HDL, kernel, U-Boot and Buildroot source is not in this repo.** Both
`src/` directories are fetched fresh and patched:

| target | fetched by | source | patches | CI |
|---|---|---|---|---|
| `firmware/` — Linux 5.15, the factory reconstruction | `./devkit setup --target factory` | a monorepo: HDL, U-Boot, Buildroot and the kernel | `firmware/patches/` | `verify-patches.yml` |
| `firmware-modern/` — **Linux 6.12 LTS**, the current kernel | `./firmware-modern/setup.sh` | just the kernel, from ADI at a pinned SHA | `firmware-modern/patches/` | `verify-modern.yml` |

A driver or kernel fix belongs in `firmware-modern/patches/` unless it is
specifically about the factory kernel. Anything HDL, U-Boot or rootfs is
`firmware/patches/`, which both targets share. Either way it is a patch file:

```bash
# run from: firmware/src, with the tree patched and your edit made
git diff -- path/to/file > ../patches/0022-what-it-does.patch
```

Number it after the highest existing patch in **both** `firmware/patches/` and
`firmware-modern/patches/`: they share one numbering space, and the same patch
carries the same number in both where it exists in both. The highest is
currently `0024`, so the next is `0025`. Rules:

- **The two directories share numbers.** `0019` exists only in the modern tree
  (the cached attenuation fix) and `0020` and `0021` only in `firmware/` (the
  libfdt build fix and the second RX filter); none of those numbers is free just
  because one directory lacks it.

- **Patches stack.** 0004, 0005 and 0007 all edit `cf_axi_dds.c`. A plain
  `git diff` of such a file includes the earlier patches' changes too. Generate
  yours against a reconstructed pre-change copy (see commit `4468327` for how),
  and check the whole series still applies in order on a fresh `setup`.
- **`setup.sh` stamps the tree** with a digest of the patch set, and
  `build_all.sh` refuses to build without a matching stamp - so after adding a
  patch, re-run `./devkit setup --target factory` before building. `firmware-modern/setup.sh`
  stamps the same way and also recognises a tree patched some other way: if the
  last patch reverses cleanly, the series is on, in order.
- **Do not put a safety-relevant field in `ad9361_rf_phy_state`.**
  `ad9361_clear_state()` `memset`s it, and the debugfs `initialize` calls
  `clear_state` - so anything kept there can be cleared by the surface it exists
  to defend against. Three fields have been moved out for this reason
  (`0016`'s latch, `0018`'s temperature limit, `0019`'s attenuation cache; a
  zeroed attenuation cache means full transmit power). Use
  `struct ad9361_rf_phy`, and seed it so that zero is not the dangerous value.

## Before opening a PR

1. `./devkit doctor` - the machine can build.
2. `./devkit sim --mutate` if you touched HDL - and **add a testbench** for any
   new module, next to `firmware/sim/tb_*.v`, plus at least one mutant in
   `run_sim.sh` that proves it can fail.
3. `./devkit build --target factory` end to end (for a `firmware-modern/` patch,
   `./devkit build --xsa "$(./firmware-modern/fetch-pinned-xsa.sh)"`),
   `./devkit verify --board` after flashing, and
   say so in the PR. CI cannot run Vivado; "I flashed it and it works" is the bar.
4. **Add a CI assertion** that your patch landed - a `grep` for something it
   introduces - in `verify-patches.yml` or `verify-modern.yml` depending on which
   target it is for. Every existing patch has one; it is what catches a patch that
   silently stops applying against upstream. If the thing your patch guarantees can
   be checked in a *built artefact* rather than in the source, prefer that:
   `verify-modern.yml` compiles the device tree and audits the `.dtb`
   (`firmware-modern/verify_dtb.py`), because device-tree mistakes can be
   invisible in the `.dts` and still boot.
5. Measured numbers in the docs come from real builds and a real board. If your
   change moves them (LUTs, WNS, `BOOT.bin` size), update them from your own
   build rather than leaving stale figures: `docs/measured-performance.md`,
   `docs/tx-gpio-bitmap.md` and the agent skill's healthy-board table.
6. If you changed anything under `docs/`, check it the way CI does. The pages are
   GitHub Markdown first and are also published as a site with MkDocs Material:

   ```bash
   # run from: the repo root
   python3 docs/check_links.py                   # links, anchors, "run from" lines
   pip install -r docs-site/requirements.txt
   mkdocs build --strict                         # the site, with no warnings
   mkdocs serve                                  # preview at http://127.0.0.1:8000
   ```

   A new page also needs a line in `mkdocs.yml`'s `nav` and in `docs/README.md`.
   For a callout use GitHub's alert syntax (`> [!WARNING]`, `> [!CAUTION]`,
   `> [!NOTE]`, `> [!TIP]`); it renders as a box on GitHub and on the site. Indent
   a code block or paragraph inside a list item by four spaces, not two: GitHub
   accepts two, the site's Markdown parser does not.

## Changing the Debian rootfs

`firmware-modern/debian/` does not work like the rest of the repo, and step 4
above does not apply to it. CI (`verify-rootfs.yml`) builds the root from
scratch when this directory changes and runs `check-rootfs.sh` on it, but
nothing in CI boots it. Run the same check on your own build:

```bash
# run from: the repo root
./devkit build --target modern --rootfs-only
./firmware-modern/debian/check-rootfs.sh
```

- **Packages go in [`packages.txt`](firmware-modern/debian/packages.txt)**, not in
  the `Containerfile`. One per line, with a comment saying what *breaks* without
  it. If you considered something and left it out, put it in the
  "deliberately NOT installed" block at the bottom. That file is also the manifest
  shipped on the board at `/usr/share/fishball/packages.txt`, so a name with no
  reason attached is a name nobody can later remove safely.
- **Anything that must run at boot is a systemd unit** in
  `overlay/etc/systemd/system/`, committed: a file you made on a running board
  is not on the next card. `/mnt/jffs2/autorun.sh` is **not** run
  on this rootfs.
- **Run `systemd-analyze verify` on a new unit.** An ordering cycle makes systemd
  *delete* a unit rather than fail it, so `systemctl status` then reports it does
  not exist, which looks exactly like a typo in the filename.
- **Nothing board-specific may be baked into the image.** It is a release asset,
  so whatever is in it is on every board anyone flashes. Read "No identity in
  the image" in [`docs/debian-root-reference.md`](docs/debian-root-reference.md#no-identity-in-the-image)
  before adding anything that looks like a key, an ID or an address.
- **The base image and the packages are pinned** in the `Containerfile` (`BASE`
  and `DEBIAN_SNAPSHOT`). Change both together, on purpose, and test the result
  on a board.
- **Say in the PR that you wrote a card and booted it**, and paste
  `./devkit selftest --ssh`. Booting it is the only test of the rootfs that
  CI cannot run.

## What CI does and does not do

- `verify-patches.yml`: a fresh clone, `setup.sh`, and an assertion per patch.
- `verify-modern.yml`: the same for the 6.12 target, plus two things a kernel
  allows that Vivado does not - it **builds the device tree and audits the
  `.dtb`** (16 checks, including that the transmit-attenuation default is still
  89750 mdB), and it **cross-builds `uImage`** and fails on a warning in any file
  this repo patches.
- `host-tools.yml`: the Python tools compile and import on 3.8 and 3.12, the
  selftest's measurement maths is asserted against known signals, and the HDL
  simulation with mutation testing runs (triggered by changes under
  `firmware/sim/`, `firmware/patches/` and `tools/`).
- `verify-rootfs.yml`: builds the Debian root from scratch under ARM emulation
  and runs `firmware-modern/debian/check-rootfs.sh` on it (triggered by changes
  under `firmware-modern/debian/`, and weekly).
- `hardware.yml`: runs on a self-hosted runner wired to a real board: the
  self-test, the GPIO check and the HDL simulation.
- The hosted workflows do **not** build the factory firmware or touch hardware.

## Style

Scripts over documentation-only workarounds: fix the build in
`build_all.sh` or the relevant `.tcl` rather than telling the next person how
to work around it. Write for someone who has not built an FPGA design before -
define a term where it first appears, and say *why*, not only *what*.

Bug reports: use the issue templates (build failure vs. hardware mismatch);
they ask for the stage, tool versions and logs that speed things up.
