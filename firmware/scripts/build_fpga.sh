#!/bin/bash
# Build the FPGA design for a hardware revision other than the R1, and stop:
# synthesis -> implementation -> bitstream -> system_top.xsa.
#
#     # run from: the repo root
#     ./devkit build --target factory --rev r2
#
#     --preflight-only   check the tools and the source tree, build nothing
#
# There is no kernel, U-Boot or root filesystem stage here, and no BOOT.bin: on
# these revisions the factory target exists to produce the XSA, and the modern
# target builds the rest from it (firmware/scripts/setup_fpga.sh says why).
#
# The Vivado step is build_all.sh's stage [1/7], run the same way - same
# build_hdl.tcl, same coefficient file, same environment. It is a copy, not a
# shared function, so that this file could be added without touching the script
# every R1 build runs. If you change one, change the other.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FW1_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$FW1_DIR")"
# shellcheck source=rev.sh
source "$SCRIPT_DIR/rev.sh"

PREFLIGHT_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --preflight-only) PREFLIGHT_ONLY=1 ;;
        -h|--help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        --hdl-only) ;;   # the only thing this builds; accepted so the habit still works
        --xsa|--xsa=*)
            echo "ERROR: --xsa has nothing to do here: on --rev $DEVKIT_REV the factory target only" >&2
            echo "       builds the FPGA. An XSA you already have goes to the modern target:" >&2
            echo "           ./devkit build$REV_FLAG --xsa FILE" >&2
            exit 1 ;;
        *) echo "ERROR: unknown option '$arg' (try --help)" >&2; exit 1 ;;
    esac
done
if [ "$DEVKIT_REV" = r1 ]; then
    echo "ERROR: build_fpga.sh is for the other revisions. On the R1:" >&2
    echo "           ./devkit build --target factory [--hdl-only]" >&2
    exit 1
fi

SRC_DIR="$FW1_DIR/src$REV_SUFFIX"
PLUTO="$SRC_DIR/hdl/projects/pluto"
XILINX_DIR="${XILINX_DIR:-/tools/Xilinx}"

fail=0
[ -f "$PLUTO/system_bd.tcl" ] || {
    echo "ERROR: $PLUTO is missing. Run ./devkit setup --target factory$REV_FLAG" >&2; fail=1; }
[ -x "$XILINX_DIR/Vivado/2022.2/bin/vivado" ] || {
    echo "ERROR: missing $XILINX_DIR/Vivado/2022.2/bin/vivado (is Vivado 2022.2 installed under $XILINX_DIR?)" >&2
    echo "       On a host too new for it: ./devkit container build --target factory$REV_FLAG" >&2
    fail=1; }
# A patch in the series that is not in the stamp has not been applied: a git pull
# that brought one is the common case, and building without it gives a bitstream
# that silently lacks the change.
STAMP="$SRC_DIR/.devkit-patches-applied"
if [ -f "$PLUTO/system_bd.tcl" ]; then
    if [ ! -f "$STAMP" ]; then
        echo "ERROR: $SRC_DIR carries no patch stamp - setup has not completed on it." >&2
        echo "       Run ./devkit setup --target factory$REV_FLAG" >&2; fail=1
    else
        while IFS= read -r p; do
            grep -qE '^(\+\+\+ b|--- a)/hdl/' "$p" || continue
            line="$(sha256sum "$p" | cut -d' ' -f1)  $(basename "$p")"
            grep -qxF "$line" "$STAMP" || {
                echo "ERROR: $(basename "$p") is not applied (or has changed since it was)." >&2
                echo "       Run ./devkit setup --target factory$REV_FLAG, then build." >&2; fail=1; }
        done < <(devkit_patch_series "$FW1_DIR")
    fi
    # The part in the project script is what Vivado will build for. If it is not
    # this revision's, the series did not put the revision's design in the tree.
    grep -q "\"$REV_PART\"" "$PLUTO/system_project.tcl" || {
        echo "ERROR: $PLUTO/system_project.tcl does not name $REV_PART." >&2
        echo "       This tree is not the $REV_NAME's design. rm -rf \"$SRC_DIR\" and set up again." >&2
        fail=1; }
fi
# An existing Vivado project is REUSED by build_hdl.tcl, which never re-sources
# system_bd.tcl - so edited sources are silently ignored. Same guard as build_all.sh.
if [ -f "$PLUTO/pluto.xpr" ]; then
    stale=""
    for f in "$PLUTO"/system_bd.tcl "$PLUTO"/system_constr.xdc "$PLUTO"/*.v "$SCRIPT_DIR"/coefile_*.coe; do
        [ -f "$f" ] && [ "$f" -nt "$PLUTO/pluto.xpr" ] && stale="$stale $(basename "$f")"
    done
    if [ -n "$stale" ] && [ -z "${FORCE_STALE_PROJECT:-}" ]; then
        echo "ERROR: these design sources are newer than the existing Vivado project:$stale" >&2
        echo "       build_hdl.tcl would reuse the OLD block design and ignore them." >&2
        echo "           rm -rf $PLUTO/pluto.{xpr,cache,gen,hw,ip_user_files,runs,sim,srcs,sdk}" >&2
        echo "       (or set FORCE_STALE_PROJECT=1 if you really mean to keep it)" >&2
        fail=1
    fi
fi
[ "$fail" -eq 0 ] || { echo "Preflight failed - fix the above and re-run." >&2; exit 1; }
[ "$PREFLIGHT_ONLY" -eq 1 ] && { echo "Preflight passed."; exit 0; }

echo "=== Building the $REV_NAME FPGA design ($REV_PART): synth -> impl -> bitstream -> XSA ==="
(
    # env-vivado.sh sets SCRIPT_DIR to its own directory, tools/ - so the
    # scripts directory is taken from FW1_DIR here, not from SCRIPT_DIR.
    source "$REPO_ROOT/tools/env-vivado.sh"
    cd "$PLUTO"
    cp "$FW1_DIR/scripts/build_hdl.tcl" .
    cp "$FW1_DIR/scripts/coefile_wbfm_102100.coe" .
    vivado -mode batch -source build_hdl.tcl -journal build_hdl.jou -log build_hdl.log
    echo "    Timing summary:"; grep -A3 "Design Timing Summary" timing.rpt | tail -2 || true
)
XSA="$PLUTO/system_top.xsa"
[ -s "$XSA" ] || { echo "ERROR: Vivado finished without writing $XSA - see $PLUTO/build_hdl.log" >&2; exit 1; }
unzip -l "$XSA" 2>/dev/null | grep -q ' system_top.bit$' || {
    echo "ERROR: $XSA has no bitstream in it - implementation failed; see $PLUTO/build_hdl.log" >&2; exit 1; }

cat <<EOF

=== Done: $XSA ===
  Read the timing summary above before using it: this revision's constraints
  were first written without a Vivado run, and a design that does not meet
  timing still produces a bitstream.
      less $PLUTO/timing.rpt

  The rest of the firmware is the modern target's, built around this XSA:
      ./devkit setup$REV_FLAG                      # once
      ./devkit build$REV_FLAG --xsa ${XSA#"$REPO_ROOT"/}
EOF
