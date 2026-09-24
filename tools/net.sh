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
# so it survives ./devkit flash --all and is invisible to anything that looks at
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
# Full background: docs/networking.md
set -euo pipefail

PASS="${BOARD_PASS:-analog}"
command -v sshpass >/dev/null || { echo "need sshpass (sudo apt install sshpass)" >&2; exit 2; }

# Same reasoning as flash.sh: every board ships as 192.168.2.1 and each keeps
# its own host key, so a second board would otherwise trip a "changed key"
# warning that sshpass hides.
SSH_OPTS=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
          -o LogLevel=ERROR -o ConnectTimeout=8)

# Where is it? BOARD wins; otherwise try the name before the USB address,
# because this is the command you run when you do not know the address.
resolve_board() {
    local cands=()
    [ -n "${BOARD:-}" ] && cands=("$BOARD") || cands=(pluto.local 192.168.2.1)
    for c in "${cands[@]}"; do
        if sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "root@$c" true 2>/dev/null; then
            echo "$c"; return 0
        fi
    done
    return 1
}

on_board() { sshpass -p "$PASS" ssh "${SSH_OPTS[@]}" "root@$1" "$2"; }

# avahi-resolve is the direct question; iio_info -s answers it too, via the
# board's own service advertisement, and is present on any machine that can
# already talk to the radio.
find_by_name() {
    local a
    if command -v avahi-resolve >/dev/null 2>&1; then
        a=$(timeout 6 avahi-resolve -n "${1:-pluto}.local" 2>/dev/null | awk '{print $2}')
        [ -n "$a" ] && { echo "$a"; return 0; }
    fi
    if command -v iio_info >/dev/null 2>&1; then
        a=$(timeout 15 iio_info -s 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -1)
        [ -n "$a" ] && { echo "$a"; return 0; }
    fi
    return 1
}

show() {
    local b="$1"
    echo "== $b =="
    on_board "$b" '
      h=$(hostname)
      mode=$(fw_printenv ipaddr_eth 2>/dev/null | cut -d= -f2)
      echo "   name          $h  ->  $h.local"
      if [ -n "$mode" ]; then
        echo "   eth0          STATIC $mode / $(fw_printenv netmask_eth 2>/dev/null | cut -d= -f2)"
      else
        echo "   eth0          DHCP (ipaddr_eth is unset, which is what selects it)"
      fi
      echo "   address now   $(ip -4 -o addr show eth0 2>/dev/null | awk "{print \$4}")"
      echo "   default route $(ip route 2>/dev/null | awk "/^default/{print \$3}" || true)"
      echo "   nameserver    $(awk "/nameserver/{print \$2}" /etc/resolv.conf 2>/dev/null | tr "\n" " ")"
      echo "   usb0 fallback $(ip -4 -o addr show usb0 2>/dev/null | awk "{print \$4}")"
    '
}

# Write, read back, and only then reboot. fw_setenv reports success on a write
# it did not make if the environment is not where fw_env.config says it is.
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
    local name="${3:-pluto}" a=""
    for _ in $(seq 1 14); do
        a=$(find_by_name "$name" || true)
        [ -n "$a" ] && break
        printf '.'; sleep 8
    done
    echo
    if [ -z "$a" ]; then
        cat >&2 <<'MSG'
The board did not answer by name within two minutes. It is probably fine - mDNS
needs avahi on THIS machine, and some networks block multicast. Ways back in:
  * USB cable, then ssh root@192.168.2.1 - usb0 keeps its own address whatever
    Ethernet is doing, so this always works
  * your router's DHCP lease table; the board's MAC starts 00:0a:35
  * the serial console on the DEBUG port, 115200 baud
MSG
        exit 1
    fi
    echo "found it: $name.local is $a"
    echo
    show "$name.local" 2>/dev/null || show "$a"
}

cmd="${1:-show}"; shift || true
case "$cmd" in
    show|"")
        b=$(resolve_board) || { echo "cannot reach the board (tried ${BOARD:-pluto.local and 192.168.2.1})" >&2; exit 1; }
        show "$b" ;;

    dhcp)
        b=$(resolve_board) || { echo "cannot reach the board" >&2; exit 1; }
        echo "Switching eth0 to DHCP. The address you are on now will change."
        set_and_reboot "$b" \
            'fw_setenv ipaddr_eth; fw_setenv netmask_eth' \
            'fw_printenv ipaddr_eth 2>&1; fw_printenv netmask_eth 2>&1' \
            "$(on_board "$b" hostname)"
        echo
        echo "Reach it as  root@pluto.local  or the libiio URI  ip:pluto.local"
        ;;

    static)
        ip="${1:-}"; mask="${2:-255.255.255.0}"
        [ -n "$ip" ] || { echo "usage: ./devkit net static <ip> [netmask]" >&2; exit 2; }
        b=$(resolve_board) || { echo "cannot reach the board" >&2; exit 1; }
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
        b=$(resolve_board) || { echo "cannot reach the board" >&2; exit 1; }
        echo "The mDNS name follows the hostname, so this becomes $n.local."
        echo "Worth doing if you have more than one board: they all ship as 'pluto'."
        set_and_reboot "$b" "fw_setenv hostname $n" 'fw_printenv hostname 2>&1' "$n"
        ;;

    find)
        a=$(find_by_name "${1:-pluto}" || true)
        if [ -n "$a" ]; then
            echo "${1:-pluto}.local is $a"
        else
            echo "not found by name; try a USB cable and root@192.168.2.1" >&2; exit 1
        fi ;;

    -h|--help|help)
        sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//' ;;

    *) echo "unknown: $cmd" >&2
       echo "usage: ./devkit net [show|dhcp|static <ip> [mask]|name <host>|find]" >&2; exit 2 ;;
esac
