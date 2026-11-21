#!/bin/bash
# Build the modern target's SD-card boot files, BOOT.bin included, from an XSA.
#
#     # run from: the repo root
#     ./devkit build --target modern --xsa FILE.xsa
#     ./devkit container build --target modern --xsa FILE.xsa   # no cross-compiler here?
#
#     ./devkit build --target modern --rootfs-only              # the Debian root
#
#     --xsa FILE         REQUIRED, except with --rootfs-only. The hardware
#                        platform, with its bitstream.
#     --boot-only        BOOT.bin and uEnv.txt only; skip the kernel. Works on a
#                        machine that has never built one.
#     --rootfs-only      Only the Debian root filesystem, rootfs.tar, which
#                        write-card puts on the card's second partition. Runs
#                        firmware-modern/debian/build.sh. Needs podman or docker,
#                        so run it on the host, not in ./devkit container.
#     --all              Everything: the boot files, then the Debian root.
#     --preflight-only   Check tools and sources, build nothing.
#
# Writes firmware-modern/output/: BOOT.bin, uImage, devicetree.dtb, uEnv.txt.
# The Debian root, firmware-modern/debian/rootfs.tar, is built only on request
# (--rootfs-only or --all): it needs armhf emulation and takes far longer than
# everything else here.
#
# COMPILER. Either ARM Linux cross-compiler works: gcc-arm-linux-gnueabi (soft
# float, what the container has) or gcc-arm-linux-gnueabihf (hard float, the one
# Arch and most distros package). With the hard-float one, U-Boot's
# -march=armv7-a probe used to fail and fall through to a bogus "unrecognized
# -march target: armv5"; U-Boot is now compiled with -mfloat-abi=soft, which
# fixes the probe and changes nothing else (#9).
#
# WHAT THIS IS. The factory target's firmware/scripts/build_all.sh builds all of
# the vendor monorepo - its 5.15 kernel and its Buildroot root filesystem too.
# This builds ONLY what the modern target uses: the FSBL and U-Boot for BOOT.bin,
# from the same pinned sources (firmware/scripts/fetch_common.sh), and ADI's
# patched 6.12 kernel from firmware-modern/src/linux. GIVEN THE SAME XSA, the
# BOOT.bin it packages is the factory one rebuilt: same FSBL, same bitstream, same
# U-Boot source. Given another XSA it is that XSA's design, which is the point.
#
# WHY --xsa IS REQUIRED. The modern target has no Vivado path, and no default
# would be honest: at the time of writing no published release carries the
# bitstream a from-source factory build produces, so silently downloading one
# would silently build a different FPGA design. Pass the platform you mean.
set -euo pipefail

FW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$FW_DIR")"
BOOT="$FW_DIR/boot"
MONO="$BOOT/fw"
KSRC="$FW_DIR/src/linux"
OUT="$FW_DIR/output"
PLUTO="$BOOT/hdl"                 # where import_xsa.sh puts the platform
FSBL_BUILD="$BOOT/fsbl-build"
BOOTGEN="$BOOT/bootgen/bootgen"
XILINX_DIR="${XILINX_DIR:-/tools/Xilinx}"
# shellcheck source=../firmware/scripts/fetch_common.sh
source "$REPO/firmware/scripts/fetch_common.sh"

usage() { sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }

XSA_FILE=""; BOOT_ONLY=0; ROOTFS_ONLY=0; WITH_ROOTFS=0; PREFLIGHT_ONLY=0; _want_xsa=0
for arg in "$@"; do
    if [ "$_want_xsa" -eq 1 ]; then XSA_FILE="$arg"; _want_xsa=0; continue; fi
    case "$arg" in
        --xsa)            _want_xsa=1 ;;
        --xsa=*)          XSA_FILE="${arg#--xsa=}" ;;
        --boot-only)      BOOT_ONLY=1 ;;
        --rootfs-only)    ROOTFS_ONLY=1 ;;
        --all)            WITH_ROOTFS=1 ;;
        --preflight-only) PREFLIGHT_ONLY=1 ;;
        -h|--help)        usage; exit 0 ;;
        *) echo "ERROR: unknown option '$arg' for the modern target." >&2
           echo "       --hdl-only is the factory target's; the modern one has no HDL build:" >&2
           echo "           ./devkit build --target factory --hdl-only" >&2
           exit 1 ;;
    esac
