#!/usr/bin/env bash
# Log into the board without typing a password, in one command.
#
#   ./devkit ssh-key            set it up, then `ssh fishball`
#   ./devkit ssh-key --check    is it already working?
#   ./devkit ssh-key --show     print the public key and stop
#
# WHAT IT DOES, all of it idempotent so running it twice is harmless:
#
#   1. makes ~/.ssh/fishball, an ed25519 key used for NOTHING ELSE
#   2. appends the public half to the board's /root/.ssh/authorized_keys - and,
#      on the factory (Buildroot) root, saves it where it survives a reboot
#   3. adds a `Host fishball` block to ~/.ssh/config, leaving the rest alone
#   4. proves it works with BatchMode=yes, which cannot fall back to a password
#
# WHY A DEDICATED KEY rather than your usual one. This board ships with a
# published root password and sits on whatever network you put it on. Giving it
# your everyday key means a board on a conference wifi is holding a credential
# that opens your other machines. A key used for one board can be deleted
# without consequence.
#
# THE PASSWORD IS LEFT ENABLED, deliberately. Turning it off is one line, and
# it is the line that turns a typo into a card reader: this board has no
# working `systemctl reboot` (see firmware-modern/debian/overlay - logind is
# masked) and no console unless you have the FTDI cable. Add
# PasswordAuthentication no yourself once key login is proven, not before.
#
# THE FACTORY ROOT FORGETS /root. Buildroot runs from a RAM disk, so a key
# written to /root/.ssh/authorized_keys is gone at the next reboot - and with a
# key as the only login, ./devkit flash then reboots the board into one that
# refuses you. The board's boot script (S21misc) restores keys from the one
# partition that persists:
#
#     [[ -d /mnt/jffs2/root/.ssh ]] && cd /mnt/jffs2/root/.ssh \
#         && md5sum -s -c keys.md5 && mkdir /root/.ssh && cp authorized_keys /root/.ssh
#
# so step 2 also writes /mnt/jffs2/root/.ssh/authorized_keys and the keys.md5
# that line checks, and says that it did. The Debian root is on the card and
# needs none of this.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY="${FISHBALL_SSH_KEY:-$HOME/.ssh/fishball}"
ALIAS_NAME="${FISHBALL_SSH_ALIAS:-fishball}"
BOARD_PASS="${BOARD_PASS:-analog}"

board() {
    if [ -n "${BOARD:-}" ]; then printf '%s\n' "$BOARD"; return; fi
    python3 "$HERE/tools/board_addr.py" 2>/dev/null || echo fishball.local
}

# The ssh options every devkit tool uses, from the shared helper: no
# known_hosts. This script used to go through ~/.ssh/known_hosts with
# accept-new, so a re-imaged card, or a second board at the same address, made
# it fail on a changed host key - and without sshpass this script is the only
# way to get a login at all.
BOARD_SSH_CONNECT_TIMEOUT=8
. "$HERE/tools/lib/board-ssh.sh"

# Does THIS key log in? It alone, and BatchMode, so nothing else can answer.
check() {
    ssh "${BOARD_SSH_OPTS[@]}" -o BatchMode=yes -o IdentitiesOnly=yes \
        -i "$KEY" "root@$1" true 2>/dev/null
}

# `ssh fishball` is the one login here that DOES use ~/.ssh/known_hosts: the
# Host block below says accept-new, which remembers the first host key it sees
# and refuses a different one afterwards. A re-imaged card has a different one.
# Ask ssh, without letting it remember anything new (StrictHostKeyChecking=yes
# adds no entry), and say what to do rather than leave it to a wall of
# "REMOTE HOST IDENTIFICATION HAS CHANGED" the first time the alias is used.
# Returns 1, having explained, only for a changed key.
alias_host_key_ok() {
    local err name
    grep -qE "^Host[[:space:]]+$ALIAS_NAME\$" "$HOME/.ssh/config" 2>/dev/null || return 0
    err=$(ssh -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=8 \
              "$ALIAS_NAME" true 2>&1 >/dev/null) && return 0
    case "$err" in *"IDENTIFICATION HAS CHANGED"*|*"host key for"*"has changed"*) ;; *) return 0 ;; esac
    name=$(ssh -G "$ALIAS_NAME" 2>/dev/null | awk '$1 == "hostname" { print $2; exit }')
    name="${name:-$1}"
    cat >&2 <<MSG

  One thing left. 'ssh $ALIAS_NAME' will be refused: ~/.ssh/known_hosts remembers
  a different host key for $name than the board there has now. That is what a
  re-imaged card looks like, or a second board at the same address. If that is
  what happened, forget the old key:

      ssh-keygen -R $name

  and 'ssh $ALIAS_NAME' accepts the new one. The devkit's own commands
  (./devkit flash, net, selftest --ssh ...) keep no host keys and are not affected.
