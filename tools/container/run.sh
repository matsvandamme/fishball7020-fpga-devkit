#!/bin/bash
# Run a devkit command inside the pinned Vivado 2022.2 environment.
#
#   ./devkit container build-image        build (or rebuild) the image
#   ./devkit container install <bin>      install Vivado 2022.2 itself, inside
#                                         the container, onto the host
#   ./devkit container doctor             run ./devkit doctor inside it
#   ./devkit container build --target factory --hdl-only
#                                         run a build inside it
#   ./devkit container shell              an interactive shell inside it
#
# Vivado itself is not in the image. /tools/Xilinx is mounted read-only, which
# keeps the image about 1 GB instead of 45 and means the toolchain you test is
# the toolchain you already have.
#
# ---- macOS (Apple Silicon, Docker through Colima) ----------------------------
#
# The same commands work there, with three differences this script takes care of:
#
#   1. TWO IMAGES. Vivado is x86-64 only, so anything that can run it (install,
#      and every command given --target factory) uses a linux/amd64 image, run
#      under Rosetta. Everything else - the modern target - uses a native arm64
#      image. build-image builds the one the rest of the command line needs:
#          ./devkit container build-image                    # arm64, modern
#          ./devkit container build-image --target factory   # amd64, Vivado
#      DEVKIT_CONTAINER_ARCH=amd64|arm64 overrides the choice (for `shell`, say).
#
#   2. SOURCES IN DOCKER VOLUMES. firmware/src, firmware-modern/src and
#      firmware-modern/boot are named volumes mounted over those paths, not
#      directories on the Mac's disk: the Linux kernel tree has file names that
#      differ only in case, which a default APFS volume cannot hold, and a build
#      through the VM's file sharing is several times slower. The outputs
#      (firmware/output, firmware-modern/output) are NOT in a volume, so they land
#      on the Mac's disk. The volumes are named <prefix>-fsrc, -src, -boot and
#      -home; the prefix is fbmac-<8 hex digits of this checkout's path>, or
#      DEVKIT_VOLUME_PREFIX. firmware-modern/boot/pinned stays on the Mac, so
#      fetch-pinned-xsa.sh gives the same file inside and outside.
#
#   3. VIVADO IN A DOCKER VOLUME, for the same two reasons. XILINX_VOLUME names
#      it (default: fbmac-xilinx, used when it exists); it is mounted at
#      $XILINX_DIR, /tools/Xilinx. `./devkit container install` creates and fills
#      it. With no display on a Mac, run the installer in batch mode - the
#      arguments after the installer go to xsetup:
#          ./devkit container install ~/Downloads/Xilinx_Unified_2022.2_*.bin -b AuthTokenGen
#          ./devkit container install ~/Downloads/Xilinx_Unified_2022.2_*.bin \
#              -a XilinxEULA,3rdPartyEULA -b Install \
#              -c tools/container/vivado-2022.2-install_config.txt
#      The -a flag accepts AMD's licence agreements on your behalf, so read
#      them first. The Destination= line of that config file is /tools/Xilinx:
#      this script does not rewrite it, so edit it if XILINX_DIR is elsewhere.
#
# DEVKIT_RUNTIME=podman|docker picks the runtime; DEVKIT_CONTAINER_VOLUMES=1|0
# forces the volume layout on or off (default: on for macOS, off for Linux).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${DEVKIT_IMAGE:-fishball7020-build:2022.2}"
XILINX_DIR="${XILINX_DIR:-/tools/Xilinx}"
# Vivado writes ~/.Xilinx; give it somewhere that persists between runs without
# putting container state in the host's home directory.
CHOME="$HERE/firmware/.container-home"

HOST_OS="$(uname -s)"
case "$(uname -m)" in
    arm64|aarch64) HOST_ARCH=arm64 ;;
    x86_64|amd64)  HOST_ARCH=amd64 ;;
    *)             HOST_ARCH="$(uname -m)" ;;
esac

