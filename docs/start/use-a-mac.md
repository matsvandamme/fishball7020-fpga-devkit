---
icon: material/apple
description: What works from macOS, what needs firmware v2.4 or later, and what was not tested.
---

# Use the devkit on a Mac

The host tools, the card writer, the container build and the patched SDR++ run
on macOS. The USB network needs one setting on the board, and firmware v2.4 or
later.

Everything on this page was tested on 2026-11-21 on one Apple Silicon Mac, with
the `/bin/bash` 3.2 that macOS ships and no `sshpass` installed. The board
tests used a PlutoSky R2; release v2.4 was then booted and switched to `ncm`
on a PlutoSky R1. Intel Macs were not tested.

| Task | On a Mac | Status |
|---|---|---|
| Log in, `status`, `net`, `selftest --ssh`, `flash` | the same commands as on Linux | tested on a board |
| Write a card | `./devkit write-card` with `/dev/diskN` | release v2.4's card was written on a Mac and booted in an R1 (2026-11-21) |
| Reach the board over the USB cable | switch the board to `ncm` | tested; needs firmware v2.4 or later |
| Build the firmware | `./devkit container`, with Docker through Colima | release v2.4's boot files and Debian root were built this way and booted; the factory-target build was not booted |
| SDR++ with this board's patch | `tools/sdrpp/build-macos.sh` | builds and starts; receiving in the window was not checked |

## Set up the host tools

Flashing and checking a board need `ssh`, `python3` and a way to log in.
macOS has `ssh`; `python3` comes with `xcode-select --install`.

```bash
# run from: the repo root, on the Mac
./devkit doctor --host      # ssh, python3 and a login, nothing about building
./devkit ssh-key            # makes ~/.ssh/fishball; asks for the board's password once (analog)
./devkit status             # what the board runs
```

- **No `sshpass` needed.** `flash`, `net`, `selftest --ssh` and `gpio-check`
  try the key `./devkit ssh-key` makes first, and use `sshpass` only where it
  is installed. Without a key and without `sshpass` they stop and name both
  fixes. One exception: `./devkit verify --target factory --board` still needs
  `sshpass`.
- **Tested from the Mac on a PlutoSky R2:** `ssh-key`, `net`, `net find`,
  `status`, `selftest --ssh`, `flash --kernel-only --no-reboot`, and `flash`
  with the reboot.
- **A macOS job in CI** runs the host tests under bash 3.2.

Tab completion, in zsh or bash:

```bash
# run from: the repo root, on the Mac
eval "$(./devkit completion)"          # this shell
./devkit completion install --rc       # every new shell: adds one line to ~/.zshrc
```

Without `--rc` it prints the line and edits nothing. `--shell bash` writes for
bash, whose startup file on a Mac is `~/.bash_profile`.

## Write a card

```bash
# run from: the repo root, on the Mac. DESTROYS everything on the card
diskutil list external physical                              # names the card: /dev/diskN
./devkit write-card --from ~/Downloads --dry-run /dev/diskN  # every check and the plan; writes nothing
sudo ./devkit write-card --from ~/Downloads /dev/diskN
```

`--from` names the directory holding a downloaded release: `BOOT.bin`,
`uImage`, `devicetree.dtb`, `uEnv.txt` and `debian-rootfs.tar.gz`, and
`SHA256SUMS` if you downloaded it, against which each file is then checked.
The writer is two Python files with no dependencies
(`tools/write_card_mac.py`, `tools/card_image.py`): no Linux tools and no
container.

