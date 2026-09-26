#!/bin/bash
# Write firmware-modern's kernel and device tree to the board's SD card, from
# a card reader on this machine.
#
#     # run from: the repo root, card in a reader
#     ./firmware-modern/write_card.sh            # uImage + devicetree.dtb
#     ./firmware-modern/write_card.sh --restore  # put main's 5.15 files back
#
# WHY THIS EXISTS. tools/flash.sh writes the card from the RUNNING board, over
# the network, which is far better - no physical access, and it verifies before
# swapping. But it mounts /dev/mmcblk0p1 on the board, so it needs the board's
# kernel to have an MMC driver. The first 6.12 build did not: ADI's
# zynq_pluto_defconfig omits CONFIG_MMC entirely, because the Pluto boots from
# QSPI and never needs Linux to see a card. The board booted fine and simply
# had no /dev/mmcblk0, which takes the network flash route away with it.
#
# So this is the escape hatch for exactly that class of mistake: any kernel
# that breaks networking or MMC needs the card out once. Once a kernel with
# CONFIG_MMC is on there, go back to tools/flash.sh.
#
# It expects the card auto-mounted by your desktop (no sudo). Insert it and
# look for /media/$USER/<something> containing BOOT.bin.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
SRC="$HERE/output"
RESTORE=0
[ "${1:-}" = "--restore" ] && RESTORE=1

# Find a mounted FAT partition that looks like this board's boot card.
CARD=""
for m in /media/"$USER"/* /run/media/"$USER"/* /mnt/*; do
    [ -d "$m" ] || continue
    if [ -f "$m/BOOT.bin" ] && [ -f "$m/uImage" ]; then CARD="$m"; break; fi
done
if [ -z "$CARD" ]; then
    echo "No SD card found." >&2
    echo "Looked for a mounted directory containing BOOT.bin and uImage under" >&2
    echo "  /media/$USER/*, /run/media/$USER/*, /mnt/*" >&2
    echo >&2
    echo "Insert the board's card in a reader and let the desktop mount it." >&2
    echo "If it is mounted somewhere else, pass the path:  CARD=/path $0" >&2
    exit 1
fi
CARD="${CARD_OVERRIDE:-$CARD}"
echo "card: $CARD"
echo "   $(ls -la "$CARD"/BOOT.bin | awk '{print $5}') bytes of BOOT.bin present (not touched)"

if [ "$RESTORE" = 1 ]; then
    echo
    echo "== restoring main's kernel and device tree from the .prev copies on the card =="
    for f in uImage devicetree.dtb; do
        [ -f "$CARD/$f.prev" ] || { echo "   no $f.prev on the card - cannot restore" >&2; exit 1; }
        cp "$CARD/$f.prev" "$CARD/$f"
        echo "   restored $f from $f.prev"
    done
    sync
    echo "   done. Eject, put it back in the board, power-cycle."
    exit 0
fi

for f in uImage devicetree.dtb; do
    [ -r "$SRC/$f" ] || { echo "missing $SRC/$f - build first" >&2; exit 1; }
done

echo
echo "== 1. back up what is on the card =="
STAMP="$(date +%Y%m%d-%H%M%S)"
BK="$ROOT/firmware/.flash-backups/card-$STAMP"
mkdir -p "$BK"
for f in uImage devicetree.dtb; do
    if [ -f "$CARD/$f" ]; then
        cp "$CARD/$f" "$BK/$f"
        echo "   saved $f  ($(md5sum "$BK/$f" | cut -d' ' -f1))"
    fi
done
echo "   backup: $BK"

echo
echo "== 2. write, then verify by reading back =="
for f in uImage devicetree.dtb; do
    # Keep a previous copy on the card so a restore never depends on this
    # host still having the backup - but NEVER overwrite an existing .prev.
    # flash.sh rolls .prev forward, which is right when every version booted.
    # Here it is wrong: the copy already on the card may be a kernel that does
    # not boot, and rolling forward would throw away the last one that did.
    # The .prev on this card is main's 5.15, and that is what it must stay.
    if [ -f "$CARD/$f" ] && [ ! -f "$CARD/$f.prev" ]; then
        cp "$CARD/$f" "$CARD/$f.prev"
        echo "   kept the existing $f as $f.prev"
    elif [ -f "$CARD/$f.prev" ]; then
        echo "   leaving $f.prev alone (it is the last known-good)"
    fi
    cp "$SRC/$f" "$CARD/$f"
    sync
    want="$(md5sum "$SRC/$f" | cut -d' ' -f1)"
    got="$(md5sum "$CARD/$f" | cut -d' ' -f1)"
    if [ "$want" != "$got" ]; then
        echo "   $f verified WRONG ($got, wanted $want)" >&2
        echo "   restoring $f from $f.prev and stopping" >&2
        cp "$CARD/$f.prev" "$CARD/$f"; sync
        exit 1
    fi
    echo "   $f written and verified  ($want)"
done

sync
echo
echo "== 3. done =="
echo "   Eject the card, put it in the board, power-cycle."
echo "   Previous copies are on the card as *.prev, and on this host in"
echo "   $BK"
