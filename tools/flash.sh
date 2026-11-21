#!/bin/bash
# Flash a built firmware onto the running board, over the network.
#
#     ./devkit flash                   # BOOT.bin + uImage (the usual case)
#     ./devkit flash --boot-only       # just the bitstream/FSBL/U-Boot
#     ./devkit flash --kernel-only     # just uImage
#     ./devkit flash --dtb-only        # just devicetree.dtb
#     ./devkit flash --no-reboot       # copy, verify, leave it running
#
# That flashes the modern build (firmware-modern/output/). The factory build
# (firmware/output/) takes --target factory, and two more options:
#
#     ./devkit flash --target factory --all          # all five SD-card files
#     ./devkit flash --target factory --rootfs-only  # just uramdisk.image.gz
#
# The modern Debian root lives on the card's second partition and cannot be
# swapped over the network: sudo ./devkit write-card /dev/sdX writes a card.
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
#
# Exit status: 0 done; 1 stopped, and the message says what state the card is
# in; 2 a bad option, or no way to log in; 3 flashed and rebooted, but the board
# now refuses the login, so the last check (step 5) could not be made.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Which build to flash. ./devkit sets FW_OUTPUT to firmware-modern/output for
# the modern target; run directly, this script flashes firmware/output.
OUT="${FW_OUTPUT:-$(dirname "$SCRIPT_DIR")/firmware/output}"
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

# Where the board is: its own name first, the USB gadget last. See
# tools/board_addr.py; $BOARD still overrides everything. After the options, so
# --help and a mistyped option answer at once instead of after a probe.
BOARD="${BOARD:-$(python3 "$SCRIPT_DIR/board_addr.py" 2>/dev/null || echo 192.168.2.1)}"

# Login is tools/lib/board-ssh.sh: the key ./devkit ssh-key makes, then the
# password through sshpass where that is installed. It also carries the ssh
# options (no known_hosts, and why).
BOARD_SSH_CONNECT_TIMEOUT=10
. "$SCRIPT_DIR/lib/board-ssh.sh"
board_ssh_require || exit 2
sh()  { board_ssh "$BOARD" "$@"; }
# No scp: OpenSSH 9+ defaults scp to SFTP, and the board's dropbear has no
# sftp-server. A plain pipe over ssh works against every version.
push() { board_ssh "$BOARD" "cat > '$2'" < "$1"; }
# md5sum is GNU coreutils; macOS has had one only since 13, and `md5 -q` before.
md5of() {
    if command -v md5sum >/dev/null 2>&1; then md5sum "$1" | cut -d' ' -f1
    else md5 -q "$1"; fi
}
stop() { echo "   $1" >&2; exit 1; }

# ASKING THE BOARD A YES/NO QUESTION. `if sh "test -r FILE"` reads every failure
# as "no" - ssh's own 255 included, when the connection drops for a moment. A
# file that IS on the card was then "not on the card yet", went without a
# backup, and the flash carried on. So: 0 is yes, 1 is no, and anything else is
# the board not answering, which stops the flash. $2 says what is true of the
# card at that point.
ask() {   # <remote test> <the state of the card if this stops here>
    local rc=0
    sh "$1" || rc=$?
    case "$rc" in 0|1) return "$rc" ;; esac
    echo "   the board did not answer (ssh exit $rc) when asked: $1" >&2
    stop "$2"
}

for f in "${FILES[@]}"; do
    [ -r "$OUT/$f" ] || { echo "missing $OUT/$f - build first" >&2; exit 1; }
done

echo "== board =="
if ! err=$(sh true 2>&1); then
    echo "cannot reach root@$BOARD: ${err:-no response}" >&2
    echo "(set BOARD=<address> and BOARD_PASS=<password> if yours differ)" >&2
    # Without sshpass the key is the only way in, and this is how to get one.
    command -v sshpass >/dev/null 2>&1 || board_ssh_hint
    exit 1
fi
echo "   $BOARD reachable, flashing: ${FILES[*]}"
uptime_before=$(sh 'cut -d. -f1 /proc/uptime')


