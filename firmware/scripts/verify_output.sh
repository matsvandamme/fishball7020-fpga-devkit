#!/usr/bin/env bash
#
# Check that a build produced a complete, sane set of SD-card files, and
# report what is actually in the bitstream. Run it after build_all.sh and
# before you spend ten minutes flashing:
#
#     ./scripts/verify_output.sh            # run from firmware/
#     ./scripts/verify_output.sh --board    # ...and compare against the board
#
# --board answers a question nothing else here answers: is the board actually
# running what you just built? A board whose SD card holds a DIFFERENT build of
# the same size looks completely normal, and every symptom of that is
# indistinguishable from "my change did not work".
#
# Exits non-zero if anything is wrong, so CI can call it too.
#
set -uo pipefail

CHECK_BOARD=0
stale=0
ARGS=()
for a in "$@"; do
    case "$a" in
        --board) CHECK_BOARD=1 ;;
        *) ARGS+=("$a") ;;
    esac
done
FW=${ARGS[0]:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}
OUT=$FW/output
PRJ=$FW/src/hdl/projects/pluto

fail=0
ck() { if eval "$2" >/dev/null 2>&1; then printf '  \033[32mPASS\033[0m  %s\n' "$1"
       else printf '  \033[31mFAIL\033[0m  %s\n' "$1"; fail=1; fi; }
note() { printf '        %s\n' "$1"; }

echo "== SD-card files =="
for f in BOOT.bin devicetree.dtb uEnv.txt uImage uramdisk.image.gz; do
    ck "$f present and non-trivial" "[ -s '$OUT/$f' ] && [ \$(stat -c%s '$OUT/$f') -gt 1000 ]"
done
ck "no stray files in output/" "[ \$(ls -A '$OUT' | grep -cv '^\.gitkeep$') -eq 5 ]"

echo
echo "== FPGA design =="
if [ -r "$PRJ/utilization.rpt" ]; then
    dsp=$(sed -n '/^4\. DSP/,/^5\./p' "$PRJ/utilization.rpt" | awk '/^\| DSPs/{print $4}')
    lut=$(awk -F'|' '/^\| Slice LUTs /{gsub(/ /,"",$3); print $3; exit}' "$PRJ/utilization.rpt")
    ck "utilization report present" "true"
    note "DSP48s ${dsp:-?} / 220   Slice LUTs ${lut:-?} / 53200"
    # 72 is the stock filter (129 taps); the channelizer patch takes it to 96.
    case "$dsp" in
        72) note "-> stock filter" ;;
        96) note "-> channelizer filter (321 taps)" ;;
        *)  note "-> custom design" ;;
    esac
else
    ck "utilization report present ($PRJ/utilization.rpt)" "false"
fi

if grep -q 'rx_ddc' "$PRJ/system_bd.tcl" 2>/dev/null; then
    note "block design: rx_ddc (Fs/4 shifter) is wired in"
    ck "ad_fs4_ddc.v present alongside it" "[ -e '$PRJ/ad_fs4_ddc.v' ]"
else
    note "block design: stock RX path, no rx_ddc"
fi
coe=$(grep -o 'coefile[A-Za-z_0-9]*\.coe' "$PRJ/system_bd.tcl" 2>/dev/null | sort -u | tr '\n' ' ')
note "FIR coefficients: ${coe:-<none found>}"

echo
echo "== bitstream =="
# Exactly the file build_all.sh packages into BOOT.bin - never "the smallest
# .bit lying around", which once let a stale compressed one from an earlier
# build vouch for a fresh uncompressed one.
bit="$PRJ/pluto.runs/impl_1/system_top.bit"
if [ -n "$bit" ]; then
    sz=$(stat -c%s "$bit")
    # An uncompressed XC7Z020 bitstream is ~4.05 MB. Anything well under that
    # means BITSTREAM.GENERAL.COMPRESS took effect - which BOOT.bin needs, or
    # the FSBL runs out of OCM loading it.
    ck "compressed (${sz} B < 3.9 MB uncompressed)" "[ $sz -lt 3900000 ]"
else
    ck "bitstream found" "false"
fi

