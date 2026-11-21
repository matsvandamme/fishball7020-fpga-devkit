#!/bin/bash
# Set how the board gets its address on the Ethernet port, permanently.
#
#     ./devkit net                     show what it is doing now
#     ./devkit net dhcp                ask the router for an address (the default)
#     ./devkit net static <ip> [mask]  pin it to one address
#     ./devkit net name <hostname>     change the name it answers to
#     ./devkit net find                find the board without knowing its address
#
# WHY THIS IS A COMMAND AND NOT A LINE IN THE README
#
# The setting lives in the U-Boot environment in QSPI flash, not on the SD card,
# so it survives ./devkit flash --target factory --all and is invisible to anything that looks at
# the card. It is also a switch with no "mode" to read: eth0 is static when the
# variable ipaddr_eth has a value and DHCP when it has none, so "go back to
# DHCP" means DELETING a variable, which is not a thing anyone guesses.
#
# And switching to DHCP throws away the address you are connected on. Done by
# hand, that is the moment you discover you have no way to find the board again.
# This writes the environment, reads it back BEFORE rebooting, and then goes and
# finds the board by name so the command that moved it also tells you where it
# went.
#
# WHICH ROOTFS THIS APPLIES TO
#
# `dhcp`, `static` and `name` change U-Boot variables, and it is the Buildroot
# rootfs's S40network script that reads them at boot. The Debian rootfs does not:
# /etc/network/interfaces is a fixed file and avahi publishes /etc/hostname. On
# Debian those three subcommands therefore refuse and print the equivalent, and
# `show` reports the interfaces file rather than the variable. `find` and `show`
# work on both.
#
# Full background: docs/networking.md
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Login is tools/lib/board-ssh.sh: the key ./devkit ssh-key makes, then the
# password through sshpass where that is installed. Whether this machine can
# log in at all is asked in resolve_board, not here: `find` and --help need no
# login, and used to die on a machine without sshpass all the same.
BOARD_SSH_CONNECT_TIMEOUT=8
. "$HERE/lib/board-ssh.sh"

