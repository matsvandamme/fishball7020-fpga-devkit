#!/bin/bash
# Check everything a build needs BEFORE the build takes an hour to fail.
#
#     ./scripts/doctor.sh
#
# Every check here exists because its absence has cost somebody a long wait:
# a missing gmp.h fails forty minutes in, at stage 4; a missing cross-compiler
# fails at stage 2; a full disk fails wherever it happens to run out. None of them are
# interesting failures, and all of them are visible in a second up front.
#
# Exits non-zero if anything would stop a build, so CI can run it too.
set -uo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(dirname "$FW_DIR")"

fail=0
warn=0
say()  { printf "  %-6s %s\n" "$1" "$2"; }
ok()   { say "ok" "$1"; }
bad()  { say "FAIL" "$1"; fail=$((fail+1)); }
soft() { say "warn" "$1"; warn=$((warn+1)); }

# This runs under macOS's /bin/bash too, which is 3.2: no associative arrays.
# A Mac cannot build the factory firmware natively (no Vivado, and the kernel
# build wants a Linux host) - ./devkit container is the way there - but the
# doctor has to get to the end and say so rather than stop at a syntax error.
# pkg <apt packages> <brew packages>: the install line for this machine.
MAC=0; case "${OSTYPE:-}" in darwin*) MAC=1 ;; esac
pkg() { if [ "$MAC" -eq 1 ]; then echo "brew install $2"; else echo "sudo apt install $1"; fi; }
# Where headers live: /usr/include, plus Homebrew's prefix on a Mac (/opt/homebrew
# on Apple Silicon, /usr/local on Intel), which is not on the default search path.
INCLUDE_DIRS="/usr/include"
if [ "$MAC" -eq 1 ]; then
    INCLUDE_DIRS="$INCLUDE_DIRS $(brew --prefix 2>/dev/null || echo /opt/homebrew)/include"
    INCLUDE_DIRS="$INCLUDE_DIRS $(brew --prefix openssl 2>/dev/null || echo /opt/homebrew/opt/openssl)/include"
fi
have_header() {   # e.g. gmp.h, openssl/evp.h
    local d
    for d in $INCLUDE_DIRS; do
        [ -e "$d/$1" ] && return 0
        # Debian keeps some under /usr/include/<triplet>/.
        find "$d" -maxdepth 3 -name "$(basename "$1")" 2>/dev/null | grep -q . && return 0
    done
    return 1
}
sha256() {        # sha256sum is GNU; macOS before 13 has only shasum
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
    else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

# Are we already inside the build container? Telling someone to use the
# container while they are in it is worse than saying nothing.
IN_CONTAINER=0
if [ -f /run/.containerenv ] || [ -f /.dockerenv ]; then IN_CONTAINER=1; fi

# Vivado 2022.2 supports Ubuntu 18.04, 20.04 and 22.04 (UG973) and nothing
# newer. On anything else the answer is not "install some packages", it is
# "build in the container" - so say that once, here, rather than letting
# someone discover it when the installer will not run either.
OS_RELEASE="${OS_RELEASE:-/etc/os-release}"   # overridable so this is testable
host_supported_by_vivado() {
    [ -r "$OS_RELEASE" ] || return 0            # unknown: do not scare anyone
    . "$OS_RELEASE"
    [ "${ID:-}" = "ubuntu" ] || return 0        # RHEL/SUSE have their own list
    case "${VERSION_ID:-}" in
        18.04|20.04|22.04) return 0 ;;
        *) return 1 ;;
    esac
}

echo "== toolchain =="
if [ "$MAC" -eq 1 ]; then
    soft "macOS cannot build the factory firmware natively: Vivado is Linux-only"
    say "" "Build in the container instead (docs/building-in-a-container.md):"
    say "" "  ./devkit container build-image"
    say "" "The host tools need none of what follows: ./devkit doctor --host"
elif [ "$IN_CONTAINER" -eq 0 ] && ! host_supported_by_vivado; then
    . "$OS_RELEASE" 2>/dev/null
    soft "Ubuntu ${VERSION_ID:-?} is newer than Vivado 2022.2 supports (18.04/20.04/22.04)"
    say "" "Build in the container instead - it needs nothing from this OS:"
    say "" "  ./devkit container build-image"
    say "" "  ./devkit container build --target factory --hdl-only"
    if command -v podman >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
        ok "container runtime present ($(command -v podman >/dev/null 2>&1 && echo podman || echo docker))"
    else
        say "" "  (install podman first: sudo apt install podman uidmap)"
    fi
    say "" "See docs/building-in-a-container.md"
