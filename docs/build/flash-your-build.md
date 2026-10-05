---
icon: material/upload-network-outline
description: ./devkit flash puts a build on the running board over the network, backed up and md5-verified.
---

# Put it on the board

```bash
# run from: the repo root
./devkit flash              # BOOT.bin + uImage
./devkit flash --boot-only  # BOOT.bin only: an HDL or bitstream change
./devkit flash --kernel-only
./devkit flash --dtb-only
```

It backs up the current files, checks the md5 of each new file on the board
before swapping it in, unmounts cleanly and reboots (about 40 seconds). The
previous files stay on the card as `*.prev` and on your disk in
`firmware/.flash-backups/<stamp>/`.

| You changed | Flag |
|---|---|
| the FPGA (HDL, block design) | `--boot-only` |
| a driver or the kernel config | `--kernel-only` |
| the device tree | `--dtb-only` |
| the Debian root | none: write a new card ([rebuild the Debian root](rebuild-the-debian-root.md)) |

**You should see:** `./devkit verify --board` report the card matches your build.

!!! danger "Never flash with DFU"
    It has bricked units of this board, and it cannot replace `BOOT.bin` at all.

??? question "The new kernel does not boot?"
    Put the `.prev` file back from a card reader. One that boots but misbehaves:
    another `--kernel-only`. Every option, including JTAG and a second card:
    [flashing reference](../flashing.md).
