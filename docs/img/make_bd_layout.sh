#!/usr/bin/env bash
# Export the Vivado block design as an image, for docs/block-design.md and
# docs/both-receive-channels.md.
#
# Why it copies the project first: Vivado locks a project it has open, and the
# one you are looking at in the GUI is usually the one you want a picture of.
# Working on a copy means this never has to ask you to close anything.
#
#   ./make_bd_layout.sh            # whichever design is currently built
#
# The project must already exist. If it does not:
#   cd firmware && ./scripts/build_all.sh --hdl-only     (or just let it run to
#   the end of system_bd.tcl - the layout does not need synthesis)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJ="$REPO/firmware/src/hdl/projects/pluto"
WORK="$REPO/firmware/src/hdl/projects/pluto-bdimg"
OUT="$REPO/docs/img"

[ -f "$PROJ/pluto.xpr" ] || { echo "no project at $PROJ/pluto.xpr - build it first" >&2; exit 1; }

rm -rf "$WORK"; mkdir -p "$WORK"
cp -a "$PROJ/pluto.xpr" "$PROJ/pluto.srcs" "$PROJ/pluto.gen" "$WORK/"

# write_bd_layout renders through the GUI canvas - in plain batch mode it fails
# with "[BD 5-349] Please run the tool in GUI mode". start_gui brings the canvas
# up for the few seconds it takes, and the window closes again when Vivado exits.
cat > "$WORK/write_layout.tcl" <<TCL
open_project pluto.xpr
start_gui
open_bd_design [get_files system.bd]
write_bd_layout -force -format svg -orientation landscape $OUT/bd-top.svg
current_bd_instance /rx_fir_decimator
write_bd_layout -force -format svg -orientation landscape $OUT/bd-rx-decimator.svg
current_bd_instance /
puts "=== layouts written ==="
TCL

source "$REPO/tools/env-vivado.sh"
cd "$WORK"
vivado -mode batch -source write_layout.tcl -log layout.log -journal layout.jou

cd "$REPO"
rm -rf "$WORK"
echo "wrote $OUT/bd-top.svg and $OUT/bd-rx-decimator.svg"
