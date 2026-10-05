# The modern kernel: Linux 6.12 on this board

Background for [`firmware-modern/`](../firmware-modern/README.md): why this
kernel, what differs from the factory 5.15, and how to check that nothing a
host tool depends on has changed. To build and flash it:
[change a kernel driver](build/change-a-driver.md) and
[change the device tree](build/change-the-device-tree.md).

## Why ADI 6.12, and not mainline

| Mainline Linux lacks | Why it matters |
|---|---|
| the AD9361 driver | no radio |
| **cyclic transmit** (the board repeating one buffer forever) | `./devkit gpio-check`, the self-test's loopback tone and the MCP server's transmit tools use it |

Cyclic mode depends on `IIO_BUFFER_BLOCK_FLAG_CYCLIC`, an Analog Devices change
to the IIO core (`include/linux/iio/buffer_impl.h`). The board's libiio (0.25,
pinned at `38483f31`) enables its high-speed path, the only one with cyclic
mode, by probing the matching `BLOCK_FREE_IOCTL`. Without it libiio falls back
to plain `read()`/`write()` and `OPEN … CYCLIC` fails at the daemon, with
nothing in the kernel log.

ADI's `main` branch is on 6.12 LTS and still ships `ad9361.c`, `cf_axi_dds.c`,
`cf_axi_adc_core.c` and that flag, so the safety patches rebase and are not
rewritten, and about 18,900 lines of driver code stay upstream's.

## The device tree

`dts/zynq-pluto-sdr-fishball.dts` is an **overlay** on ADI's
`zynq-pluto-sdr.dtsi`, stating only where this board differs from an
ADALM-Pluto. The AD9361 node differs in nine properties: 2R2T mode, four LVDS
interface settings, two synthesiser start frequencies, a transmit feedback
clock delay, and the transmit attenuation.

The attenuation is a safety setting. ADI's default of 10 dB is roughly +9 dBm
out of the SMA connector on this board, applied before any userspace runs; the
tree sets `adi,tx-attenuation-mdB = 89750`, so the transmitter comes up at
−89.75 dB.

Check the **built** `.dtb`, not the build log; two mistakes boot fine:

| Mistake | Effect |
|---|---|
| a `memory@0` node beside the dtsi's `memory` node | the kernel gets two memory sizes; `dtc` only warns "duplicate unit-address" |
| no `adi,channels` | the DMA driver fails to probe on this board's 2018-era FPGA cores (`dma-axi-dmac.c` reads it from hardware only for cores `>= 4.3.a`), and nothing streams |

`firmware-modern/verify_dtb.py` checks the built tree, including that every
node the factory tree enables is still enabled; CI runs it on every push.

## Why `zynq_pluto_defconfig` alone does not work

ADI's defconfig and dtsi describe an ADALM-Pluto, which boots from QSPI flash
and has no Ethernet and no SD card:

| missing | effect | fixed by |
|---|---|---|
| `CONFIG_MACB`, `CONFIG_REALTEK_PHY` | no Ethernet | `config/fishball_defconfig` |
| `CONFIG_MMC` | no SD card | `config/fishball_defconfig` |
| `CONFIG_GPIO_SYSFS` | no GPIO sysfs | `config/fishball_defconfig` |
| `&sdhci0 { status = "disabled"; }` in the dtsi | no SD card, even with the driver built | the board's `.dts` |

Losing the SD card is the expensive one: `tools/flash.sh` mounts
`/dev/mmcblk0p1` on the running board, so such a kernel can only be replaced by
taking the card out. `verify_dtb.py` and CI assert the SD controller is enabled.

| | |
|---|---|
| [`config/fishball_defconfig`](../firmware-modern/config/fishball_defconfig) | what to build: `savedefconfig` output, and the authoritative one |
| [`config/fishball.config`](../firmware-modern/config/fishball.config) | why each option is there. Some (`ETHERNET`, `OF_MDIO`, `DEBUG_KERNEL`, `CRYPTO_ECB`) appear only here, because `savedefconfig` drops anything Kconfig implies |

The `.dts` is built by name (`make … xilinx/zynq-pluto-sdr-fishball.dtb`) and
added to no Makefile, so it stays a drop-in file.

## The driver patches

Ten patches in [`firmware-modern/patches/`](../firmware-modern/patches/README.md),
applied in filename order:

- Eight are rebased from the factory target. Six add the same code; `0004` and
  `0015` differ because ADI's tree changed around them.
- `0019` is new: `clear_state()` cleared the attenuation the unmute restores, so
  a debugfs `initialize` followed by a transmit stream transmitted at full
  power. The same fix is on the factory target.
- ADI's 6.12 never sets `indio_dev->setup_ops`, so the DDS buffer's pre-enable
  and post-disable hooks, where transmit muting lives, never run (gcc warns).
  `0004` restores the line; this should go upstream.
- The Buildroot halves of `0004` and `0012` are not carried, because the Debian
  root replaces Buildroot.

## The IIO contract against 5.15

`firmware-modern/dump_context.py` lists every IIO device, channel and attribute
as sorted text, so comparing kernels is a `diff`. The whole difference:

| | |
|---|---|
| added | `waiting_for_supplier` on all four devices (driver core) |
| added | `adi,agc-dig-sat-ovrg-enable`, a new AD9361 debug attribute |
| removed | four `label` channel attributes on `cf-ad9361-lpc` (they returned `-ENOSYS` on 5.15 and could never be read) |

All seven transmitter-safety attributes are present and read their 5.15 values.

## Receive throughput

On the board, no network: `iio_readdev -b 1048576` at 61.44 MS/s. 5.15 and
6.12 give the same figures, run interleaved on the same board.

| samples per run | 1 receive channel | 2 receive channels |
|---|---|---|
| 33.6 M | 183.1 MB/s | 346.4 MB/s |
| 134.4 M | 220.0 MB/s (57.7 MS/s) | 430.8 MB/s (56.5 MS/s per channel) |

Run length matters more than the kernel: start-up is inside the timed window.
Use long runs, and [`tools/throughput-ab.sh`](../tools/throughput-ab.sh) to
compare two kernels with the same method.

## Reproducible builds

The device tree is reproducible (CI checks it). The `uImage` is not by default,
because the kernel and `mkimage` stamp the build time, which is how you tell
which kernel is on a card. To compare two builds byte for byte, pin the
stamps: [how](build/change-a-driver.md#comparing-two-builds-byte-for-byte).

With only `KBUILD_BUILD_*`, the kernel is identical but six bytes of the
64-byte U-Boot header (`ih_time` and its checksum) differ.
