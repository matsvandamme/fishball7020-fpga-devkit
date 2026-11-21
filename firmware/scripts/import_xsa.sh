#!/bin/bash
# Import a pre-built hardware platform (.xsa) so a boot image can be made from it
# without running Vivado.
#
#     # run from: anywhere
#     ./firmware/scripts/import_xsa.sh <file.xsa> <pluto_dir> <out_dir>
#
#   <pluto_dir>  where the FSBL build and the packaging step look for the platform:
#                <pluto_dir>/system_top.xsa, and the bitstream at
#                <pluto_dir>/pluto.runs/impl_1/system_top.bit
#   <out_dir>    where xsa-provenance.txt is written
#
# SHARED by the two targets, which is the whole reason it is a separate file:
#   firmware/scripts/build_all.sh --xsa     the factory target
#   firmware-modern/build_all.sh --xsa      the modern target (which has no Vivado
#                                           path at all, so it ALWAYS comes here)
# Before it existed this logic lived inline in build_all.sh, and a second target
# would have meant a second copy of every refusal below - the kind of duplicate
# that drifts until the two targets accept different files.
#
# Everything here refuses early and in one sentence, because the alternative is a
# confusing failure three stages later in the FSBL build.
set -eu

XSA_FILE="${1:?usage: import_xsa.sh <file.xsa> <pluto_dir> <out_dir>}"
PLUTO_DIR="${2:?usage: import_xsa.sh <file.xsa> <pluto_dir> <out_dir>}"
OUT_DIR="${3:?usage: import_xsa.sh <file.xsa> <pluto_dir> <out_dir>}"

[ -r "$XSA_FILE" ] || { echo "ERROR: cannot read $XSA_FILE" >&2; exit 1; }

# An .xsa is a zip. Check that before anything else, so a wrong file gets
# one clear sentence instead of a confusing failure three stages later.
unzip -l "$XSA_FILE" >/dev/null 2>&1 || {
    echo "ERROR: $XSA_FILE is not a readable zip archive." >&2
    echo "       An .xsa is a zip. Did you pass a .bit or a .bin by mistake?" >&2
    exit 1; }
unzip -l "$XSA_FILE" | grep -q ' system_top.bit$' || {
    echo "ERROR: $XSA_FILE contains no system_top.bit." >&2
    echo "       It was probably exported without the bitstream. The export" >&2
    echo "       needs -include_bit; see docs/building-without-vivado.md" >&2
    exit 1; }

# Refuse a platform for another part or another tool version rather than
# let it reach the FSBL build and fail there, where the message is about a
# missing peripheral rather than about the file you passed.
sysdef="$(unzip -p "$XSA_FILE" sysdef.xml 2>/dev/null || true)"
case "$sysdef" in
    *'PART="xc7z020clg400-2"'*) ;;
    "") echo "WARNING: $XSA_FILE has no sysdef.xml - cannot check the part" >&2 ;;
    *)  echo "ERROR: that XSA is not for this board's part (xc7z020clg400-2)." >&2
        echo "       It says: $(printf '%s' "$sysdef" | grep -o 'PART="[^\"]*"' | head -1)" >&2
        # CLG484 is the PlutoSky R2: another board, which boots an R1 image with
        # no radio, no Ethernet and no USB. Say where it is built.
        case "$sysdef" in
            *'PART="xc7z020clg484-2"'*)
                echo "       That is a PlutoSky R2 design. The R2 is built from its own repository:" >&2
                echo "           https://github.com/matsvandamme/plutosky-r2-fpga-devkit" >&2 ;;
        esac
        exit 1 ;;
esac
case "$sysdef" in
    *'Version="2022.2"'*|"") ;;
    *)  echo "ERROR: that XSA was written by a different tool version." >&2
        echo "       It says: $(printf '%s' "$sysdef" | grep -o 'Version="[^\"]*"' | head -1)" >&2
        echo "       This repository builds with 2022.2; mixing versions puts a" >&2
        echo "       mismatched ps7_init.c into the FSBL." >&2
        exit 1 ;;
esac

mkdir -p "$PLUTO_DIR/pluto.runs/impl_1"
# Pointing --xsa at the tree's own platform is a reasonable thing to do
# (rebuild from what is already here without re-running Vivado), and cp
# refuses to copy a file onto itself.
if [ "$XSA_FILE" -ef "$PLUTO_DIR/system_top.xsa" ]; then
    echo "    (already in place - reusing it where it is)"
else
    cp -f "$XSA_FILE" "$PLUTO_DIR/system_top.xsa"
fi

# The packaging step copies the bitstream out of the RUN directory, not out of
# the XSA, so it has to land there. Verified byte-identical to a Vivado
# run's own output.
unzip -p "$XSA_FILE" system_top.bit > "$PLUTO_DIR/pluto.runs/impl_1/system_top.bit"
[ -s "$PLUTO_DIR/pluto.runs/impl_1/system_top.bit" ] || {
    echo "ERROR: extracted system_top.bit is empty." >&2; exit 1; }

# Delete rather than ignore. verify_output.sh reads these, and a report
# left over from an earlier build would describe a bitstream it never saw
# - which is exactly how a design gets vouched for by the wrong numbers.
#
# NOTE the cost: on a tree that was built from source, these ARE that build's
# reports, and deleting them is what the import is for. Vivado's own routed
# reports survive in pluto.runs/impl_1/ and can regenerate them from the routed
# checkpoint in minutes rather than a 70-minute rebuild - see
# docs/building-without-vivado.md.
rm -f "$PLUTO_DIR/timing.rpt" "$PLUTO_DIR/utilization.rpt"

mkdir -p "$OUT_DIR"
{
    echo "# Written by import_xsa.sh. This bitstream was NOT built here."
    echo "source:   $XSA_FILE"
    echo "md5:      $(md5sum "$XSA_FILE" | cut -d' ' -f1)"
    echo "mtime:    $(date -r "$XSA_FILE" -Is 2>/dev/null || echo unknown)"
    echo "imported: $(date -Is)"
    echo "bitstream_md5: $(md5sum "$PLUTO_DIR/pluto.runs/impl_1/system_top.bit" | cut -d' ' -f1)"
    echo "# IP instances, read from the platform's own system.hwh - this"
    echo "# describes the BITSTREAM, unlike system_bd.tcl which describes"
    echo "# whatever source happens to be in the tree."
    unzip -p "$XSA_FILE" system.hwh 2>/dev/null \
        | grep -oE 'INSTANCE="[A-Za-z_0-9]+"' | sort -u | sed 's/^/ip: /' || true
} > "$OUT_DIR/xsa-provenance.txt"

bit_sz=$(stat -c %s "$PLUTO_DIR/pluto.runs/impl_1/system_top.bit")
echo "    hardware platform: $PLUTO_DIR/system_top.xsa"
echo "    bitstream:         $bit_sz bytes"
echo "    provenance:        $OUT_DIR/xsa-provenance.txt"
echo "    NOTE: this design was not implemented here, so there is no timing"
echo "          report to check. verify_output.sh will say so."
