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

# Patches STACK: 0004 and 0005 both edit cf_axi_dds.c, so once both are applied
# "git apply --check --reverse 0004" fails - 0005 sits on top and the context
# no longer matches. Asking patch-by-patch therefore reports a fully patched
# tree as broken, and simply running setup.sh twice looked like a serious
# failure with a message about upstream drift.
#
# Nor can the series be tested in one go: "git apply --check" given several
# patches checks each against the CURRENT tree rather than cumulatively, so it
# fails for exactly the same reason.
#
# So record what was applied. The stamp holds a digest of the patch files
# themselves, which means it also notices when the patch set has changed (a
# git pull bringing new ones) rather than just that setup ran once.
STAMP="$SRC_DIR/.devkit-patches-applied"
PATCH_DIGEST="$(cat "$FW1_DIR"/patches/*.patch | sha256sum | cut -d" " -f1)"

# A tree patched before this stamp existed has no stamp but is perfectly fine.
# Recognise it: if the LAST patch in the series reverses cleanly then the series
# was applied in order, because nothing else edits those regions on top of it.
LAST_PATCH="$(ls "$FW1_DIR"/patches/*.patch | sort | tail -1)"
if [ ! -f "$STAMP" ] && [ -n "$LAST_PATCH" ] \
   && git apply --check --reverse "$LAST_PATCH" 2>/dev/null; then
    echo "  series already applied (no stamp yet) - recording one"
    echo "$PATCH_DIGEST" > "$STAMP"
fi

if [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$PATCH_DIGEST" ]; then
    echo "  all patches already applied (stamp matches) - nothing to do"
else
    for p in "$FW1_DIR"/patches/*.patch; do
        echo "  -> $(basename "$p")"
        if git apply --check "$p" 2>/dev/null; then
            git apply "$p"
        elif git apply --check --reverse "$p" 2>/dev/null; then
            echo "     already applied - skipping"
        else
            echo "ERROR: $(basename "$p") does not apply cleanly, and isn't already applied." >&2
            echo "       $SRC_DIR is not in the state this patch expects." >&2
            echo "" >&2
            echo "       Nothing in src/ is yours - it is cloned and patched by this" >&2
            echo "       script - so the surest fix is to start clean:" >&2
            echo "           rm -rf \"$SRC_DIR\" && ./devkit setup      (from the repo root)" >&2
            echo "" >&2
            echo "       If that still fails, upstream has drifted from the pinned" >&2
            echo "       commit ($UPSTREAM_COMMIT)." >&2
            exit 1
        fi
    done
    echo "$PATCH_DIGEST" > "$STAMP"
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
