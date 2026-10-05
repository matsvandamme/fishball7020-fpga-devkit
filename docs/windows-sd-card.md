# Writing the card on Windows

What `write-card.cmd` does, what it needs, its error messages, and how to go
back. To write a card now, follow
[write the card on Windows](start/write-the-card-windows.md).

| | |
|---|---|
| What it writes | the modern firmware (v2.x: Linux 6.12 and Debian 13): **two partitions**, a small FAT32 one the board boots from, and a Linux (ext3) one holding Debian |
| Why a script | Windows can make the first partition but not the second, so copying files onto the card is not enough |
| PC | Windows 10 or 11, nothing installed: no WSL, no Python, no extra tools |
| Card | a microSD card of **1 GB or more** (4 to 32 GB is typical), and a card reader |
| Time | about five minutes |
| Download | seven files from the [latest release](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases/latest) |

## What it does

| Step | What happens |
|---|---|
| Check | every downloaded file against `SHA256SUMS`, so a damaged download is caught before anything is erased |
| List | the SD cards and USB disks it is willing to write, and asks which one. It never lists the disk Windows runs from, the disk the downloads are on, or anything under 1 GB or over 256 GB |
| Back up | every file already on the card, into a backup folder next to the script. For a card with the factory firmware on it, that backup is your way back |
| Confirm | asks you to type `ERASE` |
| Write | the partition table, the boot partition `FISHBOOT`, and the Debian partition `fishroot`, unpacked from `debian-rootfs.tar.gz` |
| Verify | reads everything back from the card and compares it with what it wrote, then checks the boot files once more through Windows |
| Log | `write-card-<date>.log` in the same folder. Send it along if something goes wrong |

## Step by step

The nine steps, with every prompt and what to click:
[write the card on Windows](start/write-the-card-windows.md).

## Going back to the old firmware

If you kept the old card, put it back in the board. That is all.

If you rewrote the board's own card, the backup folder holds a `README.txt`.
In short:

1. Format a microSD card as FAT32 with one partition (in Explorer: right-click
   the card, **Format**, **FAT32**).
2. Copy the files from the `partition1-...` folder onto it.
3. Put it in the board.

The factory firmware is a handful of files on one FAT32 partition, which is why
that works.

## If something goes wrong

| What you see | Cause and fix |
|---|---|
| `No SD card found` | The card is not in the reader, or the reader is not plugged in. Insert it, wait a few seconds, run again. A card over 256 GB is refused on purpose. |
| `disk N is write-protected` | A full-size SD adapter has a lock switch on its side. Slide it towards the contacts. |
| `could not open the card for writing` | Something has the card open: an Explorer window, a photo importer, an antivirus scan. Close it, take the card out and put it back, run again. |
| `SHA256SUMS ... does not match` | The download is damaged, or the files come from different releases. Download that file again. |
| `read back differs` | The card or the reader is faulty. Try another card. |
| The board does not answer at `192.168.2.1` | Give it a full minute. Check the `BOOT` switch and the mains charger. Unplug and replug the USB cable to your PC. Then see [troubleshooting](troubleshooting.md). |

!!! danger "Never update this board with DFU, or through a \"PlutoSDR\" USB drive"
    That route is meant for a different board, the ADALM-Pluto, and has bricked
    boards like this one. Changing firmware here always means rewriting the card, as above.

## How it works, briefly

| | |
|---|---|
| the Linux partition | Windows has no way to create it, so the script builds it itself: about a thousand lines of C# inside the `.cmd`, compiled on the spot by Windows PowerShell |
| filesystem | **ext3**, which is ext2 with a journal: simpler to write than ext4, and the board's kernel mounts it with its ext4 driver all the same |
| writing | the card as a raw disk, like Rufus or balenaEtcher do |
| interrupted run | the partition table is written last, so it leaves a card that is plainly blank rather than half-written |

`write-card.cmd -ImageFile card.img` writes a card image file instead, for
Rufus, balenaEtcher or testing. On Linux,
`sudo python3 tools/check_card_image.py card.img <release folder>` checks such
an image entry by entry against the release. The repository's CI runs the
script under Windows PowerShell 5.1 for every change, into an image file and
into a virtual disk, and checks both that way.

The cards it writes have been checked under Windows and Linux. They have not
yet been booted on a board: tell us how yours goes.
