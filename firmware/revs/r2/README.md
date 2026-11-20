# firmware/revs/r2: the PlutoSky R2's FPGA patches

What `--rev r2` adds to the factory patch series. The rule is in
[`firmware/scripts/rev.sh`](../../scripts/rev.sh): a patch here with the same
file name as one in [`firmware/patches/`](../../patches/) replaces it, any other
is added, and the merged list is applied in file-name order.

| Patch | Replaces | What it does |
|---|---|---|
| `0000-plutosky-r2-fpga-design.patch` | adds | turns the tree's R1 FPGA project into the R2's: part, pin constraints, Ethernet through the FPGA, the reference PLL. The `hdl/` part of the vendor's own R2 port |
| `0006-tx-sample-nibble-to-gpio.patch` | `0006` | the same design change, with the R2's header balls (M19, M20, M21, M22) |
| `0009-bitmap-flag-cdc-constraint-needs-from.patch` | `0009` | the same fix, against the R2's constraint file |

Every other patch in the series applies to the R2 unchanged. Only the `hdl/`
hunks are applied on the R2, because the factory target builds only the FPGA
there ([`setup_fpga.sh`](../../scripts/setup_fpga.sh)).

```bash
# run from: the repo root
./devkit setup --target factory --rev r2
./devkit build --target factory --rev r2      # Vivado -> firmware/src-r2/hdl/projects/pluto/system_top.xsa
```

**Changing a shared HDL patch?** Re-run `./devkit setup --target factory --rev r2`
on a clean `firmware/src-r2/`. A patch can keep applying to the R1's design and
stop applying to the R2's; CI's `verify-r2` job checks it.

**Changing an R2 pin?** Read the ball off the vendor schematic
([OpenSourceSDRLab/PlutoSky-R2](https://github.com/OpenSourceSDRLab/PlutoSky-R2),
`hardware/PlutoSky-R2_Schematic.pdf`), not off the R1's. The two packages share
no pin-out, and the R2's header is 1.8 V.

None of this has been through Vivado yet: see
[the R2 page](../../../docs/plutosky-r2.md#what-is-not-done).
