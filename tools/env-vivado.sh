# Source this instead of settings64.sh directly:
#   source tools/env-vivado.sh
#
# A default Ubuntu 22.04 install does not ship libtinfo5/libncurses5/libssl1.1, which
# Vivado 2022.2's bundled binaries require at runtime. This prepends
# locally-extracted copies of those libraries to LD_LIBRARY_PATH so
# Vivado can find them without touching the rest of the OS.
#
# Only when the system does not have them. The bundled copies were extracted
# on 22.04 and link against GLIBC_2.33, so forcing them onto an older
# distribution - Vivado 2022.2's own 20.04, say, or the build container -
# breaks Vivado with a confusing "librdi_commontasks.so: GLIBC_2.33 not found"
# that names the wrong library. Where the distro ships libtinfo.so.5 itself,
# use it.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if ! ldconfig -p 2>/dev/null | grep -q 'libtinfo\.so\.5'; then
    export LD_LIBRARY_PATH="$SCRIPT_DIR/legacy-libs/libs${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
fi
# Where Vivado/Vitis 2022.2 live. Override XILINX_DIR if you installed
# somewhere other than the default - the container build does exactly
# that to test against a throwaway installation.
XILINX_DIR="${XILINX_DIR:-/tools/Xilinx}"
source "$XILINX_DIR/Vivado/2022.2/settings64.sh"
export PATH="$PATH:$XILINX_DIR/Vitis/2022.2/bin"