MSG
    return 1
}

case "${1:-setup}" in
--show)
    [ -r "$KEY.pub" ] || { echo "no key at $KEY.pub - run ./devkit ssh-key" >&2; exit 1; }
    cat "$KEY.pub"; exit 0 ;;
--check)
    # Three different answers, because "not set up" for a board that is merely
    # switched off sends people to redo something that already works.
    [ -r "$KEY" ] || { echo "not set up yet - run ./devkit ssh-key"; exit 1; }
    rc=0; H=$(python3 "$HERE/tools/board_addr.py" --check --why) || rc=$?
    [ -n "${BOARD:-}" ] && H="$BOARD"
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then
        echo "the key is at $KEY, but the board is not reachable to try it"; exit 1
    fi
    if check "$H"; then
        echo "OK  key login works: ssh $ALIAS_NAME   (or ssh -i $KEY root@$H)"
        alias_host_key_ok "$H" || true
        exit 0
    fi
    echo "the key is at $KEY, but the board at $H does not accept it - run ./devkit ssh-key"; exit 1 ;;
-h|--help|help)
    sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

HOST=$(board)
echo "  board: $HOST"

# 1 - the key
if [ ! -r "$KEY" ]; then
    mkdir -p "$(dirname "$KEY")"; chmod 700 "$(dirname "$KEY")"
    ssh-keygen -t ed25519 -f "$KEY" -N "" -q \
        -C "fishball7020 devkit $(date +%F)"
    echo "  made $KEY (no passphrase - see --help)"
else
    echo "  using the key already at $KEY"
fi

# 2 - install it. What runs on the board, the same whoever logs in to run it:
#     append the key if it is not there; then, on a root that is not Debian
#     and has /mnt/jffs2 mounted, save it there the way S21misc restores it
#     (see the top of this file). The jffs2 copy is appended to as well, never
#     replaced: keys saved there by someone else stay. The last line it prints
#     says where the key now lives: jffs2 (saved), ram (Buildroot, and it could
#     not be saved) or disk (Debian, or any other root that keeps its files).
PUB=$(cat "$KEY.pub")
INSTALL="add() { grep -qxF '$PUB' \"\$1\" 2>/dev/null || printf '%s\n' '$PUB' >> \"\$1\"; }
     mkdir -p /root/.ssh && chmod 700 /root/.ssh || exit 1
     add /root/.ssh/authorized_keys || exit 1
     chmod 600 /root/.ssh/authorized_keys
     chown -R root:root /root/.ssh
     if grep -q '^ID=debian' /etc/os-release 2>/dev/null; then
         echo FISHBALL_KEY=disk
     elif grep -q ' /mnt/jffs2 ' /proc/mounts 2>/dev/null; then
         if mkdir -p /mnt/jffs2/root/.ssh && chmod 700 /mnt/jffs2/root /mnt/jffs2/root/.ssh \
            && add /mnt/jffs2/root/.ssh/authorized_keys && chmod 600 /mnt/jffs2/root/.ssh/authorized_keys \
            && cd /mnt/jffs2/root/.ssh && md5sum authorized_keys > keys.md5 \
            && md5sum -c keys.md5 >/dev/null 2>&1 && sync; then
             echo FISHBALL_KEY=jffs2
         else
             echo FISHBALL_KEY=ram
         fi
     elif grep -q '^ID=buildroot' /etc/os-release 2>/dev/null; then
         echo FISHBALL_KEY=ram
     else
         echo FISHBALL_KEY=disk
     fi"