# Where is it? BOARD wins; otherwise try the name before the USB address,
# because this is the command you run when you do not know the address.
# Returns 2 when this machine has no way to log in, 1 when no board answers.
resolve_board() {
    local cands c
    board_ssh_require || return 2
    # The candidate list lives in one place, board_addr.py, so this and the
    # Python tools cannot drift apart. The fallback is only for a machine with
    # no python3 at all. Split on whitespace into the array: `mapfile` is bash
    # 4, and macOS's /bin/bash is 3.2. No candidate contains a space.
    if [ -n "${BOARD:-}" ]; then
        cands=("$BOARD")
    else
        # shellcheck disable=SC2207
        cands=($(python3 "$HERE/board_addr.py" --list 2>/dev/null || true))
        [ ${#cands[@]} -eq 0 ] && cands=(fishball.local pluto.local 192.168.2.1)
    fi
    for c in "${cands[@]}"; do
        if board_ssh "$c" true 2>/dev/null; then
            echo "$c"; return 0
        fi
    done
    return 1
}

# For the commands that change something: find the board or stop, saying why.
need_board() {
    local rc=0
    b=$(resolve_board) || rc=$?
    [ "$rc" -eq 0 ] && return 0
    [ "$rc" -eq 2 ] && exit 2              # board_ssh_require has said what to do
    echo "cannot reach the board" >&2
    command -v sshpass >/dev/null 2>&1 || board_ssh_hint
    exit 1
}

on_board() { board_ssh "$1" "$2"; }

# The system resolver is the direct question, asked through Python: it answers
# .local names wherever the machine does mDNS at all (nss-mdns on Linux, built
# in on macOS). This used to call avahi-resolve under `timeout`, and neither
# exists on a Mac, so `find` could not find a board that `ping fishball.local`
# reached. A lookup can block for many seconds on a name nobody answers to and
# cannot be interrupted, hence the thread and the hard exit.
resolve_name() {   # <name> <seconds>
    python3 -c 'import os, socket, sys, threading
out = []
def look():
    try:
        out.append(socket.getaddrinfo(sys.argv[1], None, socket.AF_INET)[0][4][0])
    except OSError:
        pass
t = threading.Thread(target=look, daemon=True)
t.start(); t.join(float(sys.argv[2]))
if out:
    print(out[0])
sys.stdout.flush()
os._exit(0 if out else 1)' "$1" "$2" 2>/dev/null
}

# Run a command for at most N seconds. `timeout` is GNU coreutils: Linux has it,
# Homebrew's coreutils calls it gtimeout, and a stock Mac has neither.
bounded() {   # <seconds> <command...>
    local t="$1"; shift
    if command -v timeout >/dev/null 2>&1; then timeout "$t" "$@"
    elif command -v gtimeout >/dev/null 2>&1; then gtimeout "$t" "$@"
    else python3 -c 'import subprocess, sys
try:
    sys.exit(subprocess.run(sys.argv[2:], timeout=float(sys.argv[1])).returncode)
except subprocess.TimeoutExpired:
    sys.exit(124)' "$t" "$@"
    fi
}

# By name first; iio_info -s answers it too, via the board's own service
# advertisement, and is present on any machine that can already talk to the
# radio.
find_by_name() {
    local a n
    for n in "${1:-fishball}" fishball Fishball7020 pluto; do
        a=$(resolve_name "$n.local" 6 || true)
        # A Linux machine with avahi-daemon but no nss-mdns resolves .local
        # only through avahi's own tool.
        if [ -z "$a" ] && command -v avahi-resolve >/dev/null 2>&1; then
            a=$(bounded 6 avahi-resolve -n "$n.local" 2>/dev/null | awk '{print $2}' || true)
        fi
        [ -n "$a" ] && { echo "$a"; return 0; }
    done
    if command -v iio_info >/dev/null 2>&1; then
        a=$(bounded 15 iio_info -s 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1 || true)
        [ -n "$a" ] && { echo "$a"; return 0; }
    fi
    return 1
}

# Which userspace is on the card? Everything below writes U-Boot environment
# variables, and it is Buildroot's S40network that reads them at boot. The Debian
# rootfs has no S40network: /etc/network/interfaces is a fixed file and avahi
# publishes /etc/hostname. Nothing there reads ipaddr_eth, netmask_eth or the
# U-Boot hostname - verified on the board, zero references. So on Debian these
# commands would write a variable, read it back successfully, and report a
# working static address while the board stayed on DHCP. A confident false
# report is worse than an error, so detect the rootfs and refuse.
#
# Three answers. grep says 0 (Debian) or 1 (not; 2 where there is no os-release
# at all, which is not Debian either); anything else is ssh failing, and a board
# that did not answer must not be taken for a Buildroot one and written to.
# This used to be `grep -c ... || echo 0` compared with "0": on Buildroot grep
# prints 0 AND fails, so the answer was two zeros, which is not "0" - and every
# Buildroot board, the only kind these commands are for, was refused as Debian.
is_debian_rootfs() {
    local rc=0
    on_board "$1" 'grep -qi "^ID=debian" /etc/os-release 2>/dev/null' || rc=$?
    case "$rc" in
        0)   return 0 ;;
        1|2) return 1 ;;
    esac
    echo "the board at $1 did not say which rootfs it runs (ssh exit $rc) - nothing was changed" >&2
    exit 1
}

refuse_on_debian() {   # $1 = board, $2 = what was asked for, $3.. = how to do it there
    is_debian_rootfs "$1" || return 0
    local b="$1" what="$2"; shift 2
    cat >&2 <<EOF

This board is running the Debian rootfs, where $what does nothing.

  Nothing on Debian reads these U-Boot variables. /etc/network/interfaces is a
  fixed file and avahi publishes /etc/hostname, so the write would succeed, the
  read-back would agree, and the address would not change. Do it in Debian:

$(printf '      %s\n' "$@")

  A DHCP reservation on your router is better still - it gives a fixed address
  AND a working gateway, and survives reflashing the card.

  NET_FORCE=1 writes the variable anyway, which is only useful if you are about
  to boot the Buildroot rootfs on this board.
EOF
    if [ "${NET_FORCE:-0}" = "1" ]; then
        echo "  NET_FORCE=1 - writing it anyway." >&2
        return 0
    fi
    exit 1
}

