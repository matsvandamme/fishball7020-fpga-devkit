# How every host-side shell tool here logs in to the board. Sourced, not run:
#
#     BOARD_SSH_CONNECT_TIMEOUT=8          # optional, before sourcing; default 10
#     . "$(dirname "${BASH_SOURCE[0]}")/lib/board-ssh.sh"
#     board_ssh_require || exit 2          # can this machine log in at all?
#     board_ssh "$BOARD" 'uname -r'        # root@$BOARD; stdin, stdout and the
#                                          # remote exit status pass through
#
# tools/board_ssh.py is the same logic for the Python tools. Keep them in step.
#
# WHY ONE HELPER. These tools each used to call `sshpass -p ... ssh` themselves
# and stop without it. sshpass is one apt package on Linux, but a stock Mac has
# none and Homebrew has not always carried it, so on macOS every one of
# them died before trying - including for a user whose key (./devkit ssh-key)
# would have logged in with no password at all.
#
# WHAT IT DOES. One ssh connection when the first way in works, two when the
# board refuses it; nothing is probed beforehand and nothing is cached:
#
#   the key   ${FISHBALL_SSH_KEY:-~/.ssh/fishball}, the one ./devkit ssh-key
#             makes, is tried first whenever the file exists: alone, and with
#             BatchMode=yes, so ssh can ask for nothing - not the password, and
#             not the passphrase of a key that has one (under sshpass that
#             prompt was never answered, and the tool hung).
#   then      only if the board ANSWERED and refused that key (a fresh card, a
#             key from another card), a second connection without it: ssh's
#             usual identities and the agent, so the key you log in with every
#             day still works when the devkit one is stale, and
#   sshpass   where it is installed it wraps that second ssh, so the password
#             (${BOARD_PASS:-analog}) answers. A fresh card has no key on it
#             yet; this is what keeps that working.
#   neither   without sshpass the second ssh has BatchMode=yes too: a key or
#             nothing, and never a password prompt hanging a script. If that
#             fails, board_ssh_hint names both fixes.
#
# A board that does not answer at all costs one connection, not two.
#
# The options are the ones these tools always used. No known_hosts: every board
# is 192.168.2.1 over USB and each card has its own host key, so the second
# board you ever plug in would otherwise be refused with a "changed key"
# warning that sshpass hides.
#
# bash 3.2 (macOS's /bin/bash) runs this: no associative arrays, no mapfile.

BOARD_SSH_KEY="${FISHBALL_SSH_KEY:-$HOME/.ssh/fishball}"
BOARD_SSH_PASS="${BOARD_PASS:-analog}"
BOARD_SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
                -o LogLevel=ERROR -o "ConnectTimeout=${BOARD_SSH_CONNECT_TIMEOUT:-10}")

# The package manager's line for sshpass. $OSTYPE and not `uname`: it is a
# bash variable, so this needs nothing on PATH.
_board_ssh_install_line() {
    case "${OSTYPE:-}" in
        # Homebrew's own repository has not always carried sshpass; this
        # tap is the usual source when it does not.
        darwin*) echo "brew install sshpass    (if Homebrew has no such formula: brew install hudochenkov/sshpass/sshpass)" ;;
        *)       echo "sudo apt install sshpass" ;;
    esac
}

# The two ways to make login work, on stderr.
board_ssh_hint() {
    {
        echo "No way to log in to the board without typing a password. Either:"
        echo "    ./devkit ssh-key            a key for this board; nothing to install"
        echo "    $(_board_ssh_install_line)"
        echo "With sshpass the board's password is used (BOARD_PASS, default analog)."
    } >&2
}

# Can this machine log in unattended at all? Touches no network. Returns 2,
# having said what to do, when there is neither a key nor sshpass.
board_ssh_require() {
    [ -r "$BOARD_SSH_KEY" ] && return 0
    command -v sshpass >/dev/null 2>&1 && return 0
    board_ssh_hint
    return 2
}

# Was that failure the board ANSWERING and refusing the login, as opposed to
# not answering? Takes the exit status and the stderr of a failed board_ssh (or
# ssh). ssh says "Permission denied" itself, with status 255. sshpass says
# nothing and exits 5 when the password it typed was refused - a status a
# remote command can return too, so ask this about a probe such as `true`.
board_ssh_refused() {   # <exit status> <stderr>
    if [ "$1" -eq 255 ]; then
        case "$2" in
            *"Permission denied"*|*"Too many authentication failures"*|*"No more authentication methods"*) return 0 ;;
        esac
    fi
    [ "$1" -eq 5 ] && command -v sshpass >/dev/null 2>&1 && return 0
    return 1
}

# board_ssh HOST COMMAND
# stdin and stdout pass straight through; so does the remote exit status. The
# first attempt's stderr is held until it ends, because it decides whether
# there is a second attempt - and a refusal that the second attempt gets past
# is not worth printing.
board_ssh() {
    local host="$1"; shift
    local base rc=0 err=""
    base=(ssh "${BOARD_SSH_OPTS[@]}")
    if [ -r "$BOARD_SSH_KEY" ]; then
        # IdentitiesOnly on THIS attempt: offer the one key and no other. An
        # agent holding many keys runs the board's sshd out of attempts before
        # it reaches the right one. The other keys get their turn below.
        # `|| rc=$?`: a caller's `set -e` must not end the script here.
        { err=$("${base[@]}" -i "$BOARD_SSH_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
                    "root@$host" "$@" 2>&1 1>&3 3>&-) || rc=$?; } 3>&1
        if [ "$rc" -ne 255 ] || ! board_ssh_refused "$rc" "$err"; then
            [ -z "$err" ] || printf '%s\n' "$err" >&2
            return "$rc"
        fi
        # Refused before a session began: nothing ran, and stdin is unread.
    fi
    if command -v sshpass >/dev/null 2>&1; then
        sshpass -p "$BOARD_SSH_PASS" "${base[@]}" "root@$host" "$@"
    else
        "${base[@]}" -o BatchMode=yes "root@$host" "$@"
    fi
}
