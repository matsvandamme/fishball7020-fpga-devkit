#!/bin/bash
# Download the factory release XSA that factory-xsa.pin names, and check its hash.
#
#     # run from: the repo root
#     ./firmware-modern/fetch-pinned-xsa.sh          # prints the path it wrote
#     ./devkit build --target modern --xsa "$(./firmware-modern/fetch-pinned-xsa.sh)"
#
# What a modern RELEASE is built from, and the easy answer to "which XSA?" for
# anyone without Vivado. The file lands in firmware-modern/boot/pinned/<tag>/, and
# is re-downloaded only if missing or if its hash is wrong. A hash mismatch is an
# error, never a warning: the XSA decides which FPGA design the board runs.
set -euo pipefail
FW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIN="$FW_DIR/factory-xsa.pin"
case "${1:-}" in -h|--help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;; esac
tag="$(sed -n 's/^tag=//p' "$PIN")"
want="$(sed -n 's/^sha256=//p' "$PIN")"
[ -n "$tag" ] && [ ${#want} -eq 64 ] || { echo "ERROR: $PIN needs tag= and a 64-hex sha256=" >&2; exit 1; }
REPO_SLUG="${FISHBALL_REPO:-matsvandamme/fishball7020-fpga-devkit}"
dest="$FW_DIR/boot/pinned/$tag/system_top.xsa"
have() { [ -f "$dest" ] && [ "$(sha256sum "$dest" | cut -d' ' -f1)" = "$want" ]; }
if ! have; then
    mkdir -p "$(dirname "$dest")"
    url="https://github.com/$REPO_SLUG/releases/download/$tag/system_top.xsa"
    echo "fetching $url" >&2
    curl -fsSL --retry 3 -o "$dest.part" "$url" || { rm -f "$dest.part"; echo "ERROR: could not download $url" >&2; exit 1; }
    got="$(sha256sum "$dest.part" | cut -d' ' -f1)"
    if [ "$got" != "$want" ]; then
        rm -f "$dest.part"
        echo "ERROR: $tag's system_top.xsa has sha256 $got, the pin says $want." >&2
        echo "       Either the release asset changed or the pin is wrong. Not using it." >&2
        exit 1
    fi
    mv "$dest.part" "$dest"
fi
echo "pinned: $tag  sha256 ${want:0:16}" >&2
echo "$dest"