fi
# Where Vivado 2022.2 lives. Override XILINX_DIR if you installed
# somewhere other than the default - the container build does exactly
# that to test against a throwaway installation.
XILINX_DIR="${XILINX_DIR:-/tools/Xilinx}"
VIVADO_DIR="$XILINX_DIR/Vivado/2022.2"
# Vivado is needed to BUILD the FPGA design. It is not needed to build
# firmware from a hardware platform somebody already exported, which is what
# --xsa is for - so a missing Vivado is a warning with a way forward rather
# than a dead end. Nothing here needs Vitis any more.
if [ -x "$VIVADO_DIR/bin/vivado" ]; then ok "Vivado 2022.2 at $VIVADO_DIR"
elif [ "$IN_CONTAINER" -eq 0 ] && ! host_supported_by_vivado; then
    soft "Vivado 2022.2 not found at $VIVADO_DIR, and this OS cannot install it."
    soft "  Either use ./devkit container, or build from a pre-made hardware"
    soft "  platform: ./scripts/build_all.sh --xsa FILE (docs/building-without-vivado.md)"
else
    soft "Vivado 2022.2 not found at $VIVADO_DIR (see README step 1)."
    soft "  You can still build without it from a pre-made hardware platform:"
    soft "  ./scripts/build_all.sh --xsa FILE  (docs/building-without-vivado.md)"
fi
# What the default FSBL path actually needs.
if command -v arm-none-eabi-gcc >/dev/null 2>&1; then
    # A newlib without the hard-float multilib links with an obscure "uses VFP
    # register arguments"; checking here costs nothing and saves that hunt.
    if [ "$(arm-none-eabi-gcc -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard \
            -print-multi-directory 2>/dev/null)" = "." ]; then
        bad "arm-none-eabi-gcc has no hard-float multilib - install libnewlib-arm-none-eabi"
    else
        ok "arm-none-eabi-gcc ($(arm-none-eabi-gcc -dumpversion 2>/dev/null)) - builds the FSBL"
    fi
else
    bad "arm-none-eabi-gcc missing - the FSBL needs it ($(pkg "gcc-arm-none-eabi libnewlib-arm-none-eabi" "--cask gcc-arm-embedded"))"
fi
# u-boot, the kernel and the device tree. Either ARM Linux compiler builds
# them: build_all.sh compiles u-boot with -mfloat-abi=soft, so the hard-float
# one no longer trips u-boot's -march probe. Soft-float gnueabi is preferred
# because only it reproduces the factory kernel byte for byte.
if command -v arm-linux-gnueabi-gcc >/dev/null 2>&1; then
    ok "arm-linux-gnueabi-gcc ($(arm-linux-gnueabi-gcc -dumpversion 2>/dev/null)) - builds u-boot and the kernel"
elif command -v arm-linux-gnueabihf-gcc >/dev/null 2>&1; then
    ok "arm-linux-gnueabihf-gcc ($(arm-linux-gnueabihf-gcc -dumpversion 2>/dev/null)) - builds u-boot and the kernel"
    say "" "  the kernel will differ from a gnueabi build, so it is not the byte-identical factory reconstruction"
else
    bad "no ARM Linux cross-compiler - u-boot and the kernel need one
         Debian/Ubuntu: sudo apt install gcc-arm-linux-gnueabi
         Arch:          see docs/building.md, \"An ARM cross-compiler on Arch\""
fi
if [ -d "$FW_DIR/src/embeddedsw" ]; then ok "embeddedsw present - the FSBL is built from it"
else soft "no src/embeddedsw yet - run: ./devkit setup --target factory"; fi
if [ -r "$REPO_DIR/tools/env-vivado.sh" ]; then ok "tools/env-vivado.sh present"
else bad "tools/env-vivado.sh missing"; fi

echo
echo "== host packages =="
# command|what breaks without it. One line each and not an associative array
# (bash 4): see the note on macOS above. It also fixes the order, which an
# associative array left to its hash.
while IFS="|" read -r c why; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c"
  else bad "$c missing - needed for $why"; fi
