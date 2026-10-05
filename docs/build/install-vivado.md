---
icon: material/download-box-outline
description: Install Vivado 2022.2 for an FPGA build, on an Ubuntu host or through the container on any other Linux.
---

# Install Vivado 2022.2

You need Vivado only to change the FPGA design. It is about 50 GB installed,
and the Zynq-7020 is covered by the free WebPACK licence. Not changing the
FPGA? [Build without Vivado](build-without-vivado.md).

=== "Any Linux, through the container"

    The installer will not run on a host newer than Ubuntu 22.04, so the
    container runs it and writes to the host. Download the installer yourself
    first: AMD put it behind an account login.

    ```bash
    # run from: the repo root
    # AMD put the installer behind an account login, so download it yourself first:
    #   https://www.xilinx.com/support/download.html  ->  Vivado 2022.2  ->  Linux Self Extracting Web Installer

    # Rootless podman maps the container's root to YOUR user, so the target must be
    # yours: a root-owned /tools/Xilinx cannot be written even from "root" inside.
    sudo mkdir -p /tools/Xilinx && sudo chown "$USER" /tools/Xilinx

    ./devkit container install ~/Downloads/Xilinx_Unified_2022.2_1014_8888_Lin64.bin
    ```

    The web installer needs your AMD account and downloads the content itself;
    budget an hour.

=== "Ubuntu 18.04 to 22.04, on the host"

    1. Create an account at [xilinx.com](https://www.xilinx.com) and open the
       [2022.2 downloads page](https://www.xilinx.com/support/download/index.html/content/xilinx/en/downloadNav/vivado-design-tools/2022-2.html).
    2. Download the **Vitis** unified installer for Linux (it offers both products;
       this project uses only Vivado).
    3. Run it:

        ```bash
        # run from: the directory holding the installer, on your host
        chmod +x Xilinx_Unified_2022.2_*.bin && ./Xilinx_Unified_2022.2_*.bin
        ```

Either way, answer the installer the same:

| It asks | Choose |
|---|---|
| product | **Vivado**, edition **Vivado ML Standard** |
| device families | only **Zynq-7000** (~130 GB down to ~30 GB) |
| path | **keep the default `/tools/Xilinx`**, which `tools/env-vivado.sh` points at |

**You should see:** `./devkit doctor --target factory` (or
`./devkit container doctor --target factory`) find Vivado.

!!! warning "Always `source tools/env-vivado.sh`, never Vivado's own `settings64.sh`"
    The script supplies the old libraries Vivado 2022.2 needs
    ([why](../building.md#install-vivado-20222)).

??? question "The installer says \"Extraction failed\"?"
    Usually false: the container's install step checks for an executable
    `xsetup` instead. When it is real, and what the install mounts:
    [installing Vivado in the first place](../building-in-a-container.md#installing-vivado-in-the-first-place).

**Next:** [build with Vivado in a container](build-in-a-container.md), then
[add your own logic to the FPGA](add-fpga-logic.md).
