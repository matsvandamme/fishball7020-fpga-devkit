#!/usr/bin/env bash
# Build SDR++ with this board's PlutoSDR patch on a Mac, without installing
# anything system-wide.
#
#   tools/sdrpp/build-macos.sh                     build into ~/.cache/fishball-sdrpp
#   tools/sdrpp/build-macos.sh DIR                 build into DIR instead
#   tools/sdrpp/build-macos.sh --install-deps      brew install what is missing first
#   tools/sdrpp/build-macos.sh --clean [DIR]       delete the build trees and the prefix, then build
#
# then:   DIR/sdrpp        (a launcher; it prints its own path at the end)
#
# WHAT IT DOES, all of it idempotent so running it twice only rebuilds what
# changed:
#
#   1. checks Homebrew for cmake pkgconf fftw glfw volk portaudio zstd libusb
#      faad2 mpg123 and NAMES the missing ones; it installs them only with
#      --install-deps
#   2. builds libiio v0.26 and libad9361-iio v0.4.0 as plain dylibs into DIR/prefix
#   3. checks out SDR++ at the commit the PKGBUILD pins, applies
#      plutosdr-fishball.patch exactly as the PKGBUILD does (patch -p1), and
#      swaps in F4JTV's DAB+ decoder with welle.io inside it, also as the
#      PKGBUILD does; builds it, and installs it into DIR/prefix
#   4. writes DIR/sdrpp, which runs it with DIR/root as its config directory,
#      and gives that config a "DAB Decoder" panel once
#
# DIR must be new, empty, or a directory this script built in before: it leaves
# a file DIR/.fishball-sdrpp there, and without it a directory that has anything
# in it is refused, and so is --clean. This script deletes and overwrites inside
# DIR (--clean, and every re-patch of the SDR++ checkout), so it will not do
# that to a directory that was not its own.
#
# Nothing needs sudo and nothing lands in /usr/local, /Library or
# /Applications. Deleting DIR removes all of it. It needs about 200 MB, and
# 20 seconds on an 18-core Apple Silicon Mac (a few minutes on a small one).
#
# WHY libiio 0.26 AND NOT Homebrew's. The board runs libiio 0.26, and SDR++ and
# the patch are written against the 0.x API; libiio 1.0 is a different API.
# libad9361-iio's main branch moved to libiio 1.0 too, so that one is pinned to
# v0.4.0: the last tag for 0.x, and the first whose cmake can build a dylib
# instead of a framework (v0.3 cannot).
#
# WHY libiio IS BUILT WITH DNS-SD. SDR++'s device menu lists what libiio's scan
# finds. Over the network that scan is DNS-SD, so the board appears because it
# announces `_iio._tcp` (`dns-sd -B _iio._tcp` shows "iiod on fishball"), and
# on a network that drops mDNS it does not appear at all: type its address in
# the patch's Address field then. macOS answers DNS-SD itself; no Avahi is
# needed.
#
# THE ONE EDIT BESIDES THE PATCH. On macOS SDR++'s plutosdr_source/CMakeLists.txt
# links /Library/Frameworks/iio.framework by absolute path, which is where the
# libiio installer package puts it and where this script will not write. One
# line there is switched to the pkg-config branch Linux uses. The patch itself
# is applied unmodified.
#
# WHY THE LAUNCHER TOUCHES config.json. A module that is installed is loaded,
# but its panel exists only if config.json has an instance of it, and SDR++'s
# defaults have none for the DAB+ decoder: on Arch you add one in the Module
# Manager. The launcher adds "DAB Decoder" before SDR++ starts, once per config
# directory (DIR/root/.fishball-dab-added says it has), so removing it in the
# Module Manager stays removed. It is done at launch and not here because a
# running SDR++ writes its whole config back when it quits.
#
# ONE EDIT TO THE DAB+ DECODER TOO: five lines appended to its CMakeLists.txt,
# because clang refuses the -std=c++17 that SDR++ passes to its three C files.
#
# NOT BUILT: the sources that need a vendor library (Airspy, HackRF, RTL-SDR,
# ...). The audio sink is the PortAudio one, as in upstream's own macOS builds.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PATCH_FILE="$HERE/plutosdr-fishball.patch"

