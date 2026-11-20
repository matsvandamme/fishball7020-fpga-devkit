# AGENTS.md — fishball7020-fpga-devkit

Editable, rebuildable firmware for the **PlutoSky R1 / 7020-SDR** and, with `--rev r2`, the **PlutoSky R2** (Zynq **XC7Z020** + **AD9361**) two-channel SDR. HDL + bootloader + kernel + rootfs, patch-based. Public, **GPL-2.0**. `README.md` and `CONTRIBUTING.md` are the source of truth.

## The build driver: `./devkit`
- `./devkit doctor` — check the machine can build.
- `./devkit setup --target factory` — materialise sources + apply `firmware/patches/` (re-run after editing any patch).
- `./devkit build --target factory` — full build (bitstream → FSBL → U-Boot → kernel → rootfs), end to end.
- `./devkit sim --mutate` — HDL simulation; run it if you touch HDL and **add a testbench**.
- `./devkit verify --board` — after flashing to real hardware.
- Modern kernel path: `firmware-modern/setup.sh` (Linux 6.12 LTS, ADI at a pinned SHA); build with `./devkit build --target modern` / `--xsa "$(./firmware-modern/fetch-pinned-xsa.sh)"`.
- Rootfs only: `./devkit build --target modern --rootfs-only` then `./firmware-modern/debian/check-rootfs.sh`.
- **Two hardware revisions.** `--rev r1` (default, PlutoSky R1, CLG400) or `--rev r2` (PlutoSky R2, CLG484) on the commands that take `--target`; every revision-dependent name is in `firmware/scripts/rev.sh`. The R2 has its own FPGA design (`firmware/revs/r2/patches/`), device tree (`firmware-modern/dts/*-r2.dts`), kernel fragment (`config/r2.config`) and output directory (`output-r2/`); on the R2 the factory target builds the FPGA only. An image for one revision does not work on the other. See `docs/plutosky-r2.md`, including what is untested.

## Conventions
- **Everything is a patch.** Change a file, then `git diff -- path > firmware/patches/00NN-what-it-does.patch` (or `firmware-modern/patches/`), and re-run the matching `setup`. Don't commit materialised sources.
- CI (`verify-patches.yml`, `verify-modern.yml`) checks patches apply — **it cannot run Vivado**. The bar for hardware changes is "I flashed it and it works," stated in the PR.
- Keep GPL-2.0 headers; respect `NOTICE`/`LICENSE`.
- Docs are MkDocs (`mkdocs.yml`): `mkdocs serve` to preview, `mkdocs build` for `site/`. The 54-lesson course lives under docs.
- Don't commit large captures/binaries (`*.sigmf-data`, build outputs); keep `loop.sigmf-*` as the one sample if referenced.
