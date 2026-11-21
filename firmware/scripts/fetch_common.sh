#!/bin/bash
# Pins and fetches shared by BOTH targets' setup scripts. Source it; do not run it.
#
#     firmware/scripts/setup.sh      the factory target
#     firmware-modern/setup.sh       the modern target
#
# ONE COPY of every commit pin, on purpose. The modern target needs the same FSBL
# source, the same bootgen and the same U-Boot as the factory target - it packages
# the same BOOT.bin - and two copies of a SHA drift apart the first time someone
# bumps one. If you change a pin here, both targets move together.

UPSTREAM_URL="https://github.com/Xiaozhang-code-cloud/Fish-Wan-plutosdr-fw-7020-SDR.git"

# Pinned to the exact commit every patch/comparison in this repo was
# verified against. Upstream's history has been squashed before (see the
# firmware README), so tracking a branch HEAD instead of a fixed commit
# risks silently building against different code than what was actually
# tested - or the patches failing to apply at all with no clear reason why.
UPSTREAM_COMMIT="95aad369f0f3f4ae852bea94d980cc2db90728a2"

# AMD's embeddedsw, which the FSBL is built from - see firmware/fsbl/README.md.
# Always fetched: it is not optional any more, and a setup that skipped it would
# leave the very next command failing preflight.
EMBEDDEDSW_URL="https://github.com/Xilinx/embeddedsw.git"
# xilinx_v2022.2, the tag matching Vivado 2022.2. Pinned by SHA rather than
# by tag for the same reason UPSTREAM_COMMIT is: a tag can be moved.
EMBEDDEDSW_COMMIT="5330a64c8efd14f0eef09befdbb8d3d738c33ec2"
# Only the four subtrees the FSBL needs. A full clone is ~2 GB; this is ~75 MB.
EMBEDDEDSW_SPARSE="lib/sw_apps/zynq_fsbl lib/bsp/standalone lib/sw_services/xilffs lib/sw_services/xilrsa XilinxProcessorIPLib/drivers"

# AMD's bootgen, which packages BOOT.bin. This used to be the one Xilinx binary
# still required, and the reason Vivado had to be INSTALLED even for an --xsa
# build that never ran it. AMD publishes the source under Apache 2.0, it builds
# in about five seconds against system OpenSSL, and the BOOT.bin it produces is
# byte-identical to the one Vivado's copy produces - verified against an image a
# board has booted. Built always, and always used, so that what comes out does
# not depend on which Xilinx tools happen to be installed.
BOOTGEN_URL="https://github.com/Xilinx/bootgen.git"
# xilinx_v2022.2, pinned by SHA for the same reason as the others.
BOOTGEN_COMMIT="cf4ba93b99644dc4429ef633471a639e1382f0e7"

# Unambiguous names for the vendor monorepo pin. firmware-modern/setup.sh has
# its OWN UPSTREAM_* for ADI's kernel, so it must not rely on the bare names.
FW_MONOREPO_URL="$UPSTREAM_URL"
FW_MONOREPO_COMMIT="$UPSTREAM_COMMIT"
# What the modern target takes from that monorepo: U-Boot for BOOT.bin, and
# scripts/get_default_envs.sh for the uEnv.txt base. NOT linux/ (the modern
# target builds ADI's 6.12) and NOT buildroot/ (it ships Debian). Those two are
# 5.8 GB of the monorepo's 6.5.
FW_MONOREPO_MODERN_SPARSE="u-boot-xlnx scripts"

# ---- small portable helpers ---------------------------------------------------
# GNU coreutils spellings that macOS (BSD userland, bash 3.2) does not have.
# The supported way to build on a Mac is ./devkit container, where none of this
# matters - but pieces of the build get run by hand on the host, and "stat:
# illegal option -- c" in the middle of one is a poor way to find that out.
#
# CPUs to build with. NEVER leave this empty: `make -j` with no number means
# "unlimited jobs", which is what a missing nproc used to turn -j"$(nproc)" into.
devkit_ncpu() {
    local n
    n="$(nproc 2>/dev/null || getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null || true)"
    case "$n" in ''|*[!0-9]*) n=1 ;; esac
    echo "$n"
}
# Size of a file in bytes (stat -c %s).
devkit_fsize() { wc -c < "$1" | tr -d '[:space:]'; }
# Modification time of a file, seconds since the epoch (stat -c %Y).
devkit_mtime() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1"; }