done
[ "$_want_xsa" -eq 1 ] && { echo "ERROR: --xsa needs a file path" >&2; exit 1; }
[ $((BOOT_ONLY + ROOTFS_ONLY + WITH_ROOTFS)) -le 1 ] || {
    echo "ERROR: pick one of --boot-only, --rootfs-only and --all." >&2; exit 1; }

# The Debian root is built in an armhf container, so it needs podman or docker
# on THIS machine. The build container has neither: say so now, before --all has
# spent ten minutes on the boot files.
if [ "$ROOTFS_ONLY" -eq 1 ] || [ "$WITH_ROOTFS" -eq 1 ]; then
    # $container is what podman and systemd-nspawn set inside; the files are
    # podman's and docker's markers.
    if [ -n "${container:-}" ] || [ -e /run/.containerenv ] || [ -e /.dockerenv ]; then
        echo "ERROR: the Debian root is built in its own container, so build it on the" >&2
        echo "       host, not in ./devkit container:" >&2
        echo "           ./devkit build --target modern --rootfs-only" >&2
        exit 1
    fi
    [ "$ROOTFS_ONLY" -eq 1 ] && exec "$FW_DIR/debian/build.sh"
fi
# --preflight-only (what `./devkit doctor --target modern` runs) is "can this
# machine build?", which does not depend on which XSA you will pass later.
if [ -z "$XSA_FILE" ] && [ "$PREFLIGHT_ONLY" -eq 0 ]; then
    echo "ERROR: the modern target needs --xsa FILE: the FPGA design it builds around." >&2
    echo "       The one a factory release shipped, fetched and checked for you:" >&2
    echo "           ./devkit build --xsa \"\$(./firmware-modern/fetch-pinned-xsa.sh)\"" >&2
    echo "       or your own factory build's:" >&2
    echo "           --xsa firmware/src/hdl/projects/pluto/system_top.xsa" >&2
    echo "       To build the FPGA itself with Vivado, that is the factory target:" >&2
    echo "           ./devkit build --target factory" >&2
    exit 1
