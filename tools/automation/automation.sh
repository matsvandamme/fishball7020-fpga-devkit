#!/usr/bin/env bash
# The Fishball7020 automation server: install it on the board, and talk to it.
#
#   # run from: the repo root on your PC
#   ./devkit automation install      # put the server on the board, as a service
#   ./devkit automation status       # the board, the radio, the clock, who holds the buffers
#   ./devkit automation clock --measure          # time the reference against the board's crystal
#   ./devkit automation capture loop --samples 2e6 --channels 1,2
#   ./devkit automation smoke        # an end-to-end check; receive only
#   ./devkit automation mute         # both transmitters to the floor, read back
#   ./devkit automation test         # the unit tests, against a fake board (no board needed)
#   ./devkit automation uninstall
#
# The server never transmits. Your own scripts use the Python client:
# tools/automation/README.md, docs/automation.md.
#
# BOARD overrides the address (default fishball.local). install/uninstall use
# ssh with the devkit key, else BOARD_PASS through sshpass. The client runs in
# its own venv, tools/automation/.venv, created on first use.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOARD="${BOARD:-fishball.local}"
PASS="${BOARD_PASS:-analog}"
OPTS=(-o ConnectTimeout=8 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

on_board() {
    if ssh "${OPTS[@]}" -o BatchMode=yes "root@$BOARD" true 2>/dev/null; then
        ssh "${OPTS[@]}" -o BatchMode=yes "root@$BOARD" "$@"
    else
        command -v sshpass >/dev/null || { echo "cannot log in to $BOARD: run ./devkit ssh-key, or install sshpass" >&2; exit 2; }
        sshpass -p "$PASS" ssh "${OPTS[@]}" "root@$BOARD" "$@"
    fi
}

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
        echo "== installing the automation server on $BOARD"
        on_board 'grep -q "^ID=debian" /etc/os-release' || {
            echo "the server needs the Debian root (firmware-modern); this board runs something else" >&2; exit 1; }
        tar -C "$HERE" --exclude=__pycache__ -cf - fishball_automation fishball-automation.service \
            | on_board 'mkdir -p /opt/fishball-automation && tar -C /opt/fishball-automation -xf -'
        on_board '
            set -e
            # python3-grpclib, not python3-grpcio: the Debian grpcio aborts on this
            # board (64-bit time in its armhf build); grpclib is pure Python.
            dpkg -s python3-grpclib python3-protobuf >/dev/null 2>&1 || {
                echo "   installing python3-grpclib and python3-protobuf (apt)"
                DEBIAN_FRONTEND=noninteractive apt-get install -y -q python3-grpclib python3-protobuf >/dev/null 2>&1; }
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
        on_board 'systemctl disable -q --now fishball-automation 2>/dev/null; rm -f /etc/systemd/system/fishball-automation.service; rm -rf /opt/fishball-automation; systemctl daemon-reload; echo removed' ;;
    test)
        venv; exec "$HERE/.venv/bin/python" "$HERE/tests/test_automation.py" "$@" ;;
    status|clock|capture|smoke|mute)
        venv; cd "$HERE"; exec "$HERE/.venv/bin/python" -m fishball_automation.cli --host "$BOARD" "$cmd" "$@" ;;
    help|-h|--help)
        sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//' ;;
    *)
        echo "unknown: automation $cmd (see ./devkit automation help)" >&2; exit 2 ;;
esac
