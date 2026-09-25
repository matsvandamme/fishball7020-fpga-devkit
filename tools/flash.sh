#!/bin/bash
# Flash a built firmware onto the running board, over the network.
#
#     ./tools/flash.sh                 # BOOT.bin + uImage (the usual case)
#     ./tools/flash.sh --all           # all five SD-card files
#     ./tools/flash.sh --boot-only     # just the bitstream/FSBL/U-Boot
#     ./tools/flash.sh --kernel-only   # just uImage
#     ./tools/flash.sh --rootfs-only   # just uramdisk.image.gz
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

# Where the board is: its own name first, the USB gadget last. See
# tools/board_addr.py; $BOARD still overrides everything.
BOARD="${BOARD:-$(python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/board_addr.py" 2>/dev/null || echo 192.168.2.1)}"
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
        # Three patches in this repo (0002, 0008, 0011) change only the device
        # tree, and a dtb change needs a reboot but not a new kernel.
        --dtb-only)    FILES=(devicetree.dtb) ;;
        --rootfs-only) FILES=(uramdisk.image.gz) ;;
        --no-reboot)   REBOOT=0 ;;
        -h|--help)     sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2
           case "$arg" in -all|-boot-only|-kernel-only|-dtb-only|-rootfs-only|-no-reboot)
               echo "did you mean -$arg? (options take two dashes)" >&2 ;; esac
           echo "options: --all  --boot-only  --kernel-only  --dtb-only  --rootfs-only  --no-reboot  --help" >&2
           exit 2 ;;
    esac
done

command -v sshpass >/dev/null || { echo "need sshpass (sudo apt install sshpass)" >&2; exit 2; }
# UserKnownHostsFile=/dev/null: every board is 192.168.2.1 and each keeps its
# own host key, so the second board you ever plug in would otherwise make
# OpenSSH refuse password auth with a "changed key" warning that sshpass hides.
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR -o ConnectTimeout=10)
sh()  { sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "root@$BOARD" "$@"; }
# No scp: OpenSSH 9+ defaults scp to SFTP, and the board's dropbear has no
# sftp-server. A plain pipe over ssh works against every version.
push() { sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "root@$BOARD" "cat > '$2'" < "$1"; }

for f in "${FILES[@]}"; do
    [ -r "$OUT/$f" ] || { echo "missing $OUT/$f - build first" >&2; exit 1; }
done

echo "== board =="
if ! err=$(sh true 2>&1); then
    echo "cannot reach root@$BOARD: ${err:-no response}" >&2
    echo "(set BOARD=<address> and BOARD_PASS=<password> if yours differ)" >&2
    exit 1
fi
echo "   $BOARD reachable, flashing: ${FILES[*]}"
uptime_before=$(sh 'cut -d. -f1 /proc/uptime')

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
    push "$OUT/$f" "/tmp/sd/$f.new"
    want=$(md5sum "$OUT/$f" | cut -d' ' -f1)
    got=$(sh "md5sum /tmp/sd/$f.new" | cut -d' ' -f1)
    if [ "$want" != "$got" ]; then
        echo "   $f copied WRONG ($got, wanted $want) - removing every .new, card untouched" >&2
        sh "rm -f /tmp/sd/*.new; cd / && umount /tmp/sd"
        exit 1
    fi
    echo "   $f verified  ($want)"
done

echo
echo "== 3. swap, flush, unmount =="
for f in "${FILES[@]}"; do
    # Keep the previous copy ON the card. If that copy cannot be made (card
    # full), stop before the swap rather than swap with no on-card fallback.
    if ! sh "cd /tmp/sd && { [ ! -r $f ] || cp $f $f.prev; } && mv $f.new $f"; then
        echo "   could not keep $f.prev (card full?) - $f NOT swapped; card unchanged" >&2
        sh "rm -f /tmp/sd/*.new; sync; cd / && umount /tmp/sd"
        exit 1
    fi
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
# "It answered ssh" is not "it rebooted": a board tearing down its services can
# still answer for a few seconds, and that used to print "back after 7s" with
# the OLD firmware still running. Require the uptime counter to have reset.
for i in $(seq 1 90); do
    sleep 2
    if up=$(sh 'cut -d. -f1 /proc/uptime' 2>/dev/null) && [ -n "$up" ]; then
        if [ "$up" -lt "${uptime_before:-999999}" ] && [ "$up" -lt 300 ]; then
            echo "   back after $((i * 2))s (uptime reset: ${up}s)"
            echo
            echo "== 5. confirm the card holds what we sent =="
            # /tmp is tmpfs - the reboot just erased the mount point.
            sh 'mkdir -p /tmp/sd && mount -o ro /dev/mmcblk0p1 /tmp/sd'
            bad=0
            for f in "${FILES[@]}"; do
                want=$(md5sum "$OUT/$f" | cut -d' ' -f1)
                got=$(sh "md5sum /tmp/sd/$f" | cut -d' ' -f1)
                if [ "$want" = "$got" ]; then echo "   $f  ok"; else echo "   $f  MISMATCH ($got)"; bad=1; fi
            done
            sh 'cd / && umount /tmp/sd'
            sh 'cat /opt/VERSIONS 2>/dev/null | head -1' || true
            echo
            if [ $bad -eq 0 ]; then
                echo "Flashed and booted. Previous firmware is on the card as *.prev"
                echo "and in $BACKUP_DIR/$stamp."
                exit 0
            fi
            echo "Booted, but the card does not hold what was sent - investigate before trusting it." >&2
            exit 1
        fi
        fi                          # else: still the old instance answering; keep waiting
done

echo "   board has not come back after ~3 minutes." >&2
echo "   It may still be booting. If it does not return, the previous firmware is" >&2
echo "   in $BACKUP_DIR/$stamp - restore it with a card reader." >&2
exit 1
