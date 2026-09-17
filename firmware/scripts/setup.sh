#!/bin/bash
# Clones the upstream firmware source and applies this repo's fixes on top.
# Run once before the first build_all.sh (or after deleting src/ to start clean).
#
# The upstream repo is vendored as a flattened monorepo (hdl/buildroot/linux/
# u-boot-xlnx all committed directly, no git submodules) - many hundreds of MB
# of Linux kernel / U-Boot / buildroot source, which is why it's cloned fresh
# here rather than committed into this repo.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW1_DIR="$(dirname "$SCRIPT_DIR")"
SRC_DIR="$FW1_DIR/src"

UPSTREAM_URL="https://github.com/Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR.git"

# Pinned to the exact commit every patch/comparison in this repo was
# verified against. Upstream's history has been squashed before (see the
# firmware README), so tracking a branch HEAD instead of a fixed commit
# risks silently building against different code than what was actually
# tested - or the patches failing to apply at all with no clear reason why.
UPSTREAM_COMMIT="95aad369f0f3f4ae852bea94d980cc2db90728a2"

if [ -d "$SRC_DIR/.git" ]; then
    echo "=== $SRC_DIR already exists - skipping clone. Delete it first for a clean setup. ==="
    current="$(cd "$SRC_DIR" && git rev-parse HEAD)"
    if [ "$current" != "$UPSTREAM_COMMIT" ]; then
        echo "WARNING: $SRC_DIR is at $current, not the pinned $UPSTREAM_COMMIT."
        echo "         Patches may fail to apply or apply against different code."
    fi
    # A clone that was interrupted (machine rebooted, disk full, Ctrl-C) leaves
    # .git and the right HEAD behind, so the commit check above passes - but the
    # working tree is half-populated and the index is full of staged deletions.
    # Patching that produces a confusing cascade of failures a long way from the
    # real cause, so detect it here and say plainly what to do.
    # NB: grep -c, not grep -q. Under `set -o pipefail`, `grep -q` exits on the
    # first match, git status dies of SIGPIPE, and the pipeline returns 141 -
    # so the test silently evaluates false on exactly the broken trees it is
    # meant to catch. grep -c consumes all input and cannot be SIGPIPE'd.
    staged_deletions="$(cd "$SRC_DIR" && git status --porcelain 2>/dev/null | grep -c '^D ' || true)"
    if [ "${staged_deletions:-0}" -gt 0 ]; then
        echo "ERROR: $SRC_DIR looks like an interrupted checkout - tracked files are" >&2
        echo "       missing from the working tree. This is not recoverable in place." >&2
        echo "       Delete it and run setup.sh again:" >&2
        echo "           rm -rf \"$SRC_DIR\" && ./scripts/setup.sh" >&2
        exit 1
    fi
else
    echo "=== Cloning $UPSTREAM_URL ==="
    git clone "$UPSTREAM_URL" "$SRC_DIR"
    echo "=== Checking out pinned commit $UPSTREAM_COMMIT ==="
    (cd "$SRC_DIR" && git checkout --quiet "$UPSTREAM_COMMIT") || {
        echo "ERROR: pinned commit $UPSTREAM_COMMIT not found in $UPSTREAM_URL." >&2
        echo "       Upstream may have force-pushed/rewritten its history -" >&2
        echo "       see the firmware README for what to do next." >&2
        exit 1
    }
fi

cd "$SRC_DIR"
# Only the top level of patches/ is applied automatically. patches/optional/
# holds worked examples that CHANGE what the radio does rather than fixing it -
# the FM channelizer narrows RX channel 0 to a single 200 kHz broadcast channel,
# which is the last thing you want on a general-purpose build. Apply those by
# hand when you want them:
#     (cd src && git apply ../patches/optional/0003-wbfm-channelizer.patch)
echo "=== Applying patches ==="