show() {
    local b="$1"
    echo "== $b =="
    on_board "$b" '
      h=$(hostname)
      mode=$(fw_printenv ipaddr_eth 2>/dev/null | cut -d= -f2)
      echo "   name          $h  ->  $h.local"
      # Only report what ipaddr_eth MEANS on a rootfs that reads it. On Debian
      # the same variable selects nothing, and printing STATIC from it is how
      # this tool used to state a configuration the board did not have.
      if grep -qi "^ID=debian" /etc/os-release 2>/dev/null; then
        echo "   rootfs        Debian - eth0 is configured by /etc/network/interfaces,"
        echo "                 not by the U-Boot environment."
        cfg=$(awk "/^iface[ \t]+eth0/{print \$4}" /etc/network/interfaces 2>/dev/null | head -1)
        echo "   eth0          ${cfg:-unknown} (from /etc/network/interfaces)"
        [ -n "$mode" ] && echo "   note          ipaddr_eth=$mode is set in QSPI and IGNORED here"
      elif [ -n "$mode" ]; then
        echo "   eth0          STATIC $mode / $(fw_printenv netmask_eth 2>/dev/null | cut -d= -f2)"
      else
        echo "   eth0          DHCP (ipaddr_eth is unset, which is what selects it)"
      fi
      # An empty field here is a real answer - no address, no route - so say so
      # rather than printing a blank and letting it read as "not checked".
      a=$(ip -4 -o addr show eth0 2>/dev/null | awk "{print \$4}")
      r=$(ip route 2>/dev/null | awk "/^default/{print \$3}" || true)
      echo "   address now   ${a:-none yet - no DHCP answer, or the link is down}"
      echo "   default route ${r:-none}"
      echo "   nameserver    $(awk "/nameserver/{print \$2}" /etc/resolv.conf 2>/dev/null | tr "\n" " ")"
      echo "   usb0 fallback $(ip -4 -o addr show usb0 2>/dev/null | awk "{print \$4}")"
    '
}

# Write, read back, and only then reboot. fw_setenv reports success on a write
# it did not make if the environment is not where fw_env.config says it is.
# Exits 1 if the write failed or the board cannot be found afterwards, and 3 if
# it is found and refuses the login (the setting is written; only the last look
# at it was not possible).
set_and_reboot() {
    local b="$1"; shift
    echo "writing the U-Boot environment in QSPI ..."
    on_board "$b" "$1" || { echo "the write failed - nothing was changed, not rebooting" >&2; exit 1; }
    echo "reading it back before rebooting:"
    # fw_printenv exits non-zero for a variable that is not defined, and "not
    # defined" is exactly the SUCCESS condition for DHCP - so the read-back must
    # not be allowed to look like a failure. Hence "; true" on the remote side
    # and a guard on the pipeline.
    on_board "$b" "$2 ; true" 2>&1 | sed 's/^/   /' || true
    printf 'rebooting ... '
    on_board "$b" 'nohup sh -c "sleep 1; reboot" >/dev/null 2>&1 &' || true
    sleep 35
    local name="${3:-fishball}" a=""
    for _ in $(seq 1 14); do
        a=$(find_by_name "$name" || true)
        [ -n "$a" ] && break
        printf '.'; sleep 8
    done
    echo
    if [ -z "$a" ]; then
        cat >&2 <<'MSG'
The board did not answer by name within two minutes. It is probably fine - finding
it by name needs mDNS on THIS machine (avahi on Linux; built in on macOS), and
some networks block multicast. Ways back in:
  * USB cable, then ssh root@192.168.2.1 - usb0 keeps its own address whatever
    Ethernet is doing, so this always works
  * your router's DHCP lease table; the board's MAC starts 00:0a:35
  * the serial console on the DEBUG port, 115200 baud
MSG
        exit 1
    fi
    echo "found it: $name.local is $a"
    echo
    # It answers by name. Does it still let us in? These commands are for the
    # Buildroot root, where /root is a RAM disk: a key in /root/.ssh that was
    # not also saved in /mnt/jffs2 (./devkit ssh-key saves it) is gone after
    # this reboot. With a key as the only login, `show` then died on ssh's
    # "Permission denied" and the command that had just worked looked failed.
    local t rc=0 err=""
    for t in "$name.local" "$a"; do
        rc=0; err=$(board_ssh "$t" true 2>&1) || rc=$?
        if [ "$rc" -eq 0 ]; then show "$t"; return 0; fi
        if board_ssh_refused "$rc" "$err"; then break; fi
    done
    if board_ssh_refused "$rc" "$err"; then
        cat >&2 <<MSG
The board is back at $a, and it refuses the login this command began with.

The setting was written - it is read back above, from before the reboot. What
did not survive the reboot is the login: on the Buildroot root /root is a RAM
disk, and a key that was not also saved in /mnt/jffs2 is gone. Put it back,
this time to stay:

    BOARD=$a ./devkit ssh-key

NOT DONE: the look at what the board came up with. After ssh-key:

    BOARD=$a ./devkit net
MSG
        exit 3
    fi
    echo "It answers by name but not over ssh yet (${err:-ssh exit $rc}). Give it a moment, then:" >&2
    echo "    BOARD=$a ./devkit net" >&2
    exit 1
}

