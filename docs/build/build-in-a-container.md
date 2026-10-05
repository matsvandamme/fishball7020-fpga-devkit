---
icon: material/docker
description: Run the Vivado build in a pinned Ubuntu 22.04 container, so your host distribution does not matter.
---

# Build with Vivado in a container

Vivado 2022.2 runs only on Ubuntu 18.04 to 22.04. `./devkit container` runs the
build in a pinned Ubuntu 22.04 container, so your distribution does not matter,
and the `BOOT.bin` comes out byte-identical to a host build. **This is the
recommended way to build the FPGA.**

```bash
# run from: the repo root
./devkit container build-image                       # once, ~3 min
./devkit container doctor --target factory           # the same checks as ./devkit doctor, inside
./devkit container setup --target factory            # clone upstream source + apply patches   (~5 min)
./devkit container build --target factory            # everything                           (45-90 min)

# after that first full build, the fast loop for an HDL change:
./devkit container build --target factory --hdl-only #                                       (~20 min)
```

**Build in the container; flash from the host:** `flash`, `selftest`,
`gpio-check` and `verify --board` are host commands.

??? question "No Vivado installed yet?"
    Download the Vivado 2022.2 installer from AMD (it needs an account), then let
    the container run it:

    ```bash
    # run from: the repo root
    sudo mkdir -p /tools/Xilinx && sudo chown "$USER" /tools/Xilinx
    ./devkit container install ~/Downloads/Xilinx_Unified_2022.2_1014_8888_Lin64.bin
    ```

    Choose **Vivado**, only **Zynq-7000** under device families, path
    `/tools/Xilinx`. Budget an hour. Details:
    [installing Vivado in the first place](../building-in-a-container.md#installing-vivado-in-the-first-place).

**Next:** [check the build](verify-the-build.md).
