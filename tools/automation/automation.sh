#!/usr/bin/env bash
# The Fishball7020 automation server: install it on the board, and talk to it.
#
#   # run from: the repo root on your PC
#   ./devkit automation install      # put the server on the board, as a service
#   ./devkit automation status       # the board, the radio, the clock, who holds the buffers
#   ./devkit automation clock --measure          # time the reference against the board's crystal
#   ./devkit automation capture loop --samples 2e6 --channels 1,2   # writes loop.sigmf-data/-meta here
#   ./devkit automation smoke        # an end-to-end check; receive only
#   ./devkit automation mute         # both transmitters to the floor, read back
#   ./devkit automation test         # the unit tests, against a fake board (no board needed)
#   ./devkit automation uninstall
#
# The server transmits only when a script asks, through Transmit or
# TransmitCapture, with the transmit rules enforced. Scripts use the Python client:
# tools/automation/README.md, docs/automation.md.
#
# BOARD overrides the address (default fishball.local). install/uninstall use
# ssh with the devkit key, else BOARD_PASS through sshpass. The client runs in
# its own venv, tools/automation/.venv, created on first use.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOARD="${BOARD:-fishball.local}"
# Login is tools/lib/board-ssh.sh: the devkit key (~/.ssh/fishball) first, and
# if the board refuses that one, your usual keys and the agent. Neither alone
# was enough: plain `ssh -o BatchMode=yes` never offered the devkit key, and
# the devkit key with IdentitiesOnly shut out the key you log in with every day.
BOARD_SSH_CONNECT_TIMEOUT=8
. "$HERE/../lib/board-ssh.sh"

on_board() { board_ssh "$BOARD" "$@"; }

venv() {
    if [ ! -x "$HERE/.venv/bin/python" ]; then
        echo "creating the client's venv in tools/automation/.venv (once)..." >&2
        python3 -m venv "$HERE/.venv"
        "$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"
    fi
}

cmd="${1:-help}"; shift || true
case "$cmd" in
    install)
        board_ssh_require || exit 2
        echo "== installing the automation server on $BOARD"
        # Three answers, not two: grep says 0 (Debian) or 1 (something else);
        # anything else is ssh failing, and "this board runs something else"
        # was what a board that could not be logged in to used to be told.
        rc=0; err=$(on_board 'grep -q "^ID=debian" /etc/os-release' 2>&1) || rc=$?
        if [ "$rc" -eq 1 ]; then
            echo "the server needs the Debian root (firmware-modern); this board runs something else" >&2; exit 1
        elif [ "$rc" -ne 0 ]; then
            if board_ssh_refused "$rc" "$err"; then
                echo "$BOARD answers, and refuses the login: ${err:-ssh exit $rc}" >&2
                echo "    ./devkit ssh-key            a key for this board (BOARD_PASS=<password> if it is not analog)" >&2
            else
                echo "cannot log in to root@$BOARD: ${err:-ssh exit $rc}" >&2
                echo "(is the board up? BOARD=<address> if it is not $BOARD)" >&2
                command -v sshpass >/dev/null 2>&1 || board_ssh_hint
            fi
            exit 1
        fi
        # macOS tar (bsdtar) adds what GNU tar on the board cannot use: a ._NAME
        # AppleDouble file beside every file that has extended attributes, and
        # xattr headers that print a warning per file. COPYFILE_DISABLE stops
        # the first; --no-xattrs the second, where this tar knows the option
        # (GNU tar 1.27+, bsdtar; not busybox).
        noxattr=""
        tar --no-xattrs -cf /dev/null -T /dev/null 2>/dev/null && noxattr=--no-xattrs
        COPYFILE_DISABLE=1 tar -C "$HERE" --exclude=__pycache__ $noxattr -cf - fishball_automation fishball-automation.service fishball-automation-mute.sh \
            | on_board 'mkdir -p /opt/fishball-automation && tar -C /opt/fishball-automation -xf -'
        on_board '
            set -e
            # python3-grpclib, not python3-grpcio: the Debian grpcio aborts on this
            # board (64-bit time in its armhf build); grpclib is pure Python.
            # python3-libiio: the transmit path holds its buffer in-process.
            dpkg -s python3-grpclib python3-protobuf python3-libiio >/dev/null 2>&1 || {
                echo "   installing python3-grpclib, python3-protobuf and python3-libiio (apt)"
                DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-grpclib python3-protobuf python3-libiio >/dev/null 2>&1; }
            cd /opt/fishball-automation
            python3 -c "import fishball_automation.proto as p; print(\"   protocol loads:\", len(p.METHODS), \"calls\")"
            mv fishball-automation.service /etc/systemd/system/
            systemctl daemon-reload
            systemctl enable -q fishball-automation
            systemctl reset-failed fishball-automation 2>/dev/null || true
            systemctl restart fishball-automation
            sleep 5                              # long enough to see a crash loop
            systemctl is-active fishball-automation >/dev/null && ss -ltn | grep -q ":7020 " || {
                echo "   the service did not stay up:"; journalctl -u fishball-automation -n 8 --no-pager; exit 1; }
            echo "   the service is running, on port 7020"'
        echo "== installed: try ./devkit automation status" ;;
    uninstall)
        board_ssh_require || exit 2
        on_board 'systemctl disable -q --now fishball-automation 2>/dev/null; rm -f /etc/systemd/system/fishball-automation.service; rm -rf /opt/fishball-automation; systemctl daemon-reload; echo removed' ;;
    test)
        venv; exec "$HERE/.venv/bin/python" "$HERE/tests/test_automation.py" "$@" ;;
    status|clock|capture|smoke|mute)
        # No cd: a capture's PATH is relative to where you ran the command.
        venv; PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}" exec "$HERE/.venv/bin/python" -m fishball_automation.cli --host "$BOARD" "$cmd" "$@" ;;
    help|-h|--help)
        sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' ;;
    *)
        echo "unknown: automation $cmd (see ./devkit automation help)" >&2; exit 2 ;;
esac