SDRPP_URL=https://github.com/AlexandreRouma/SDRPlusPlus.git
# The same commit as the Arch package: read from the PKGBUILD, so the two
# cannot drift apart.
SDRPP_COMMIT=$(sed -n 's/^_commit=//p' "$HERE/PKGBUILD")
DAB_URL=https://github.com/F4JTV/dab_decoder.git
DAB_COMMIT=$(sed -n 's/^_dabcommit=//p' "$HERE/PKGBUILD")
WELLE_URL=https://github.com/AlbrechtL/welle.io.git
WELLE_COMMIT=$(sed -n 's/^_wellecommit=//p' "$HERE/PKGBUILD")
LIBIIO_URL=https://github.com/analogdevicesinc/libiio.git
LIBIIO_COMMIT=a0eca0d2bf10326506fb762f0eec14255b27bef5      # tag v0.26
LIBAD9361_URL=https://github.com/analogdevicesinc/libad9361-iio.git
LIBAD9361_COMMIT=d9c7b1463a6c9c066bb5f7be6c3ec6e411351636   # tag v0.4.0
FORMULAE="cmake pkgconf fftw glfw volk portaudio zstd libusb faad2 mpg123"

INSTALL_DEPS=0; CLEAN=0; WORK=""
for a in "$@"; do
    case "$a" in
    --install-deps) INSTALL_DEPS=1 ;;
    --clean)        CLEAN=1 ;;
    -h|--help|help)
        sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option $a - see --help" >&2; exit 2 ;;
    *)  [ -z "$WORK" ] || { echo "one directory, not two: $WORK and $a" >&2; exit 2; }
        WORK="$a" ;;
    esac
done
WORK="${WORK:-${FISHBALL_SDRPP_DIR:-$HOME/.cache/fishball-sdrpp}}"

die() { echo "build-macos.sh: $*" >&2; exit 1; }

[ "$(uname -s)" = Darwin ] || die "this is the macOS build; on Arch use makepkg (see README.md)"
[ -n "$SDRPP_COMMIT" ] && [ -n "$DAB_COMMIT" ] && [ -n "$WELLE_COMMIT" ] \
    || die "no _commit=, _dabcommit= or _wellecommit= line in $HERE/PKGBUILD"
[ -r "$PATCH_FILE" ] || die "missing $PATCH_FILE"
xcode-select -p >/dev/null 2>&1 || die "no compiler: run  xcode-select --install"
command -v brew >/dev/null || die "Homebrew is not installed: see https://brew.sh"
BREW="$(brew --prefix)"

# 1 - the Homebrew formulae. Named, not installed, unless asked: a build script
# that changes what is installed on your Mac should have been told to.
missing=""
for f in $FORMULAE; do
    [ -d "$BREW/opt/$f" ] || missing="$missing $f"
done
if [ -n "$missing" ]; then
    if [ "$INSTALL_DEPS" = 1 ]; then
        echo "  brew install$missing"
        # shellcheck disable=SC2086
        HOMEBREW_NO_AUTO_UPDATE=1 brew install $missing
    else
        echo "missing Homebrew formulae:$missing" >&2
        echo >&2
        echo "      brew install$missing" >&2
        echo >&2
        die "install them, or run this again with --install-deps"
    fi
fi
export PATH="$BREW/bin:$PATH"

mkdir -p "$WORK"
WORK="$(cd "$WORK" && pwd)"
# The paths below are compiled into the binaries and written into shell and
# cmake command lines; a space in them breaks SDR++'s own build.
case "$WORK" in *[[:space:]]*) die "the directory must not contain spaces: $WORK" ;; esac
SRC="$WORK/src"; BUILD="$WORK/build"; PREFIX="$WORK/prefix"; ROOT="$WORK/root"
# Is this directory ours? Below, --clean deletes DIR/build and DIR/prefix, and a
# re-patch runs `git checkout -f` and `git clean -fdx` in DIR/src/SDRPlusPlus:
# in a directory somebody merely named, that is their own build, prefix or
# checkout. The marker is written on first use, into a directory that was
# empty. A directory built before the marker existed is recognised by the
# launcher this script wrote there, and gets its marker now.
MARKER="$WORK/.fishball-sdrpp"
if [ ! -e "$MARKER" ] && grep -qs 'Written by tools/sdrpp/build-macos.sh' "$WORK/sdrpp"; then
    echo "made by tools/sdrpp/build-macos.sh - it deletes and overwrites in here" > "$MARKER"
