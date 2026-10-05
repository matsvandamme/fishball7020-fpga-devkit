# Why the modern target runs Debian

The factory firmware runs Buildroot and busybox from a RAM disk: no `apt`,
nothing survives a reboot, many tools missing. The modern target's root
filesystem is **Debian 13 (trixie) armhf with systemd** on an ext4 SD-card
partition ([issue #4](https://github.com/matsvandamme/fishball7020-fpga-devkit/issues/4)).
This page explains the design, for anyone changing it.

| To | See |
|---|---|
| rebuild the root and write a card | [rebuild the Debian root](build/rebuild-the-debian-root.md) |
| start quickly | [`firmware-modern/debian/README.md`](../firmware-modern/debian/README.md) |
| look up a unit or setting | [`debian-root-reference.md`](debian-root-reference.md) |

## Building and writing the root

The commands: [rebuild the Debian root](build/rebuild-the-debian-root.md).
Rebuild whenever `firmware-modern/debian/overlay/` changes: `write-card`
refuses a `rootfs.tar` older than the overlay and lists what it would miss.

The root is built inside Debian's official `arm32v7/debian:trixie` container
image, with `apt` running as native armhf under `qemu-user` emulation. Not
`mmdebstrap`: Ubuntu 22.04's `debian-archive-keyring` stops at bullseye and
fails with `NO_PUBKEY 6ED0E7B82643E131`. Every package, with the reason for
each unobvious one, is in
[`packages.txt`](../firmware-modern/debian/packages.txt); for example
`fw_printenv`/`fw_setenv` come from `libubootenv-tool`, and without them the
board cannot read its MAC from U-Boot and picks a random one each boot.

## The card and the boot path

The Zynq's boot ROM reads `BOOT.bin` from a **FAT** partition:

| | | |
|---|---|---|
| `p1` | FAT32, 128 MB | `BOOT.bin`, `uImage`, `devicetree.dtb`, `uEnv.txt`, and the Buildroot ramdisk if a factory build is available |
| `p2` | ext4, the rest | the Debian root (about 300 MB minimal; a few GB with a compiler and Python) |

- **U-Boot needs no rebuild and no ext4 support.** `preboot` imports
  `uEnv.txt`, which defines the boot command `sdboot`, so the boot command and
  kernel command line are data on the card. U-Boot loads the kernel and device
  tree from FAT; the kernel mounts the ext4 root.
- **The kernel needs two more options**, `CONFIG_NAMESPACES` and
  `CONFIG_AUTOFS_FS`, added in `fishball_defconfig`; systemd's other
  requirements were already on.

The factory `sdboot` loads a ramdisk; the ext4 version drops that load, passes
`-` in its place, and names the root on the command line:

```
bootargs=console=ttyPS0,115200 root=/dev/mmcblk0p2 rootwait rw clk_ignore_unused net.ifnames=0
sdboot=if mmcinfo; then run uenvboot; load mmc 0 ${fit_load_address} ${kernel_image} \
  && load mmc 0 ${devicetree_load_address} ${devicetree_image} \
  && bootm ${fit_load_address} - ${devicetree_load_address}; fi
```

**`rootwait` is required**: the SD controller probes asynchronously.
`firmware-modern/debian/make-uenv.sh` generates the real file, which boots
either root, chosen by `rootfs_mode`.

## Why Debian's `iiod` is safe to use

`iiod` is the libiio server every host tool talks to. **Cyclic transmit**
(`OPEN <dev> <n> <mask> CYCLIC` on TCP 30431, the board repeating one buffer in
hardware) exists only in libiio's high-speed path, enabled by probing for
`BLOCK_FREE_IOCTL`; an `iiod` without it silently breaks `./devkit gpio-check`,
the self-test's loopback tone and the MCP server's transmit tools.

The factory board runs libiio 0.25 (commit `38483f31`); trixie ships **0.26**,
the last 0.x. `local.c`, which holds the high-speed probe and cyclic code, is
identical between them (`git diff --quiet 38483f31 v0.26 -- local.c`), so the
image installs Debian's `iiod`, held at that version by an apt pin
(`overlay/etc/apt/preferences.d/fishball-libiio.pref`).

The factory `iiod` binary cannot be copied across: it needs `libaio.so.1`, and
trixie has only `libaio.so.1t64` (64-bit `time_t`). A symlink would hand a
32-bit-`time_t` caller a library expecting 64 bits, since `io_getevents()`
takes a `struct timespec *`.

## The factory init scripts, and what replaced them

| factory script | what it does | on Debian |
|---|---|---|
| `S21misc` | sets both transmitters to −89.75 dB at boot; points the USER LED at the `tx-active` trigger | `fishball-rf-quiesce`, and `fishball-identity` for the LED |
| `S23udc` | mints the persistent `hw_serial` into `/mnt/jffs2`; writes `/etc/libiio.ini`; sets up the USB gadget | `fishball-identity`, `fishball-usb-gadget`, `fishball-usb-bind` |
| `S40network` | takes `eth0`'s MAC from U-Boot's environment; sends a DHCP hostname | `overlay/etc/network/interfaces` |

Three things must not be lost:

- **The boot-time transmitter mute is a safety mechanism, and its ordering is
  what makes it work**: it must run before anything can open a transmit buffer.
- **`/etc/libiio.ini`** supplies `hw_model`, `hw_serial` and `fw_version` to
  the self-test and the MCP server.
- **`/mnt/jffs2` is never reformatted.** `hw_serial` lives there and fixes the
  USB interface name on your PC and the board's identity in stored baselines.

## The compatibility contract

"It boots" is not the bar. Every host tool, the MCP server and the GNU Radio
examples depend on:

- `iiod` on TCP 30431 **with cyclic transmit working** (`./devkit gpio-check`
  fails loudly if it is broken)
- the seven transmitter-safety attributes present and behaving
- `/etc/libiio.ini` supplying `hw_model`, `fw_version` and the *same* `hw_serial`
- `ssh` as root, which `tools/flash.sh` and `./devkit selftest --ssh` use
- `./devkit selftest --loopback --pad 20` passing, as on the factory firmware
- `./devkit temps`, `./devkit net show` and `./devkit gpio-check` unchanged

`tools/flash.sh` mounts only the FAT `p1`, so `flash --rootfs-only` does not
apply to this target.

## What this does not change

- **U-Boot is still 2016.07.** Replacing it has its own rollback problem: the
  boot ROM loads `BOOT.bin` by a fixed name, with no A/B slot.
- **The bitstream is unchanged**; both targets boot the same FPGA design.
- **The factory target keeps Buildroot**, which its byte-identical claim needs.