done <<'NEED'
git|cloning the upstream source
make|every build stage
gcc|host tools and the cross-toolchain build
bison|the kernel build
flex|the kernel build
bc|the kernel build (include/generated/timeconst.h)
dtc|the device tree (device-tree-compiler)
mkimage|the uImage and ramdisk (u-boot-tools)
NEED
if command -v python3 >/dev/null 2>&1; then ok "python3"; else bad "python3 missing"; fi
# bootgen is built from AMD's Apache-2.0 source by setup.sh, not taken from a
# Xilinx install. That is what makes an --xsa build need nothing from Xilinx.
if [ -x "$FW_DIR/src/bootgen/bootgen" ]; then ok "bootgen (built from source; packages BOOT.bin)"
elif [ -d "$FW_DIR/src" ]; then bad "no src/bootgen/bootgen - run: ./devkit setup --target factory"
else soft "bootgen not built yet - ./devkit setup --target factory builds it"; fi
# It is C++ against OpenSSL. Both are in build-essential/libssl-dev, which the
# kernel build needs anyway, so this only fires on an unusually bare host.
command -v g++ >/dev/null 2>&1 || bad "g++ missing - bootgen cannot be built ($(pkg build-essential gcc))"
have_header openssl/evp.h || bad "openssl headers missing - bootgen cannot be built ($(pkg libssl-dev openssl))"
# Headers, which are not commands. The kernel's GCC plugins #include <gmp.h>
# and the failure appears at stage 4 as a bare "gmp.h: No such file".
for h in gmp.h mpc.h mpfr.h; do
  if have_header "$h"; then ok "$h"
  else bad "$h missing - $(pkg "libgmp-dev libmpc-dev libmpfr-dev" "gmp libmpc mpfr")"; fi
done
if command -v iverilog >/dev/null 2>&1; then ok "iverilog (HDL simulation)"
else soft "iverilog missing - ./sim/run_sim.sh will not run ($(pkg iverilog icarus-verilog))"; fi
# Logging in to the board unattended: the key ./devkit ssh-key makes, or
# sshpass typing the password. Either will do (tools/lib/board-ssh.sh).
if [ -r "${FISHBALL_SSH_KEY:-$HOME/.ssh/fishball}" ]; then ok "board ssh key (scripted board access)"
elif command -v sshpass >/dev/null 2>&1; then ok "sshpass (scripted board access)"
else soft "no board ssh key and no sshpass - flash.sh and the hardware checks cannot log in (./devkit ssh-key, or $(pkg sshpass sshpass))"; fi

echo
echo "== disk =="
avail_kb=$(df -Pk "$FW_DIR" | awk 'NR==2 {print $4}')
avail_gb=$(( avail_kb / 1024 / 1024 ))
# Measured: src/ plus a full build is about 25 GB, and Buildroot is the part
# that grows late, so running out happens near the end of a 70-minute run.
if   [ "$avail_gb" -ge 40 ]; then ok "${avail_gb} GB free"
elif [ "$avail_gb" -ge 25 ]; then soft "${avail_gb} GB free - tight; a full build needs ~25 GB"
else bad "${avail_gb} GB free - a full build needs about 25 GB"; fi

echo
echo "== source tree =="
if [ -d "$FW_DIR/src/.git" ]; then
  ok "src/ present"
  stamp="$FW_DIR/src/.devkit-patches-applied"
  if [ ! -f "$stamp" ]; then
    soft "patches not applied - run ./devkit setup --target factory"
  else
    missing=0
    for p in "$FW_DIR"/patches/*.patch; do
      grep -qxF "$(sha256 "$p")  $(basename "$p")" "$stamp" || missing=$((missing+1))
    done
    if [ "$missing" -eq 0 ]; then ok "patches applied (current set)"
    else soft "$missing patch(es) not applied - run ./devkit setup --target factory"; fi
  fi
else
  soft "src/ not present yet - run ./scripts/setup.sh first"
fi

echo
echo "== board (optional) =="
# Ask board_addr.py for the verdict, not ping. Two reasons, and the second one
# is why this changed: reachable() makes each service identify itself - iiod
# answers VERSION, dropbear names itself in its banner - so something else on an
# open port is not mistaken for the board; and it needs no ICMP, so it still
# works in the build container, which ships no ping at all. With ping this check
# could never pass in a container however good the address was.
_BOARD_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../tools" && pwd)/board_addr.py"
if BOARD_AT="$(python3 "$_BOARD_PY" --check 2>/dev/null)"; then
  ok "board reachable at $BOARD_AT"
else
  soft "no board at ${BOARD_AT:-${BOARD:-192.168.2.1}} - fine for building, needed for flashing and tests (set BOARD=<address>)"
fi

echo
if [ $fail -gt 0 ]; then
  echo "$fail problem(s) would stop a build. Fix those first."
  exit 1
fi
[ $warn -gt 0 ] && echo "Ready to build ($warn optional item(s) missing)." \
                || echo "Ready to build."
exit 0