- **It refuses** internal disks (except a card in the Mac's own SD slot), the
  disk macOS runs from, disks that are not removable, disk images, partitions,
  and anything over 280 GB (`ALLOW_LARGE=1` lifts that one).
- **It checks the whole release before it erases anything**, shows what it
  will erase, and makes you type the disk's name.
- **It reads back everything it wrote** and compares, then reads the four boot
  files out of the FAT partition and compares their SHA-256.
- **`--image FILE`** writes the same layout into a new file, 2048 MB unless
  `--size MB` says otherwise. It needs no `sudo`.

The card differs from one the Linux writer makes in one way: the root
partition is **ext3**, as from the Windows writer, where Linux makes ext4. The
kernel mounts it with its ext4 driver. As on Linux, the root fills the rest of
the card.

**Tested:** a 32 GB card in a USB reader, release v2.3: 926 MB written in 81 s
and read back identical. That card was written on a Mac and booted in an R1 on 2026-11-21.
So was a card with release v2.4's files: 24 s to a running system, no failed
units, and `/boot` on the board matching `SHA256SUMS`.

## Reach the board over the USB cable

The board's USB network is RNDIS by default, and macOS has no RNDIS driver: a
Mac sees no network port, and `192.168.2.1` does not answer. Three things still
work in that state:

- **Ethernet:** `ssh root@fishball.local`.
- **libiio over USB:** the `usb:` transport needs no network. A scan from the
  Mac listed the boards over USB in either mode.
- **The serial console on the same cable:** `screen /dev/cu.usbmodem* 115200`,
  user `root` (not tested).

!!! warning "Needs firmware v2.4 or later"
    The switch below is not in release v2.3 or earlier. On those a Mac reaches
    the board over Ethernet.

Switch the board to NCM, which macOS drives:

```bash
# run on: the board (over Ethernet, or the serial console)
fishball-usb-mode ncm       # stores it in the U-Boot environment and applies it now
fishball-usb-mode           # shows what is set and what runs
fishball-usb-mode rndis     # back to the default
```

Everything on the USB cable drops for a few seconds while it switches: the
network, the console and USB libiio. Ethernet is not touched.

**You should see** a network port named `PlutoSDR (ADALM-PLUTO)` in System
Settings on the Mac. The board hands the Mac `192.168.2.10`, and
`ssh root@192.168.2.1` works.

**Tested** on a PlutoSky R2 with the Mac: with `ncm` set in `/etc/default/fishball-usb-gadget` the
port appeared, the Mac got `192.168.2.10`, and ping, ssh and
`./devkit selftest` worked over `192.168.2.1`. The setting survived a
reboot, and switching back to `rndis` worked. On a PlutoSky R1 with release
v2.4, `fishball-usb-mode ncm` gave the Mac a network port and `192.168.2.10`,
and `fishball-usb-mode rndis` switched it back.

| Mode | Windows | Linux | macOS |
|---|---|---|---|
| `rndis` (the default) | yes | yes | no driver |
| `ncm` | Windows 11; Windows 10 has no in-box driver | yes | yes |
| `ecm` | no driver | yes | yes |

With no Ethernet and no console, the mode can be set on the card instead. Put
the card in the Mac's reader and add one line to `uEnv.txt` on its `FISHBOOT`
partition (not tested on a board):

```bash
# run from: anywhere, on the Mac, with the card in a reader
printf '\nusb_ethernet_mode=ncm\n' >> /Volumes/FISHBOOT/uEnv.txt
diskutil eject /Volumes/FISHBOOT
```

A rewritten card loses that line; the U-Boot variable `fishball-usb-mode` sets
does not. All three places the mode is read from, and their order:
[networking](../networking.md#the-usb-network-rndis-ncm-or-ecm).

## Build the firmware

macOS cannot build the firmware natively, and `./devkit build` says so. The
build runs in a Linux container, with Docker through Colima:

```bash
# run from: anywhere, on the Mac, once
brew install colima docker docker-buildx
colima start --vm-type vz --vz-rosetta --mount-type virtiofs --cpu 8 --memory 16 --disk 120
```

The modern firmware, with no Vivado:

```bash
# run from: the repo root, on the Mac
./devkit container build-image                    # once: a native arm64 image
./devkit container doctor
./devkit container setup                          # the sources, 1 min 36 s
./devkit container build --xsa "$(./firmware-modern/fetch-pinned-xsa.sh)"   # 46 s
./devkit container verify                         # checks the output; not ./devkit verify
./devkit build --rootfs-only                      # the Debian root, on the Mac itself: 1 min 43 s
```

- **The sources live in Docker volumes**, not on the Mac's disk. The output
  lands on the Mac's disk, in `firmware-modern/output/`.
- **`--rootfs-only` is the one build that runs on the Mac itself.** It drives
  `docker buildx`.
- **Keep the checkout under your home directory:** Colima shares only that
  with its VM.

The FPGA build with Vivado also works, in an x86-64 image under Rosetta: the
full factory build took 1 h 04 min and met timing. The commands, what was
measured and what was not proven:
[building in a container](../building-in-a-container.md#macos-on-apple-silicon).

Release v2.4's boot files and Debian root were built this way on an Apple
Silicon Mac and booted in an R1. The factory-target build made on the Mac was
not booted.

## SDR++ with this board's patch

```bash
# run from: the repo root, on the Mac
tools/sdrpp/build-macos.sh --install-deps    # without the flag it names the missing Homebrew formulae and stops
~/.cache/fishball-sdrpp/sdrpp                # the launcher it writes
```

It builds SDR++ at the pinned commit with the patch and the DAB+ decoder into
one directory, with no `sudo`. Pick the board from the device menu under the
**PlutoSDR** source, which lists what libiio's scan finds. If the board is not
in it, type its address (`192.168.2.1` on the USB cable) in **Address** and
press **Use address**.

**Tested:** it builds, starts, and loads the PlutoSDR source, the audio sink
and the DAB+ decoder. Receiving in the window was not checked. Fast TCP
(`zc-stream`) was measured from the Mac with a script on a PlutoSky R2: 20 MS/s
arrived in full on both receive ports.

Details: [install the patched SDR++](../radio/install-patched-sdrpp.md).

## Not tested

- Intel Macs, and podman on macOS.
- `./devkit container install` with AMD's real installer. Vivado came from an
  existing Docker volume.
- Booting the factory-target build made in the container on the Mac.
- `./devkit ssh-key` saving the key in `/mnt/jffs2` on the factory (Buildroot)
  root, so that it survives a reboot.
- Receiving in the SDR++ window.
