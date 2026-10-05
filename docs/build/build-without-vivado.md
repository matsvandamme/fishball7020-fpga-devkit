---
icon: material/package-variant-closed
description: Build the modern firmware (kernel, drivers, Debian) from a pinned FPGA design, with nothing from AMD installed.
---

# Build without Vivado

The modern firmware takes its FPGA design from an **XSA** (AMD's export of a
finished design: the bitstream plus the processor setup), so it builds with
nothing from AMD installed. Vivado is about 50 GB and 20 to 70 minutes of every
build; you need it only to change the FPGA design.

```bash
# run from: wherever you want the devkit to live (e.g. ~)
git clone https://github.com/matsvandamme/fishball7020-fpga-devkit.git
cd fishball7020-fpga-devkit
./devkit doctor                                     # can this machine build?
./devkit setup                                      # fetch the sources, apply the patches (~0.6 GB)
XSA="$(./firmware-modern/fetch-pinned-xsa.sh)"      # the FPGA design of a factory release
./devkit build --all --xsa "$XSA"                   # boot files, kernel and Debian root
```

`fetch-pinned-xsa.sh` downloads the factory release named in
`firmware-modern/factory-xsa.pin` and refuses it unless the sha256 matches.

**You should see:** the first stage say it is importing, not building:

```
=== [1/7] Importing a pre-built XSA (Vivado not invoked) ===
```

**The import refuses the XSA?**

More: [building without Vivado](../building-without-vivado.md).

| If you pass | You get |
|---|---|
| something that is not a zip | `ERROR: … is not a readable zip archive.` |
| an XSA exported without the bitstream | `ERROR: … contains no system_top.bit.` |
| an XSA for a different chip | `ERROR: that XSA is not for this board's part (xc7z020clg400-2).` |
| an XSA from a different Vivado version | `ERROR: that XSA was written by a different tool version.` |

**Next:** [check the build](verify-the-build.md).