echo
echo "== timing =="
# A build that fails timing leaves timing.rpt where it was and writes a fresh
# report inside the run directory, so reading timing.rpt alone will happily
# vouch for an earlier build while the newest one has failed. That nearly put
# a bitstream on a board it was never built for.
newest_impl=$(ls -t "$PRJ"/pluto.runs/impl_1/*timing_summary_postroute*.rpt 2>/dev/null | head -1)
if [ -n "$newest_impl" ] && [ -r "$PRJ/timing.rpt" ]    && [ "$newest_impl" -nt "$PRJ/timing.rpt" ]; then
    ck "the reports describe the newest build" "false"
    note "a later build ran and did not finish: $(basename "$newest_impl") is newer"
    note "than timing.rpt, so everything below is from an earlier build."
    note "Check the build log before flashing any of this."
fi
if [ -r "$PRJ/timing.rpt" ]; then
    read -r wns _ tnsfail total < <(grep -A6 'Design Timing Summary' "$PRJ/timing.rpt" \
        | awk 'NF>=8 && $1 ~ /^-?[0-9.]+$/ {print $1, $2, $3, $4; exit}')
    ck "no failing setup endpoints" "[ '${tnsfail:-x}' = 0 ]"
    note "WNS ${wns:-?} ns over ${total:-?} endpoints"
else
    ck "timing report present ($PRJ/timing.rpt)" "false"
fi

if [ $CHECK_BOARD -eq 1 ]; then
    echo
    echo "== against the board =="
    BOARD=${BOARD:-192.168.2.1}
    PASS=${BOARD_PASS:-analog}
    if ! command -v sshpass >/dev/null 2>&1; then
        note "sshpass not installed - cannot compare (sudo apt install sshpass)"
    elif ! sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
            -o ConnectTimeout=8 "root@$BOARD" true 2>/dev/null; then
        note "no board at $BOARD - skipping the comparison"
    else
        if ! sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
                -o LogLevel=ERROR "root@$BOARD" \
                'mkdir -p /tmp/sd && mount -o ro /dev/mmcblk0p1 /tmp/sd' 2>/dev/null; then
            note "could not mount /dev/mmcblk0p1 on the board (still mounted from an interrupted flash? try: ssh root@$BOARD umount /tmp/sd)"
            stale=$((stale+1))
        else
        for f in BOOT.bin devicetree.dtb uEnv.txt uImage uramdisk.image.gz; do
            [ -r "$OUT/$f" ] || continue
            want=$(md5sum "$OUT/$f" | cut -d' ' -f1)
            got=$(sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR "root@$BOARD" \
                  "md5sum /tmp/sd/$f 2>/dev/null" | cut -d' ' -f1)
            if [ -z "$got" ]; then
                printf '  \033[33mSTALE\033[0m %s\n' "$f is not on the card"
                stale=$((stale+1))
            elif [ "$want" = "$got" ]; then
                printf '  \033[32mPASS\033[0m  %s\n' "$f on the card matches output/"
            else
                printf '  \033[33mSTALE\033[0m %s\n' "$f on the card differs from output/"
                note "card $got vs built $want"
                stale=$((stale+1))
            fi
        done
        sshpass -p "$PASS" ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
            -o LogLevel=ERROR "root@$BOARD" 'cd / && umount /tmp/sd' 2>/dev/null || true
        note "the card is what it BOOTS from; a reboot is still needed after flashing"
        fi
    fi
fi

echo
if [ $fail -ne 0 ]; then
    echo "PROBLEMS FOUND - do not flash this build."
elif [ $stale -ne 0 ]; then
    # The build is fine; the BOARD is behind. Different question, different
    # answer - saying "do not flash" here would be exactly backwards.
    echo "OK - output/ is ready to flash."
    echo "$stale file(s) on the board differ from this build: it is running older"
    echo "firmware. Update it with  ./devkit flash --all"
elif [ $CHECK_BOARD -eq 1 ]; then
    echo "OK - output/ is ready to flash, and the board is running it."
else
    # Say nothing about the board: without --board it was never looked at, and
    # stale=0 here only means "not checked".
    echo "OK - output/ is ready to flash."
fi
exit $fail
