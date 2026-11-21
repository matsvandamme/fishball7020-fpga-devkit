---
icon: material/stethoscope
description: ./devkit doctor checks the compilers, host packages, disk and sources in about a second.
---

# Check your machine can build

```bash
# run from: the repo root
./devkit doctor                     # the modern firmware
./devkit doctor --target factory    # the factory firmware: also Vivado, the patch stamp and the board
```

It checks the host tools (ssh, python3, a way to log in to the board), then the
compilers, host packages, disk and the sources, in about a second.
`./devkit doctor --host` stops after the host tools: the whole answer on a
machine that only flashes and tests. Every check is a failure that once cost somebody an hour: run it before
the build, not during.

**You should see** every line say `ok`, as on a machine that can build the
modern firmware:

```
=== preflight ===
  ok     kernel source
  ok     U-Boot source
  ok     get_default_envs.sh
  ok     embeddedsw
  ok     bootgen source
  ok     bare-metal cross (FSBL)
  ok     ARM Linux cross (U-Boot, kernel): arm-linux-gnueabihf-gcc
  ok     make
  ok     flex (U-Boot, kernel)
  ok     bison (U-Boot, kernel)
  ok     mkimage (uImage)
  ok     bc (kernel)
  ok     unzip
  ARM Linux compiler: arm-linux-gnueabihf-gcc
=== preflight passed; nothing built (--preflight-only) ===
```

| Missing | What to install |
|---|---|
| `arm-none-eabi-gcc`, or one without the hard-float multilib (*"uses VFP register arguments"*) | `gcc-arm-none-eabi` + `libnewlib-arm-none-eabi` |
| an ARM Linux cross-compiler | `gcc-arm-linux-gnueabi` (or `arm-linux-gnueabihf-gcc`) |
| `gmp.h` | `libgmp-dev`, `libmpc-dev`, `libmpfr-dev` |
| Vivado | only for an FPGA change; with `--target factory` it is a warning |

On Ubuntu 22.04, one line installs the lot:

```bash
# run from: anywhere, on your host
sudo apt update
sudo apt install -y git build-essential bison flex libssl-dev \
    device-tree-compiler u-boot-tools screen python3 \
    libgmp-dev libmpc-dev libmpfr-dev sshpass iverilog libiio-utils \
    gcc-arm-none-eabi libnewlib-arm-none-eabi gcc-arm-linux-gnueabi
```

??? question "On a Mac?"
    macOS cannot build the firmware natively, and `./devkit doctor` says so in
    one line. `./devkit doctor --host` checks what flashing and testing a board
    need (ssh, python3 and a way to log in); `./devkit container doctor` checks
    the build, inside the container.
    [Use the devkit on a Mac](../start/use-a-mac.md#build-the-firmware).

??? question "On Arch, or another distribution?"
    Arch has no ARM Linux cross-compiler in its official repositories: use Arm's
    prebuilt toolchain ([how](../building.md#an-arm-cross-compiler-on-arch)). For an
    FPGA build on anything but Ubuntu 18.04 to 22.04, use
    [the container](build-in-a-container.md).

**Next:** [build without Vivado](build-without-vivado.md).
