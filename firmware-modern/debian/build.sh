#!/bin/bash
# Build the Debian armhf root filesystem for this board, as a tarball.
#
#     # run from: the repo root
#     ./devkit build --target modern --rootfs-only    # writes rootfs.tar
#
# Needs podman, or docker with its buildx plugin, and armhf emulation registered
# with the kernel (on macOS: Colima, which registers it in its VM). If
# the emulation is missing, this registers it by itself from a container
# (tonistiigi/binfmt), which needs a rootful runtime: docker, or sudo podman.
# Rootless podman cannot, so install it from your distro instead:
#     Debian/Ubuntu:  sudo apt install qemu-user-static binfmt-support
#     Arch:           sudo pacman -S qemu-user-static qemu-user-static-binfmt
#
# This does NOT touch any SD card. write-card.sh does that, separately and
# deliberately, because the two failure modes are completely different: a bad
# tarball wastes ten minutes, a bad card write costs a card-reader trip.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE=fishball-debian-armhf
OUT="$HERE/rootfs.tar"

# The same choice as tools/container/run.sh makes: DEVKIT_RUNTIME if it is set;
# otherwise podman before docker, and on macOS docker first (Colima).
if [ -n "${DEVKIT_RUNTIME:-}" ]; then
    RT=$(command -v "$DEVKIT_RUNTIME") || { echo "ERROR: DEVKIT_RUNTIME=$DEVKIT_RUNTIME, but there is no such command" >&2; exit 1; }
elif [ "$(uname -s)" = Darwin ]; then
    RT=$(command -v docker || command -v podman) || { echo "need docker or podman" >&2; exit 1; }
else
    RT=$(command -v podman || command -v docker) || { echo "need podman or docker" >&2; exit 1; }
fi

armhf_ok() {
    "$RT" run --rm --platform linux/arm/v7 docker.io/arm32v7/debian:trixie \
        /bin/true 2>/dev/null
}

if ! armhf_ok; then
    echo "=== no armhf emulation on the kernel; registering it from a container ==="
    # Registers a qemu-arm binfmt_misc handler (persistent "F" flag, so it
    # keeps working for containers after this helper exits). Needs a rootful
    # runtime: plain docker as a user in the docker group, or sudo podman.
    # (Contributed by @MrMati, #9.)
    if "$RT" run --privileged --rm docker.io/tonistiigi/binfmt --install arm \
            && armhf_ok; then
        echo "=== armhf emulation ready ==="
    else
        echo "ERROR: cannot run armhf containers, and automatic registration" >&2
        echo "       via tonistiigi/binfmt did not take (rootless podman cannot)." >&2
        echo "       Install the emulation from your distro, then retry:" >&2
        echo "           Debian/Ubuntu:  sudo apt install qemu-user-static binfmt-support" >&2
        echo "           Arch:           sudo pacman -S qemu-user-static qemu-user-static-binfmt" >&2
        exit 1
    fi
fi

echo "=== building $IMAGE (armhf, under emulation - this is slow) ==="
# What this build is, for /opt/VERSIONS inside the image. The container cannot
# reach the host's git, so it is computed here and passed in. `|| echo unknown`
# because a tarball download with no .git must still build.
FW_VERSION="$(cd "$HERE" && git describe --abbrev=8 --dirty --always --tags 2>/dev/null || echo unknown)"
echo "=== building $IMAGE  (device-fw $FW_VERSION) ==="

# podman: build the image, then export a container made from it. A podman
# container that was never started carries the image's own files, so what
# comes out is the image.
#
# docker: NOT that. docker lays its own empty /etc/hostname, /etc/hosts and
# /etc/resolv.conf over every container it creates, and `docker export` writes
# those placeholders, not the image's files - a card written from the result
# boots a board with no name (found building a release on 2026-11-21). So with
# docker the build itself writes the tarball: BuildKit's tar exporter emits the
# image's filesystem directly, with no container in between.
rm -f "$OUT.part"
trap 'rm -f "$OUT.part"' EXIT
if [ "$(basename "$RT")" = docker ]; then
    "$RT" buildx version >/dev/null 2>&1 || {
        echo "ERROR: docker has no buildx plugin, and without it the root cannot be" >&2
        echo "       exported correctly (see the comment in this script)." >&2
        echo "           macOS:          brew install docker-buildx   (and follow its caveat)" >&2
        echo "           Debian/Ubuntu:  sudo apt install docker-buildx-plugin   (or docker-buildx)" >&2
        exit 1; }
    "$RT" buildx build --platform linux/arm/v7 --build-arg "FW_VERSION=$FW_VERSION" \
          -f "$HERE/Containerfile" --output "type=tar,dest=$OUT.part" "$HERE"
else
    "$RT" build --platform linux/arm/v7 --build-arg "FW_VERSION=$FW_VERSION" \
          -t "$IMAGE" -f "$HERE/Containerfile" "$HERE"

    echo "=== exporting the root filesystem ==="
    cid=$("$RT" create --platform linux/arm/v7 "$IMAGE" /bin/true)
    trap '"$RT" rm -f "$cid" >/dev/null 2>&1 || true; rm -f "$OUT.part"' EXIT
    "$RT" export "$cid" > "$OUT.part"
fi

# Whichever way it was made: an empty /etc/hostname means the runtime's
# placeholders got in after all. Refuse it here rather than on a board.
# /etc/resolv.conf is the third placeholder: the released root has one with two
# nameservers in it (from the base image), so an empty one is the same fault.
if [ -z "$(tar xOf "$OUT.part" etc/hostname 2>/dev/null || tar xOf "$OUT.part" ./etc/hostname 2>/dev/null)" ] \
   || [ -z "$(tar xOf "$OUT.part" etc/hosts 2>/dev/null || tar xOf "$OUT.part" ./etc/hosts 2>/dev/null)" ] \
   || [ -z "$(tar xOf "$OUT.part" etc/resolv.conf 2>/dev/null || tar xOf "$OUT.part" ./etc/resolv.conf 2>/dev/null)" ]; then
    echo "ERROR: the exported root has an empty /etc/hostname, /etc/hosts or /etc/resolv.conf -" >&2
    echo "       this runtime ($RT) exported its own placeholders instead of the image's files." >&2
    echo "       $OUT is left as it was." >&2
    exit 1
fi
mv -f "$OUT.part" "$OUT"

echo
echo "  $OUT  $(du -h "$OUT" | cut -f1)"
echo "  $(tar tf "$OUT" | wc -l) entries"
echo
echo "Next: sudo ./devkit write-card --target modern /dev/sdX"
echo "      (it shows you what it is about to do, and refuses anything that is"
echo "      not removable)"