cmd="${1:-show}"; shift || true
case "$cmd" in
    show|"")
        rc=0; b=$(resolve_board) || rc=$?
        [ "$rc" -eq 2 ] && exit 2          # board_ssh_require has said what to do
        if [ "$rc" -ne 0 ]; then
            # `paste -sd" " -`: BSD paste reads stdin only when given the "-".
            echo "cannot reach the board over ssh (tried ${BOARD:-$(python3 "$HERE/board_addr.py" --list 2>/dev/null | paste -sd" " -)})" >&2
            command -v sshpass >/dev/null 2>&1 || board_ssh_hint
            exit 1
        fi
        show "$b" ;;

    dhcp)
        need_board
        refuse_on_debian "$b" "clearing ipaddr_eth" \
            "ssh root@$b" \
            "\$EDITOR /etc/network/interfaces   # iface eth0 inet dhcp" \
            "systemctl restart networking"
        echo "Switching eth0 to DHCP. The address you are on now will change."
        set_and_reboot "$b" \
            'fw_setenv ipaddr_eth; fw_setenv netmask_eth' \
            'fw_printenv ipaddr_eth 2>&1; fw_printenv netmask_eth 2>&1' \
            "$(on_board "$b" hostname)"
        echo
        hn=$(on_board "$b" hostname 2>/dev/null || echo fishball)
        echo "Reach it as  root@$hn.local  or the libiio URI  ip:$hn.local"
        ;;

    static)
        ip="${1:-}"; mask="${2:-255.255.255.0}"
        [ -n "$ip" ] || { echo "usage: ./devkit net static <ip> [netmask]" >&2; exit 2; }
        need_board
        refuse_on_debian "$b" "a static address via fw_setenv" \
            "ssh root@$b" \
            "\$EDITOR /etc/network/interfaces" \
            "    iface eth0 inet static" \
            "        address $ip" \
            "        netmask $mask" \
            "        gateway <your router>" \
            "systemctl restart networking"
        cat <<'WARN'
Note what a static address on this board does NOT come with: the generated
config carries an address and a netmask and nothing else, so there is no
default route and no /etc/resolv.conf. The board will reach its own subnet and
nothing beyond it. A DHCP reservation on your router gives you a fixed address
AND a working gateway - prefer that if you can.
WARN
        set_and_reboot "$b" \
            "fw_setenv ipaddr_eth $ip; fw_setenv netmask_eth $mask" \
            'fw_printenv ipaddr_eth netmask_eth 2>&1' \
            "$(on_board "$b" hostname)"
        ;;

    name)
        n="${1:-}"
        [ -n "$n" ] || { echo "usage: ./devkit net name <hostname>" >&2; exit 2; }
        need_board
        refuse_on_debian "$b" "setting the hostname via fw_setenv" \
            "ssh root@$b hostnamectl set-hostname $n" \
            "# avahi picks the new name up immediately; no reboot needed"
        echo "The mDNS name follows the hostname, so this becomes $n.local."
        echo "Worth doing if you have more than one board: they all ship as 'pluto'."
        set_and_reboot "$b" "fw_setenv hostname $n" 'fw_printenv hostname 2>&1' "$n"
        ;;

    find)
        a=$(find_by_name "${1:-fishball}" || true)
        if [ -n "$a" ]; then
            echo "found at $a"
        else
            echo "not found by name; try a USB cable and root@192.168.2.1" >&2; exit 1
        fi ;;

    -h|--help|help)
        sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//' ;;

    *) echo "unknown: $cmd" >&2
       echo "usage: ./devkit net [show|dhcp|static <ip> [mask]|name <host>|find]" >&2; exit 2 ;;
esac