# MOUNTING THE CARD WHEN SOMETHING ELSE ALREADY HAS IT.
#
# This script has always mounted /dev/mmcblk0p1 at /tmp/sd, which worked because
# the Buildroot rootfs leaves the FAT partition unmounted. A Debian root does not:
# firmware-modern/debian mounts it at /boot, as any ordinary distribution would.
# `mount /dev/mmcblk0p1 /tmp/sd` then fails with
#
#     mmcblk0p1: Can't mount, would change RO state
#     mount: /tmp/sd: /dev/mmcblk0p1 already mounted on /boot.
#
# ...and flashing is impossible on the very userspace this repo now ships.
#
# So: if the partition is already mounted, BIND-mount its mountpoint into /tmp/sd.
# Every path below keeps working unchanged, and unmounting the bind afterwards
# leaves the original mount in place.
#
# ...BUT A BIND MOUNT SHARES ITS READ-ONLY STATE WITH THE ORIGINAL. This used to
# end with `mount -o remount,ro /tmp/sd` (or rw) whichever way the card had been
# mounted, and on a bind that remounts the filesystem itself: /boot went
# read-only with it, and stayed read-only after the bind was gone. Found on a
# Debian board, where fstab mounts /boot read-write and after a flash it was
# not. So for a card somebody else mounted:
#   - reading needs no remount at all, so `ro` leaves the state as it is;
#   - `rw` remounts only when it has to, having first written the original
#     state (ro or rw) to /tmp/sd.was on the board;
#   - sd_umount puts that state back, and every exit path goes through it.
# /tmp on the board is tmpfs, so the note cannot outlive the mount it describes.
#
# Every mount below is checked, and so is the result. A failed `mount --bind`
# used to go unnoticed, and the rest of the flash then ran against an empty
# directory in the board's RAM: nothing to back up, a copy that verified, a
# swap, "done" - and a card that had not changed.
sd_mount() {   # $1 = ro | rw
    sh 'mkdir -p /tmp/sd || exit 1
        existing=$(awk "\$1 == \"/dev/mmcblk0p1\" && \$2 != \"/tmp/sd\" { print \$2; exit }" /proc/mounts)
        mounted=$(awk "\$2 == \"/tmp/sd\" { print 1; exit }" /proc/mounts)
        if [ -n "$existing" ]; then
            [ -n "$mounted" ] || mount --bind "$existing" /tmp/sd || exit 1
            was=$(awk -v m="$existing" "\$2 == m { split(\$4, o, \",\"); print o[1]; exit }" /proc/mounts)
            if [ "'"$1"'" = rw ] && [ "$was" = ro ]; then
                [ -f /tmp/sd.was ] || echo ro > /tmp/sd.was
                mount -o remount,rw /tmp/sd || exit 1
            fi
        elif [ -n "$mounted" ]; then
            mount -o remount,'"$1"' /tmp/sd || exit 1
        else
            mount -o '"$1"' /dev/mmcblk0p1 /tmp/sd || exit 1
        fi
        # Believe /proc/mounts, not the exit statuses above. If the card is not
        # at /tmp/sd, /tmp/sd is a directory in RAM: every step after this one
        # would "succeed" there and the card would never be touched.
        now=$(awk "\$2 == \"/tmp/sd\" { split(\$4, o, \",\"); print o[1]; exit }" /proc/mounts)
        [ -n "$now" ] || { echo "the card is not mounted at /tmp/sd" >&2; exit 1; }
        [ "'"$1"'" != rw ] || [ "$now" = rw ] || { echo "the card is mounted at /tmp/sd, but still read-only" >&2; exit 1; }'
}

# Unmount /tmp/sd and, where sd_mount changed somebody else's mount, put its
# read-only state back. Runs `sync` first: unmounting a bind flushes nothing.
sd_umount() {
    sh 'sync; cd /
        if [ -f /tmp/sd.was ]; then
            m=$(awk "\$1 == \"/dev/mmcblk0p1\" && \$2 != \"/tmp/sd\" { print \$2; exit }" /proc/mounts)
            umount /tmp/sd 2>/dev/null
            [ -z "$m" ] || mount -o remount,$(cat /tmp/sd.was) "$m" \
                || echo "   could not put $m back to $(cat /tmp/sd.was) - it is still read-write" >&2
            rm -f /tmp/sd.was
        else
            umount /tmp/sd
        fi'
}

cleanup() { sd_umount >/dev/null 2>&1 || true; }
trap cleanup EXIT

