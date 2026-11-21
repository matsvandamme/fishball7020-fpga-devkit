#!/bin/bash
# What the bootloader must still do after you replace it.
#
#     # run from: the repo root
#     ./tools/uboot-contract.sh            # check the running board
#     ./tools/uboot-contract.sh --save     # record today's answers as the baseline
#
# WHY THIS EXISTS
#
# U-Boot here is 2016.07, and replacing it with mainline is a reasonable thing to
# want. The danger is not that the board fails to boot - you find that out
# immediately. It is that it boots perfectly and quietly stops doing one of the
# half-dozen other jobs the bootloader has on this board, none of which a boot
# test exercises. The worst case is `ethaddr`: lose it and the Ethernet MAC goes
# random every boot, which is the exact defect firmware/patches/0013 exists to
# fix, and the symptom appears days later as "the router keeps giving it a new
# address".
#
# So: run this BEFORE touching the bootloader, with --save. Run it after. Diff.
#
# It checks what is observable from Linux. The things that are not - whether
# `preboot` ran, what `modeboot` was - are inferred from their consequences,
# which is the honest way round: a variable being readable proves more than a
# log line saying it was read.
#
# WHAT IT DOES NOT COVER, deliberately:
#   - the QSPI/DFU boot paths. Nothing here uses them, `./devkit flash` is the
#     supported route, and DFU has bricked units on this board.
#   - whether U-Boot itself has a network stack. It does not
#     (`# CONFIG_NET is not set`), and nothing needs it to.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASELINE="${BASELINE:-$HERE/../firmware-modern/baseline/uboot-contract.txt}"
SAVE=0
[ "${1:-}" = "--save" ] && SAVE=1
[ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ] && {
    sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0; }

# Login is tools/lib/board-ssh.sh: the key ./devkit ssh-key makes, then the
# password through sshpass where that is installed.
BOARD_SSH_CONNECT_TIMEOUT=8
. "$HERE/lib/board-ssh.sh"
board_ssh_require || exit 2

board=""
for c in ${BOARD:-} $(python3 "$HERE/board_addr.py" --list 2>/dev/null) fishball.local 192.168.2.1; do
    board_ssh "$c" true 2>/dev/null && { board="$c"; break; }
done
[ -n "$board" ] || { echo "cannot reach the board" >&2
                     command -v sshpass >/dev/null 2>&1 || board_ssh_hint; exit 1; }

# NOTE the `|| true`. ssh returns the REMOTE command's exit status, and several
# reads here legitimately exit non-zero - `grep -c` with no match is 1, and
# fw_printenv on an unset variable is non-zero on Buildroot. Without this, set -e
# kills the script partway through and it looks like a passing run that simply
# stopped printing. That happened on the first version of this file.
on() { board_ssh "$board" "$1" 2>/dev/null || true; }

fails=0
report=""
# check = must have a value. An empty one is a failure.
check() {   # name, value, "what is broken if this is empty"
    printf '  %-26s %s\n' "$1" "${2:-<empty>}"
    report="${report}$1=$2"$'\n'
    [ -n "${2:-}" ] || { echo "      ^ EMPTY - $3" >&2; fails=$((fails+1)); }
}
# note = may legitimately be empty, and usually is. Recorded so the DIFF against
# the baseline catches a change, without crying wolf on a healthy board. Getting
# this the wrong way round would make the tool report a fault it had invented,
# which is worse than not having the tool.
note() {    # name, value, "what it does when it IS set"
    printf '  %-26s %s\n' "$1" "${2:-unset  ($3)}"
    report="${report}$1=$2"$'\n'
}

echo "== the bootloader contract, on $board =="
echo

echo "-- the QSPI environment is readable at all --"
# If fw_printenv cannot find the environment where /etc/fw_env.config says it is,
# every check below reads empty AND fw_setenv would report success on writes it
# never made. So this is the first thing, not a detail.
check fw_env_config  "$(on 'grep -v "^#" /etc/fw_env.config | tr -s " \t" " " | head -1')" \
    "no /etc/fw_env.config - fw_printenv cannot find the environment"
check mtd1_size      "$(on 'grep mtd1 /proc/mtd | tr -s " "')" \
    "mtd1 is missing; the kernel device tree must define the env partition"
check env_readable   "$(on 'fw_printenv 2>/dev/null | wc -l') vars" \
    "the environment read back as nothing"

echo
echo "-- variables that MUST survive --"
check ethaddr  "$(on 'fw_printenv -n ethaddr 2>/dev/null')" \
    "the Ethernet MAC becomes random every boot; a DHCP reservation is impossible"
check hostname "$(on 'fw_printenv -n hostname 2>/dev/null')" \
    "the board loses its mDNS name and answers to nothing you can predict"
check maxcpus  "$(on 'fw_printenv -n maxcpus 2>/dev/null')" \
    "patch 0001 sets this to 2; without it Linux may run on one core"
check ipaddr   "$(on 'fw_printenv -n ipaddr 2>/dev/null')" \
    "the USB fallback address; unset means the compiled-in default is in play"

