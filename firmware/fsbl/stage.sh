#!/bin/bash
# Assemble a build tree for the FSBL from embeddedsw + the generated files here
# + ps7_init from the hardware platform. See README.md for why this exists.
#
# Everything this writes is disposable: the tree is rebuilt from scratch each
# time, and nothing outside $BUILD is touched.
set -euo pipefail

FSBL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$FSBL_DIR/../.." && pwd)"
ESW="${ESW:-$REPO/firmware/src/embeddedsw}"
XSA="${XSA:-$REPO/firmware/src/hdl/projects/pluto/system_top.xsa}"
BUILD="${BUILD:-$REPO/firmware/src/hdl/fsbl/build}"

[ -d "$ESW" ] || { echo "ERROR: no embeddedsw at $ESW (set ESW=, or run ./devkit setup)" >&2; exit 1; }
[ -r "$XSA" ] || { echo "ERROR: no hardware platform at $XSA" >&2; exit 1; }

# Every component the BSP is built from. `generic` is deliberately absent: its
# src/ is empty and nothing in libxil.a comes from it.
DRIVERS="coresightps_dcc cpu_cortexa9 ddrps devcfg dmaps emacps gpiops iic
         qspips scugic scutimer scuwdt sdps spi spips uartps usbps xadcps"

echo "=== staging into $BUILD ==="
rm -rf "$BUILD"
BSP="$BUILD/bsp/ps7_cortexa9_0"
mkdir -p "$BSP"/{include,lib} "$BUILD/app/src" "$BUILD/app/Debug"

# --- drivers: embeddedsw sources verbatim, then the generated config table -----
for d in $DRIVERS; do
    src="$ESW/XilinxProcessorIPLib/drivers/$d/src"
    [ -d "$src" ] || { echo "ERROR: $d missing from embeddedsw ($src)" >&2; exit 1; }
    mkdir -p "$BSP/libsrc/$d/src"
    cp -a "$src/." "$BSP/libsrc/$d/src/"
done

# --- the two software services ------------------------------------------------
for s in xilffs xilrsa; do
    src="$ESW/lib/sw_services/$s/src"
    [ -d "$src" ] || { echo "ERROR: $s missing from embeddedsw" >&2; exit 1; }
    mkdir -p "$BSP/libsrc/$s/src"
    cp -a "$src/." "$BSP/libsrc/$s/src/"
done

# --- standalone: Vitis FLATTENS this, so replay that from the manifest ---------
# The manifest records where each file came from in embeddedsw's per-architecture
# layout. It was derived by matching the xsct output file-by-file, not guessed:
# 88 of 91 matched, and the three that did not are the generated ones below.
mkdir -p "$BSP/libsrc/standalone/src"
while read -r rel; do
    [ -n "$rel" ] || continue
    [ -f "$ESW/lib/bsp/standalone/src/$rel" ] || { echo "ERROR: standalone/$rel missing from embeddedsw" >&2; exit 1; }
    cp "$ESW/lib/bsp/standalone/src/$rel" "$BSP/libsrc/standalone/src/$(basename "$rel")"
done < "$FSBL_DIR/standalone-manifest.txt"
cp -a "$ESW/lib/bsp/standalone/src/profile" "$BSP/libsrc/standalone/src/" 2>/dev/null || true
cp "$FSBL_DIR/generated/standalone-Makefile" "$BSP/libsrc/standalone/src/Makefile"
cp "$FSBL_DIR/generated/config.make"         "$BSP/libsrc/standalone/src/config.make"

# --- overlay everything that describes THIS design ----------------------------
cp "$FSBL_DIR/generated/xparameters.h" "$FSBL_DIR/generated/bspconfig.h" "$BSP/include/"
cp "$FSBL_DIR/generated/bspconfig.h" "$FSBL_DIR/generated/inbyte.c" \
   "$FSBL_DIR/generated/outbyte.c"   "$BSP/libsrc/standalone/src/"
for g in "$FSBL_DIR"/generated/config/*_g.c; do
    b=$(basename "$g"); base=${b%_g.c}
    # Most tables are x<driver>_g.c (xuartps_g.c -> uartps), but not all:
    # xadcps_g.c belongs to the driver named xadcps. Try the name as written
    # first, then with the leading x removed, rather than assuming either.
    drv=""
    for cand in "$base" "${base#x}"; do
        [ -d "$BSP/libsrc/$cand/src" ] && { drv="$cand"; break; }
    done
    [ -n "$drv" ] || { echo "ERROR: no driver directory for $b (tried '$base' and '${base#x}')" >&2; exit 1; }
    cp "$g" "$BSP/libsrc/$drv/src/$b"
done

# --- the application ----------------------------------------------------------
cp -a "$ESW/lib/sw_apps/zynq_fsbl/src/." "$BUILD/app/src/"
# ps7_init is the DDR and pad bring-up for this exact board. It is design output,
# lives in the platform, and must never be committed or cached.
unzip -o -j "$XSA" ps7_init.c ps7_init.h -d "$BUILD/app/src/" >/dev/null
cp "$FSBL_DIR/generated/Xilinx.spec" "$BUILD/app/Debug/"
cp "$FSBL_DIR/generated/bsp-Makefile" "$BUILD/bsp/Makefile"

echo "  drivers      : $(echo $DRIVERS | wc -w)"
echo "  standalone   : $(ls "$BSP/libsrc/standalone/src"/*.c "$BSP/libsrc/standalone/src"/*.S 2>/dev/null | wc -l) sources"
echo "  app          : $(ls "$BUILD/app/src"/*.c "$BUILD/app/src"/*.S 2>/dev/null | wc -l) sources"
echo "  ps7_init.c   : $(wc -c < "$BUILD/app/src/ps7_init.c" | tr -d '[:space:]') bytes from the XSA"
echo "staged."
