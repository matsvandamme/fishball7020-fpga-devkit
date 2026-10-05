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
   ([what is safe to change](../block-design.md#what-you-can-change)). To edit
   in the Vivado GUI instead, see [below](#editing-in-the-vivado-gui).

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

![This devkit's default datapath in two columns under axi_ad9361. Receive: both channels, RX1 and RX2, go through rx_fir_decimator, divide by 8, into cpack, which feeds adc_dma. Transmit: dac_dma, tx_upack, then tx_fir_interpolator times 8 on channel 0 only; channel 1 connects directly. Green circles mark where your logic goes: before and after rx_fir_decimator, before and after tx_fir_interpolator, and on transmit channel 1's direct connection.](../img/build-insert-points-light.svg#only-light)
![This devkit's default datapath in two columns under axi_ad9361. Receive: both channels, RX1 and RX2, go through rx_fir_decimator, divide by 8, into cpack, which feeds adc_dma. Transmit: dac_dma, tx_upack, then tx_fir_interpolator times 8 on channel 0 only; channel 1 connects directly. Green circles mark where your logic goes: before and after rx_fir_decimator, before and after tx_fir_interpolator, and on transmit channel 1's direct connection.](../img/build-insert-points-dark.svg#only-dark)

*Where a block can go on the default build, which filters both receive
channels (patch `0021`). Upstream's wiring, built with `STOCK_RX_FILTER=1`,
sends receive channel 1 straight to `cpack` instead
([the design as built](../block-design.md#a-samples-journey)).*

## Editing in the Vivado GUI

The block design exists only after a first full build. Open it:

```bash
# run from: firmware/
source ../tools/env-vivado.sh
cd src/hdl/projects/pluto
vivado pluto.xpr
```

In the GUI: **Sources → Design Sources → system_top → system_i**, right-click
**Open Block Design**.

**After a GUI edit**, save the block design (`Ctrl-S`; unsaved edits are
silently left out), Validate Design (F6) and close Vivado (it holds a project
lock), then run `./scripts/build_all.sh` from `firmware/`. A GUI edit saved
into `pluto.xpr` is picked up without deleting the project.

Worked examples: [an FM channelizer in the FPGA](../wbfm-channelizer.md) and the
[sample-locked GPIO outputs](../tx-gpio-bitmap.md). Every block, clock and trap:
[the stock block design](../block-design.md). New to Verilog?
[Fabric School](../course/index.html).