# Make sure bootgen exists AND RUNS IN THIS ENVIRONMENT, rebuilding it if not.
# Costs ~5 s. Called by both setup scripts and by both build scripts just before
# they package BOOT.bin.
#
# "Exists" was the old test, and it is not enough. A bootgen built on a host with
# a new glibc does not run in the Ubuntu 22.04 build container:
#     bootgen: /lib/x86_64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
# Found when the modern target's first container build got through the FSBL,
# U-Boot, the kernel and uEnv.txt and then failed to package. The factory target
# has the same exposure; its bootgen worked in the container only because it had
# last been built there. A binary built against the OLDER glibc runs on both,
# so rebuilding wherever it will not run converges instead of ping-ponging.
# The run-here probe captures bootgen's output rather than piping it into
# `grep -q`: every caller runs under `set -o pipefail`, where grep -q exits on the
# first match, bootgen takes SIGPIPE, and the pipeline reports failure - so a
# WORKING bootgen would be rebuilt and then declared broken. setup.sh records the
# same trap for git status.
_bootgen_runs_here() { local o; o="$("$1" 2>&1 || true)"; case "$o" in *"Bootgen v"*) return 0 ;; esac; return 1; }

devkit_ensure_bootgen() {
    local d="${1:?devkit_ensure_bootgen: need the bootgen source directory}"
    local bg="$d/bootgen"
    if [ -x "$bg" ] \
       && [ -z "$(find "$d" -name '*.cpp' -newer "$bg" -print -quit 2>/dev/null)" ] \
       && _bootgen_runs_here "$bg"; then
        return 0
    fi
    if [ -x "$bg" ]; then echo "=== Rebuilding bootgen: the one here does not run in this environment ==="
    else echo "=== Building bootgen ==="; fi
    command -v g++ >/dev/null 2>&1 || {
        echo "ERROR: g++ not found - bootgen is C++." >&2
        echo "       sudo apt install build-essential libssl-dev" >&2
        exit 1; }
    # clean first: objects compiled against another libstdc++ will not relink.
    make -C "$d" clean >/dev/null 2>&1 || true
    make -C "$d" -j"$(devkit_ncpu)" "LIBS=-lssl -lcrypto -ldl -lpthread" >/dev/null 2>&1 || {
        echo "ERROR: bootgen failed to build. It needs OpenSSL headers:" >&2
        echo "       sudo apt install build-essential libssl-dev" >&2
        exit 1; }
    _bootgen_runs_here "$bg" || {
        echo "ERROR: bootgen was rebuilt but still does not run here." >&2; exit 1; }
    echo "    bootgen: $("$bg" 2>&1 | grep -oE 'Bootgen v[0-9.]+' | head -1)"
}

# Fetch AMD's embeddedsw (sparse) and bootgen into $1, and build bootgen.
# Idempotent: an existing checkout at the pinned commit is reused; one at any
# other commit is refused rather than silently built against.
devkit_fetch_fsbl_and_bootgen() {
    [ -n "${1:-}" ] || { echo "devkit_fetch_fsbl_and_bootgen: need a destination" >&2; return 1; }
    mkdir -p "$1"
    ESW_DIR="$1/embeddedsw"
    if [ -d "$ESW_DIR/.git" ]; then
        have="$(cd "$ESW_DIR" && git rev-parse HEAD)"
        if [ "$have" = "$EMBEDDEDSW_COMMIT" ]; then
            echo "=== embeddedsw already at $EMBEDDEDSW_COMMIT ==="
        else
            echo "ERROR: $ESW_DIR is at $have, not the pinned $EMBEDDEDSW_COMMIT." >&2
            echo "       rm -rf \"$ESW_DIR\" and run setup again." >&2
            exit 1
        fi
    else
        echo "=== Cloning embeddedsw (sparse, ~75 MB) - the FSBL is built from it ==="
        git clone --filter=blob:none --no-checkout "$EMBEDDEDSW_URL" "$ESW_DIR"
        (cd "$ESW_DIR" \
            && git sparse-checkout init --cone \
            && git sparse-checkout set $EMBEDDEDSW_SPARSE \
            && git checkout --quiet "$EMBEDDEDSW_COMMIT") || {
            echo "ERROR: could not check out embeddedsw at $EMBEDDEDSW_COMMIT." >&2
            exit 1; }
        echo "    embeddedsw at $EMBEDDEDSW_COMMIT"
    fi

    BOOTGEN_DIR="$1/bootgen"
    if [ -d "$BOOTGEN_DIR/.git" ]; then
        have="$(cd "$BOOTGEN_DIR" && git rev-parse HEAD)"
        if [ "$have" != "$BOOTGEN_COMMIT" ]; then
            echo "ERROR: $BOOTGEN_DIR is at $have, not the pinned $BOOTGEN_COMMIT." >&2
            echo "       rm -rf \"$BOOTGEN_DIR\" and run setup again." >&2
            exit 1
        fi
        echo "=== bootgen already at $BOOTGEN_COMMIT ==="
    else
        echo "=== Cloning bootgen (~8 MB) - it packages BOOT.bin ==="
        git clone --quiet --no-checkout "$BOOTGEN_URL" "$BOOTGEN_DIR"
        (cd "$BOOTGEN_DIR" && git checkout --quiet "$BOOTGEN_COMMIT") || {
            echo "ERROR: could not check out bootgen at $BOOTGEN_COMMIT." >&2
            exit 1; }
        echo "    bootgen at $BOOTGEN_COMMIT"
    fi
    devkit_ensure_bootgen "$BOOTGEN_DIR"
}
