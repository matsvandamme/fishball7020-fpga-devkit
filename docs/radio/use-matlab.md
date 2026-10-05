---
icon: material/matrix
description: One command checks MATLAB is ready; three rules keep levels and settings right.
---

# Use MATLAB

One command checks that MATLAB is ready for this board; another runs the
first example.

```bash
# run from: the repo root
./devkit matlab            # is MATLAB ready to use this board?
./devkit matlab shell      # interactive, package already on the path
./devkit matlab hello      # run example 01
```

You need the **Communications Toolbox** and, for live radio, the
**ADALM-Pluto support package**. Without it, every analysis still runs on a
capture file.

!!! danger "Never accept MATLAB's offer to \"switch the firmware version\""
    That image is for an ADALM-Pluto (Zynq-7010, AD9363). **There is no undo.**

| Rule | |
|---|---|
| **full scale** | `int16`: **±2047**; `double`/`single`: **±1.0**; transmit: **±32767** |
| **channels** | `sdrrx`/`sdrtx` see **only RX1/TX1**; RX2 and TX2 through the `fishball` package |
| **changing a setting** | release and re-create: a property set on a running object does nothing |
| **Simulink blocks** | must run with **Simulate using = Interpreted execution** |
| **listening** | engage the FPGA ÷8 decimator, or the sound card starves |

Everything else, including Simulink: [MATLAB](../matlab.md).