fi
if [ ! -e "$MARKER" ]; then
    [ "$CLEAN" = 0 ] || die "--clean: $WORK was not made by this script (no $MARKER) - nothing removed"
    [ -z "$(ls -A "$WORK")" ] \
        || die "$WORK is not empty and was not made by this script (no $MARKER) - name a new or empty directory"
    echo "made by tools/sdrpp/build-macos.sh - it deletes and overwrites in here" > "$MARKER"
fi
# Installing rewrites every library in the prefix, the ones a running SDR++ has
# loaded included, and macOS kills a process whose code changes under it.
if pgrep -f "$PREFIX/bin/sdrpp" >/dev/null 2>&1; then
    die "SDR++ from $PREFIX is running: quit it first, the build replaces the libraries it has loaded"
fi
if [ "$CLEAN" = 1 ]; then
    echo "  removing $BUILD and $PREFIX"
    rm -rf "$BUILD" "$PREFIX"
fi
mkdir -p "$SRC" "$BUILD" "$PREFIX"
JOBS="$(sysctl -n hw.ncpu)"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"

echo "  work dir: $WORK"

# fetch NAME URL COMMIT [force] - a clone at exactly that commit. With force,
# local edits to tracked files are thrown away and so is every file git does
# not track (patch's .orig and .rej, the DAB+ decoder copied in below), which
# is what makes re-patching repeatable. The checkout is this script's own: the
# marker above says so.
fetch() {
    local dir="$SRC/$1"
    [ -d "$dir/.git" ] || git clone -q "$2" "$dir"
    git -C "$dir" cat-file -e "$3^{commit}" 2>/dev/null || git -C "$dir" fetch -q --tags origin
    if [ "$(git -C "$dir" rev-parse HEAD)" != "$3" ] || [ "${4:-}" = force ]; then
        git -C "$dir" -c advice.detachedHead=false checkout -q -f "$3"
    fi
    if [ "${4:-}" = force ]; then git -C "$dir" clean -q -fdx; fi
}

# Common to all three: Release, into the prefix, and install names that are
# absolute paths into the prefix so nothing needs DYLD_LIBRARY_PATH.
# CMAKE_POLICY_VERSION_MINIMUM is what the PKGBUILD passes too: these projects
# declare a cmake older than cmake 4 accepts.
cmake_common=(
    -DCMAKE_BUILD_TYPE=Release
    -DCMAKE_INSTALL_PREFIX="$PREFIX"
    -DCMAKE_PREFIX_PATH="$PREFIX;$BREW"
    -DCMAKE_INSTALL_NAME_DIR="$PREFIX/lib"
    -DCMAKE_INSTALL_RPATH="$PREFIX/lib"
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5
)

# 2a - libiio 0.26: network (with DNS-SD), USB and XML backends, as a dylib.
# OSX_FRAMEWORK=OFF is what keeps it out of /Library/Frameworks.
echo "  libiio v0.26"
fetch libiio "$LIBIIO_URL" "$LIBIIO_COMMIT"
cmake -S "$SRC/libiio" -B "$BUILD/libiio" "${cmake_common[@]}" \
    -DOSX_FRAMEWORK=OFF -DOSX_PACKAGE=OFF \
    -DWITH_NETWORK_BACKEND=ON -DHAVE_DNS_SD=ON -DWITH_XML_BACKEND=ON \
    -DWITH_USB_BACKEND=ON -DWITH_SERIAL_BACKEND=OFF -DWITH_ZSTD=OFF \
    -DWITH_TESTS=ON -DWITH_EXAMPLES=OFF -DWITH_DOC=OFF -DWITH_MAN=OFF \
    -DENABLE_PACKAGING=OFF >"$BUILD/libiio.cmake.log" 2>&1 \
    || { tail -30 "$BUILD/libiio.cmake.log" >&2; die "libiio did not configure (full log: $BUILD/libiio.cmake.log)"; }
cmake --build "$BUILD/libiio" -j "$JOBS" >"$BUILD/libiio.build.log" 2>&1 \
    || { tail -30 "$BUILD/libiio.build.log" >&2; die "libiio did not build (full log: $BUILD/libiio.build.log)"; }
