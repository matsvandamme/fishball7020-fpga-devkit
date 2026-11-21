#!/bin/bash
# Set up the modern target's sources (issue #9):
#   1. Analog Devices' Linux at the pinned commit, with this board's device tree
#      and kernel configuration dropped in and the driver patches applied;
#   2. the boot side, for BOOT.bin: U-Boot and scripts/ from the vendor monorepo
#      as a blob-less SPARSE clone (never its linux/ or buildroot/), plus AMD's
#      embeddedsw and bootgen - all at the same pins the factory target uses.
#
#   # run from: the repo root
#   ./devkit setup --target modern                    # both
#   ./firmware-modern/setup.sh --kernel-only          # just 1 - what CI needs
#
# Run once before building, or after deleting src/ or boot/ to start clean. CI
# runs the kernel half, so a kernel built by hand and one built by CI come from
# the same tree.

set -euo pipefail
FW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KERNEL_ONLY=0
for a in "$@"; do
    case "$a" in
        --kernel-only) KERNEL_ONLY=1 ;;
        -h|--help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "ERROR: unknown option '$a' (the one option is --kernel-only)" >&2; exit 1 ;;
    esac
done
SRC_DIR="$FW_DIR/src/linux"

ADI_LINUX_URL="https://github.com/analogdevicesinc/linux.git"

# Pinned to the exact commit every measurement in baseline/ was taken against.
# ADI's main moves daily and this is a vendor fork, so tracking its HEAD means
# the patches can stop applying between one clone and the next with nothing in
# this repo having changed. 2026-09-24, Linux 6.12.0.
ADI_LINUX_COMMIT="947298737646475ebb557be24d6ee9fc7901e0a9"

if [ -d "$SRC_DIR/.git" ]; then
    echo "=== $SRC_DIR already exists - skipping clone. Delete it first for a clean setup. ==="
    current="$(cd "$SRC_DIR" && git rev-parse HEAD)"
    if [ "$current" != "$ADI_LINUX_COMMIT" ]; then
        echo "NOTE: $SRC_DIR is at $current, not the pinned $ADI_LINUX_COMMIT."
        echo "      That is expected once the patches are applied as commits;"
        echo "      it is a problem if you have not touched the tree."
    fi
else
    # A depth-1 fetch of one commit, not a clone: the full history is ~5 GB and
    # nothing here needs it. github.com allows fetching an arbitrary SHA, so the
    # pin does not have to be a branch tip.
    echo "=== Fetching $ADI_LINUX_COMMIT from $ADI_LINUX_URL (shallow) ==="
    mkdir -p "$SRC_DIR"
    (cd "$SRC_DIR"
     git init --quiet
     git remote add origin "$ADI_LINUX_URL" 2>/dev/null || true
     git fetch --quiet --depth 1 origin "$ADI_LINUX_COMMIT" || {
        echo "ERROR: could not fetch $ADI_LINUX_COMMIT." >&2
        echo "       ADI rewrites history on main from time to time. If the commit" >&2
        echo "       is genuinely gone, the patches will need rebasing onto a new" >&2
        echo "       pin - see patches/README.md for what that cost last time." >&2
        exit 1
     }
     git checkout --quiet FETCH_HEAD)
fi

echo "=== Installing the board's device tree and kernel configuration ==="
# Both are plain drop-ins rather than patches, deliberately: the .dts is a new
# file that overlays ADI's zynq-pluto-sdr.dtsi, and the defconfig is a new file
# too, so neither needs to carry context that can rot.
install -m 644 "$FW_DIR/dts/zynq-pluto-sdr-fishball.dts" \
    "$SRC_DIR/arch/arm/boot/dts/xilinx/"
install -m 644 "$FW_DIR/config/fishball_defconfig" "$SRC_DIR/arch/arm/configs/"

echo "=== Applying patches ==="
# Patches STACK - 0004 -> 0005 -> 0012 and 0004 -> 0015 -> 0017 each edit the
# lines the one before added - so they must go on in filename order, and
# "git apply --check --reverse" on an earlier patch fails once a later one is
# on top. That makes patch-by-patch checking report a fully patched tree as
# broken. Record which patches were applied instead, one "sha256  name" line
# each; main's setup.sh learned this the same way.
STAMP="$SRC_DIR/.devkit-patches-applied"
patch_line() { printf '%s  %s\n' "$(sha256sum "$1" | cut -d" " -f1)" "$(basename "$1")"; }