echo
echo "== 1. back up what is on the card now =="
stamp=$(date +%Y%m%d-%H%M%S)
mkdir -p "$BACKUP_DIR/$stamp"
untouched="Nothing has been written: the card is as it was."
sd_mount ro || stop "could not mount the card on the board. $untouched"
for f in "${FILES[@]}"; do
    if ask "test -r /tmp/sd/$f" "$untouched"; then
        rc=0; sh "cat /tmp/sd/$f" > "$BACKUP_DIR/$stamp/$f" || rc=$?
        [ "$rc" -eq 0 ] || stop "could not copy $f off the card to back it up (exit $rc). $untouched"
        rc=0; on_board=$(sh "md5sum /tmp/sd/$f") || rc=$?
        [ "$rc" -eq 0 ] || stop "could not checksum $f on the card (exit $rc). $untouched"
        on_board=${on_board%% *}
        local_md5=$(md5of "$BACKUP_DIR/$stamp/$f")
        [ "$on_board" = "$local_md5" ] || {
            echo "   backup of $f does not match the board - refusing to continue" >&2; exit 1; }
        echo "   saved $f  ($on_board)"
    else
        echo "   $f not on the card yet - nothing to back up"
    fi
done
sd_umount || stop "could not unmount the card after the backup. $untouched"
echo "   backup: $BACKUP_DIR/$stamp"

# REFUSE TO SILENTLY UNDO A DEBIAN CARD.
#
# `--all` includes uEnv.txt, and the uEnv.txt in firmware/output/ carries only the
# ramdisk boot path. The Debian root is selected by an `sdboot_debian` block that
# lives in firmware-modern/debian/make-uenv.sh. So flashing --all onto a card
# running Debian replaces the boot selector with one that cannot reach the Debian
# root, and the next reboot comes up on Buildroot with nothing reporting an error.
# The card is intact; the board just quietly becomes a different machine.
#
# READ THE BACKUP STEP 1 JUST MADE, not the card. Two earlier versions of this
# check probed the card over ssh with a second mount and a quoted remote script,
# and both silently returned 0 for a card that demonstrably had the Debian
# selector on it - so the check sailed past and did the damage it exists to
# prevent, twice. Step 1 has already copied the card's uEnv.txt to a local file
# and md5-verified it. Grep that. No second mount, no remote quoting, no doubt.
#
# ONLY WHEN uEnv.txt IS ACTUALLY BEING WRITTEN. The condition used to be "did the
# build produce a uEnv.txt", which is true after every build - so on --boot-only,
# where FILES is just BOOT.bin, step 1 never backed a uEnv.txt up and the check
# below could only ever hit "no backup to compare against" and refuse. That made
# `./devkit flash --boot-only` impossible to run: the very command this script
# recommends three lines further down for a mixed card. Nothing is being
# downgraded when uEnv.txt is not in FILES, so there is nothing to guard.
case " ${FILES[*]} " in
    *" uEnv.txt "*) flashing_uenv=1 ;;
    *)              flashing_uenv=0 ;;
esac
if [ "$flashing_uenv" = 1 ] && [ -r "$OUT/uEnv.txt" ]; then
    card_uenv="$BACKUP_DIR/$stamp/uEnv.txt"
    if [ ! -r "$card_uenv" ]; then
        echo "   no backup of the card's uEnv.txt to compare against - refusing." >&2
        echo "   (FLASH_ALLOW_UENV_DOWNGRADE=1 overrides)" >&2
        [ "${FLASH_ALLOW_UENV_DOWNGRADE:-0}" = "1" ] || exit 1
    else
        card_n=$(grep -c sdboot_debian "$card_uenv" || true)
        new_n=$(grep -c sdboot_debian "$OUT/uEnv.txt" || true)
        echo "   uEnv.txt: the card has ${card_n:-0} sdboot_debian line(s), this build has ${new_n:-0}"
        if [ "${card_n:-0}" -gt 0 ] && [ "${new_n:-0}" -eq 0 ]; then
            cat >&2 <<'WARN'

   REFUSING. The card's uEnv.txt selects the Debian root; the one about to be
   flashed does not. This would boot the board back onto the Buildroot ramdisk,
   and nothing would report an error.

   Flash only what you rebuilt:
       ./devkit flash --boot-only                   # the bitstream
       FW_OUTPUT=$PWD/firmware-modern/output ./tools/flash.sh --kernel-only

   Or regenerate a dual-boot uEnv.txt first:
       ./firmware-modern/debian/make-uenv.sh > firmware/output/uEnv.txt

   FLASH_ALLOW_UENV_DOWNGRADE=1 if you really do mean to go back to Buildroot.