# Who runs it. The key itself where it already logs in - an earlier version of
# this script left a Buildroot board with a key in RAM only, and this is what
# moves it to jffs2 without asking for a password again. Otherwise the
# password, once: typed by sshpass where that is installed (it is not on a
# stock Mac, and not in every package repository), else by YOU, which needs a
# terminal.
#
# PASSWORD ONLY for that one login. This used to hand the step to ssh-copy-id,
# which offers every key your agent holds first; with enough of them the
# board's sshd closes the connection before it ever asks for the password. And
# always the commands above rather than ssh-copy-id, which knows nothing about
# /mnt/jffs2.
PW_ONLY=(-o PubkeyAuthentication=no -o PreferredAuthentications=password,keyboard-interactive)
rc=0
if check "$HOST"; then
    echo "  the board already accepts this key"
    out=$(ssh "${BOARD_SSH_OPTS[@]}" -o BatchMode=yes -o IdentitiesOnly=yes -i "$KEY" "root@$HOST" "$INSTALL") || rc=$?
elif command -v sshpass >/dev/null 2>&1; then
    out=$(sshpass -p "$BOARD_PASS" ssh "${BOARD_SSH_OPTS[@]}" "${PW_ONLY[@]}" "root@$HOST" "$INSTALL") || rc=$?
elif [ -t 0 ]; then
    echo "  sshpass is not installed, so ssh will ask for the board's password"
    echo "  (analog, unless you changed it):"
    # The prompt goes to the terminal, not into $out.
    out=$(ssh "${BOARD_SSH_OPTS[@]}" "${PW_ONLY[@]}" "root@$HOST" "$INSTALL") || rc=$?
else
    cat >&2 <<MSG

  sshpass is not installed and this is not a terminal, so nothing here can
  type the board's password. Run ./devkit ssh-key in a terminal and type it
  once, or install sshpass, or copy the key across by hand:

      ssh-copy-id -i $KEY.pub root@$HOST

  (By hand, a board on the factory Buildroot root forgets the key at its next
  reboot; ./devkit ssh-key in a terminal saves it properly.)

MSG
    exit 1
fi
if [ "$rc" -ne 0 ]; then
    echo "  could not install the key on root@$HOST (ssh exit $rc)." >&2
    echo "  Is the board up, and is the password right? BOARD_PASS=<password> if it is not analog." >&2
    exit 1
fi
case "$out" in
    *FISHBALL_KEY=jffs2*)
        echo "  installed on the board, and saved in /mnt/jffs2/root/.ssh (with the keys.md5"
        echo "  the boot script checks): this root is a RAM disk, and that copy is what"
        echo "  puts the key back after a reboot" ;;
    *FISHBALL_KEY=ram*)
        echo "  installed on the board - FOR NOW. This root is a RAM disk and the key could" >&2
        echo "  not be saved in /mnt/jffs2 (not mounted, or not writable), so it will be gone" >&2
        echo "  after a reboot. Run ./devkit ssh-key again then." >&2 ;;
    *)  echo "  installed on the board" ;;
esac

# 3 - the shorthand
CFG="$HOME/.ssh/config"
touch "$CFG"; chmod 600 "$CFG"
if ! grep -qE "^Host[[:space:]]+$ALIAS_NAME\$" "$CFG"; then
    cat >> "$CFG" <<CFGEOF

# Fishball7020 SDR - added by ./devkit ssh-key
Host $ALIAS_NAME
    HostName $HOST
    User root
    IdentityFile $KEY
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
CFGEOF
    echo "  added 'Host $ALIAS_NAME' to $CFG"
else
    echo "  'Host $ALIAS_NAME' already in $CFG - left alone"
fi

# 4 - prove it, without a password being possible
if check "$HOST"; then
    echo
    echo "  OK - key login works."
    echo
    echo "      ssh $ALIAS_NAME"
    echo "      ssh $ALIAS_NAME reboot"
    echo "      scp capture.iq $ALIAS_NAME:/tmp/"
    alias_host_key_ok "$HOST" || true
else
    echo >&2
    echo "  The key was installed but BatchMode login still failed." >&2
    echo "  Check the board's sshd allows it:  sshd -T | grep pubkey" >&2
    exit 1
fi