# Patches STACK: 0004, 0005 and 0007 all edit cf_axi_dds.c, and 0008 edits the
# device tree 0002 creates. Once a later patch is applied, "git apply --check
# --reverse" on an earlier one fails - the later patch sits on top and the
# context no longer matches. Asking patch-by-patch therefore reports a fully
# patched tree as broken, and running setup.sh twice looked like a serious
# failure with a message about upstream drift.
#
# Nor can the series be tested in one go: "git apply --check" given several
# patches checks each against the CURRENT tree rather than cumulatively, so it
# fails for exactly the same reason.
#
# So record WHICH patches were applied, one "sha256  name" line each. An
# aggregate digest was the first attempt and was too coarse: adding a patch
# changed the digest, which sent the whole series back through the per-patch
# loop and straight into the stacking problem above. Per-patch lines mean a
# new patch applies on its own and the rest are left alone.
STAMP="$SRC_DIR/.devkit-patches-applied"

patch_line() { printf '%s  %s\n' "$(sha256sum "$1" | cut -d" " -f1)" "$(basename "$1")"; }

# A tree patched before this stamp existed, or by the older aggregate-digest
# version, has no usable stamp but is perfectly fine. Recognise it: if the LAST
# patch in the series reverses cleanly then the series was applied in order,
# because nothing sits on top of it.
LAST_PATCH="$(ls "$FW1_DIR"/patches/*.patch | sort | tail -1)"
if [ -n "$LAST_PATCH" ] && git apply --check --reverse "$LAST_PATCH" 2>/dev/null; then
    if [ ! -f "$STAMP" ] || ! grep -q "  $(basename "$LAST_PATCH")$" "$STAMP" 2>/dev/null; then
        echo "  series already applied - recording a per-patch stamp"
        : > "$STAMP"
        for p in "$FW1_DIR"/patches/*.patch; do patch_line "$p" >> "$STAMP"; done
    fi
fi

applied=0
skipped=0
for p in "$FW1_DIR"/patches/*.patch; do
    name=$(basename "$p")
    if [ -f "$STAMP" ] && grep -qxF "$(patch_line "$p")" "$STAMP"; then
        skipped=$((skipped + 1))
        continue
    fi
    echo "  -> $name"
    if git apply --check "$p" 2>/dev/null; then
        git apply "$p"
        applied=$((applied + 1))
    elif git apply --check --reverse "$p" 2>/dev/null; then
        echo "     already applied - recording it"
    else
        echo "ERROR: $name does not apply cleanly, and isn't already applied." >&2
        echo "       $SRC_DIR is not in the state this patch expects." >&2
        echo "" >&2
        if [ -f "$STAMP" ] && grep -q "  $name$" "$STAMP"; then
            echo "       This patch IS in the stamp but its contents have changed," >&2
            echo "       so an older version of it is already in the tree. A patch" >&2
            echo "       cannot be re-applied over its own earlier version." >&2
        fi
        echo "       Nothing in src/ is yours - it is cloned and patched by this" >&2
        echo "       script - so the surest fix is to start clean:" >&2
        echo "           rm -rf \"$SRC_DIR\" && ./devkit setup      (from the repo root)" >&2
        echo "" >&2
        echo "       If that still fails, upstream has drifted from the pinned" >&2
        echo "       commit ($UPSTREAM_COMMIT)." >&2
        exit 1
    fi
    # Record it immediately, so an interrupted run does not claim patches it
    # never reached.
    patch_line "$p" >> "$STAMP"
done

if [ "$applied" -eq 0 ]; then
    echo "  all $skipped patch(es) already applied - nothing to do"
else
    echo "  applied $applied, skipped $skipped already-applied"
fi

if ls "$FW1_DIR"/patches/optional/*.patch >/dev/null 2>&1; then
    echo "=== Optional patches NOT applied (worked examples; apply by hand) ==="
    for p in "$FW1_DIR"/patches/optional/*.patch; do
        echo "  -- $(basename "$p")"
    done
fi

echo
echo "=== Done. Source tree ready at $SRC_DIR ==="
echo "Next: ./scripts/build_all.sh"
