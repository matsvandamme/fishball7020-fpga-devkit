# Two receivers that both survive decimation

The stock design filters **one** of this board's two receivers. Engage the
FPGA's ÷8 decimator and channel 0 comes out clean while channel 1 comes out
aliased — a defect you can measure at 70 dB.

`firmware/patches/optional/0004-filter-both-receive-channels.patch` fixes it in
about six lines of Tcl and 22 DSP slices. This page is why it is needed, what it
costs, and how to turn it on.

> **Opt-in.** `setup.sh` applies only the top level of `patches/`, so nothing
> here happens unless you ask for it. The default build stays byte-identical to
> upstream's block design.

## The defect

Three facts in the stock block design combine badly:

1. **Only channel 0 is filtered.** Channel 0 passes through
   `rx_fir_decimator`; channel 1 goes straight to `cpack` inputs 2 and 3.
2. **`cpack` captures everything on channel 0's timing.** Its write strobe,
   `fifo_wr_en`, comes from `rx_fir_decimator/valid_out_0`. Channel 1's own
   valid, `adc_valid_i1`, is connected to nothing.
3. **The decimator drops the rate by 8.** With it engaged, that strobe fires
   once per eight input samples.

So the moment you engage decimation, channel 1 is sampled at one eighth rate
**with no anti-alias filter in front of it**. Everything outside ±Fs/16 folds
onto it ([why](modulation-and-throughput.md#the-units-first)), and it is
additionally offset from channel 0 by the filter's group delay.

Channel 1 is only a trustworthy receiver while the filter is bypassed.

### Why upstream never noticed

This block design is shared across a family of ADI boards, and many of them run
**1R1T** — one receiver, one transmitter. On those, "a filter on channel 0" is a
filter on the only channel there is, and the asymmetry cannot be observed. It
becomes a defect only on a 2R2T board like this one.

## Measured, before and after

`TX2A` → 20 dB attenuator → `RX2A`. Converter at 61.44 MSPS, decimator engaged
so the fabric delivers 7.68 MSPS — a window of ±3.84 MHz. A tone was generated
in the FPGA at **10 MHz**, deliberately outside that window.

| Channel 1, filter engaged | Strongest bin | Level |
|---|---|---|
| **Stock** | **+2.320 MHz** — an alias | **70.1 dB** |
| **With this patch** | 0.000 MHz (DC offset) | −2.8 dB |

2.320 MHz is exactly 10 − 7.68: the out-of-band tone folding in. Stock, it
arrives at essentially full strength. Patched, it is gone — **better than 70 dB
of suppression**, which is the filter's stopband doing the job it was always
meant to do on this channel.

With the filter bypassed both builds behave identically (tone at +9.999 MHz), so
nothing is lost in the default case.

## What the patch does

The Tcl helper that builds the filter hierarchy already loops over its channel
count:

```tcl
# projects/common/xilinx/adi_fir_filter_bd.tcl
for {set i 0} {$i < $n_chan} {incr i} {
  ad_ip_instance fir_compiler $name/${filter_name}_${i} [ ... ]
  ...
}
```

So the fix is to ask for four channels instead of two, and wire the second pair
through:

```tcl
# ask for 4 (ch0 I/Q and ch1 I/Q) rather than 2
ad_add_decimation_filter "rx_fir_decimator" 8 4 1 {61.44} {61.44} <coe>

# feed channel 1 in
ad_connect axi_ad9361/adc_valid_i1  rx_fir_decimator/valid_in_2
ad_connect axi_ad9361/adc_enable_i1 rx_fir_decimator/enable_in_2
ad_connect axi_ad9361/adc_data_i1   rx_fir_decimator/data_in_2
ad_connect axi_ad9361/adc_valid_q1  rx_fir_decimator/valid_in_3
ad_connect axi_ad9361/adc_enable_q1 rx_fir_decimator/enable_in_3
ad_connect axi_ad9361/adc_data_q1   rx_fir_decimator/data_in_3

# and take cpack's inputs from the filter instead of from axi_ad9361
ad_connect cpack/enable_2        rx_fir_decimator/enable_out_2
ad_connect cpack/fifo_wr_data_2  rx_fir_decimator/data_out_2
ad_connect cpack/enable_3        rx_fir_decimator/enable_out_3
ad_connect cpack/fifo_wr_data_3  rx_fir_decimator/data_out_3
```

Both channels now share one `active` bit, one coefficient set and therefore one
group delay, so they stay sample-aligned. `cpack/fifo_wr_en` still takes
`valid_out_0` — correct, because all four paths now produce output on the same
schedule.

## What it costs

| | Stock | With the patch |
|---|---|---|
| DSP48 slices | 72 / 220 | **94 / 220** |
| Slice LUTs | 11,896 / 53,200 | 12,521 / 53,200 |
| Worst negative slack | +0.205 ns | **+0.215 ns** |
| Timing endpoints | 48,263 | 54,211 |

Two extra `fir_compiler` instances, about 11 DSP slices each. Timing is met with
slightly more margin than stock, and 126 DSP slices remain free.

## Using it

```bash
# run from: the repo root
cd firmware/src && git apply ../patches/optional/0004-filter-both-receive-channels.patch && cd ..

# a block-design change means the Vivado project must go, or it is ignored
rm -rf src/hdl/projects/pluto/pluto.{xpr,cache,gen,hw,ip_user_files,runs,sim,srcs,sdk}

cd .. && ./devkit build --hdl-only && ./devkit verify && ./devkit flash --boot-only
```

`./devkit verify` will report `-> custom design`, which is expected — the block
design is deliberately no longer upstream's.

Then engage the decimator and check both channels:

```bash
# run on your HOST
iio_attr -u ip:192.168.2.1 -i -c cf-ad9361-lpc voltage0 sampling_frequency_available
#   61440000 7680000        <- always {converter rate, converter rate / 8}

iio_attr -u ip:192.168.2.1 -i -c cf-ad9361-lpc voltage0 sampling_frequency 7680000

# channel 0 is voltage0/voltage1, channel 1 is voltage2/voltage3
iio_readdev -u ip:192.168.2.1 -b 131072 -s 262144 cf-ad9361-lpc \
  voltage0 voltage1 voltage2 voltage3 > both.bin
```

## What this does not fix

- **The transmit interpolator.** It is broken for a different reason —
  `tx_upack/fifo_rd_en` is the OR of the interpolator's valid *and* channel 1's
  DAC valid, so on a 2R2T board channel 1 drags the packer along at full rate.
  Measured, TX1 then emits nothing at all. See
  [block-design.md](block-design.md#the-transmit-path). Do not engage it.
- **The shared coefficient file.** Receive and transmit still both point at
  `library/util_fir_int/coefile_int.coe`. Editing it still changes both.
- **Anything about the ÷8 factor.** The driver offers exactly `{1, 8}`; a
  different rate would build and be unreachable from software.

## Why a decimator needs a filter at all

Keeping one sample in eight *is* undersampling. It folds the whole captured
bandwidth into one eighth of it — eight slices stacked on top of one another,
noise included. The FIR empties the seven slices you are discarding **before**
they can fold in.

That is also where the dynamic-range gain comes from: decimating by D buys
10·log₁₀(D) dB of signal-to-noise only *because* the filter removed the noise
living in the bands being dropped. Remove the filter and the gain disappears
along with the usable signal. The anti-alias filter and the processing gain are
the same fact seen from two directions.
