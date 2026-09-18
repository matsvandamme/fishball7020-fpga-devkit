# How this repo came to exist

The board ships with no published, editable firmware source. This firmware was
reverse-engineered and rebuilt from scratch, starting from the public upstream
fork
[`Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR`](https://github.com/Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR),
cross-referenced against:

- **The board's real schematic**, used to check the HDL project's pin
  constraints by hand. Several other candidate projects compiled perfectly well
  and turned out to target *different*, similarly-named boards.
- **A byte-for-byte comparison** against
  [`OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR`](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR),
  confirming it as the genuine source of the prebuilt binaries (though not of
  editable HDL/kernel source, which was never published).
- **An extracted `IKCONFIG` kernel `.config`** pulled out of the real
  firmware's compiled kernel image, proving this rebuild's configuration
  identical rather than merely close.

The result was then verified file by file against a real unit. The device tree
recompiles byte-for-byte identical to the factory one, with patch `0008` adding
`gpio-line-names` as the one intentional departure. `uEnv.txt` and
the rootfs file list are content-identical. Kernel and bootloader come out
within a few hundred bytes of the originals (the
upstream history was squashed *after* this board's firmware was built, so some
source has drifted — not recoverable from public sources). The
[firmware README](../firmware/README.md) has the exact patch list, including two
genuine upstream bugs found along the way.

## Vendor resources

Published by the board's distributor — useful primary reference, but none of it
includes editable HDL sources, which is the gap this repo fills.

- [**Hardware schematic**](vendor/7020_936x_SDR-schematic.pdf) — kept here,
  because the vendor's own GitHub copy is a **different revision** that does not
  describe this board. [Which is which](vendor/README.md).
- [**PlutoSky R1 write-up**](https://blog.opensourcesdrlab.com/archives/PlutoSky-R1)
- [**Vendor file archive**](https://workupload.com/archive/kc2v7ryVZZ)
- [`OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR`](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR)
  — confirmed by checksum as the genuine source of the prebuilt factory binaries.