WARN
            [ "${FLASH_ALLOW_UENV_DOWNGRADE:-0}" = "1" ] || exit 1
            echo "   FLASH_ALLOW_UENV_DOWNGRADE=1 - proceeding anyway" >&2
        fi
    fi
fi

echo "== 2. copy in beside the old, and verify BEFORE swapping =="
# A copy that fails - the connection drops, the card fills up - used to end the
# script on the spot (set -e) with no word of explanation, the half-written
# *.new still on the card and the card still mounted read-write. Nothing has
# been swapped at this point, so say so, and leave the card as it was found.
sent=""          # the *.new files this run has started, as remote paths
copy_failed() {   # <what happened>
    echo "   $1" >&2
    # shellcheck disable=SC2086
    if sh "rm -f $sent" 2>/dev/null; then
        echo "   removed the partial copies ($(echo $sent | sed 's#/tmp/sd/##g'))." >&2
    else
        echo "   could not remove $(echo $sent | sed 's#/tmp/sd/##g') from the card - the board is not" >&2
        echo "   answering. They are spare copies beside the real files; the next flash overwrites them." >&2
    fi
    sd_umount 2>/dev/null || echo "   could not unmount the card either; a reboot of the board does that." >&2
    echo "   Nothing was swapped: the files the board boots from are untouched." >&2
    trap - EXIT
    exit 1
}
sd_mount rw || stop "could not mount the card read-write on the board. $untouched"
for f in "${FILES[@]}"; do
    sent="$sent /tmp/sd/$f.new"
    rc=0; push "$OUT/$f" "/tmp/sd/$f.new" || rc=$?
    [ "$rc" -eq 0 ] || copy_failed "copying $f to the card failed (exit $rc): the connection dropped, or the card is full."
    want=$(md5of "$OUT/$f")
    rc=0; got=$(sh "md5sum /tmp/sd/$f.new") || rc=$?
    [ "$rc" -eq 0 ] || copy_failed "could not read $f.new back from the card to verify it (exit $rc)."
    got=${got%% *}
    [ "$want" = "$got" ] || copy_failed "$f copied WRONG ($got, wanted $want)."
    echo "   $f verified  ($want)"
done

echo
echo "== 3. swap, flush, unmount =="
swapped=""
for f in "${FILES[@]}"; do
    # Keep the previous copy ON the card. If that copy cannot be made (card
    # full), stop before the swap rather than swap with no on-card fallback.
    # Three answers again: 1 is the board saying no; anything else is the board
    # not answering, and then nobody knows whether this file was swapped.
    rc=0
    sh "cd /tmp/sd && { [ ! -r $f ] || cp $f $f.prev; } && mv $f.new $f" || rc=$?
    if [ "$rc" -ne 0 ]; then
        if [ "$rc" -eq 1 ]; then
            echo "   could not keep $f.prev (card full?) - $f NOT swapped." >&2
        else
            echo "   the board stopped answering (ssh exit $rc) while $f was being swapped;" >&2
            echo "   it may or may not have been." >&2
        fi
        # shellcheck disable=SC2086
        sh "rm -f $sent" 2>/dev/null || true
        sd_umount 2>/dev/null || echo "   could not unmount the card; do not pull power." >&2
        if [ -z "$swapped" ] && [ "$rc" -eq 1 ]; then
            echo "   Nothing was swapped: the files the board boots from are untouched." >&2
        else
            echo "   Already swapped:${swapped:- nothing for certain}. The card may now hold a mix of old and new:" >&2
            echo "   do not reboot the board. Run this flash again once it answers; each" >&2
            echo "   previous file is on the card as *.prev and in $BACKUP_DIR/$stamp." >&2
        fi
        trap - EXIT
        exit 1
    fi
    swapped="$swapped $f"