runtime() {
    if [ -n "${DEVKIT_RUNTIME:-}" ]; then
        command -v "$DEVKIT_RUNTIME" >/dev/null 2>&1 || {
            echo "ERROR: DEVKIT_RUNTIME=$DEVKIT_RUNTIME, but there is no such command" >&2; exit 1; }
        echo "$DEVKIT_RUNTIME"; return
    fi
    # docker first on macOS: it is the one this was proven with there (Colima).
    local order="podman docker"
    [ "$HOST_OS" = Darwin ] && order="docker podman"
    local r
    for r in $order; do
        if command -v "$r" >/dev/null 2>&1; then echo "$r"; return; fi
    done
    echo "ERROR: neither podman nor docker found" >&2
    [ "$HOST_OS" = Darwin ] && {
        echo "       On macOS:  brew install colima docker docker-buildx" >&2
        echo "                  colima start --vm-type vz --vz-rosetta --mount-type virtiofs \\" >&2
        echo "                      --cpu 8 --memory 16 --disk 120" >&2; }
    exit 1
}
RT="$(runtime)"

# Is the daemon there at all? On macOS the usual reason for every later command
# failing is a VM that is not running, and docker's own message about a socket
# path does not say so.
if [ "$HOST_OS" = Darwin ] && ! "$RT" info >/dev/null 2>&1; then
    echo "ERROR: $RT cannot reach its daemon - the Linux VM is probably not running." >&2
    echo "       colima start        (the first time: colima start --vm-type vz --vz-rosetta \\" >&2
    echo "                            --mount-type virtiofs --cpu 8 --memory 16 --disk 120)" >&2
    exit 1
fi

# ---- which image: the platform -------------------------------------------------
# On Linux, whatever the machine, and on an x86-64 Mac there is one image and no
# --platform, exactly as before. On Apple Silicon Vivado still needs x86-64, so
# there are two images and the command line decides. "Needs Vivado" is:
# install, or the factory target - by --target, or by DEVKIT_TARGET with no
# --target given. Setting DEVKIT_CONTAINER_ARCH asks for the same on any host.
#
# An image you name yourself (DEVKIT_IMAGE) is used under exactly that name:
# the -amd64/-arm64 suffix goes on the default name only.
want_arch() {
    case "${DEVKIT_CONTAINER_ARCH:-}" in
        amd64|arm64) echo "$DEVKIT_CONTAINER_ARCH"; return ;;
        "") ;;
        *) echo "ERROR: DEVKIT_CONTAINER_ARCH is amd64 or arm64, not '$DEVKIT_CONTAINER_ARCH'" >&2; exit 1 ;;
    esac
    local target="${DEVKIT_TARGET:-modern}" prev="" a
    [ "${1:-}" = install ] && target=factory
    for a in "$@"; do
        [ "$prev" = "--target" ] && target="$a"
        case "$a" in --target=*) target="${a#--target=}" ;; esac
        prev="$a"
    done
    if [ "$target" = factory ]; then echo amd64; else echo "$HOST_ARCH"; fi
}
PLATFORM=()
if [ -n "${DEVKIT_CONTAINER_ARCH:-}" ] || { [ "$HOST_OS" = Darwin ] && [ "$HOST_ARCH" != amd64 ]; }; then
    ARCH="$(want_arch "$@")"
    PLATFORM=(--platform "linux/$ARCH")
    [ -n "${DEVKIT_IMAGE:-}" ] || IMAGE="$IMAGE-$ARCH"
fi

if [ "${1:-}" = "build-image" ]; then
    exec "$RT" build ${PLATFORM[@]+"${PLATFORM[@]}"} -t "$IMAGE" \
        -f "$HERE/tools/container/Containerfile" "$HERE/tools/container"
fi

if ! "$RT" image exists "$IMAGE" 2>/dev/null && ! "$RT" image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "ERROR: image '$IMAGE' not built yet - run:" >&2
    if [ "${#PLATFORM[@]}" -gt 0 ] && [ "$ARCH" != "$HOST_ARCH" ]; then
        echo "           ./devkit container build-image --target factory" >&2
        echo "       (the x86-64 image, which is the one that can run Vivado)" >&2
    else
        echo "           ./devkit container build-image" >&2
    fi
    exit 1
