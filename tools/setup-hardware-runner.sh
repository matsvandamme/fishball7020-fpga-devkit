#!/bin/bash
# Register this machine as the self-hosted GitHub Actions runner that runs the
# hardware checks against the attached board.
#
#     ./tools/setup-hardware-runner.sh              # install and configure
#     ./tools/setup-hardware-runner.sh --service    # ...and run it as a service
#     ./tools/setup-hardware-runner.sh --remove     # unregister and delete
#
# WHAT THIS DOES TO YOUR MACHINE
# It downloads GitHub's runner, registers it against this repository with the
# label "fishball-board", and (with --service) installs a systemd unit that
# starts it at boot. From then on, workflow code from this repository RUNS ON
# THIS MACHINE.
#
# That is a real trust decision, which is why this is a script you run rather
# than something set up for you:
#
#   * .github/workflows/hardware.yml never triggers on pull_request - only on
#     pushes to main and manual dispatch - so an outside contributor cannot
#     reach this machine by opening a PR.
#   * Set Settings -> Actions -> General -> "Fork pull request workflows from
#     outside collaborators" to "Require approval for all outside
#     collaborators" as well.
#   * Do not point this at a repository whose main branch other people can
#     push to.
#
# The runner needs: a working ./devkit build environment, the board reachable,
# and `gh` authenticated with admin rights on the repo (for the registration
# token).
set -euo pipefail

REPO="${REPO:-matsvandamme/fishball7020-fpga-devkit}"
LABEL="fishball-board"
DIR="${RUNNER_DIR:-$HOME/actions-runner-fishball}"
MODE="configure"

for arg in "$@"; do
    case "$arg" in
        --service) MODE="service" ;;
        --remove)  MODE="remove" ;;
        -h|--help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

command -v gh >/dev/null || { echo "needs the GitHub CLI (gh)" >&2; exit 2; }
gh auth status >/dev/null 2>&1 || { echo "run 'gh auth login' first" >&2; exit 2; }

token() {
    gh api -X POST "repos/$REPO/actions/runners/registration-token" \
        --jq .token 2>/dev/null || {
        echo "could not get a registration token - do you have admin on $REPO?" >&2
        exit 1; }
}

# The workflows are gated on a repository variable so they stay inert - rather
# than queued forever against a runner that does not exist - until one is
# registered. "gh variable" only exists in gh >= 2.34, so go through the API,
# which works on every version and needs no extra subcommand.
set_runner_flag() {
    local value=$1
    if gh api -X PATCH "repos/$REPO/actions/variables/HARDWARE_RUNNER" \
            -f name=HARDWARE_RUNNER -f value="$value" >/dev/null 2>&1; then
        echo "   repository variable HARDWARE_RUNNER=$value"
    elif gh api -X POST "repos/$REPO/actions/variables" \
            -f name=HARDWARE_RUNNER -f value="$value" >/dev/null 2>&1; then
        echo "   repository variable HARDWARE_RUNNER=$value (created)"
    else
        echo "   NOTE: could not set HARDWARE_RUNNER=$value automatically." >&2
        echo "         Set it by hand, or the workflows stay inert:" >&2
        echo "         gh api -X POST repos/$REPO/actions/variables \\" >&2
        echo "             -f name=HARDWARE_RUNNER -f value=$value" >&2
    fi
}

if [ "$MODE" = "remove" ]; then
    [ -d "$DIR" ] || { echo "nothing at $DIR"; exit 0; }
    cd "$DIR"
    sudo ./svc.sh uninstall 2>/dev/null || true
    rm_token=$(gh api -X POST "repos/$REPO/actions/runners/remove-token" --jq .token)
    ./config.sh remove --token "$rm_token" || true
    cd - >/dev/null
    rm -rf "$DIR"
    set_runner_flag disabled
    echo "runner removed and $DIR deleted."
    exit 0
fi

echo "== board =="
BOARD="${BOARD:-192.168.2.1}"
if ping -c1 -W1 "$BOARD" >/dev/null 2>&1; then
    echo "   reachable at $BOARD"
else
    echo "   WARNING: no board at $BOARD. The runner will register, but every"
    echo "            hardware job will fail until a board is attached."
fi

if [ ! -x "$DIR/config.sh" ]; then
    echo
    echo "== downloading the runner =="
    mkdir -p "$DIR"; cd "$DIR"
    ver=$(gh api repos/actions/runner/releases/latest --jq .tag_name | sed 's/^v//')
    case "$(uname -m)" in
        x86_64)  arch=x64 ;;
        aarch64) arch=arm64 ;;
        *) echo "unsupported architecture $(uname -m)" >&2; exit 1 ;;
    esac
    tarball="actions-runner-linux-${arch}-${ver}.tar.gz"
    echo "   actions/runner ${ver} (${arch})"
    curl -fsSL -o "$tarball" \
        "https://github.com/actions/runner/releases/download/v${ver}/${tarball}"
    tar xzf "$tarball" && rm -f "$tarball"
else
    cd "$DIR"
    echo "   runner already downloaded in $DIR"
fi

echo
echo "== registering against $REPO =="
if [ -f "$DIR/.runner" ]; then
    echo "   already configured - skipping (use --remove first to re-register)"
else
    ./config.sh --unattended --replace \
        --url "https://github.com/$REPO" \
        --token "$(token)" \
        --name "$(hostname)-fishball" \
        --labels "$LABEL" \
        --work _work
fi

if [ "$MODE" = "service" ]; then
    echo
    echo "== installing as a service =="
    sudo ./svc.sh install "$USER"
    sudo ./svc.sh start
    sudo ./svc.sh status | head -5
    set_runner_flag enabled
    echo
    echo "Runner is live. .github/workflows/hardware.yml will now run on pushes"
    echo "to main. Stop it with: cd $DIR && sudo ./svc.sh stop"
else
    echo
    echo "NOTE: the workflows stay inert until the repository variable is set:"
    echo "    gh api -X POST repos/$REPO/actions/variables \\"
    echo "        -f name=HARDWARE_RUNNER -f value=enabled"
    echo "  (or re-run this script with --service, which sets it for you)"
    echo
    echo "Configured. Start it in the foreground with:"
    echo "    cd $DIR && ./run.sh"
    echo "Or install it as a service with:"
    echo "    $0 --service"
fi