done
if ! sd_umount; then
    echo "   the files are swapped, but the card did not unmount (is the board still" >&2
    echo "   answering?). Do not pull power: the new files may not be flushed to the card." >&2
    echo "   Run this flash again once the board answers." >&2
    exit 1
fi
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
# $SECONDS, not the turn count: a turn is the 2 s sleep PLUS however long ssh
# took to fail, so "turns x 2" under-reported by up to a factor of six.
#
# AND "IT REFUSED THE LOGIN" IS NOT "IT HAS NOT COME BACK". On the factory
# Buildroot root, /root is a RAM disk: a key in /root/.ssh/authorized_keys that
# is not also saved under /mnt/jffs2 is gone after any reboot (./devkit ssh-key
# saves it there). With a key as the only login - no sshpass, the usual Mac -
# this loop then heard "Permission denied" ninety times, discarded it, and
# reported a board that "has not come back ... restore it with a card reader"
# after a flash that had worked. A refusal is an answer: the board is up. Three
# in a row, so that a board refusing logins on its way down does not count.
reboot_at=$SECONDS
refusals=0
for _ in $(seq 1 90); do
    sleep 2
    rc=0; up=$(sh 'cut -d. -f1 /proc/uptime' 2>&1) || rc=$?
    if [ "$rc" -ne 0 ]; then
        if board_ssh_refused "$rc" "$up"; then refusals=$((refusals + 1)); else refusals=0; fi
        if [ "$refusals" -ge 3 ]; then
            trap - EXIT
            {
                echo "   the board is back after $((SECONDS - reboot_at))s, and it refuses the login this flash began with."
                echo
                echo "   The flash itself went through: steps 1 to 3 copied, verified and swapped"
                echo "   ${FILES[*]}. What did not survive the reboot is the login. On the"
                echo "   factory (Buildroot) root /root is a RAM disk, and a key that was not also"
                echo "   saved in /mnt/jffs2 is gone after a reboot. Put it back, this time to stay:"
                echo
                echo "       ./devkit ssh-key"
                echo
                echo "   NOT DONE: step 5, the check that the card still holds what was sent now"
                echo "   that the board has booted from it. Once you can log in, compare on the"
                echo "   board (md5sum /boot/FILE on Debian; on Buildroot after"
                echo "   mount -o ro /dev/mmcblk0p1 /mnt):"
                for f in "${FILES[@]}"; do echo "       $(md5of "$OUT/$f")  $f"; done
                echo "   The previous firmware is on the card as *.prev and in $BACKUP_DIR/$stamp."
            } >&2
            exit 3
        fi
        continue                    # no answer yet
    fi
    refusals=0
    case "$up" in ''|*[!0-9]*) continue ;; esac
    if [ "$up" -lt "${uptime_before:-999999}" ] && [ "$up" -lt 300 ]; then
        echo "   back after $((SECONDS - reboot_at))s (uptime reset: ${up}s)"
        echo
        echo "== 5. confirm the card holds what we sent =="
        # /tmp is tmpfs - the reboot just erased the mount point.
        sd_mount ro || stop "Booted, but could not mount the card to check what it holds."
        bad=0
        for f in "${FILES[@]}"; do
            want=$(md5of "$OUT/$f")
            rc=0; got=$(sh "md5sum /tmp/sd/$f") || rc=$?
            got=${got%% *}
            if [ "$rc" -eq 0 ] && [ "$want" = "$got" ]; then echo "   $f  ok"
            else echo "   $f  MISMATCH (${got:-could not read it, exit $rc})"; bad=1; fi
        done
        sd_umount || true
        sh 'cat /opt/VERSIONS 2>/dev/null | head -1' || true
        echo
        if [ $bad -eq 0 ]; then
            echo "Flashed and booted. Previous firmware is on the card as *.prev"
            echo "and in $BACKUP_DIR/$stamp."
            exit 0
        fi
        echo "Booted, but the card does not hold what was sent - investigate before trusting it." >&2
        exit 1
    fi                              # else: still the old instance answering; keep waiting
done

echo "   board has not come back after $((SECONDS - reboot_at))s." >&2
echo "   It may still be booting. If it does not return, the previous firmware is" >&2
echo "   in $BACKUP_DIR/$stamp - restore it with a card reader." >&2
exit 1
