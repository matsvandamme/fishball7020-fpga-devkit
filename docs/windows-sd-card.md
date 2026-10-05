# Writing the card on Windows

The modern firmware (v2.x: Linux 6.12 and Debian 13) lives on a microSD card
with **two partitions**: a small FAT32 one the board boots from, and a Linux
(ext3) one holding Debian. Windows can make the first but not the second, so
copying files onto the card is not enough. `write-card.cmd` does the whole job
on a Windows 10 or 11 PC with nothing installed: no WSL, no Python, no extra
tools.

- **time:** about five minutes
- **card:** a microSD card of **1 GB or more** (4 to 32 GB is typical), and a card reader
- **PC:** Windows 10 or 11, nothing installed
- **download:** seven files from the [latest release](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases/latest)

!!! tip "Use a new card if you can, and keep the one in the board as it is"
    Going back to the old firmware is then just swapping the cards.

## What it does

1. Checks every downloaded file against `SHA256SUMS`, so a damaged download is
   caught before anything is erased.
2. Lists the SD cards and USB disks it is willing to write, and asks which one.
   It never lists the disk Windows runs from, the disk the downloads are on, or
   anything under 1 GB or over 256 GB.
3. Copies every file already on the card into a backup folder next to the
   script. For a card with the factory firmware on it, that backup is your way
   back.
4. Asks you to type `ERASE`.
5. Writes the card: the partition table, the boot partition `FISHBOOT`, and the
   Debian partition `fishroot`, unpacked from `debian-rootfs.tar.gz`.
6. Reads everything back from the card and compares it with what it wrote, then
   checks the boot files once more through Windows.

!!! note "The log"
    It writes `write-card-<date>.log` in the same folder. Send it along if something goes wrong.

## Step by step

**1. Download the release.** Make a new folder, for example
`Downloads\fishball-v2.3`. From the
[latest release](https://github.com/matsvandamme/fishball7020-fpga-devkit/releases/latest),
save these seven files into it:

| File | What it is |
|---|---|
| `write-card.cmd` | this card writer |
| `BOOT.bin` | the boot loader and FPGA design |
| `uImage` | the Linux kernel |
| `devicetree.dtb` | the hardware description the kernel reads |
| `uEnv.txt` | the boot settings |
| `debian-rootfs.tar.gz` | Debian, about 100 MB |
| `SHA256SUMS` | checksums for all of the above |

- If the browser warns that `write-card.cmd` "is not commonly downloaded", choose **Keep**.
- **Check that no file was renamed on the way** (`uImage (1)` and the like): the
  script looks for the names above.

**2. Unplug the board from this PC**, and leave it unplugged while the script
runs: the factory firmware shows up on Windows as a small USB drive, which is
just one more disk in the list.

| Card | Now |
|---|---|
| rewriting the board's own card | take it out of the board |
| a new card | leave the old one where it is for the moment |

**3. Put the card in the reader.**

!!! warning "If Windows offers to format the card, click Cancel"
    Every time that message appears, at this step or later.

**4. Double-click `write-card.cmd`.**

- Windows may show **"Windows protected your PC"**. Click **More info**, then
  **Run anyway**. It appears because the file came from the internet.
- Then Windows asks whether the app may make changes to your device. Click
  **Yes**: writing a whole card needs administrator rights. The rest happens in
  the new window that opens.

**5. Choose the card.** The script lists what it can write, like this:

```text
  Cards and USB disks this script can write:
  Disk 2   Generic STORAGE DEVICE              31.9 GB  USB   E: 'BOOT' FAT32
```

Pick by **size**: a 32 GB card reads as about 31.9 GB. Type its disk number,
here `2`, and press Enter.

**6. Let it back up the card, then type `ERASE`.** The backup lands in
`card-backup-<date>` next to the script. Typing anything other than `ERASE`, in
capitals, stops the script without writing anything.

**7. Wait.** Writing takes one to three minutes, depending on the card. Reading
it back takes about as long again. The script finishes with:

```text
  OK: all 407 MB read back identical
  OK: Windows reads the boot partition as E: FISHBOOT, and all four boot files match
== Done
  The card is ready. You can take it out of the reader now.
```

**8. Start the board on the new card.**

1. With the board unpowered, take the old card out (keep it: it is your way
   back) and put the new one in.
2. Check the **`BOOT`** DIP switch next to `RST`: both sliders away from `ON`
   (SD mode). Boards ship like that.
3. Connect **both** USB-C sockets: one to a **mains USB charger**, the other to
   your PC.

    !!! warning "On a laptop's USB power alone the board can hang"
4. Wait about a minute.

**9. Check that it runs the new firmware.** Open a Command Prompt and log in to
the board over the USB cable:

```text
# run from: a Command Prompt on the PC the board is plugged into
ssh root@192.168.2.1
```

The password is `analog`. Once logged in:

```text
# run on the board
cat /etc/os-release      # first line: PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
uname -r                 # 6.12.0-...
```

`board-info.cmd`, from the [repository's tools](https://github.com/matsvandamme/fishball7020-fpga-devkit/tree/main/tools),
shows the same information without logging in. SDR software reaches the board
at `ip:192.168.2.1`, as before.

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
