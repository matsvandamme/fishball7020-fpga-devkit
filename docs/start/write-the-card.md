---
icon: material/sd
description: Download the latest release and write it to a microSD card, from Linux or Windows.
---

# Put the firmware on a card

Download the [latest release](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases/latest)
and write it to the card. The modern firmware needs **two partitions**
(boot files, then Debian), so copying files is not enough: use the writer.


![The two partitions of the card: a 128 MB FAT boot partition holding BOOT.bin, uImage, devicetree.dtb and uEnv.txt, and a Debian root partition on the rest of the card, which Windows cannot create by itself.](../img/start-card-light.svg#only-light)
![The two partitions of the card: a 128 MB FAT boot partition holding BOOT.bin, uImage, devicetree.dtb and uEnv.txt, and a Debian root partition on the rest of the card, which Windows cannot create by itself.](../img/start-card-dark.svg#only-dark)

**Back up every file on the board's current card first.** That is your way back.

=== "Linux"

    With the release files in `~/Downloads`:

    ```bash
    # run from: the repo root. DESTROYS everything on the card
    ./devkit write-card --dry-run /dev/sdX        # checks the device, writes nothing
    sudo ./devkit write-card --from ~/Downloads /dev/sdX
    ```

    It refuses non-removable disks, but **check the device name yourself**.

=== "Windows"

    Put `write-card.cmd` from the release next to its other six files and
    double-click it. Nothing to install. Step by step, with every prompt:
    [write the card on Windows](write-the-card-windows.md).

=== "Factory firmware"

    One FAT32 partition: copy the five files of
    [v1.7](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases/tag/v1.7)
    onto the card.

**You should see:** the writer ends with its own check passing (on Windows,
`OK: all ... read back identical`).

!!! warning "Never update this board with DFU"
    It has bricked units of this board. Changing firmware always means rewriting
    the card, or `./devkit flash` on a running board ([flashing reference](../flashing.md)).

**Next:** [connect and find the board](connect.md).