fi
# On macOS the containers run in a VM that shares only part of the disk (Colima:
# your home directory). A path outside that part is mounted as an EMPTY
# directory, with no error, and what follows fails with something like
# "./devkit: no such file". So look, with a container that does nothing else.
# Only there: on Linux a bind mount is the directory itself.
require_shared() {    # FILE (absolute, on the host)
    [ "$HOST_OS" = Darwin ] || return 0
    local rc=0
    "$RT" run --rm ${PLATFORM[@]+"${PLATFORM[@]}"} -v "$(dirname "$1"):$(dirname "$1"):ro" "$IMAGE" \
        test -f "$1" </dev/null >/dev/null 2>&1 || rc=$?
    # 1 is test's own answer. Anything else is the runtime failing to start the
    # container at all, which the real command reports better than this can.
    [ "$rc" -eq 1 ] || return 0
    echo "ERROR: $1 is not visible inside the container." >&2
    echo "       On macOS the VM shares only part of the disk (Colima: your home" >&2
    echo "       directory). Put it somewhere under that, or share its directory" >&2
    echo "       with the VM (Colima: colima start --mount ...)." >&2
    exit 1
}
[ "${1:-}" = install ] || require_shared "$HERE/devkit"

# -t only when there really is a terminal. Asking for one when stdin is a pipe
# (a script, CI, an agent) makes podman block with no output at all, which
# looks exactly like the build hanging.
#
# Expanded as ${TTY[@]+"${TTY[@]}"} everywhere: macOS ships bash 3.2, where a
# plain "${TTY[@]}" on an EMPTY array is "unbound variable" under set -u.
TTY=()
[ -t 0 ] && TTY=(-i -t)

# ---- macOS: named volumes instead of directories on the host's disk ------------
VOLMODE="${DEVKIT_CONTAINER_VOLUMES:-}"
if [ -z "$VOLMODE" ]; then
    if [ "$HOST_OS" = Darwin ]; then VOLMODE=1; else VOLMODE=0; fi
fi
# docker has no user mapping, so it is told who you are; rootless podman maps the
# container's root to you by itself. See the long comment further down.
USERARGS=()
if [ "$RT" != podman ]; then
    # USER and LOGNAME go with the uid: it has no passwd entry in the image, and
    # Vivado, its installer and git all ask who you are.
    USERARGS=(--user "$(id -u):$(id -g)" -e USER=builder -e LOGNAME=builder)
    # ...and a passwd entry, because asking is not always enough: ssh refuses
    # outright ("No user exists for uid 501"), which took `./devkit container
    # shell` + ssh to the board away from every docker user. The image's own
    # /etc/passwd with one line added would need a container run to read, so
    # this is the few accounts a build container uses, written beside the
    # container's home on the host and mounted over the image's file.
    if [ "$(id -u)" -ne 0 ]; then
        mkdir -p "$CHOME"
        _pw="$CHOME/.passwd-$(id -u)-$(id -g)"
        [ -s "$_pw" ] || printf '%s\n' \
            'root:x:0:0:root:/root:/bin/bash' \
            '_apt:x:100:65534::/nonexistent:/usr/sbin/nologin' \
            'nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin' \
            "builder:x:$(id -u):$(id -g):builder:/home/builder:/bin/bash" > "$_pw"
        USERARGS+=(-v "$_pw:/etc/passwd:ro")
    fi
fi

