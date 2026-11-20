#!/bin/bash
# Which hardware revision is this command for? Source it; do not run it.
#
#     DEVKIT_REV=r1   PlutoSky R1 / 7020-SDR   XC7Z020-CLG400   (the default)
#     DEVKIT_REV=r2   PlutoSky R2              XC7Z020-CLG484
#
# ./devkit sets DEVKIT_REV from --rev and exports it; a script run directly reads
# it from the environment. Every revision-dependent name lives HERE, once, so the
# scripts that source this cannot disagree about where the R2's files are.
#
# WHY A REVISION AT ALL. The R2 is not an R1 with a different label. It is
# another package (CLG484), so every FPGA ball is different; its Ethernet PHY is
# on FPGA pins behind a GMII-to-RGMII core where the R1's is on PS MIO 16-27;
# and its MIO bank 501 runs at 3.3 V where the R1's runs at 1.8 V. An R1 boot
# image on an R2 boots Linux with no radio, no Ethernet and no USB (measured
# 2026-11-18: AD9361 PRODUCT_ID 0xFF, "Could not attach PHY (-19)", no usb0).
# So the two must never share an output directory, and an XSA for one must be
# refused for the other.
#
# The R1's names carry no suffix, so every path an R1 user has ever typed still
# means what it meant.
DEVKIT_REV="${DEVKIT_REV:-r1}"
case "$DEVKIT_REV" in
    r1)
        REV_SUFFIX=""
        REV_NAME="PlutoSky R1"
        REV_PART="xc7z020clg400-2"
        REV_DTB="zynq-pluto-sdr-fishball"
        ;;
    r2)
        REV_SUFFIX="-r2"
        REV_NAME="PlutoSky R2"
        REV_PART="xc7z020clg484-2"
        REV_DTB="zynq-pluto-sdr-fishball-r2"
        ;;
    *)
        echo "ERROR: unknown hardware revision '$DEVKIT_REV'. It is r1 (the default) or r2." >&2
        exit 1 ;;
esac
export DEVKIT_REV
# " --rev r2" on the R2 and nothing on the R1, for the commands messages print.
REV_FLAG=""
[ "$DEVKIT_REV" = r1 ] || REV_FLAG=" --rev $DEVKIT_REV"

# The factory patch series for this revision, one path per line, in apply order.
#
#   firmware/patches/*.patch              the series, written for the R1
#   firmware/revs/<rev>/patches/*.patch   this revision's own
#
# A revision patch with the SAME FILE NAME as a series patch REPLACES it; any
# other is added. The merged list is ordered by file name, so 0000-... goes on
# first. On the R1 this is exactly firmware/patches/*.patch.
devkit_patch_series() {   # <firmware dir>
    local fw="$1" revdir="$1/revs/$DEVKIT_REV/patches" p
    {
        for p in "$fw"/patches/*.patch; do
            [ -f "$revdir/$(basename "$p")" ] || echo "$p"
        done
        if [ -d "$revdir" ]; then
            for p in "$revdir"/*.patch; do [ -f "$p" ] && echo "$p"; done
        fi
    } | awk -F/ '{ print $NF "\t" $0 }' | sort | cut -f2-
}
