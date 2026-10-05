---
icon: material/memory
description: Simulate first, delete the Vivado project, rebuild only the bitstream, and check the utilization.
---

# Add your own logic to the FPGA

This needs Vivado 2022.2 ([in a container](build-in-a-container.md) on any
Linux) and a previous full factory build.

1. **Simulate first.** Synthesis tells you the logic fits, not that it is right:

    ```bash
    # run from: firmware/
    ./sim/run_sim.sh            # ad_fs4_ddc: 473 checks; tx_gpio_bitmap: 2092 checks
    ./sim/run_sim.sh --mutate   # breaks the modules ten ways; every mutant must be caught
    ```

    The key check is **gapped valid**: in 2R2T mode the AD9361 asserts `valid`
    only every second clock, so a counter must advance once per sample, not per
    clock.

2. **Make the change**, in `system_bd.tcl` or the block design
   ([what is safe to change](../block-design.md#what-you-can-change)).

3. **Delete the Vivado project, then rebuild only the FPGA:**

    ```bash
    # run from: firmware/
    rm -rf src/hdl/projects/pluto/pluto.{xpr,cache,gen,hw,ip_user_files,runs,sim,srcs,sdk}
    ./scripts/build_all.sh --hdl-only     # ~20 min; skips kernel/u-boot/rootfs
    ```

    !!! danger "Always delete the Vivado project before an HDL or coefficient change"
        `build_hdl.tcl` reuses an existing `pluto.xpr`. A `system_bd.tcl` or `.coe`
        edit is **not** picked up, and the build quietly produces the old design.

4. **Check it landed**, then [flash it](flash-your-build.md) with
   `./devkit flash --target factory --boot-only`:

    ```bash
    # run from: the repo root
    ./devkit verify --target factory
    ```

**You should see:** the DSP and LUT counts in `verify`'s FPGA section change
the way your design should.

Worked examples: [an FM channelizer in the FPGA](../wbfm-channelizer.md) and the
[sample-locked GPIO outputs](../tx-gpio-bitmap.md). Every block, clock and trap:
[the stock block design](../block-design.md). New to Verilog?
[Fabric School](../course/index.html).
