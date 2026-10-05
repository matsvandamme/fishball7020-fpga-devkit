---
icon: material/debian
description: Rebuild rootfs.tar after a change to the overlay, then write a new card.
---

# Rebuild the Debian root

The modern firmware's root is **Debian 13 (trixie) armhf with systemd**, on its
own ext4 partition. Rebuild it whenever `firmware-modern/debian/overlay/`
changes:

```bash
# run from: the repo root
./devkit build --rootfs-only        # -> firmware-modern/debian/rootfs.tar
sudo ./devkit write-card /dev/sdX   # refuses anything not removable
```

`write-card` refuses a `rootfs.tar` older than the overlay, and lists what it
would miss. The root cannot be swapped over the network: it takes a card.

![The two partitions of the card: a 128 MB FAT boot partition holding BOOT.bin, uImage, devicetree.dtb and uEnv.txt, and a Debian root partition on the rest of the card.](../img/start-card-light.svg#only-light)
![The two partitions of the card: a 128 MB FAT boot partition holding BOOT.bin, uImage, devicetree.dtb and uEnv.txt, and a Debian root partition on the rest of the card.](../img/start-card-dark.svg#only-dark)

| Where | What |
|---|---|
| `firmware-modern/debian/packages.txt` | every package, with the reason for each unobvious one |
| `firmware-modern/debian/overlay/` | the files laid over Debian: units, scripts, settings |

!!! tip "A small change needs no rebuild"
    The root is an ordinary writable disk: `apt install`, or edit the file in
    place on the board. Rebuild when the change belongs in every card.

Why Debian, and what each unit does: [why Debian](../debian-rootfs.md) ·
[the Debian root reference](../debian-root-reference.md).
