#!/bin/bash
# Is the modern build sane? The boot files present, BOOT.bin carrying exactly its
# three partitions, and the bitstream in it the one the provenance says.
#
#     # run from: the repo root
#     ./devkit verify --target modern
#     ./devkit verify --target modern --board     # also: is the board running it?
#
# The factory target's verify reads Vivado's timing and utilisation reports. The
# modern target never runs Vivado - its bitstream always comes from an imported
# XSA - so there is nothing of that kind to read, and this checks what can be:
# what went INTO BOOT.bin, read back out of it.
set -euo pipefail
FW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$FW_DIR")"
OUT="$FW_DIR/output"
PLUTO="$FW_DIR/boot/hdl"
BOARD_CHECK=0
for a in "$@"; do
    case "$a" in
        --board) BOARD_CHECK=1 ;;
        -h|--help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "ERROR: unknown option '$a'" >&2; exit 1 ;;
    esac
done

fail=0
echo "=== files ==="
for f in BOOT.bin uImage devicetree.dtb uEnv.txt; do
    if [ -s "$OUT/$f" ]; then printf '  ok    %-16s %9s B\n' "$f" "$(stat -c%s "$OUT/$f")"
    elif { [ "$f" = uImage ] || [ "$f" = devicetree.dtb ]; } && [ -s "$OUT/BOOT.bin" ]; then
        # BOOT.bin without the rest is what --boot-only leaves on a fresh tree.
        printf '  FAIL  %-16s missing - --boot-only builds BOOT.bin and uEnv.txt only; drop it to build the kernel\n' "$f"; fail=1
    else printf '  FAIL  %-16s missing - run ./devkit build --target modern --xsa FILE\n' "$f"; fail=1; fi
done
# The root filesystem write-card reads is debian/rootfs.tar, from debian/build.sh
# (the .tar.gz in output/ is what a release publishes, and nothing reads it here).
TAR="$FW_DIR/debian/rootfs.tar"
if [ -s "$TAR" ]; then
    if [ -n "$(find "$FW_DIR/debian/overlay" -newer "$TAR" \( -type f -o -type l \) -print -quit 2>/dev/null)" ]; then
        echo "  STALE debian/rootfs.tar is older than debian/overlay/ - rebuild it (./devkit build --target modern --rootfs-only)"
        echo "        before writing a card, or the card gets a root without those changes"
    else echo "  ok    debian/rootfs.tar, newer than the overlay"; fi
else echo "  --    debian/rootfs.tar not built - only needed to write a whole card"; fi
[ "$fail" -eq 0 ] || exit 1

echo "=== BOOT.bin ==="
# Against the XSA this build PUBLISHED with its outputs - not boot/hdl/'s, which is
# whatever was imported last, including by a build that failed afterwards.
if [ -r "$OUT/system_top.xsa" ]; then
    "$REPO/firmware/scripts/check_bootbin.py" "$OUT/BOOT.bin" --xsa "$OUT/system_top.xsa" || fail=1
else
    echo "  (no system_top.xsa in output/ - an older build; checking partitions only)"
    "$REPO/firmware/scripts/check_bootbin.py" "$OUT/BOOT.bin" || fail=1
fi
[ -r "$OUT/xsa-provenance.txt" ] && sed -n '2,6p' "$OUT/xsa-provenance.txt" | sed 's/^/  /'

if [ "$BOARD_CHECK" -eq 1 ]; then
    echo "=== the board ==="
    # The same comparison the factory verify makes: md5 of what is on the card's
    # boot partition against what is here. The only thing that proves the board
    # runs THIS build rather than one that looks like it.
    tgt="${FISHBALL_SSH_ALIAS:-fishball}"
    for f in BOOT.bin uImage devicetree.dtb uEnv.txt; do
        here="$(md5sum "$OUT/$f" | cut -d' ' -f1)"
        there="$(ssh -o BatchMode=yes -o ConnectTimeout=5 "$tgt" "md5sum /boot/$f 2>/dev/null" | cut -d' ' -f1)" || there=""
        if [ -z "$there" ]; then printf '  ??    %-16s could not read it from the board\n' "$f"; fail=1
        elif [ "$here" = "$there" ]; then printf '  same  %-16s %s\n' "$f" "$here"
        else printf '  DIFF  %-16s here %s  board %s\n' "$f" "$here" "$there"; fail=1; fi
    done
fi
exit "$fail"