# A tree that was patched some other way - by hand, or as one commit per patch
# while rebasing - has no stamp and is perfectly fine. Recognise it before the
# loop below declares it broken: if the LAST patch reverses cleanly then the
# whole series is on, in order, because nothing sits on top of it.
LAST_PATCH="$(ls "$FW_DIR"/patches/*.patch | sort | tail -1)"
if [ -n "$LAST_PATCH" ] && (cd "$SRC_DIR" && git apply --check --reverse "$LAST_PATCH" 2>/dev/null); then
    if [ ! -f "$STAMP" ] || ! grep -q "  $(basename "$LAST_PATCH")$" "$STAMP" 2>/dev/null; then
        echo "  series already applied - recording a per-patch stamp"
        : > "$STAMP"
        for p in "$FW_DIR"/patches/*.patch; do patch_line "$p" >> "$STAMP"; done
    fi
fi

applied=0
skipped=0
for p in "$FW_DIR"/patches/*.patch; do
    name=$(basename "$p")
    if [ -f "$STAMP" ] && grep -qxF "$(patch_line "$p")" "$STAMP"; then
        skipped=$((skipped + 1))
        continue
    fi
    echo "  -> $name"
    if (cd "$SRC_DIR" && git apply --check "$p" 2>/dev/null); then
        (cd "$SRC_DIR" && git apply "$p")
        applied=$((applied + 1))
    elif (cd "$SRC_DIR" && git apply --check --reverse "$p" 2>/dev/null); then
        echo "     already applied - recording it"
    else
        echo "ERROR: $name does not apply cleanly, and is not already applied." >&2
        echo "       Nothing in src/ is yours - it is fetched and patched by this" >&2
        echo "       script - so the surest fix is to start clean:" >&2
        echo "           rm -rf \"$SRC_DIR\" && ./setup.sh" >&2
        exit 1
    fi
    patch_line "$p" >> "$STAMP"
done

if [ "$applied" -eq 0 ]; then
    echo "  all $skipped patch(es) already applied - nothing to do"
else
    echo "  $applied applied, $skipped already there"
fi

# ============================================================================
# The boot side: everything BOOT.bin needs, and nothing it does not (issue #9).
#
# BOOT.bin is FSBL + bitstream + U-Boot. The bitstream comes from an XSA you
# pass to the build; the other two are built here, from the SAME pinned sources
# the factory target uses (firmware/scripts/fetch_common.sh), so the modern
# BOOT.bin is the factory BOOT.bin rebuilt - not a second design.
#
# From the vendor monorepo this takes u-boot-xlnx/ and scripts/ only, as a
# blob-less sparse clone. linux/ and buildroot/ are 5.8 GB of its 6.5 and the
# modern target uses neither. Everything lands in firmware-modern/boot/, never in
# firmware/src/, so the two targets can be set up side by side.
# ============================================================================
if [ "$KERNEL_ONLY" -eq 1 ]; then
    echo "=== --kernel-only: the boot side (U-Boot, embeddedsw, bootgen) is not fetched ==="
    exit 0
fi
BOOT_DIR="$FW_DIR/boot"
REPO="$(dirname "$FW_DIR")"
# shellcheck source=../firmware/scripts/fetch_common.sh
source "$REPO/firmware/scripts/fetch_common.sh"
MONO="$BOOT_DIR/fw"

# Cone mode, set explicitly. Before git 2.37 `sparse-checkout set` defaults to
# non-cone patterns, where "scripts" matches every directory of that name -
# linux/scripts among them - so git 2.34 (Ubuntu 22.04) checked out linux/,
# buildroot/ and hdl/. `init --cone` exists from git 2.25 on; `set --cone` only
# from 2.35, so it cannot be used here.
sparse_cone() {
    git -C "$MONO" sparse-checkout init --cone 2>/dev/null
    # shellcheck disable=SC2086
    git -C "$MONO" sparse-checkout set $FW_MONOREPO_MODERN_SPARSE
}
if [ -d "$MONO/.git" ]; then
    have="$(git -C "$MONO" rev-parse HEAD)"
    [ "$have" = "$FW_MONOREPO_COMMIT" ] || {
        echo "ERROR: $MONO is at $have, not the pinned $FW_MONOREPO_COMMIT." >&2
        echo "       rm -rf \"$MONO\" and run setup again." >&2
        exit 1; }
    if [ -e "$MONO/linux" ] || [ -e "$MONO/buildroot" ]; then
        echo "=== vendor monorepo checked out too widely (an older git's non-cone mode): narrowing it ==="
        sparse_cone || { echo "ERROR: could not narrow $MONO; rm -rf \"$MONO\" and run setup again." >&2; exit 1; }
    fi
    echo "=== vendor monorepo already at $FW_MONOREPO_COMMIT (sparse: $FW_MONOREPO_MODERN_SPARSE) ==="
else
    echo "=== Fetching U-Boot and scripts/ from the vendor monorepo (sparse, blob-less) ==="
    mkdir -p "$BOOT_DIR"
    git clone --quiet --filter=blob:none --no-checkout --sparse "$FW_MONOREPO_URL" "$MONO"
    (sparse_cone && git -C "$MONO" checkout --quiet "$FW_MONOREPO_COMMIT") || {
        echo "ERROR: could not check out $FW_MONOREPO_COMMIT from $FW_MONOREPO_URL." >&2
        exit 1; }
fi
# Proof, not a promise: the two directories the modern target must NOT carry.
for skip in linux buildroot; do
    [ ! -e "$MONO/$skip" ] || {
        echo "ERROR: $MONO/$skip exists - the sparse checkout is not sparse." >&2
        exit 1; }
done

echo "=== Applying this repo's U-Boot patches ==="
# The factory patches are applied to the whole monorepo. Here only the U-Boot
# hunks can apply: 0001 also carries Buildroot hunks, and Buildroot is not in
# this tree. --include keeps just the u-boot-xlnx/ part of each patch, so the
# U-Boot source ends up identical to the factory target's. Check that BY CONTENT -
# sha256 of every modified-or-added file under u-boot-xlnx/ in each tree - and NOT
# with `git diff HEAD`: patch 0020 creates three new headers, which are untracked
# here and staged in the factory tree, so git diff reports a difference that is
# not there.
USTAMP="$MONO/.devkit-uboot-patches-applied"
uapplied=0
for p in "$REPO"/firmware/patches/*.patch; do
    grep -qE '^(\+\+\+ b|--- a)/u-boot-xlnx/' "$p" || continue
    line="$(patch_line "$p")"
    if [ -f "$USTAMP" ] && grep -qxF "$line" "$USTAMP"; then continue; fi
    echo "  -> $(basename "$p") (u-boot-xlnx/ hunks only)"
    if (cd "$MONO" && git apply --check --include='u-boot-xlnx/*' "$p" 2>/dev/null); then
        (cd "$MONO" && git apply --include='u-boot-xlnx/*' "$p")
        uapplied=$((uapplied + 1))
    elif (cd "$MONO" && git apply --check --reverse --include='u-boot-xlnx/*' "$p" 2>/dev/null); then
        echo "     already applied - recording it"
    else
        echo "ERROR: $(basename "$p") does not apply to u-boot-xlnx/ cleanly." >&2
        echo "       rm -rf \"$MONO\" and run setup again." >&2
        exit 1
    fi
    echo "$line" >> "$USTAMP"
done
[ "$uapplied" -eq 0 ] && echo "  U-Boot patches already applied - nothing to do"

devkit_fetch_fsbl_and_bootgen "$BOOT_DIR"

cat <<EOF

=== Ready ===
  Kernel source:  $SRC_DIR
  Boot source:    $BOOT_DIR  (U-Boot, embeddedsw, bootgen - no linux/, no buildroot/)

  Build everything, BOOT.bin included, from an XSA:
      # run from: the repo root
      ./devkit build --target modern --xsa FILE.xsa

  The XSA is required: the modern target has no Vivado path. Use the one from
  your own factory build (firmware/src/hdl/projects/pluto/system_top.xsa), or the
  system_top.xsa attached to a FACTORY release - knowing that a release's XSA is
  that release's design, not necessarily what your board runs.

  U-Boot and the kernel need an ARM Linux cross-compiler. If this machine has
  none, run the same command through the build container, which does:
      ./devkit container build --target modern --xsa FILE.xsa
EOF
