#!/bin/bash
# Run a devkit command inside the pinned Vivado 2022.2 environment.
#
#   ./devkit container build-image        build (or rebuild) the image
#   ./devkit container doctor             run ./devkit doctor inside it
#   ./devkit container build --hdl-only   run a build inside it
#   ./devkit container shell              an interactive shell inside it
#
# Vivado itself is not in the image. /tools/Xilinx is bind-mounted read-only,
# which keeps the image about 1 GB instead of 45 and means the toolchain you
# test is the toolchain you already have.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${DEVKIT_IMAGE:-fishball7020-build:2022.2}"
XILINX_DIR="${XILINX_DIR:-/tools/Xilinx}"
# Vivado writes ~/.Xilinx; give it somewhere that persists between runs without
# putting container state in the host's home directory.
CHOME="$HERE/firmware/.container-home"

runtime() {
    if   command -v podman >/dev/null 2>&1; then echo podman
    elif command -v docker >/dev/null 2>&1; then echo docker
    else echo "ERROR: neither podman nor docker found" >&2; exit 1; fi
}
RT="$(runtime)"

if [ "${1:-}" = "build-image" ]; then
    exec "$RT" build -t "$IMAGE" -f "$HERE/tools/container/Containerfile" "$HERE/tools/container"
fi

if ! "$RT" image exists "$IMAGE" 2>/dev/null && ! "$RT" image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "ERROR: image '$IMAGE' not built yet - run: ./devkit container build-image" >&2
    exit 1
fi
if [ ! -d "$XILINX_DIR" ]; then
    echo "ERROR: $XILINX_DIR not found on the host (set XILINX_DIR)" >&2
    exit 1
fi

mkdir -p "$CHOME"

# The repo is mounted at ITS OWN absolute path, not at /work. Vivado stores
# absolute paths inside pluto.xpr, so a project created on the host and one
# created in the container are only interchangeable if the path matches. Get
# this wrong and --hdl-only silently rebuilds against a project it cannot find.
# /run/udev is mounted because Vivado's licence manager fingerprints the host
# through libudev. With no udev database in the container,
# udev_enumerate_scan_devices() returns a pointer that malloc_usable_size()
# then underflows on, and Vivado dies mid-synthesis with
# "tcmalloc: large alloc 115875935977472 bytes" and a SIGSEGV whose stack
# names neither udev nor licensing. Read-only is enough; it only reads.
ARGS=(
    --rm
    -v "$HERE:$HERE"
    -v "$XILINX_DIR:$XILINX_DIR:ro"
    -v "$CHOME:/home/builder"
    -v /run/udev:/run/udev:ro
    -e HOME=/home/builder
    -w "$HERE"
)
# Rootless podman already maps the container's root to the invoking user, so
# files land owned by you without --userns=keep-id. Leaving keep-id off also
# avoids the permission oddities it creates inside bind mounts, and Vivado got
# measurably further without it. Docker has no such mapping and must be told.
if [ "$RT" != podman ]; then ARGS+=(--user "$(id -u):$(id -g)"); fi

# Pass the display through when there is one, so the block design can be opened
# in the container too. Without it, build_all.sh falls back to Xvfb by itself.
if [ -n "${DISPLAY:-}" ] && [ -S /tmp/.X11-unix/X"${DISPLAY#*:}" ] 2>/dev/null; then
    ARGS+=(-e "DISPLAY=$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix)
elif [ -n "${DISPLAY:-}" ]; then
    ARGS+=(-e "DISPLAY=$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix)
fi

# -t only when there really is a terminal. Asking for one when stdin is a pipe
# (a script, CI, an agent) makes podman block with no output at all, which
# looks exactly like the build hanging.
TTY=()
[ -t 0 ] && TTY=(-i -t)

if [ "${1:-}" = "shell" ]; then
    shift
    exec "$RT" run "${TTY[@]}" "${ARGS[@]}" "$IMAGE" bash "$@"
fi

exec "$RT" run "${TTY[@]}" "${ARGS[@]}" "$IMAGE" ./devkit "$@"
