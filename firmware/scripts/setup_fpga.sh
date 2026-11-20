#!/bin/bash
# Set up the FPGA source for a hardware revision other than the R1, and nothing
# else: hdl/ from the vendor monorepo, with the hdl/ part of the patch series.
#
#     # run from: the repo root
#     ./devkit setup --target factory --rev r2
#
# WHY THIS IS NOT setup.sh. The factory target's setup.sh clones the whole
# monorepo - its 5.15 kernel, U-Boot and Buildroot, ~6.8 GB - because the R1's
# factory build produces all five SD-card files. For the R2 the factory target
# builds ONE thing, the FPGA design, and hands its system_top.xsa to the modern
# target, which builds everything else. So this takes hdl/ only, as a blob-less
# sparse clone (~0.2 GB), into firmware/src-r2/, beside the R1's firmware/src/
# and never inside it.
#
# The patches are the same series, by the same rule (firmware/scripts/rev.sh):
# firmware/patches/, with firmware/revs/r2/patches/ replacing or adding. Only
# the hdl/ hunks of each are applied, because only hdl/ is here - which is how
# the modern target's setup takes just the u-boot-xlnx/ hunks.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW1_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=rev.sh
source "$SCRIPT_DIR/rev.sh"
# shellcheck source=fetch_common.sh
source "$SCRIPT_DIR/fetch_common.sh"
case "${1:-}" in -h|--help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;; esac

if [ "$DEVKIT_REV" = r1 ]; then
    echo "ERROR: setup_fpga.sh is for the other revisions. The R1's FPGA source comes" >&2
    echo "       with the whole factory tree: ./devkit setup --target factory" >&2
    exit 1
fi
SRC_DIR="$FW1_DIR/src$REV_SUFFIX"

# Cone mode, set explicitly: before git 2.37 `sparse-checkout set` defaults to
# non-cone patterns (see firmware-modern/setup.sh, which learned it first).
if [ -d "$SRC_DIR/.git" ]; then
    have="$(git -C "$SRC_DIR" rev-parse HEAD)"
    [ "$have" = "$FW_MONOREPO_COMMIT" ] || {
        echo "ERROR: $SRC_DIR is at $have, not the pinned $FW_MONOREPO_COMMIT." >&2
        echo "       rm -rf \"$SRC_DIR\" and run setup again." >&2
        exit 1; }
    echo "=== $SRC_DIR already at $FW_MONOREPO_COMMIT (sparse: hdl) ==="
else
    echo "=== Fetching hdl/ from the vendor monorepo (sparse, blob-less) for the $REV_NAME ==="
    git clone --quiet --filter=blob:none --no-checkout --sparse "$FW_MONOREPO_URL" "$SRC_DIR"
    (git -C "$SRC_DIR" sparse-checkout init --cone 2>/dev/null \
        && git -C "$SRC_DIR" sparse-checkout set hdl \
        && git -C "$SRC_DIR" checkout --quiet "$FW_MONOREPO_COMMIT") || {
        echo "ERROR: could not check out $FW_MONOREPO_COMMIT from $FW_MONOREPO_URL." >&2
        exit 1; }
fi
[ -f "$SRC_DIR/hdl/projects/pluto/system_bd.tcl" ] || {
    echo "ERROR: $SRC_DIR/hdl/projects/pluto is not there - an interrupted checkout." >&2
    echo "       rm -rf \"$SRC_DIR\" and run setup again." >&2
    exit 1; }

echo "=== Applying the $REV_NAME patch series (hdl/ hunks only) ==="
# One "sha256  name" line per applied patch, as in setup.sh and for its reason:
# the patches stack, so "does this one reverse cleanly?" stops being answerable
# once a later one is on top.
STAMP="$SRC_DIR/.devkit-patches-applied"
patch_line() { printf '%s  %s\n' "$(sha256sum "$1" | cut -d" " -f1)" "$(basename "$1")"; }
applied=0; skipped=0
while IFS= read -r p; do
    grep -qE '^(\+\+\+ b|--- a)/hdl/' "$p" || continue
    name="$(basename "$p")"
    if [ -f "$STAMP" ] && grep -qxF "$(patch_line "$p")" "$STAMP"; then
        skipped=$((skipped + 1)); continue
    fi
    echo "  -> $name   (${p#"$FW1_DIR"/})"
    if (cd "$SRC_DIR" && git apply --check --include='hdl/*' "$p" 2>/dev/null); then
        (cd "$SRC_DIR" && git apply --whitespace=nowarn --include='hdl/*' "$p")
        applied=$((applied + 1))
    elif (cd "$SRC_DIR" && git apply --check --reverse --include='hdl/*' "$p" 2>/dev/null); then
        echo "     already applied - recording it"
    else
        echo "ERROR: $name does not apply to hdl/ cleanly, and is not already applied." >&2
        if [ -f "$STAMP" ] && grep -q "  $name$" "$STAMP"; then
            echo "       It IS in the stamp but its contents have changed, so an older" >&2
            echo "       version of it is in the tree." >&2
        fi
        echo "       Nothing in $SRC_DIR is yours - it is fetched and patched by this" >&2
        echo "       script - so start clean:" >&2
        echo "           rm -rf \"$SRC_DIR\" && ./devkit setup --target factory$REV_FLAG" >&2
        exit 1
    fi
    patch_line "$p" >> "$STAMP"
done < <(devkit_patch_series "$FW1_DIR")
if [ "$applied" -eq 0 ]; then echo "  all $skipped patch(es) already applied - nothing to do"
else echo "  applied $applied, skipped $skipped already-applied"; fi

cat <<EOF

=== Ready: $SRC_DIR/hdl ===
  Build the FPGA design (Vivado 2022.2, 45-90 min):
      ./devkit build --target factory$REV_FLAG
  It writes $SRC_DIR/hdl/projects/pluto/system_top.xsa, which the
  modern target takes:
      ./devkit setup$REV_FLAG
      ./devkit build$REV_FLAG --xsa firmware/src$REV_SUFFIX/hdl/projects/pluto/system_top.xsa
EOF
