# Changing the kernel

Much of the board's behaviour (what appears in `/sys`, when the transmitter is
muted, the serial number) lives in the Linux kernel and Analog Devices' (ADI's)
drivers, not in the FPGA. This page is the reference for both kernels: which
one to use, what is already patched, the options, debugging, and making a
change stick. The steps are in [change a kernel driver](build/change-a-driver.md)
and [change the device tree](build/change-the-device-tree.md).

![The kernel loop as four boxes: edit the driver and add dev_warn(); build uImage, about two minutes; flash --kernel-only, back in about fifteen seconds; read dmesg on the board. A dashed arrow leads back to the start: and again.](img/build-kernel-loop-light.svg#only-light)
![The kernel loop as four boxes: edit the driver and add dev_warn(); build uImage, about two minutes; flash --kernel-only, back in about fifteen seconds; read dmesg on the board. A dashed arrow leads back to the start: and again.](img/build-kernel-loop-dark.svg#only-dark)

## Rebuild and flash

`./devkit build` builds the kernel with everything else; while iterating, build
it alone (about two minutes) and flash `uImage` alone: the board is back in
about fifteen seconds. A changed device tree goes with `--dtb-only`.

| | Commands |
|---|---|
| build and flash `uImage`, either kernel | [change a kernel driver](build/change-a-driver.md) |
| build and flash the device tree, either kernel | [change the device tree](build/change-the-device-tree.md) |

| Term | Meaning |
|---|---|
| **the kernel** | built as one file (`uImage`) |
| **a driver** | kernel code operating a device (the AD9361, the FPGA's capture and playback blocks) |
| **the device tree** | `devicetree.dtb`, compiled from a `.dts`: describes what hardware exists and where |
| **a defconfig** | a saved set of build options |
| **cross-compiling** | building on your PC for the board's ARM cores, hence `ARCH=arm CROSS_COMPILE=…` |

Not sure the kernel is where your change belongs? See
[using this board in your own project](your-own-project.md) and lesson 23 of
[Fabric School](course/index.html).

**Compiler.** Either ARM Linux compiler builds both kernels and, through
`./devkit build`, U-Boot. On the factory target prefer
`gcc-arm-linux-gnueabi`: only it rebuilds the factory kernel byte for byte.
Building U-Boot by hand with `gnueabihf` needs
`CC="arm-linux-gnueabihf-gcc -mfloat-abi=soft"` ([troubleshooting](troubleshooting.md)).
Buildroot's toolchain is needed only for the factory root filesystem.

## Which kernel

| | `firmware/` | `firmware-modern/` |
|---|---|---|
| Linux | **5.15.0**, the vendor's fork of a fork | **6.12.0 LTS**, Analog Devices' `main` |
| source appears at | `firmware/src/linux` (beside U-Boot and Buildroot) | `firmware-modern/src/linux` (just the kernel) |
| created by | `./devkit setup --target factory` | `./firmware-modern/setup.sh` |
| device tree | `arch/arm/boot/dts/zynq-pluto-sdr-fishball.dts`, 1003 lines, flat | `arch/arm/boot/dts/xilinx/zynq-pluto-sdr-fishball.dts`, 228 lines, an overlay on ADI's `zynq-pluto-sdr.dtsi` |
| defconfig | `zynq_pluto_defconfig` | `fishball_defconfig` |
| patches | `firmware/patches/`, 18 of them | `firmware-modern/patches/`, nine, drivers only |

**Use `firmware-modern/` unless you need the factory kernel**: it is a current
LTS kernel with the transmitter-safety patches, tested on hardware.
`firmware/` exists because the byte-identical factory claim only means
something against the factory kernel. [Why 6.12 and not
mainline](modern-kernel.md#why-adi-612-and-not-mainline).

## What is already patched

The full factory list, with a section on each, is
[`firmware/patches/README.md`](../firmware/patches/README.md). Examples:

| Patch | Touches | Does |
|---|---|---|
| `0001-fishball7020-fixes.patch` | buildroot scripts | six upstream fixes; mints a persistent `hw_serial` on first boot |
| `0002-add-fishball-devicetree.patch` | `arch/arm/boot/dts/` | the board's device tree, as editable source |
| `0004-mute-tx-when-no-dma-stream.patch` | `drivers/iio/adc/ad9361.*`, `drivers/iio/frequency/cf_axi_dds*` | mutes the transmitter whenever no DMA buffer streams |
| `0005-dont-clobber-a-gain-set-before-streaming.patch` | the same two drivers | stops the unmute overwriting a gain you set before starting (the smallest; read it first) |

[`firmware-modern/patches/`](../firmware-modern/patches/README.md) carries
`0004`, `0005`, `0007`, `0012`, `0015`, `0016`, `0017` and `0018` rebased (six
add byte-identical code), plus `0019`. `0019` fixes a case also present in 5.15:
`ad9361_clear_state()` memset the attenuation the kernel restores on unmute,
and 0 mdB (millidecibels) is full output, so a debugfs `initialize` followed by
any transmit stream keyed the transmitter at full power.

## Kernel options

On `firmware/`, `build_all.sh` reapplies `zynq_pluto_defconfig` on **every**
full build, so `menuconfig` is a scratch edit; to keep it, edit the defconfig
(as a patch) or use `make savedefconfig`.

```bash
# run from: firmware/
make -C src/linux ARCH=arm CROSS_COMPILE=arm-linux-gnueabi- menuconfig
```

On `firmware-modern/` the source is `fishball_defconfig` (CI checks it
round-trips through `savedefconfig`). **Do not build `zynq_pluto_defconfig`
there**: it is for an ADALM-Pluto and gives a kernel that boots cleanly with no
Ethernet and no SD card. `firmware-modern/config/fishball.config` explains the
26-option difference. On either board, `zcat /proc/config.gz` shows what the
running kernel was built with.

| Option | Why you would touch it |
|---|---|
| `CONFIG_AD9361` | the transceiver driver: already `y` |
| `CONFIG_CF_AXI_ADC` / `CONFIG_CF_AXI_DDS` | capture and playback behind `cf-ad9361-lpc` and `cf-ad9361-dds-core-lpc` |
| `CONFIG_IIO_BUFFER` / `CONFIG_IIO_KFIFO_BUF` | the buffered-capture machinery every streaming tool needs |
| `CONFIG_DYNAMIC_DEBUG` | turns the drivers' `dev_dbg` messages on at runtime; off by default, and very useful |
| `CONFIG_FTRACE` / `CONFIG_KPROBES` | effectively **off on both kernels**: without `CONFIG_FUNCTION_TRACER` the only tracer is `nop`, though `trace_marker` works for userspace timestamps. Enable it for a debug build if printk is not enough |

## Debugging a driver change

On the factory target (busybox) the points below apply; on
`firmware-modern/` (Debian 13) `pkill`, full `ps`, `gdb` and anything you
`apt install` are available.

- **No ftrace, no kprobes** (both kernels). Use `dev_warn()` plus
  `dump_stack()` and read `dmesg`; the `Comm:` line names the process that
  called in, often the whole answer.
- **No `pkill` on busybox.** Use `ps` and `kill` with a PID; a `pkill` with
  `2>/dev/null` fails silently and leaves the process running.
- **An empty `dmesg` is information**: look in userspace, or in `/mnt/jffs2`
  (scripts there run at boot on Buildroot).
- **`/sys/kernel/debug/iio/iio:device0/`** exposes the AD9361's BIST (built-in
  self test), every `adi,*` device-tree value, and `calib_mode`.

## Transmitter safety attributes

Settings the patched driver adds. All report what the radio actually holds.

| Attribute | Device | Default | What it does |
|---|---|---|---|
| `tx_starve_timeout_ms` | `iio:device2` | `250` | Mute if the DAC gets no data for this long. `0` disables. Values under 20 ms are refused: this board's network path delivers in bursts, and a shorter timeout would mute healthy streams. |
| `tx_cyclic_timeout_ms` | `iio:device2` | `0` (off) in the driver, **`60000` on this devkit's root filesystem** | Bound an unattended **cyclic** transmit, which otherwise repeats forever in hardware. `fishball-rf-quiesce` arms it at boot; `fw_setenv tx_cyclic_bound <ms>` changes it, `0` disables. |
| `tx_disable` | `iio:device0` | `0` | Latch maximum attenuation. Survives debugfs `initialize`, and blocks `bist_tone` mode 1. |
| `tx_temp_limit` | `iio:device0` | `0` (off) | Millidegrees C. Refuse to *lower* attenuation above this die temperature. |
| `tx_dma_underflow_count` | `iio:device2` | counter | the DAC ran out of data; any write resets it |
| `tx_dma_overflow_count` | `iio:device2` | counter | the DMA could not keep up; any write resets it |

```bash
# run from: the board
cd /sys/bus/iio/devices/iio:device2
cat tx_starve_timeout_ms tx_dma_underflow_count
echo 0 > tx_dma_underflow_count      # any write resets it
```

Why these exist: [transmitter safety](transmitter-safety.md) and
[`tools/IDLE-CASES.md`](../tools/IDLE-CASES.md).

## Making it stick

Both `src/` directories are regenerated by their `setup.sh`, so a change
survives only as a patch. Generate it against the applied tree, number it after
the existing ones, and add a CI assertion (every patch has one):

| target | patches go in | assertion goes in |
|---|---|---|
| `firmware/` | `firmware/patches/` | `.github/workflows/verify-patches.yml` |
| `firmware-modern/` | `firmware-modern/patches/` | `.github/workflows/verify-modern.yml` |

**Never put a safety-relevant field in `struct ad9361_rf_phy_state`.**
`ad9361_clear_state()` memsets it and debugfs `initialize` calls that, so
anything there can be cleared by the interface it defends against. Use
`struct ad9361_rf_phy`, and seed the field so that zero is not the dangerous
value.

The modern workflow also builds and audits the device tree
(`firmware-modern/verify_dtb.py`, 16 checks, because device-tree mistakes
usually build and boot) and cross-builds `uImage`, failing on a warning in any
patched file. Details: [`CONTRIBUTING.md`](../CONTRIBUTING.md).
