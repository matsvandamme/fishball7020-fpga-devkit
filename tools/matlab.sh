#!/usr/bin/env bash
# Start MATLAB with this repository's package on the path, or check it over.
#
#   ./devkit matlab            is MATLAB ready, and can it see the board?
#   ./devkit matlab shell      interactive MATLAB, path already set
#   ./devkit matlab hello      run example 01 against the board
#   ./devkit matlab run <expr> evaluate one expression with the path set
#
# WHY THIS EXISTS. The first thing anyone does wrong is paste MATLAB into a
# shell - `addpath: command not found` - because every other code block in this
# repository is a shell block. This wrapper means the getting-started path never
# requires typing `addpath` at all.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MATLAB="${MATLAB_BIN:-matlab}"

# Help needs no MATLAB.
case "${1:-}" in
    -h|--help|help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

# On macOS MATLAB is an application bundle and puts nothing on PATH, so look
# where the installer puts it; the newest release sorts last.
if ! command -v "$MATLAB" >/dev/null 2>&1 && [ -z "${MATLAB_BIN:-}" ]; then
    for m in /Applications/MATLAB_R20*.app/bin/matlab; do
        [ -x "$m" ] && MATLAB="$m"
    done
fi

if ! command -v "$MATLAB" >/dev/null 2>&1; then
    case "${OSTYPE:-}" in
        darwin*) eg=/Applications/MATLAB_R2026a.app/bin/matlab ;;
        *)       eg=/usr/local/MATLAB/R2026a/bin/matlab ;;
    esac
    cat >&2 <<MSG
matlab: not found on PATH.

  MATLAB is not installed here, or its bin directory is not on PATH. Set
  MATLAB_BIN to the binary if it lives somewhere unusual:

      MATLAB_BIN=$eg ./devkit matlab

  Everything in matlab/+fishball that does not need live radio also works
  without MATLAB at all - see docs/matlab.md for the capture-file route.
MSG
    exit 127
fi

# -sd puts MATLAB's current folder at the repo root, so relative paths in the
# examples mean what they say.
cmd="${1:-doctor}"; shift || true

case "$cmd" in
    doctor|"")
        exec "$MATLAB" -sd "$HERE" -batch \
            "addpath('$HERE/matlab'); ok = fishball.doctor; exit(double(~ok))"
        ;;
    shell)
        # -r rather than -batch: this one is meant to stay open.
        exec "$MATLAB" -sd "$HERE" -r \
            "addpath('$HERE/matlab'); addpath(genpath('$HERE/examples/matlab')); \
             fprintf('\n  fishball package on the path. Try: fishball.doctor\n\n');"
        ;;
    hello)
        exec "$MATLAB" -sd "$HERE" -batch \
            "addpath('$HERE/matlab','$HERE/examples/matlab/01-hello-board'); \
             hello_board('Plot', false)"
        ;;
    run)
        [ $# -ge 1 ] || { echo "usage: ./devkit matlab run <expression>" >&2; exit 2; }
        exec "$MATLAB" -sd "$HERE" -batch \
            "addpath('$HERE/matlab'); addpath(genpath('$HERE/examples/matlab')); $*"
        ;;
    *)
        echo "unknown: matlab $cmd" >&2
        echo "try: doctor | shell | hello | run <expr>" >&2
        exit 2
        ;;
esac