fi
[ -n "$XSA_FILE" ] && case "$XSA_FILE" in /*) ;; *) XSA_FILE="$PWD/$XSA_FILE" ;; esac

# ---- preflight ----------------------------------------------------------------
# Every tool and source is checked BEFORE anything is built, and a missing ARM
# Linux cross-compiler names the one command that has it, rather than failing
# ten minutes in. That compiler is what a typical desktop lacks.
fail=0
need() { if [ -e "$2" ] || command -v "$2" >/dev/null 2>&1; then printf '  ok     %s\n' "$1"
         else printf '  MISSING %s  (%s)\n' "$1" "$2"; fail=1; fi; }
echo "=== preflight ==="
[ -n "$XSA_FILE" ] && need "XSA" "$XSA_FILE"
[ "$BOOT_ONLY" -eq 1 ] || need "kernel source" "$KSRC/Makefile"
need "U-Boot source"              "$MONO/u-boot-xlnx/Makefile"
need "get_default_envs.sh"        "$MONO/scripts/get_default_envs.sh"
need "embeddedsw"                 "$BOOT/embeddedsw/lib"
need "bootgen source"             "$BOOT/bootgen/Makefile"
need "bare-metal cross (FSBL)"    arm-none-eabi-gcc
# Either ARM Linux compiler; soft-float first, because it is what the container
# has and what every published build so far was made with.
if   command -v arm-linux-gnueabi-gcc   >/dev/null 2>&1; then CROSS=arm-linux-gnueabi-
elif command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then CROSS=arm-linux-gnueabihf-
else CROSS=""; fi
if [ -n "$CROSS" ]; then printf '  ok     ARM Linux cross (U-Boot, kernel): %sgcc\n' "$CROSS"
else printf '  MISSING ARM Linux cross (U-Boot, kernel)  (arm-linux-gnueabi-gcc or arm-linux-gnueabihf-gcc)\n'; fail=1; fi
need "make"                       make
need "flex (U-Boot, kernel)"      flex
need "bison (U-Boot, kernel)"     bison
[ "$BOOT_ONLY" -eq 1 ] || need "mkimage (uImage)" mkimage
# The kernel computes include/generated/timeconst.h with bc; without it the
# build stops at "prepare0" with "bc: command not found".
[ "$BOOT_ONLY" -eq 1 ] || need "bc (kernel)" bc
# bootgen is rebuilt when the one here cannot run in this environment, which needs a
# C++ compiler - say so now, not after the FSBL, U-Boot and the kernel have built.
if [ -x "$BOOTGEN" ] && _bootgen_runs_here "$BOOTGEN"; then :; else need "g++ (to rebuild bootgen)" g++; fi
need "unzip"                      unzip
if [ "$fail" -ne 0 ]; then
    echo >&2
    [ -e "$MONO/u-boot-xlnx/Makefile" ] || \
        echo "Sources missing: run  ./devkit setup --target modern" >&2
    [ -n "$CROSS" ] || {
        echo "No ARM Linux cross-compiler on this machine. Install either one:" >&2
        echo "    Debian/Ubuntu:  sudo apt install gcc-arm-linux-gnueabi" >&2
        echo "    Arch:           see docs/building.md, \"An ARM cross-compiler on Arch\"" >&2
        echo "or use the build container, which has one:" >&2
        echo "    ./devkit container build --target modern --xsa ${XSA_FILE:-FILE.xsa}" >&2; }
    command -v bc >/dev/null 2>&1 || [ "$BOOT_ONLY" -eq 1 ] || \
        echo "Missing host tools: Debian/Ubuntu sudo apt install bc flex bison; Arch sudo pacman -S bc flex bison" >&2
    exit 1
fi
echo "  ARM Linux compiler: ${CROSS}gcc"
[ "$PREFLIGHT_ONLY" -eq 1 ] && { echo "=== preflight passed; nothing built (--preflight-only) ==="; exit 0; }

mkdir -p "$OUT"
# EVERYTHING IS BUILT INTO $STAGE AND PUBLISHED TO $OUT ONLY WHEN IT HAS ALL PASSED.
# It used to write straight into output/: the XSA's provenance at step 1, BOOT.bin
# before it was checked. A build that then failed - an XSA the FSBL's headers do not
# match, say - left the PREVIOUS BOOT.bin sitting next to the NEW XSA's provenance,
# and write-card, which takes output/BOOT.bin by default, printed one design's
# name for the other's bitstream. Now a failed build leaves output/ exactly as it
# was: a consistent set, just an older one.
STAGE="$(mktemp -d "$OUT/.stage.XXXXXX")"
UENV_WORK=""; PKG=""
trap 'rm -rf "$STAGE" ${UENV_WORK:+"$UENV_WORK"} ${PKG:+"$PKG"}' EXIT

# ---- [1] the hardware platform --------------------------------------------------
echo "=== [1/6] Importing the XSA (shared with the factory target: import_xsa.sh) ==="
"$REPO/firmware/scripts/import_xsa.sh" "$XSA_FILE" "$PLUTO" "$STAGE"
BIT="$PLUTO/pluto.runs/impl_1/system_top.bit"

# ---- [2] FSBL ------------------------------------------------------------------
echo "=== [2/6] Building the FSBL (embeddedsw) ==="
# The committed BSP headers describe ONE hardware design; refuse an XSA they do
# not match, exactly as the factory target does, rather than build an FSBL with
# the wrong peripheral addresses - a board that does not boot and prints nothing.
"$REPO/firmware/fsbl/hwcheck.py" --xsa "$PLUTO/system_top.xsa" || {
    echo "ERROR: firmware/fsbl/generated/ does not match this hardware platform." >&2
    exit 1; }
# Distro compiler, with every Xilinx directory off PATH, for the same reason the
# factory target gives: which compiler you get must not depend on whether Vitis
# happens to be installed.
FSBL_PATH="$(printf '%s' "$PATH" | tr ':' '\n' | grep -v "^$XILINX_DIR" | paste -sd: -)"
PATH="$FSBL_PATH" make -s -C "$REPO/firmware/fsbl" \
    ESW="$BOOT/embeddedsw" XSA="$PLUTO/system_top.xsa" BUILD="$FSBL_BUILD"
FSBL_ELF="$FSBL_BUILD/app/Debug/fsbl.elf"
[ -f "$FSBL_ELF" ] || { echo "ERROR: the FSBL build produced no fsbl.elf" >&2; exit 1; }

# ---- [3] U-Boot ----------------------------------------------------------------
echo "=== [3/6] Building U-Boot ==="
# CC with -mfloat-abi=soft, so a hard-float compiler works too. Without it,
# U-Boot's -march=armv7-a probe fails (hard float, but armv7-a names no FPU) and
# falls through to -march=armv5, which GCC rejects. U-Boot compiles everything
# -msoft-float and links its own libgcc anyway, so the code is the same either
# way: tested on Ubuntu 22.04's gnueabi and gnueabihf GCC 11, the instructions
# are identical.
UCC="${CROSS}gcc -mfloat-abi=soft"
make -s -C "$MONO/u-boot-xlnx" ARCH=arm CROSS_COMPILE=$CROSS CC="$UCC" zynq_pluto_defconfig
make -s -C "$MONO/u-boot-xlnx" ARCH=arm CROSS_COMPILE=$CROSS CC="$UCC" UBOOTVERSION="PlutoSDR" -j"$(nproc)"
UBOOT_ELF="$MONO/u-boot-xlnx/u-boot"
[ -f "$UBOOT_ELF" ] || { echo "ERROR: the U-Boot build produced no u-boot" >&2; exit 1; }

# ---- [4] kernel ----------------------------------------------------------------
if [ "$BOOT_ONLY" -eq 1 ]; then
    echo "=== [skipped] kernel (--boot-only) - output/uImage and devicetree.dtb are not touched ==="
else
    echo "=== [4/6] Building the 6.12 kernel and the board's device tree ==="
    # fishball_defconfig, never zynq_pluto_defconfig on its own - that is an
    # ADALM-Pluto, with no Ethernet, SD card or GPIO sysfs (see README.md).
    make -s -C "$KSRC" ARCH=arm CROSS_COMPILE=$CROSS fishball_defconfig
    make -s -C "$KSRC" ARCH=arm CROSS_COMPILE=$CROSS uImage LOADADDR=0x8000 -j"$(nproc)"
    make -s -C "$KSRC" ARCH=arm CROSS_COMPILE=$CROSS DTC_FLAGS=-@ xilinx/zynq-pluto-sdr-fishball.dtb
    cp "$KSRC/arch/arm/boot/uImage" "$STAGE/uImage"
    # NOTE THE RENAME: the flasher wants the literal name devicetree.dtb.
    cp "$KSRC/arch/arm/boot/dts/xilinx/zynq-pluto-sdr-fishball.dtb" "$STAGE/devicetree.dtb"
fi

# ---- [5] uEnv.txt ----------------------------------------------------------------
echo "=== [5/6] Generating uEnv.txt from the freshly built U-Boot ==="
# Base: U-Boot's own default environment, extracted from THIS build - never the
# factory target's output/uEnv.txt, which make-uenv.sh would otherwise fall back
# to and which need not exist, or match, on a machine that only builds modern.
UENV_WORK="$(mktemp -d)"
( cd "$UENV_WORK" && CROSS_COMPILE=$CROSS "$MONO/scripts/get_default_envs.sh" > base-uEnv.txt )
[ -s "$UENV_WORK/base-uEnv.txt" ] || { echo "ERROR: get_default_envs.sh produced nothing" >&2; exit 1; }
"$FW_DIR/debian/make-uenv.sh" "$UENV_WORK/base-uEnv.txt" > "$STAGE/uEnv.txt"
# What this build is, for the board's login message (debian/overlay/etc/
# update-motd.d/10-fishball reads /boot/uEnv.txt). U-Boot imports these as
# variables nothing uses; they ride along wherever uEnv.txt goes - a release,
# write-card on Linux or Windows, ./devkit flash - so no copy path changes.
# No timestamp: two builds of one commit must give the same uEnv.txt.
case "$XSA_FILE" in
    */pinned/*/system_top.xsa) XSA_NAME="$(basename "$(dirname "$XSA_FILE")") pinned XSA" ;;
    *)                         XSA_NAME="$(basename "$XSA_FILE")" ;;
esac
HWH="$(unzip -p "$XSA_FILE" '*.hwh' 2>/dev/null || true)"
hwh() { printf '%s' "$HWH" | grep -o -m1 "$1=\"[^\"]*\"" | head -1 | cut -d'"' -f2; }
{
    echo "fishball_build=$(git -C "$REPO" describe --abbrev=8 --dirty --always --tags 2>/dev/null || echo unknown) modern"
    echo "fishball_xsa=$XSA_NAME, md5 $(md5sum < "$XSA_FILE" | cut -c1-8)"
    echo "fishball_fpga=xc$(hwh DEVICE)$(hwh PACKAGE)$(hwh SPEEDGRADE), Vivado $(hwh VIVADOVERSION)"
} >> "$STAGE/uEnv.txt"

# ---- [6] BOOT.bin ----------------------------------------------------------------
echo "=== [6/6] Packaging BOOT.bin: FSBL + bitstream + U-Boot ==="
devkit_ensure_bootgen "$BOOT/bootgen"
PKG="$(mktemp -d)"
cp "$FSBL_ELF" "$PKG/fsbl.elf"
cp "$BIT" "$PKG/system_top.bit"
cp "$UBOOT_ELF" "$PKG/u-boot.elf"
cp "$REPO/firmware/scripts/boot.bif" "$PKG/boot.bif"
( cd "$PKG" && "$BOOTGEN" -image boot.bif -arch zynq -o "$STAGE/BOOT.bin" -w >/dev/null )
# The bitstream as it sits in BOOT.bin (bootgen strips the .bit header), hashed
# by the same parser the board's login message uses, so the two always agree.
echo "fishball_bitstream=sha256 $("$FW_DIR/debian/overlay/usr/local/sbin/fishball-bootbin" --pl-sha256 "$STAGE/BOOT.bin" | cut -c1-16)" >> "$STAGE/uEnv.txt"

# ---- check, THEN publish -------------------------------------------------------
echo "=== Checking the output ==="
BUILT="BOOT.bin uEnv.txt"
[ "$BOOT_ONLY" -eq 1 ] || BUILT="$BUILT uImage devicetree.dtb"
for f in $BUILT; do
    [ -s "$STAGE/$f" ] || { echo "ERROR: $f is missing or empty - output/ left untouched." >&2; exit 1; }
done
sz=$(stat -c %s "$STAGE/BOOT.bin")
[ "$sz" -ge 1000000 ] || { echo "ERROR: BOOT.bin is only $sz bytes - bootgen failed quietly." >&2; exit 1; }
# Not just "a file of the right size": the three partitions BOOT.bin exists to
# carry, read back out of it, with the bitstream checked against the XSA byte for
# byte (bootgen stores it converted, so it is compared after the same conversion).
"$REPO/firmware/scripts/check_bootbin.py" "$STAGE/BOOT.bin" --xsa "$PLUTO/system_top.xsa" --bootgen "$BOOTGEN" || {
    echo "ERROR: BOOT.bin failed its check - output/ left untouched." >&2; exit 1; }

# Publish: every file of this build, its provenance AND the XSA it was built
# from, together. The XSA travels with the outputs because boot/hdl/ only ever
# holds the LAST one imported - including by a build that then failed - and a
# verify against that would compare a good BOOT.bin with somebody else's design.
cp "$PLUTO/system_top.xsa" "$STAGE/system_top.xsa"
for f in $BUILT xsa-provenance.txt system_top.xsa; do mv -f "$STAGE/$f" "$OUT/$f"; done
# shellcheck disable=SC2086
( cd "$OUT" && sha256sum $BUILT > SHA256SUMS.boot )
echo
echo "=== Done: $OUT ==="
# shellcheck disable=SC2086
( cd "$OUT" && sha256sum $BUILT )
[ "$BOOT_ONLY" -eq 1 ] && echo "(--boot-only: uImage and devicetree.dtb in output/ are from an earlier build, or absent)"
echo
echo "Onto a running board, with a backup and an md5 check before anything is swapped:"
echo "    ./devkit flash --target modern --boot-only      # BOOT.bin"
echo "    ./devkit flash --target modern --kernel-only    # uImage"
echo "Or a whole card from a reader, with the Debian root:"
echo "    sudo ./devkit write-card --target modern /dev/sdX"
if [ "$WITH_ROOTFS" -eq 1 ]; then
    echo
    echo "=== The boot files are done; now the Debian root (--all) ==="
    # Called, not exec'd: exec would skip the EXIT trap and leave the staging
    # and temp directories behind.
    "$FW_DIR/debian/build.sh"
fi