cmake --install "$BUILD/libiio" >>"$BUILD/libiio.build.log" 2>&1 \
    || { tail -30 "$BUILD/libiio.build.log" >&2; die "libiio did not install (full log: $BUILD/libiio.build.log)"; }

# 2b - libad9361-iio 0.4.0, against that libiio. No tests: on macOS they
# include <iio/iio.h>, the framework's spelling.
echo "  libad9361-iio v0.4.0"
fetch libad9361-iio "$LIBAD9361_URL" "$LIBAD9361_COMMIT"
cmake -S "$SRC/libad9361-iio" -B "$BUILD/libad9361-iio" "${cmake_common[@]}" \
    -DOSX_FRAMEWORK=OFF -DOSX_PACKAGE=OFF \
    -DLIBIIO_LIBRARIES="$PREFIX/lib/libiio.dylib" -DLIBIIO_INCLUDEDIR="$PREFIX/include" \
    -DBUILD_TESTS=OFF -DWITH_DOC=OFF -DENABLE_PACKAGING=OFF \
    >"$BUILD/libad9361.cmake.log" 2>&1 \
    || { tail -30 "$BUILD/libad9361.cmake.log" >&2; die "libad9361-iio did not configure (full log: $BUILD/libad9361.cmake.log)"; }
cmake --build "$BUILD/libad9361-iio" -j "$JOBS" >"$BUILD/libad9361.build.log" 2>&1 \
    || { tail -30 "$BUILD/libad9361.build.log" >&2; die "libad9361-iio did not build (full log: $BUILD/libad9361.build.log)"; }
cmake --install "$BUILD/libad9361-iio" >>"$BUILD/libad9361.build.log" 2>&1 \
    || { tail -30 "$BUILD/libad9361.build.log" >&2; die "libad9361-iio did not install (full log: $BUILD/libad9361.build.log)"; }