# A named volume starts out owned by root, and the build does not run as root.
# Create it and hand its top directory to the building user, once. An existing
# volume is taken as it is. Called from this shell, never from $( ): it exits.
ensure_volume() {    # NAME
    "$RT" volume inspect "$1" >/dev/null 2>&1 && return 0
    "$RT" volume create "$1" >/dev/null
    [ "$RT" = podman ] && return 0
    "$RT" run --rm ${PLATFORM[@]+"${PLATFORM[@]}"} --user 0:0 -v "$1:/v" "$IMAGE" \
        chown "$(id -u):$(id -g)" /v && return 0
    # Left as it is, the next run would take the root-owned volume as it found
    # it and every write into it would fail. It was created a moment ago, by
    # this run, and is empty: remove it, so that the next run starts over.
    "$RT" volume rm "$1" >/dev/null 2>&1 || true
    echo "ERROR: could not hand the new $RT volume '$1' to uid $(id -u) - removed it again." >&2
    echo "       The line above is ${RT}'s reason. The next run creates it afresh." >&2
    exit 1
}
if [ "$VOLMODE" = 1 ]; then
    VP="${DEVKIT_VOLUME_PREFIX:-fbmac-$(printf '%s' "$HERE" | cksum | awk '{printf "%08x", $1}')}"
    HOMESRC="$VP-home"
    ensure_volume "$HOMESRC"
else
    HOMESRC="$CHOME"
fi
# Vivado: a volume when one is named (or, in the volume layout, when the default
# one exists), otherwise the directory on the host.
XVOL="${XILINX_VOLUME:-}"
if [ -z "$XVOL" ] && [ "$VOLMODE" = 1 ]; then
    if [ "${1:-}" = install ] || "$RT" volume inspect fbmac-xilinx >/dev/null 2>&1; then XVOL=fbmac-xilinx; fi
