# Troubleshooting

Problems people have actually hit, and what fixed them. If the radio itself
misbehaves rather than the build, run the [self-test](../tools/selftest/README.md) first.

- **SDRangel lists the board as `PlutoSDR0 TBD` and won't open it.** SDRangel
  identifies Plutos by serial number, and firmware built before patch 0001
  reported an empty one — this board's W25Q128 flash never emits the
  `SPI-NOR-UniqueID` line the boot script looks for. Rebuild with the current
  `patches/` and reflash; the board mints a persistent serial on first boot. If
  SDRangel is a snap, also `sudo snap connect sdrangel:raw-usb`.
- **`vivado`/`xsct`/`bootgen` fail to start, or complain about missing shared
  libraries** — you sourced Vivado's `settings64.sh` instead of
  `tools/env-vivado.sh`.
- **The kernel build fails with `GLIBC_2.xx not found` in a `gcc-plugins`
  step** — you sourced `env-vivado.sh` in the same shell you then built the
  kernel in; it injects Xilinx toolchain directories into `PATH` that conflict.
  `build_all.sh` isolates this correctly; by hand, use a fresh shell.
- **U-Boot/kernel builds fail with `unrecognized -march target: armv5`** —
  Buildroot's cross-compiler (stage 1b) isn't built yet. Re-run `build_all.sh`
  rather than invoking `make` directly.
- **Buildroot fails with `has wrong sha256 hash`** — known, harmless
  git-archive repackaging drift for a few pinned commits.
  `fix_and_retry_buildroot.sh` repairs it automatically; if it still fails,
  check `/tmp/buildroot_autoretry_*.log` for a different cause.
- **`dfu-util -l` shows nothing** — you didn't stop autoboot in time, or
  `run dfu_mmc` wasn't accepted. (Prefer [flashing over SSH](flashing.md#option-c--over-ssh-from-the-running-board-no-card-removal) anyway.)
- **You moved the checkout and Buildroot fails with `cp: cannot stat`** —
  Buildroot's `output/` is **not relocatable**; autotools bakes absolute paths
  into thousands of generated files. Discard the stale build state (the
  download cache is unaffected):
  ```bash
  # run from: firmware/
  rm -rf src/buildroot/output
  ./scripts/build_all.sh
  ```

Still stuck? [Open an issue](https://github.com/matsvandamme/fishball7020-fpga-devkit/issues/new/choose) — the templates ask for
the details that actually speed up debugging. See also
[CONTRIBUTING.md](../CONTRIBUTING.md).