# 3 - SDR++. The stamp holds the commit and the patch's hash: an unchanged
# tree is left alone, so a second run does not recompile the module for
# nothing; anything else is reset and patched again.
echo "  SDR++ $(printf '%.8s' "$SDRPP_COMMIT") + plutosdr-fishball.patch"
want="$SDRPP_COMMIT $(shasum -a 256 "$PATCH_FILE" | cut -d' ' -f1)"
stamp="$SRC/SDRPlusPlus.patched"
if [ ! -d "$SRC/SDRPlusPlus/.git" ] || [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
    rm -f "$stamp" "$SRC/SDRPlusPlus.dab"
    fetch SDRPlusPlus "$SDRPP_URL" "$SDRPP_COMMIT" force
    # exactly the PKGBUILD's prepare(): patch -d sdrpp -p1 < plutosdr-fishball.patch
    patch -d "$SRC/SDRPlusPlus" -p1 < "$PATCH_FILE" \
        || die "the patch does not apply to $SDRPP_COMMIT - do not edit it by hand, report it"
    # the one edit: take the pkg-config branch instead of /Library/Frameworks
    pluto_cmake="$SRC/SDRPlusPlus/source_modules/plutosdr_source/CMakeLists.txt"
    perl -pi -e 's/^(\s*)if \(\$\{CMAKE_SYSTEM_NAME\} MATCHES "Darwin"\)/$1if (FALSE) # fishball build-macos.sh: libiio comes from pkg-config, not \/Library\/Frameworks/' "$pluto_cmake"
    grep -q 'fishball build-macos.sh' "$pluto_cmake" \
        || die "plutosdr_source/CMakeLists.txt changed upstream: the /Library/Frameworks line was not found"
    echo "$want" > "$stamp"
fi

# The DAB+ decoder, the PKGBUILD's prepare() again: F4JTV's module replaces
# SDR++'s own unfinished dab_decoder, with welle.io's source inside it. It has
# its own stamp so that adding it to a tree already patched recompiles nothing
# else.
echo "  DAB+ decoder $(printf '%.8s' "$DAB_COMMIT") + welle.io $(printf '%.8s' "$WELLE_COMMIT")"
want="$DAB_COMMIT $WELLE_COMMIT"
stamp="$SRC/SDRPlusPlus.dab"
if [ "$(cat "$stamp" 2>/dev/null)" != "$want" ]; then
    rm -f "$stamp"
    fetch dab_decoder "$DAB_URL" "$DAB_COMMIT"
    fetch welle.io "$WELLE_URL" "$WELLE_COMMIT"
    dab="$SRC/SDRPlusPlus/decoder_modules/dab_decoder"
    rm -rf "$dab"
    cp -R "$SRC/dab_decoder" "$dab"
    cp -R "$SRC/welle.io" "$dab/welle.io"
    rm -rf "$dab/.git" "$dab/welle.io/.git"     # 40 MB of history nothing reads
    # SDR++ hands every module -std=c++17, and this one has three C files:
    # gcc warns, clang stops. Take the flag off this module; its CMakeLists
    # asks for C++17 itself (CMAKE_CXX_STANDARD), so the C++ is built the same.
    cat >> "$dab/CMakeLists.txt" <<'EOF'

# fishball build-macos.sh: clang refuses -std=c++17 on welle.io's C files
get_target_property(_fishball_opts dab_decoder COMPILE_OPTIONS)
list(REMOVE_ITEM _fishball_opts -std=c++17)
set_target_properties(dab_decoder PROPERTIES COMPILE_OPTIONS "${_fishball_opts}")
EOF
    echo "$want" > "$stamp"
fi

# Upstream's macOS recipe (readme, "Building on MacOS"): PortAudio sinks on,
# the RtAudio sink and source off. USE_BUNDLE_DEFAULTS stays off, so the
# defaults for modules and resources are the prefix (INSTALL_PREFIX/lib/sdrpp/
# plugins, INSTALL_PREFIX/share/sdrpp) and no .app is needed.
cmake -S "$SRC/SDRPlusPlus" -B "$BUILD/sdrpp" "${cmake_common[@]}" \
    -DOPT_BUILD_PLUTOSDR_SOURCE=ON \
    -DOPT_BUILD_AIRSPY_SOURCE=OFF \
    -DOPT_BUILD_AIRSPYHF_SOURCE=OFF \
    -DOPT_BUILD_HACKRF_SOURCE=OFF \
    -DOPT_BUILD_RTL_SDR_SOURCE=OFF \
    -DOPT_BUILD_AUDIO_SOURCE=OFF \
    -DOPT_BUILD_AUDIO_SINK=OFF \
    -DOPT_BUILD_PORTAUDIO_SINK=ON \
    -DOPT_BUILD_NEW_PORTAUDIO_SINK=ON \
    -DOPT_BUILD_DAB_DECODER=ON \
    -DUSE_BUNDLE_DEFAULTS=OFF >"$BUILD/sdrpp.cmake.log" 2>&1 \
    || { tail -30 "$BUILD/sdrpp.cmake.log" >&2; die "SDR++ did not configure (full log: $BUILD/sdrpp.cmake.log)"; }
echo "  compiling (log: $BUILD/sdrpp.build.log)"
cmake --build "$BUILD/sdrpp" -j "$JOBS" >"$BUILD/sdrpp.build.log" 2>&1 \
    || { tail -40 "$BUILD/sdrpp.build.log" >&2; die "SDR++ did not build (full log: $BUILD/sdrpp.build.log)"; }
cmake --install "$BUILD/sdrpp" >>"$BUILD/sdrpp.build.log" 2>&1 \
    || { tail -40 "$BUILD/sdrpp.build.log" >&2; die "SDR++ did not install (full log: $BUILD/sdrpp.build.log)"; }

# Prove the module that was installed is the patched one, linked to the libiio
# built above: a build that silently picked up another libiio would start, and
# then fail on the board.
MODULE="$PREFIX/lib/sdrpp/plugins/plutosdr_source.dylib"
[ -f "$MODULE" ] || die "no $MODULE after install"
grep -q 'Fast TCP' "$MODULE" || die "$MODULE does not contain the patch"
otool -L "$MODULE" | grep -q "$PREFIX/lib/libiio" \
    || die "$MODULE is not linked to $PREFIX/lib/libiio: $(otool -L "$MODULE" | grep -i iio)"

DAB_MODULE="$PREFIX/lib/sdrpp/plugins/dab_decoder.dylib"
[ -f "$DAB_MODULE" ] || die "no $DAB_MODULE after install"
otool -L "$DAB_MODULE" | grep -q 'libfaad' || die "$DAB_MODULE is not linked to faad2"

# 4 - the launcher. SDR++ keeps the module and resource directories in
# ROOT/config.json, written with the prefix's paths the first time it runs;
# its own root keeps this build apart from any other SDR++ on the Mac.
#
# default-instances.json is SDR++'s own default module list, read out of the
# pinned core.cpp, plus the DAB Decoder. A config.json holding only that key is
# a valid one: SDR++ fills in every key that is missing ("Missing key in
# config, repairing"), so a first start gets the DAB panel too.
SHARE="$PREFIX/share/fishball-sdrpp"
mkdir -p "$SHARE"
python3 - "$SRC/SDRPlusPlus/core/src/core.cpp" "$SHARE/default-instances.json" <<'EOF'
import json, re, sys
inst = {}
for line in open(sys.argv[1], encoding="utf-8"):
    if line.lstrip().startswith("//"):
        continue
    m = re.search(r'defConfig\["moduleInstances"\]\["([^"]+)"\](?:\["module"\])? = "([^"]+)";', line)
    if m:
        inst[m.group(1)] = {"module": m.group(2), "enabled": True}
if "PlutoSDR Source" not in inst or "Radio" not in inst:
    sys.exit("core.cpp changed upstream: its default moduleInstances were not found")
inst["DAB Decoder"] = {"module": "dab_decoder", "enabled": True}
json.dump(inst, open(sys.argv[2], "w"), indent=4)
EOF

cat > "$SHARE/ensure-dab.py" <<'EOF'
#!/usr/bin/env python3
"""Give an SDR++ config directory a "DAB Decoder" instance, once.

Written by tools/sdrpp/build-macos.sh and run by the launcher before SDR++
starts. usage: ensure-dab.py ROOT DEFAULT-INSTANCES.json
"""
import json, os, sys

root, defaults = sys.argv[1], sys.argv[2]
marker = os.path.join(root, ".fishball-dab-added")
path = os.path.join(root, "config.json")
if os.path.exists(marker):
    sys.exit(0)
os.makedirs(root, exist_ok=True)
if os.path.exists(path):
    try:
        conf = json.load(open(path, encoding="utf-8"))
    except ValueError:
        sys.exit(0)             # SDR++ resets a config it cannot read; leave it to it
    inst = conf.setdefault("moduleInstances", {})
    have = any((v.get("module") if isinstance(v, dict) else v) == "dab_decoder"
               for v in inst.values())
    if not have:
        inst["DAB Decoder"] = {"module": "dab_decoder", "enabled": True}
else:
    conf, have = {"moduleInstances": json.load(open(defaults, encoding="utf-8"))}, False
if not have:
    tmp = path + ".fishball-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=4)
    os.replace(tmp, path)
open(marker, "w").close()
EOF

cat > "$WORK/sdrpp" <<EOF
#!/bin/sh
# Written by tools/sdrpp/build-macos.sh. SDR++ with the Fishball7020 patch;
# settings live in $ROOT (delete it to start from defaults), or in
# \$FISHBALL_SDRPP_ROOT if that is set.
ROOT="\${FISHBALL_SDRPP_ROOT:-$ROOT}"
# the DAB Decoder panel, once per config directory (see build-macos.sh --help)
python3 "$SHARE/ensure-dab.py" "\$ROOT" "$SHARE/default-instances.json" \\
    || echo "sdrpp: could not add the DAB Decoder to \$ROOT/config.json; add dab_decoder in the Module Manager" >&2
exec "$PREFIX/bin/sdrpp" -r "\$ROOT" "\$@"
EOF
chmod +x "$WORK/sdrpp"

cat <<EOF

  built: $PREFIX/bin/sdrpp
         libiio $("$PREFIX/bin/iio_info" -V 2>/dev/null | sed -n 's/.*version: *//p' | head -1), SDR++ $(printf '%.8s' "$SDRPP_COMMIT")

  run it:

      $WORK/sdrpp

  then: Source -> PlutoSDR, and pick the board in the menu under it. It is
  listed as "(ip) ..." once libiio finds it on the network; if it is not,
  type its address in Address and press "Use address" (more under "macOS" in
  tools/sdrpp/README.md). DAB+ is the "DAB Decoder" panel in the same
  left-hand menu: docs/radio/listen-to-dab.md.
EOF