fi
# A display the container can actually use. On Linux that is the X socket. On
# macOS $DISPLAY is a launchd socket path that means nothing inside the VM; only
# a host:display form (XQuartz listening on TCP) is passed on, and no socket.
DISPLAYARGS=()
if [ -n "${DISPLAY:-}" ]; then
    if [ "$HOST_OS" = Darwin ]; then
        case "$DISPLAY" in /*|:*) ;; *) DISPLAYARGS=(-e "DISPLAY=$DISPLAY") ;; esac
    else
        DISPLAYARGS=(-e "DISPLAY=$DISPLAY" -v /tmp/.X11-unix:/tmp/.X11-unix)
    fi
fi

if [ "${1:-}" = "install" ]; then
    shift
    BIN="${1:-}"
    # Drop the installer path too, so "$@" below is only the extra arguments
    # meant for xsetup - otherwise the installer path is passed to it twice.
    [ $# -gt 0 ] && shift
    if [ -z "$BIN" ] || [ ! -f "$BIN" ]; then
        echo "usage: ./devkit container install /path/to/Xilinx_Unified_2022.2_*.bin [xsetup arguments]" >&2
        echo "Download it from AMD first - it is behind an account login, so" >&2
        echo "this cannot fetch it for you." >&2
        exit 2
    fi
    require_shared "$(cd "$(dirname "$BIN")" && pwd)/$(basename "$BIN")"
    # The bootstrap problem this solves: the container exists because the host
    # is too new to run Vivado 2022.2, and the Xilinx installer is the same
    # Java/GTK application with the same requirements. So it runs in here too,
    # writing OUT to the host through a read-write mount - the one time
    # $XILINX_DIR is not mounted read-only.
    if [ -n "$XVOL" ]; then
        # Into a volume: created here if it is not there, and owned by you, so
        # the installer runs as you exactly as it does on Linux.
        ensure_volume "$XVOL"
        XSRC="$XVOL"
        echo "Installing into the $RT volume '$XVOL', mounted at $XILINX_DIR."
    else
        if [ ! -d "$XILINX_DIR" ] || [ ! -w "$XILINX_DIR" ]; then
            echo "ERROR: $XILINX_DIR must exist and be writable by you." >&2
            echo "Rootless podman maps the container's root to your own user, so a" >&2
            echo "root-owned directory cannot be written even from 'root' inside." >&2
            echo "  sudo mkdir -p $XILINX_DIR && sudo chown \"$USER\" $XILINX_DIR" >&2
            exit 1
        fi
        XSRC="$XILINX_DIR"
    fi
    [ "$VOLMODE" = 1 ] || mkdir -p "$CHOME"
    BIN_DIR="$(cd "$(dirname "$BIN")" && pwd)"
    # The installer's directory, read-only - unless it IS the repo, which is
    # mounted two lines further down: the same path twice is an error to podman.
    BINMOUNT=(-v "$BIN_DIR:$BIN_DIR:ro")
    [ "$BIN_DIR" = "$HERE" ] && BINMOUNT=()
    # Extract explicitly, then run xsetup from where it landed. Two ways this
    # goes wrong, both reported as a bare "Extraction failed":
    #   - running the .bin in place, because it unpacks relative to the working
    #     directory and the directory holding the installer is read-only here;
    #   - unpacking onto the container's own overlay (/tmp), which rootless
    #     podman mounts with userxattr and which the installer's tar does not
    #     survive - despite having the whole disk free.
    # A bind mount (or a volume) is neither, so the work directory is one of those.
    #
    # The repo is mounted read-only, at its own path and as the working
    # directory's neighbour, so that `-c tools/container/...install_config.txt`
    # can be given as it is typed on the host: a relative path among xsetup's
    # arguments that names a file in the repo is made absolute.
    XARGS=()
    for _a in "$@"; do
        case "$_a" in
            /*) ;;
            *)  if [ -f "$PWD/$_a" ]; then _a="$PWD/$_a"; elif [ -f "$HERE/$_a" ]; then _a="$HERE/$_a"; fi ;;
        esac
        XARGS+=("$_a")
    done
    exec "$RT" run ${TTY[@]+"${TTY[@]}"} --rm ${PLATFORM[@]+"${PLATFORM[@]}"} \
        ${USERARGS[@]+"${USERARGS[@]}"} \
        -v "$XSRC:$XILINX_DIR" \
        ${BINMOUNT[@]+"${BINMOUNT[@]}"} \
        -v "$HERE:$HERE:ro" \
        -v "$HOMESRC:/home/builder" -e HOME=/home/builder \
        ${DISPLAYARGS[@]+"${DISPLAYARGS[@]}"} \
        -w /home/builder "$IMAGE" bash -c '
            dest="$1"; bin="$2"; shift 2
            [ -f "$bin" ] || { echo "ERROR: $bin is not visible inside the container." >&2; exit 1; }
            [ -w "$dest" ] || {
                echo "ERROR: $dest is not writable by uid $(id -u) inside the container." >&2
                echo "       An existing volume made by root? Name a new one: XILINX_VOLUME=..." >&2
                exit 1; }
            # Extracted once per installer and kept: the batch install is two or
            # three runs of xsetup (AuthTokenGen, then Install), and unpacking
            # 720 MB before each one helps nobody.
            tag="$(basename "$bin") $(wc -c < "$bin" | tr -d " ")"
            if [ -x /home/builder/installer/xsetup ] && [ "$(cat /home/builder/installer/.devkit-from 2>/dev/null)" = "$tag" ]; then
                echo "Using the installer extracted earlier."
            else
                echo "Extracting the installer (about 720 MB, once)..."
                rm -rf /home/builder/installer
                mkdir -p /home/builder/installer
                # Its exit code is not worth believing. The self-extractor trips
                # its own signal trap on the way out and reports "Extraction
                # failed." with status 143 having extracted everything correctly,
                # so check for the thing we came for instead.
                bash "$bin" --noexec --target /home/builder/installer >/dev/null 2>&1 || true
                if [ ! -x /home/builder/installer/xsetup ]; then
                    echo "ERROR: extraction really did fail - no xsetup produced." >&2
                    exit 1
                fi
                printf "%s\n" "$tag" > /home/builder/installer/.devkit-from
            fi
            cd /home/builder/installer
            exec ./xsetup "$@"
        ' _ "$XILINX_DIR" "$BIN_DIR/$(basename "$BIN")" ${XARGS[@]+"${XARGS[@]}"}
fi

# Vivado is mounted only when it exists. It used to be REQUIRED for every container
# command, which made the container useless to exactly the people it most helps:
# the modern target has no Vivado path at all, and on a machine with no ARM Linux
# cross-compiler the container is how it builds (#9). A command that genuinely
# needs Vivado - a factory build without --xsa - still stops in its own preflight,
# with a message about Vivado rather than about this directory.
#
# Whether Vivado is really IN there is that preflight's question, asked inside
# the container (build_all.sh and doctor.sh test $XILINX_DIR/Vivado/2022.2/bin/
# vivado). Asking the host's filesystem is wrong the moment Vivado lives in a
# volume, which on macOS is the only place it can live.
HAVE_XILINX=0; XSRC=""
if [ -n "$XVOL" ]; then
    if "$RT" volume inspect "$XVOL" >/dev/null 2>&1; then
        HAVE_XILINX=1; XSRC="$XVOL"
    else
        echo "note: XILINX_VOLUME=$XVOL, but there is no such $RT volume - running without Vivado." >&2
        echo "      ./devkit container install <installer.bin> creates and fills it." >&2
    fi
elif [ -d "$XILINX_DIR" ]; then
    HAVE_XILINX=1; XSRC="$XILINX_DIR"
elif [ "${#PLATFORM[@]}" -eq 0 ] || [ "$ARCH" = amd64 ]; then
    # Said only where Vivado could run at all: on the arm64 image it never can,
    # and the modern target that image is for never asks.
    echo "note: $XILINX_DIR not found - running without Vivado. Fine for --xsa and" >&2
    echo "      --target modern builds; a factory build from source needs Vivado" >&2
    echo "      (./devkit container install <installer.bin>)." >&2
fi
# x86-64 Vivado in an arm64 container cannot run; do not offer it.
if [ "$HAVE_XILINX" -eq 1 ] && [ "${#PLATFORM[@]}" -gt 0 ] && [ "$ARCH" != amd64 ]; then HAVE_XILINX=0; fi

[ "$VOLMODE" = 1 ] || mkdir -p "$CHOME"

# The repo is mounted at ITS OWN absolute path, not at /work. Vivado stores
# absolute paths inside pluto.xpr, so a project created on the host and one
# created in the container are only interchangeable if the path matches. Get
# this wrong and --hdl-only silently rebuilds against a project it cannot find.
# XILINX_DIR is passed in as well as mounted: doctor.sh, build_all.sh and
# env-vivado.sh read it to find Vivado, so mounting alone would leave them
# looking at /tools/Xilinx inside a container that has no such directory.
ARGS=(
    --rm
    -v "$HERE:$HERE"
    -e "XILINX_DIR=$XILINX_DIR"
    -v "$HOMESRC:/home/builder"
    -e HOME=/home/builder
    -w "$HERE"
)
# /run/udev is mounted because Vivado's licence manager fingerprints the host
# through libudev. With no udev database in the container,
# udev_enumerate_scan_devices() returns a pointer that malloc_usable_size()
# then underflows on, and Vivado dies mid-synthesis with
# "tcmalloc: large alloc 115875935977472 bytes" and a SIGSEGV whose stack
# names neither udev nor licensing. Read-only is enough; it only reads.
# Only where there is one: macOS has no /run/udev, and the image's libudev stub
# (udev-stub.c) is what actually keeps Vivado alive in either case.
[ -d /run/udev ] && ARGS+=(-v /run/udev:/run/udev:ro)
# A git WORKTREE keeps its history in the main checkout, outside this directory,
# and without it every `git describe` inside says "unknown" - which then goes
# into uEnv.txt as the build's name. Mount that one .git read-only, at its own
# path. A plain clone has it inside the repo and needs nothing.
_gcd="$(git -C "$HERE" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true)"
case "$_gcd" in
    ""|"$HERE"/*) ;;
    /*) [ -d "$_gcd" ] && ARGS+=(-v "$_gcd:$_gcd:ro") ;;
esac
# The ./devkit inside must pick the same default target as the one outside.
[ -n "${DEVKIT_TARGET:-}" ] && ARGS+=(-e "DEVKIT_TARGET=$DEVKIT_TARGET")
[ "$HAVE_XILINX" -eq 1 ] && ARGS+=(-v "$XSRC:$XILINX_DIR:ro")

if [ "$VOLMODE" = 1 ]; then
    # The three source trees, as volumes over their own paths. Each directory is
    # made on the host first (so it is yours, not root's), with a note in it:
    # an empty firmware/src on the Mac is otherwise a puzzle.
    for _pair in "fsrc:firmware/src" "src:firmware-modern/src" "boot:firmware-modern/boot"; do
        _vol="$VP-${_pair%%:*}"; _dir="$HERE/${_pair#*:}"
        ensure_volume "$_vol"
        mkdir -p "$_dir"
        [ -e "$_dir/IN-A-DOCKER-VOLUME.txt" ] || cat > "$_dir/IN-A-DOCKER-VOLUME.txt" <<EOF
On this machine the contents of this directory are in the $RT volume
    $_vol
which ./devkit container mounts here, inside the container. Look at them with
    ./devkit container shell
See the top of tools/container/run.sh for why.
EOF
        ARGS+=(-v "$_vol:$_dir")
    done
    # firmware-modern/boot/pinned stays on the host, mounted over the volume:
    # fetch-pinned-xsa.sh writes the release XSA there, and it has to be the same
    # file whether it ran outside (as the docs' build command does) or inside.
    mkdir -p "$HERE/firmware-modern/boot/pinned"
    ARGS+=(-v "$HERE/firmware-modern/boot/pinned:$HERE/firmware-modern/boot/pinned")
fi

# --xsa FILE: resolve it HERE, against the directory you typed it in, and mount the
# directory it lives in if that is outside the repo. The container sees only the
# repo, and works from its root, so both "--xsa ~/fishball-platform.xsa" - the
# location the docs themselves use - and a relative path typed from a
# subdirectory used to fail inside it with "cannot read". Read-only: the build
# only reads the platform.
_fwd=(); _takex=0
for _a in "$@"; do
    if [ "$_takex" -eq 1 ]; then
        _takex=0
        case "$_a" in /*) ;; *) _a="$PWD/$_a" ;; esac
    elif [ "$_a" = "--xsa" ]; then
        _takex=1
    else
        case "$_a" in --xsa=/*) ;; --xsa=*) _a="--xsa=$PWD/${_a#--xsa=}" ;; esac
    fi
    case "$_a" in
        --xsa=*) _x="${_a#--xsa=}" ;;
        /*.xsa)  _x="$_a" ;;
        *)       _x="" ;;
    esac
    if [ -n "$_x" ] && [ -f "$_x" ]; then
        # The FILE, read-only - not its directory: for ~/platform.xsa that would
        # hand the container all of $HOME, .ssh included.
        _xabs="$(cd "$(dirname "$_x")" && pwd)/$(basename "$_x")"
        case "$_xabs" in
            "$HERE"/firmware-modern/boot/pinned/*) ;;
            "$HERE"/firmware/src/*|"$HERE"/firmware-modern/src/*|"$HERE"/firmware-modern/boot/*)
                # In the volume layout these paths are volumes inside, so a file
                # that is there on the HOST has to be mounted to be seen.
                [ "$VOLMODE" = 1 ] && ARGS+=(-v "$_xabs:$_xabs:ro") ;;
            "$HERE"/*) ;;
            *) ARGS+=(-v "$_xabs:$_xabs:ro") ;;
        esac
    fi
    _fwd+=("$_a")
done
set -- ${_fwd[@]+"${_fwd[@]}"}
# Rootless podman already maps the container's root to the invoking user, so
# files land owned by you without --userns=keep-id. Leaving keep-id off also
# avoids the permission oddities it creates inside bind mounts, and Vivado got
# measurably further without it. Docker has no such mapping and must be told
# (USERARGS, set near the top).
[ "${#USERARGS[@]}" -gt 0 ] && ARGS+=("${USERARGS[@]}")
# Through a VM's file sharing (macOS) the repo's files appear inside under
# another owner than the user the build runs as - root, with Colima - and git
# then refuses the repository as "dubious ownership". Every `git describe` in
# the build would quietly say "unknown". Name this one repository as safe, for
# this container only; nothing is written to anybody's git configuration.
if [ "$VOLMODE" = 1 ]; then
    ARGS+=(-e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e "GIT_CONFIG_VALUE_0=$HERE")
fi

# Where the board is, resolved HERE and passed in.
#
# The container can reach the board perfectly well - TCP to iiod and ssh both
# work on the default network - but it cannot NAME it. A .local address is mDNS,
# the image has no nss-mdns and no avahi, so board_addr.py exhausts fishball.local
# and friends inside and falls through to its last candidate, the USB gadget at
# 192.168.2.1 - which is not connected when the board is on Ethernet. The result
# was doctor reporting "no board" with the board plainly up.
#
# So resolve on the host, where mDNS works, and hand the answer over. An explicit
# $BOARD is forwarded untouched; otherwise --check probes and we forward only an
# address that actually answered, leaving "no board" to mean what it says.
_board_at="${BOARD:-}"
if [ -z "$_board_at" ]; then
    _board_at="$(python3 "$HERE/tools/board_addr.py" --check 2>/dev/null)" || _board_at=""
fi
if [ -n "$_board_at" ]; then
    # Forward an ADDRESS, never a name. board_addr.py prefers names - that is
    # the point of it - but a name is exactly what cannot be looked up in here,
    # so resolve it on the way through. IPv4 on purpose: the container's default
    # network carries it, and the board's IPv6 is a global SLAAC address that
    # rootless podman does not route.
    #
    # getent where there is one; macOS has none, so Python's resolver (which
    # goes through the system's, mDNS included) does it there.
    _board_ip=""
    case "$_board_at" in
        *[!0-9.]*)
            if command -v getent >/dev/null 2>&1; then
                _board_ip="$(getent ahostsv4 "$_board_at" 2>/dev/null | awk 'NR==1{print $1}')" || _board_ip=""
            fi
            [ -n "$_board_ip" ] || _board_ip="$(python3 -c '
import socket, sys
try:
    print(socket.getaddrinfo(sys.argv[1], None, socket.AF_INET)[0][4][0])
except Exception:
    pass' "$_board_at" 2>/dev/null)" || _board_ip=""
            if [ -n "$_board_ip" ]; then
                # Keep the name working too, so ssh/scp inside a `container
                # shell` behave the way they do on the host.
                ARGS+=(-e "BOARD=$_board_ip" --add-host "$_board_at:$_board_ip")
            else
                # A name nothing here can resolve. Pass it on as it was given and
                # leave --add-host out: "name:name" is not a mapping, and docker
                # refuses to start the container over it.
                ARGS+=(-e "BOARD=$_board_at")
            fi ;;
        *)  ARGS+=(-e "BOARD=$_board_at") ;;      # already an address
    esac
fi

# Pass the display through when there is one, so the block design can be opened
# in the container too. Nothing in the build needs a display - it is Vivado's
# GUI or nothing, which is why the image carries GTK2 and no longer Xvfb.
[ "${#DISPLAYARGS[@]}" -gt 0 ] && ARGS+=("${DISPLAYARGS[@]}")

if [ "${1:-}" = "shell" ]; then
    shift
    exec "$RT" run ${TTY[@]+"${TTY[@]}"} ${PLATFORM[@]+"${PLATFORM[@]}"} "${ARGS[@]}" "$IMAGE" bash "$@"
fi

exec "$RT" run ${TTY[@]+"${TTY[@]}"} ${PLATFORM[@]+"${PLATFORM[@]}"} "${ARGS[@]}" "$IMAGE" ./devkit "$@"