echo
echo "-- optional overrides: unset is normal, a CHANGE is what matters --"
note rootfs_mode        "$(on 'fw_printenv -n rootfs_mode 2>/dev/null')" "= debian"
note tx_quiesce         "$(on 'fw_printenv -n tx_quiesce 2>/dev/null')" "quiesce runs"
note tx_led             "$(on 'fw_printenv -n tx_led 2>/dev/null')" "LED follows TX"
note xo_correction      "$(on 'fw_printenv -n xo_correction 2>/dev/null')" "no correction"
note iio_max_block_size "$(on 'fw_printenv -n iio_max_block_size 2>/dev/null')" "driver default"
note ipaddr_eth         "$(on 'fw_printenv -n ipaddr_eth 2>/dev/null')" "DHCP on eth0"
note ipaddr_host        "$(on 'fw_printenv -n ipaddr_host 2>/dev/null')" "USB DHCP default"

echo
echo "-- ethaddr is the one that fails silently --"
# The MAC has to MATCH, not merely exist. A random MAC is a working network
# interface that a DHCP reservation cannot pin.
mac=$(on 'cat /sys/class/net/eth0/address 2>/dev/null')
eth=$(on 'fw_printenv -n ethaddr 2>/dev/null')
printf '  %-26s %s\n' "eth0 MAC" "${mac:-<no eth0>}"
if [ -n "$eth" ] && [ "$mac" = "$eth" ]; then
    echo "      matches ethaddr - a DHCP reservation will hold"
else
    echo "      ^ eth0 is $mac but ethaddr is ${eth:-unset} - THE MAC IS NOT PINNED" >&2
    fails=$((fails+1))
fi
rnd=$(on 'dmesg 2>/dev/null | grep -c "invalid hw address"')
printf '  %-26s %s\n' "macb random-MAC warning" "${rnd:-?} occurrences"
[ "${rnd:-0}" = "0" ] || { echo "      ^ the driver improvised a MAC this boot" >&2; fails=$((fails+1)); }

echo
echo "-- the USB gadget name, which derives from the environment --"
# host_addr = sha1(hw_serial)[1..6]. If hw_serial or the derivation moves, the
# HOST's interface is renamed and any static address or NM profile bound to the
# old name stops working.
check hw_serial "$(on 'cat /mnt/jffs2/hw_serial 2>/dev/null')" \
    "no hw_serial - fishball-identity should have minted one; the gadget cannot come up"
check usb0_addr "$(on 'cat /sys/class/net/usb0/address 2>/dev/null')" \
    "usb0 absent - the gadget did not bind"

echo
echo "-- uEnv.txt is still being read, proved by its effect --"
# rootfs_mode is TESTED by the imported sdboot and never DEFINED in the file, so
# "which root am I on" is evidence that the import happened and the script ran.
rootfs=$(on 'grep -qi "^ID=debian" /etc/os-release && echo debian || echo buildroot')
mode=$(on 'fw_printenv -n rootfs_mode 2>/dev/null')
printf '  %-26s %s\n' "running rootfs" "$rootfs"
printf '  %-26s %s\n' "rootfs_mode says" "${mode:-unset (= debian)}"
want=debian; [ "$mode" = "ramdisk" ] && want=buildroot
if [ "$rootfs" = "$want" ]; then
    echo "      consistent - the imported sdboot honoured it"
else
    echo "      ^ rootfs_mode asks for $want and the board is on $rootfs" >&2
    echo "        either uEnv.txt was not imported, or sdboot ignored it" >&2
    fails=$((fails+1))
fi

echo
echo "-- the kernel command line, which sdboot sets on one path and not the other --"
check cmdline "$(on 'cat /proc/cmdline')" "no /proc/cmdline"

echo
echo "-- and the transmitter is still silent before userspace --"
# Not a bootloader job, but it is what a wrong device tree or a wrong boot
# argument would show up as, and it is the one failure with a cost outside the
# board.
for ch in 0 1; do
    check "tx${ch}_at_probe" "$(on "cat /sys/bus/iio/devices/iio:device0/out_voltage${ch}_hardwaregain 2>/dev/null")" \
        "cannot read the attenuation - is the driver up?"
done

echo
if [ "$SAVE" = "1" ]; then
    mkdir -p "$(dirname "$BASELINE")"
    { echo "# The bootloader contract as measured on $(date -u +%Y-%m-%dT%H:%M:%SZ)."
      # `strings` is NOT on the Debian rootfs (no binutils), so grep -a on the
      # BOOT.bin the board actually booted from. A bare "U-Boot .*" also matches
      # "U-Boot EFI: Relocation at", hence the shape of the pattern.
      echo "# Board: $board.  U-Boot: $(on 'grep -ao "U-Boot [A-Za-z]* ([A-Za-z]* [0-9]* [0-9]* - [0-9:]* [+0-9]*)" /boot/BOOT.bin | head -1')"
      echo "# Re-run tools/uboot-contract.sh and diff against this after changing the bootloader."
      echo "$report"; } > "$BASELINE"
    echo "baseline written: $BASELINE"
elif [ -f "$BASELINE" ]; then
    echo "-- against the recorded baseline --"
    ubc="${TMPDIR:-/tmp}/.ubc.$$"
    if diff <(grep -v '^#' "$BASELINE" | grep -v '^$') <(echo "$report" | grep -v '^$') > "$ubc" 2>&1; then
        echo "  identical to $BASELINE"
    else
        echo "  DIFFERS from the baseline:"; sed 's/^/    /' "$ubc"; fails=$((fails+1))
    fi
    rm -f "$ubc"
else
    echo "no baseline at $BASELINE - run with --save to record one"
fi

echo
if [ "$fails" = "0" ]; then echo "CONTRACT HELD ($board)"; else
    echo "$fails check(s) failed - see the lines marked ^ above" >&2; exit 1; fi
