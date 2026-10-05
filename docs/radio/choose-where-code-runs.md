---
icon: material/sitemap-outline
description: Your PC, the board, the kernel or the FPGA - four questions decide where your code belongs.
---

# Choose where your code runs

**Most projects belong on your PC.** Ask these in order and stop at the first yes:

![Three questions, asked in order. Can my PC keep up (streaming plateaus near 44 MB/s)? Yes: on your PC. If no: must it run with no PC, or is the data too big to ship? Yes: on the board. If no: a new sysfs file, or act between samples? Yes: in the kernel. If no: in the FPGA, for a high input rate and a small output.](../img/radio-code-places-light.svg#only-light)
![Three questions, asked in order. Can my PC keep up (streaming plateaus near 44 MB/s)? Yes: on your PC. If no: must it run with no PC, or is the data too big to ship? Yes: on the board. If no: a new sysfs file, or act between samples? Yes: in the kernel. If no: in the FPGA, for a high input rate and a small output.](../img/radio-code-places-dark.svg#only-dark)

| # | Question | If yes |
|---|---|---|
| 1 | **Can my PC keep up?** Streaming over gigabit Ethernet plateaus near **44 MB/s** | **on your PC** |
| 2 | **Must it run with no PC, or is the data too big to ship?** | **on the board**, on the Debian root |
| 3 | **Do I need a new sysfs file, or to act between samples?** | **in the kernel** |
| 4 | **Is the input rate higher than the bus can carry, with a small output?** | **in the FPGA** |

| | What it costs you | Rebuild loop |
|---|---|---|
| **Your PC** | nothing: a venv, `.venv/bin/pip install`, and go | seconds |
| **The board** | an ssh session | seconds |
| **The kernel** | a kernel build and a patch to maintain | **2m46s** from clean, **6 s** to flash |
| **The FPGA** | Vivado, and HDL | **20 min** with `--hdl-only`, **70** from cold |

For scale: one channel at the full 61.44 MS/s is 245.8 MB/s.

!!! tip "Before any of them"
    Rule out a damaged board with `./devkit selftest --ssh`
    ([check the radio is healthy](check-the-radio.md)).

**Next:** [talk to the board from Python](talk-from-python.md). Each place in
detail: [your own project](../your-own-project.md).
