---
icon: material/hammer-wrench
description: Build your own firmware, check it, and put it on the board, then change the kernel, the device tree, the FPGA or the Debian root.
---

# Build your own firmware

Every file on the SD card rebuilds from source. The modern firmware (Linux 6.12
and Debian) builds **without Vivado**; only a change to the FPGA design needs it.

## The path

<div class="grid cards steps" markdown>

-   :material-numeric-1-circle:{ .lg } **[Check your machine can build](check-your-machine.md)**


    `./devkit doctor` answers in about a second.

-   :material-numeric-2-circle:{ .lg } **[Build without Vivado](build-without-vivado.md)**


    The kernel, drivers and Debian, from a pinned FPGA design.

-   :material-numeric-3-circle:{ .lg } **[Check the build](verify-the-build.md)**


    `./devkit verify` before flashing; `--board` after.

-   :material-numeric-4-circle:{ .lg } **[Put it on the board](flash-your-build.md)**


    `./devkit flash` over the network, backed up and md5-verified.

</div>

## Change something

<div class="grid cards" markdown>

-   :material-chip:{ .lg .middle } **[Change a kernel driver](change-a-driver.md)**


    The two-minute loop: build `uImage` alone, flash it alone.

-   :material-file-tree-outline:{ .lg .middle } **[Change the device tree](change-the-device-tree.md)**


    Build it, audit the built `.dtb`, flash it with `--dtb-only`.

-   :material-memory:{ .lg .middle } **[Add your own logic to the FPGA](add-fpga-logic.md)**


    Simulate first, delete the Vivado project, rebuild the bitstream.

-   :material-docker:{ .lg .middle } **[Build with Vivado in a container](build-in-a-container.md)**


    The recommended route for FPGA builds, on any Linux.

-   :material-debian:{ .lg .middle } **[Rebuild the Debian root](rebuild-the-debian-root.md)**


    After a change to the root's overlay, then a new card.

-   :material-scale-balance:{ .lg .middle } **[Compare with the factory firmware](check-provenance.md)**


    How close the rebuild is, and how to check it yourself.

</div>

## Reference

The long pages, with every detail and measurement:
[building your own firmware](../building.md) ·
[building in a container](../building-in-a-container.md) ·
[building without Vivado](../building-without-vivado.md) ·
[the stock block design](../block-design.md) ·
[an FM channelizer in the FPGA](../wbfm-channelizer.md) ·
[changing the kernel](../kernel.md) ·
[the modern kernel](../modern-kernel.md) ·
[why Debian](../debian-rootfs.md) ·
[the Debian root reference](../debian-root-reference.md) ·
[provenance](../provenance.md).
