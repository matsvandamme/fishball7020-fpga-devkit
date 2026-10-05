---
icon: material/radio
description: Apply the optional patch, rebuild only the FPGA, flash it, and receive one FM channel filtered in the fabric.
---

# Build the FM channelizer example

A worked example of your own DSP in the datapath: the optional patch
`0003-wbfm-channelizer.patch` makes the board deliver **one** 200 kHz FM
broadcast channel, every other station removed in the FPGA. It needs Vivado
2022.2 and a previous full factory build.

![The receive path with the patch applied, top to bottom. The AD9361, with its LO at 101.044 MHz and 4.224 MSPS: the wanted channel sits at +1.056 MHz, the LO leak and DC offset at 0. axi_ad9361 passes adc_data_i0 and adc_data_q0. rx_ddc (ad_fs4_ddc.v) is new: it multiplies by exp(-j pi n/2), with 0 DSPs and 0 block RAM, so the wanted channel is now at DC and the spur is pushed to -1.056 MHz. rx_fir_decimator is the existing block with new coefficients: a 321-tap lowpass, Fpass 100 kHz, Fstop 175 kHz, then divide by 8. cpack, adc_dma and USB deliver 528 kSPS: the channel and nothing else.](../img/build-wbfm-datapath-light.svg#only-light)
![The receive path with the patch applied, top to bottom. The AD9361, with its LO at 101.044 MHz and 4.224 MSPS: the wanted channel sits at +1.056 MHz, the LO leak and DC offset at 0. axi_ad9361 passes adc_data_i0 and adc_data_q0. rx_ddc (ad_fs4_ddc.v) is new: it multiplies by exp(-j pi n/2), with 0 DSPs and 0 block RAM, so the wanted channel is now at DC and the spur is pushed to -1.056 MHz. rx_fir_decimator is the existing block with new coefficients: a 321-tap lowpass, Fpass 100 kHz, Fstop 175 kHz, then divide by 8. cpack, adc_dma and USB deliver 528 kSPS: the channel and nothing else.](../img/build-wbfm-datapath-dark.svg#only-dark)

## Build it

The default targets **102.1 MHz** (Studio Brussel); the station is a runtime
setting ([retuning](../wbfm-channelizer.md#retuning-to-another-station)). The coefficients and the
block-design change both need the FIR IP regenerated, and `build_hdl.tcl` reuses
an existing `pluto.xpr`, so **delete the project first** or the build silently
produces the old filter.

```bash
# run from: firmware/
./scripts/setup.sh          # if src/ does not exist yet
# --hdl-only reuses the kernel, U-Boot and rootfs from a previous FULL build
# and refuses to run without one - run a plain ./scripts/build_all.sh first.
(cd src && git apply ../patches/optional/0003-wbfm-channelizer.patch)
rm -rf src/hdl/projects/pluto/pluto.{xpr,cache,gen,hw,ip_user_files,runs,sim,srcs,sdk}
./scripts/build_all.sh --hdl-only     # ~20 min instead of 70
```

It is not applied by default because it narrows RX channel 0 to one broadcast
channel. Check before flashing `output/` as usual:

```bash
# run from: firmware/
grep -A6 "^4. DSP" src/hdl/projects/pluto/utilization.rpt   # expect 96 / 220
grep -A3 "Design Timing Summary" src/hdl/projects/pluto/timing.rpt
```

Then flash it: `./devkit flash --target factory --boot-only`
([put it on the board](flash-your-build.md)).

!!! danger "Delete the Vivado project before the rebuild"
    Without the `rm -rf` line above the build reuses the old project and
    silently produces the old filter.

## Run it

The second rate **engages the filter**: it drives `GP_CONTROL` bit 0, which
selects the filtered path through the bypass mux. Without it samples arrive
unfiltered.

```bash
# run from: the board
iio_attr -o -c ad9361-phy altvoltage0 frequency 101044000     # RX LO
iio_attr -i -c ad9361-phy voltage0 sampling_frequency 4224000 # converter rate
iio_attr -i -c ad9361-phy voltage0 rf_bandwidth 4000000       # analog LPF
iio_attr -i -c cf-ad9361-lpc voltage0 sampling_frequency 528000   # <- engages the FIR
```

- **Read the converter rate back.** Anything other than 4224000 puts the channel
  off-centre.
- **Check the shifter is in the bitstream:** the LO-leakage spur (always at 0 Hz
  on a zero-IF receiver) should appear at −1.056 MHz. Still at DC means the
  flashed bitstream lacks the change.
- **A/B the filter:** set `cf-ad9361-lpc voltage0 sampling_frequency` back to
  4224000 to bypass it, then to 528000 again. With a 65 536-point transform:

| | Filter bypassed | Filter engaged |
|---|---|---|
| Out-of-band signal at −724 kHz | −66.5 dBFS, 37.8 dB over the floor | gone |
| Capture RMS | −49.2 dBFS | −78.6 dBFS |
| Peak sample | 23 LSB | 1 LSB |

`rx_ddc` (the shifter) sits *ahead* of the bypass mux, so an undecimated capture
from this build is frequency-shifted but unfiltered, not raw.

**The GNU Radio flowgraph `docs/grc/fishball_wbfm_rx.grc` is untested on
hardware.** It sets both rates from a Python snippet after initialisation,
because gr-iio does not know about the FPGA decimator. Treat it as a starting
point, and report in an issue or PR if you run it.

Why the channel is shifted first, the rate plan and the filter's performance:
[an FM channelizer in the FPGA](../wbfm-channelizer.md).
