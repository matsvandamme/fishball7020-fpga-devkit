#!/bin/bash
# Check everything a build needs BEFORE the build takes an hour to fail.
#
#     ./scripts/doctor.sh
#
# Every check here exists because its absence has cost somebody a long wait:
# a missing gmp.h fails forty minutes in, at stage 4; a missing Xvfb fails at
# stage 2; a full disk fails wherever it happens to run out. None of them are
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
if [ "$IN_CONTAINER" -eq 0 ] && ! host_supported_by_vivado; then
    . "$OS_RELEASE" 2>/dev/null
    soft "Ubuntu ${VERSION_ID:-?} is newer than Vivado 2022.2 supports (18.04/20.04/22.04)"
    say "" "Build in the container instead - it needs nothing from this OS:"
    say "" "  ./devkit container build-image"
    say "" "  ./devkit container build --hdl-only"
    if command -v podman >/dev/null 2>&1 || command -v docker >/dev/null 2>&1; then
        ok "container runtime present ($(command -v podman >/dev/null 2>&1 && echo podman || echo docker))"
    else
        say "" "  (install podman first: sudo apt install podman uidmap)"
    fi
    say "" "See docs/building-in-a-container.md"
fi
# Where Vivado/Vitis 2022.2 live. Override XILINX_DIR if you installed
# somewhere other than the default - the container build does exactly
# that to test against a throwaway installation.
XILINX_DIR="${XILINX_DIR:-/tools/Xilinx}"
VIVADO_DIR="$XILINX_DIR/Vivado/2022.2"
VITIS_DIR="$XILINX_DIR/Vitis/2022.2"
if [ -x "$VIVADO_DIR/bin/vivado" ]; then ok "Vivado 2022.2 at $VIVADO_DIR"
elif [ "$IN_CONTAINER" -eq 0 ] && ! host_supported_by_vivado; then
    bad "Vivado 2022.2 not found at $VIVADO_DIR - and this OS cannot install it; use ./devkit container"
else bad "Vivado 2022.2 not found at $VIVADO_DIR (see README step 1)"; fi
if [ -x "$VITIS_DIR/bin/xsct" ]; then ok "Vitis 2022.2 (xsct) - needed for the FSBL"
else bad "Vitis 2022.2 not found at $VITIS_DIR - the FSBL stage will fail"; fi
if [ -r "$REPO_DIR/tools/env-vivado.sh" ]; then ok "tools/env-vivado.sh present"
else bad "tools/env-vivado.sh missing"; fi

echo
echo "== host packages =="
# command -> what breaks without it
declare -A NEED=(
  [git]="cloning the upstream source"
  [make]="every build stage"
  [gcc]="host tools and the cross-toolchain build"
  [bison]="the kernel build"
  [flex]="the kernel build"
  [dtc]="the device tree (device-tree-compiler)"
  [mkimage]="the uImage and ramdisk (u-boot-tools)"
)
for c in "${!NEED[@]}"; do
  if command -v "$c" >/dev/null 2>&1; then ok "$c"
  else bad "$c missing - needed for ${NEED[$c]}"; fi
done
# Xvfb is needed only when there is no display: build_all.sh uses $DISPLAY if
# set and falls back to Xvfb otherwise. Failing a desktop user for it is false.
if [ -n "${DISPLAY:-}" ]; then ok "DISPLAY set ($DISPLAY) - Vitis can use it for the FSBL stage"
elif command -v Xvfb >/dev/null 2>&1; then ok "Xvfb (no DISPLAY, so the FSBL stage will use it)"
else bad "no DISPLAY and no Xvfb - the FSBL stage will fail (sudo apt install xvfb)"; fi
if command -v python3 >/dev/null 2>&1; then ok "python3"; else bad "python3 missing"; fi
if [ -x "$VIVADO_DIR/bin/bootgen" ] || [ -x "$VITIS_DIR/bin/bootgen" ]; then ok "bootgen (packages BOOT.bin)"
else bad "bootgen not found under Vivado or Vitis - packaging will fail"; fi
# Headers, which are not commands. The kernel's GCC plugins #include <gmp.h>
# and the failure appears at stage 4 as a bare "gmp.h: No such file".
for h in gmp.h mpc.h mpfr.h; do
  if find /usr/include -maxdepth 3 -name "$h" 2>/dev/null | grep -q .; then ok "$h"
  else bad "$h missing - install libgmp-dev libmpc-dev libmpfr-dev"; fi
done
if command -v iverilog >/dev/null 2>&1; then ok "iverilog (HDL simulation)"
else soft "iverilog missing - ./sim/run_sim.sh will not run (sudo apt install iverilog)"; fi
if command -v sshpass >/dev/null 2>&1; then ok "sshpass (scripted board access)"
else soft "sshpass missing - flash.sh and the hardware checks need it"; fi

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
    soft "patches not applied - run ./devkit setup"
  else
    missing=0
    for p in "$FW_DIR"/patches/*.patch; do
      grep -qxF "$(sha256sum "$p" | cut -d' ' -f1)  $(basename "$p")" "$stamp" || missing=$((missing+1))
    done
    if [ "$missing" -eq 0 ]; then ok "patches applied (current set)"
    else soft "$missing patch(es) not applied - run ./devkit setup"; fi
  fi
else
  soft "src/ not present yet - run ./scripts/setup.sh first"
fi

echo
echo "== board (optional) =="
BOARD="${BOARD:-192.168.2.1}"     # the one knob: flash, verify, gpio-check, selftest
if ping -c1 -W1 "$BOARD" >/dev/null 2>&1; then
  ok "board reachable at $BOARD"
else
  soft "no board at $BOARD - fine for building, needed for flashing and tests (set BOARD=<address>)"
fi

echo
if [ $fail -gt 0 ]; then
  echo "$fail problem(s) would stop a build. Fix those first."
  exit 1
fi
[ $warn -gt 0 ] && echo "Ready to build ($warn optional item(s) missing)." \
                || echo "Ready to build."
exit 0
