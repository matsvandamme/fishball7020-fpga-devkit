#!/bin/bash
# Flash a built firmware onto the running board, over the network.
#
#     ./tools/flash.sh                 # BOOT.bin + uImage (the usual case)
#     ./tools/flash.sh --all           # all five SD-card files
#     ./tools/flash.sh --boot-only     # just the bitstream/FSBL/U-Boot
#     ./tools/flash.sh --kernel-only   # just uImage
#     ./tools/flash.sh --no-reboot     # copy, verify, leave it running
#
# The board's FAT partition is /dev/mmcblk0p1, normally unmounted, so a running
# board can rewrite its own SD card. This is the only remote route that can
# update the FPGA bitstream - DFU has no BOOT.bin target - and it is why HDL
# iteration here does not involve a card reader.
#
# WHY THIS IS A SCRIPT AND NOT A PARAGRAPH IN THE README
# A bad BOOT.bin means a board that will not boot, and then this route is gone:
# recovery needs a card reader. Every step below exists to make that outcome
# unlikely and recoverable - back up first, verify the copy by checksum BEFORE
# swapping it in, unmount cleanly so FAT metadata is flushed, and keep the old
# one on the card. Done by hand those steps are easy to skip.
#
# Never DFU for BOOT.bin, and never pull power mid-write.
set -euo pipefail

BOARD="${BOARD:-192.168.2.1}"
PASS="${BOARD_PASS:-analog}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$(dirname "$SCRIPT_DIR")/firmware/output"
BACKUP_DIR="${BACKUP_DIR:-$(dirname "$SCRIPT_DIR")/firmware/.flash-backups}"

FILES=(BOOT.bin uImage)
REBOOT=1
for arg in "$@"; do
    case "$arg" in
        --all)         FILES=(BOOT.bin devicetree.dtb uEnv.txt uImage uramdisk.image.gz) ;;
        --boot-only)   FILES=(BOOT.bin) ;;
        --kernel-only) FILES=(uImage) ;;
        --no-reboot)   REBOOT=0 ;;
        -h|--help)     sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

command -v sshpass >/dev/null || { echo "need sshpass (sudo apt install sshpass)" >&2; exit 2; }
sh()  { sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o ConnectTimeout=10 \
            "root@$BOARD" "$@"; }
cpy() { sshpass -p "$PASS" scp -o StrictHostKeyChecking=no "$@"; }

for f in "${FILES[@]}"; do
    [ -r "$OUT/$f" ] || { echo "missing $OUT/$f - build first" >&2; exit 1; }
done

echo "== board =="
sh true 2>/dev/null || { echo "cannot reach root@$BOARD" >&2; exit 1; }
echo "   $BOARD reachable, flashing: ${FILES[*]}"

cleanup() { sh 'cd / && umount /tmp/sd 2>/dev/null' >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo
echo "== 1. back up what is on the card now =="
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR/$stamp"
sh 'mkdir -p /tmp/sd && mount -o ro /dev/mmcblk0p1 /tmp/sd'
for f in "${FILES[@]}"; do
    if sh "test -r /tmp/sd/$f"; then
        sh "cat /tmp/sd/$f" > "$BACKUP_DIR/$stamp/$f"
        on_board=$(sh "md5sum /tmp/sd/$f" | cut -d' ' -f1)
        local_md5=$(md5sum "$BACKUP_DIR/$stamp/$f" | cut -d' ' -f1)
        [ "$on_board" = "$local_md5" ] || {
            echo "   backup of $f does not match the board - refusing to continue" >&2; exit 1; }
        echo "   saved $f  ($on_board)"
    else
        echo "   $f not on the card yet - nothing to back up"
    fi
done
sh 'cd / && umount /tmp/sd'
echo "   backup: $BACKUP_DIR/$stamp"

echo
echo "== 2. copy in beside the old, and verify BEFORE swapping =="
sh 'mount -o rw /dev/mmcblk0p1 /tmp/sd'
for f in "${FILES[@]}"; do
    cpy "$OUT/$f" "root@$BOARD:/tmp/sd/$f.new" >/dev/null
    want=$(md5sum "$OUT/$f" | cut -d' ' -f1)
    got=$(sh "md5sum /tmp/sd/$f.new" | cut -d' ' -f1)
    if [ "$want" != "$got" ]; then
        echo "   $f copied WRONG ($got, wanted $want) - removing it, card untouched" >&2
        sh "rm -f /tmp/sd/$f.new; cd / && umount /tmp/sd"
        exit 1
    fi
    echo "   $f verified  ($want)"
done

echo
echo "== 3. swap, flush, unmount =="
for f in "${FILES[@]}"; do
    sh "cd /tmp/sd && { [ -r $f ] && cp $f $f.prev || true; } && mv $f.new $f"
done
sh 'sync; cd / && umount /tmp/sd'
echo "   done - previous copies kept on the card as *.prev"

if [ "$REBOOT" -eq 0 ]; then
    echo
    echo "Not rebooting (--no-reboot). The board is still running the OLD firmware"
    echo "until it restarts."
    exit 0
fi

echo
echo "== 4. reboot =="
sh '(sleep 1; reboot) >/dev/null 2>&1 &' || true
sleep 5
for i in $(seq 1 60); do
    sleep 2
    if sh 'echo up' >/dev/null 2>&1; then
        echo "   back after $((i * 2 + 5))s"
        sh 'cat /opt/VERSIONS 2>/dev/null | head -1' || true
        echo
        echo "Flashed. If something is wrong, the previous firmware is on the card"
        echo "as BOOT.bin.prev (and in $BACKUP_DIR/$stamp)."
        exit 0
    fi
done

echo "   board has not come back after ~2 minutes." >&2
echo "   It may still be booting. If it does not return, the previous firmware is" >&2
echo "   in $BACKUP_DIR/$stamp - restore it with a card reader." >&2
exit 1
