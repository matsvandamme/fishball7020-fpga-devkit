#!/bin/bash
# Test the USB gadget scripts without a board.
#
#     # run from: anywhere (Linux or macOS)
#     ./firmware-modern/debian/tests/test-usb-gadget.sh
#
# overlay/usr/local/sbin/fishball-usb-gadget is run against a plain directory
# standing in for configfs, with the commands it calls (fw_printenv, mount,
# mountpoint, sha1sum, and fishball-usb-bind) replaced by stubs. That checks
# what the script decides and what it writes: which network function, in what
# order, with which MACs, and that it is bound again after a change.
# fishball-usb-mode is run the same way, with systemctl and fw_setenv stubbed.
# It does NOT check that a kernel accepts it or that a PC enumerates it; that
# needs a board. Then the DHCP server's packet handling (test_usb_dhcp.py).
#
# The board's /bin/sh is dash. The scripts are run with `sh`, and then the whole
# test again with `dash` if there is one (TEST_SH=dash runs only that).
#
# Exit 0 if everything passes, 1 otherwise.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SBIN="$HERE/../overlay/usr/local/sbin"
SH="${TEST_SH:-sh}"
command -v "$SH" >/dev/null || { echo "ERROR: no $SH to run the scripts with" >&2; exit 1; }
echo "== the scripts run by: $SH"
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
fail=0
ok()  { printf '  ok    %s\n' "$1"; }
bad() { printf '  FAIL  %s\n' "$1"; fail=1; }
check() { if eval "$2"; then ok "$1"; else bad "$1"; fi; }

# --- stubs ---------------------------------------------------------------
mkdir -p "$T/bin"
# fw_printenv -n <var>: the value from $T/env/<var>. Exit 0 and empty output
# when unset, as libubootenv's does.
# FW_HANG=1: a flash that never answers.
printf '#!/bin/sh\n[ -z "${FW_HANG:-}" ] || exec sleep 30\ncat "%s/env/$2" 2>/dev/null\nexit 0\n' "$T" > "$T/bin/fw_printenv"
# fw_setenv <var> [value]: no value deletes. FW_FAIL=1: it cannot write.
cat > "$T/bin/fw_setenv" <<STUB
#!/bin/sh
[ -z "\${FW_HANG:-}" ] || exec sleep 30
[ -z "\${FW_FAIL:-}" ] || exit 1
if [ \$# -ge 2 ]; then echo "\$2" > "$T/env/\$1"; else rm -f "$T/env/\$1"; fi
STUB
# macOS has no timeout(1); the board has (coreutils). Exit 124 when it had to
# kill, as the real one does.
command -v timeout >/dev/null || cat > "$T/bin/timeout" <<'STUB'
#!/bin/sh
t=$1; shift
"$@" & p=$!
( sleep "$t"; kill $p 2>/dev/null ) >/dev/null 2>&1 & w=$!
wait $p; rc=$?
kill $w 2>/dev/null
[ $rc -gt 128 ] && rc=124
exit $rc
STUB
# fishball-usb-bind: the real one needs a UDC. This one logs how it was called
# and what it found (the UDC file, the links), then binds. NO_BIND=1: it cannot.
cat > "$T/bin/fishball-usb-bind" <<STUB
#!/bin/sh
g="$T/cfg/usb_gadget/composite_gadget"
echo "bind \$* udc=[\$(cat "\$g/UDC" 2>/dev/null)] links=[\$(ls "\$g/configs/c.1" | tr '\n' ' ')]" >> "$T/bind.log"
[ -z "\${NO_BIND:-}" ] || exit 1
echo ci_hdrc.0 > "\$g/UDC"
STUB
# The gadget script as fishball-usb-mode calls it, run by \$SH.
printf '#!/bin/sh\nexec %s "%s/fishball-usb-gadget" "$@"\n' "$SH" "$SBIN" > "$T/bin/gadget"
# systemctl, for fishball-usb-mode: log the call; a restart of the gadget unit
# runs the gadget script, a restart of the bind unit the bind stub (systemd
# does nothing more than that with them).
cat > "$T/bin/systemctl" <<STUB
#!/bin/sh
echo "\$*" >> "$T/systemctl.log"
case "\$*" in *restart*fishball-usb-gadget.service*) "$T/bin/gadget" >/dev/null 2>&1 || exit 1 ;; esac
case "\$*" in *restart*fishball-usb-bind.service*)
    [ -n "\$(cat "$T/cfg/usb_gadget/composite_gadget/UDC" 2>/dev/null)" ] || "$T/bin/fishball-usb-bind" || exit 1 ;;
esac
exit 0
STUB
printf '#!/bin/sh\nexit 0\n' > "$T/bin/mount"
printf '#!/bin/sh\nexit 0\n' > "$T/bin/mountpoint"
# macOS has shasum but no sha1sum; the board has sha1sum.
command -v sha1sum >/dev/null || printf '#!/bin/sh\nexec shasum -a 1 "$@"\n' > "$T/bin/sha1sum"
# mkdir that refuses a function the "kernel" was built without (NO_FUNC=ncm),
# as configfs does.
cat > "$T/bin/mkdir" <<STUB
#!/bin/sh
for a in "\$@"; do
    case "\$a" in */functions/\${NO_FUNC:-none}.*) exit 1 ;; esac
done
exec /bin/mkdir "\$@"
STUB
# rmdir of a function: configfs removes its attribute files with it, a plain
# directory does not. KEEP_FUNC=1 makes it fail, as on a function still in use.
cat > "$T/bin/rmdir" <<STUB
#!/bin/sh
case "\$1" in */functions/*) [ -z "\${KEEP_FUNC:-}" ] || exit 1; exec rm -rf "\$1" ;; esac
exec /bin/rmdir "\$@"
STUB
chmod +x "$T/bin"/*

# run [VAR=value ...] [-- args]: a fresh run of the gadget script.
G="$T/cfg/usb_gadget/composite_gadget"
fresh() { rm -rf "$T/cfg" "$T/env" "$T/uEnv.txt" "$T/ffs" "$T/default" "$T/bind.log" "$T/systemctl.log"; mkdir -p "$T/cfg/usb_gadget" "$T/env"; echo 0123456789abcdef > "$T/serial"; }
# USB_ETHERNET_MODE is unset: a developer's own must not decide the result.
fenv() {
    env -u USB_ETHERNET_MODE PATH="$T/bin:$PATH" FISHBALL_CONFIGFS="$T/cfg" FISHBALL_UENV="$T/uEnv.txt" \
        FISHBALL_HW_SERIAL="$T/serial" FISHBALL_FFS="$T/ffs" FISHBALL_DEFAULTS="$T/default" \
        FISHBALL_USB_BIND="$T/bin/fishball-usb-bind" FISHBALL_USB_GADGET="$T/bin/gadget" "$@"
}
run() { fenv "$@" "$SH" "$SBIN/fishball-usb-gadget" > "$T/out" 2> "$T/err"; }
show() { fenv "$@" "$SH" "$SBIN/fishball-usb-gadget" --show 2>"$T/err" | cut -d' ' -f1; }
# usbmode [VAR=value ...] -- [args]: fishball-usb-mode.
usbmode() {
    local e=()
    while [ "$1" != -- ]; do e+=("$1"); shift; done; shift
    fenv ${e[@]+"${e[@]}"} "$SH" "$SBIN/fishball-usb-mode" "$@" > "$T/out" 2> "$T/err"
}
binds() { if [ -f "$T/bind.log" ]; then wc -l < "$T/bind.log" | tr -d ' '; else echo 0; fi; }
funcs() { ls "$G/functions" | tr '\n' ' '; }
# The links in creation order, which is the interface order. Directory order is
# not creation order, so sort by the link's own timestamp is no use either: the
# script is traced instead.
order() { fenv "$@" "$SH" -x "$SBIN/fishball-usb-gadget" 2>&1 \
            | sed -n 's|^+ ln -sf .*/functions/\([a-z_.0-9]*\) .*|\1|p' | tr '\n' ' '; }

echo "-- the default is unchanged: RNDIS"
fresh; run; rc=$?
check "exit 0"                                   '[ $rc -eq 0 ]'
check "not bound here: at boot that waits for iiod (fishball-usb-bind)" '[ "$(binds)" = 0 ]'
check "functions are rndis.0, acm.usb0, ffs.iio_ffs" '[ "$(funcs)" = "acm.usb0 ffs.iio_ffs rndis.0 " ]'
check "the configuration is named RNDIS/ACM/IIOUSBD" '[ "$(cat "$G/configs/c.1/strings/0x409/configuration")" = RNDIS/ACM/IIOUSBD ]'
check "the factory IDs"                          '[ "$(cat "$G/idVendor")" = 0x0456 ] && [ "$(cat "$G/idProduct")" = 0xb673 ]'
# sha1("0123456789abcdef\n") = 2a2b8abb2ca2...: the MACs every mode must keep.
sha=$(printf '0123456789abcdef\n' | { sha1sum 2>/dev/null || shasum -a 1; } | cut -c1-12)
want_host="00:E0:22:$(echo "$sha" | cut -c1-2):$(echo "$sha" | cut -c3-4):$(echo "$sha" | cut -c5-6)"
want_dev="00:05:F7:$(echo "$sha" | cut -c7-8):$(echo "$sha" | cut -c9-10):$(echo "$sha" | cut -c11-12)"
check "host_addr is 00:E0:22 + sha1(hw_serial)"  '[ "$(cat "$G/functions/rndis.0/host_addr")" = "$want_host" ]'
check "dev_addr is 00:05:F7 + sha1(hw_serial)"   '[ "$(cat "$G/functions/rndis.0/dev_addr")" = "$want_dev" ]'
check "all three functions are linked"           '[ -L "$G/configs/c.1/rndis.0" ] && [ -L "$G/configs/c.1/acm.usb0" ] && [ -L "$G/configs/c.1/ffs.iio_ffs" ]'
fresh
check "link order: network, console, libiio"     '[ "$(order)" = "rndis.0 acm.usb0 ffs.iio_ffs " ]'

echo "-- where the mode comes from"
fresh
check "nothing set -> rndis"                     '[ "$(show)" = rndis ]'
echo ncm > "$T/env/usb_ethernet_mode"
check "U-Boot variable ncm -> ncm"               '[ "$(show)" = ncm ]'
printf 'bootdelay=1\r\nusb_ethernet_mode = ecm\r\n' > "$T/uEnv.txt"
check "uEnv.txt wins over the U-Boot variable (CRLF, spaces)" '[ "$(show)" = ecm ]'
check "the environment file wins over both"      '[ "$(show USB_ETHERNET_MODE=rndis)" = rndis ]'
check "the old function-name form still works"   '[ "$(show USB_ETHERNET_MODE=ncm.usb0)" = ncm ]'
check "upper case is accepted"                   '[ "$(show USB_ETHERNET_MODE=NCM)" = ncm ]'
check "an unknown value is rndis, not an error"  '[ "$(show USB_ETHERNET_MODE=wifi)" = rndis ]'
printf '#usb_ethernet_mode=ncm\nxusb_ethernet_mode=ncm\n' > "$T/uEnv.txt"; rm -f "$T/env/usb_ethernet_mode"
check "a commented or look-alike uEnv line is ignored" '[ "$(show)" = rndis ]'

echo "-- /etc/default/fishball-usb-gadget, read as systemd reads it"
fresh; echo ecm > "$T/env/usb_ethernet_mode"
echo 'USB_ETHERNET_MODE=ncm' > "$T/default"
check "the file is read when systemd has not (run by hand)" '[ "$(show)" = ncm ]'
check "and wins over the U-Boot variable"        '[ "$(fenv "$SH" "$SBIN/fishball-usb-gadget" --show)" = "ncm USB_ETHERNET_MODE in $T/default" ]'
printf '# USB_ETHERNET_MODE=ncm\n;USB_ETHERNET_MODE=ncm\nOTHER=1\n' > "$T/default"
check "commented lines are not assignments"      '[ "$(show)" = ecm ]'
printf 'USB_ETHERNET_MODE=ncm\n  USB_ETHERNET_MODE = "rndis"  \r\n' > "$T/default"
check "the last assignment wins; spaces, quotes and CR go" '[ "$(show)" = rndis ]'
# The finding: a shell reads this as ncm, systemd as "ncm # for the Mac".
echo 'USB_ETHERNET_MODE=ncm # for the Mac' > "$T/default"
from_file=$(show); file_err=$(cat "$T/err")
from_systemd=$(show "USB_ETHERNET_MODE=ncm # for the Mac"); systemd_err=$(cat "$T/err")
check "a trailing comment: the same answer by hand as under systemd" '[ "$from_file" = "$from_systemd" ] && [ "$from_file" = rndis ]'
check "and the same complaint, naming the value" '[ "$file_err" = "$systemd_err" ] && echo "$file_err" | grep -qi "ncm # for the Mac"'
usbmode --; rc=$?
check "fishball-usb-mode shows that answer too"  '[ $rc -eq 0 ] && grep -q "^set:      rndis " "$T/out"'
check "fishball-usb-mode does not source the file" '! grep -q "^[^#]*\. */etc/default" "$SBIN/fishball-usb-mode"'
check "the file says a trailing comment is not allowed" 'grep -qi "comment at the end of the line is NOT allowed" "$HERE/../overlay/etc/default/fishball-usb-gadget"'

echo "-- a flash that does not answer"
fresh; s0=$SECONDS
check "fw_printenv hanging: rndis, not a hang"   '[ "$(show FW_HANG=1)" = rndis ] && [ $((SECONDS - s0)) -lt 15 ]'
run FW_HANG=1; rc=$?
check "and the gadget is still created"          '[ $rc -eq 0 ] && [ -L "$G/configs/c.1/rndis.0" ] && [ $((SECONDS - s0)) -lt 25 ]'
check "the gadget unit has a start timeout"      'grep -q "^TimeoutStartSec=[0-9]" "$HERE/../overlay/etc/systemd/system/fishball-usb-gadget.service"'

echo "-- ncm and ecm"
for m in ncm ecm; do
    fresh; run USB_ETHERNET_MODE=$m
    upper=$(echo $m | tr a-z A-Z)
    check "$m: functions are $m.usb0, acm.usb0, ffs.iio_ffs" '[ "$(funcs)" = "acm.usb0 ffs.iio_ffs $m.usb0 " ] || [ "$(funcs)" = "acm.usb0 $m.usb0 ffs.iio_ffs " ]'
    check "$m: no rndis function"                '[ ! -e "$G/functions/rndis.0" ]'
    check "$m: the same MACs as rndis"           '[ "$(cat "$G/functions/$m.usb0/host_addr")" = "$want_host" ] && [ "$(cat "$G/functions/$m.usb0/dev_addr")" = "$want_dev" ]'
    check "$m: the configuration is named $upper/ACM/IIOUSBD" '[ "$(cat "$G/configs/c.1/strings/0x409/configuration")" = "$upper/ACM/IIOUSBD" ]'
    fresh
    check "$m: link order: network, console, libiio" '[ "$(order USB_ETHERNET_MODE=$m)" = "$m.usb0 acm.usb0 ffs.iio_ffs " ]'
done

echo "-- a kernel without the function falls back to RNDIS"
fresh; run USB_ETHERNET_MODE=ncm NO_FUNC=ncm; rc=$?
check "exit 0"                                   '[ $rc -eq 0 ]'
check "it says so"                               'grep -q "falling back to rndis" "$T/err"'
check "the gadget is the RNDIS one"              '[ -L "$G/configs/c.1/rndis.0" ] && [ ! -e "$G/functions/ncm.usb0" ] && [ "$(cat "$G/configs/c.1/strings/0x409/configuration")" = RNDIS/ACM/IIOUSBD ]'
check "with its MACs"                            '[ "$(cat "$G/functions/rndis.0/host_addr")" = "$want_host" ]'

echo "-- changing the mode of a gadget that exists"
fresh; run; echo ci_hdrc.0 > "$G/UDC"
run USB_ETHERNET_MODE=ncm; rc=$?
check "exit 0"                                   '[ $rc -eq 0 ]'
check "rndis.0 is gone, ncm.usb0 is there"       '[ ! -e "$G/functions/rndis.0" ] && [ ! -e "$G/configs/c.1/rndis.0" ] && [ -L "$G/configs/c.1/ncm.usb0" ]'
check "it was unbound first, and bound again with the new function linked" 'grep -q "^bind --no-wait udc=\[\] links=\[.*ncm\.usb0.*\]$" "$T/bind.log" && ! grep -q "rndis" "$T/bind.log"'
check "bound again once, and bound now"          '[ "$(binds)" = 1 ] && [ "$(cat "$G/UDC")" = ci_hdrc.0 ]'
check "console and libiio are linked again"      '[ -L "$G/configs/c.1/acm.usb0" ] && [ -L "$G/configs/c.1/ffs.iio_ffs" ]'
check "the name follows"                         '[ "$(cat "$G/configs/c.1/strings/0x409/configuration")" = NCM/ACM/IIOUSBD ]'
check "and back, relinked in order: network, console, libiio" '[ "$(order)" = "rndis.0 acm.usb0 ffs.iio_ffs " ]'
check "bound again after that too"               '[ "$(cat "$G/UDC")" = ci_hdrc.0 ]'
rm -f "$T/bind.log"; run; rc=$?
check "same mode again: nothing touched, still bound, bind not called" '[ $rc -eq 0 ] && grep -q "already present" "$T/out" && [ "$(cat "$G/UDC")" = ci_hdrc.0 ] && [ "$(binds)" = 0 ]'
run USB_ETHERNET_MODE=ncm KEEP_FUNC=1; rc=$?
check "a function that cannot be removed is kept, linked, exit 0" '[ $rc -eq 0 ] && [ -L "$G/configs/c.1/rndis.0" ] && [ -L "$G/configs/c.1/acm.usb0" ] && [ -L "$G/configs/c.1/ffs.iio_ffs" ] && [ ! -e "$G/functions/ncm.usb0" ]'
check "and bound again, with its links back"     '[ "$(cat "$G/UDC")" = ci_hdrc.0 ] && grep -q "^bind --no-wait udc=\[\] links=\[.*rndis\.0.*\]$" "$T/bind.log"'
run USB_ETHERNET_MODE=ecm; rm -f "$T/bind.log"; run USB_ETHERNET_MODE=ncm NO_FUNC=ncm; rc=$?
check "a change to a missing function ends on RNDIS" '[ -L "$G/configs/c.1/rndis.0" ] && [ -L "$G/configs/c.1/acm.usb0" ] && [ ! -e "$G/functions/ecm.usb0" ] && [ ! -e "$G/functions/ncm.usb0" ]'
check "bound, exit 0"                            '[ $rc -eq 0 ] && [ "$(binds)" = 1 ] && [ "$(cat "$G/UDC")" = ci_hdrc.0 ]'
run USB_ETHERNET_MODE=ncm NO_BIND=1; rc=$?
check "a change that cannot bind again: exit 1, and it says so" '[ $rc -eq 1 ] && [ -z "$(cat "$G/UDC")" ] && grep -q "NOT bound" "$T/err"'
run USB_ETHERNET_MODE=rndis KEEP_FUNC=1 NO_BIND=1; rc=$?
check "the same when the old function is kept"   '[ $rc -eq 1 ] && grep -q "keeping it" "$T/err" && grep -q "NOT bound" "$T/err"'

echo "-- no serial"
fresh; rm -f "$T/serial"; run; rc=$?
check "no gadget yet: exit 1 without hw_serial (as before)" '[ $rc -eq 1 ] && [ ! -d "$G" ]'
fresh; run; echo ci_hdrc.0 > "$G/UDC"; rm -f "$T/serial"
run; rc=$?
check "a restart with the gadget up: exit 0, left alone (as before)" '[ $rc -eq 0 ] && [ "$(cat "$G/UDC")" = ci_hdrc.0 ] && [ -L "$G/configs/c.1/rndis.0" ] && [ "$(binds)" = 0 ]'
run USB_ETHERNET_MODE=ncm; rc=$?
check "even when the mode differs: exit 0, still bound, still rndis" '[ $rc -eq 0 ] && [ "$(cat "$G/UDC")" = ci_hdrc.0 ] && [ -L "$G/configs/c.1/rndis.0" ] && [ ! -e "$G/functions/ncm.usb0" ] && [ "$(binds)" = 0 ]'

echo "-- fishball-usb-mode"
fresh; run; echo ci_hdrc.0 > "$G/UDC"
usbmode -- ncm; rc=$?
check "ncm: exit 0, stored in the U-Boot environment" '[ $rc -eq 0 ] && [ "$(cat "$T/env/usb_ethernet_mode")" = ncm ]'
check "it restarts both units, and waits for them" 'grep -qx "restart fishball-usb-gadget.service fishball-usb-bind.service" "$T/systemctl.log"'
check "the gadget runs ncm and is bound"         '[ -L "$G/configs/c.1/ncm.usb0" ] && [ ! -e "$G/functions/rndis.0" ] && [ "$(cat "$G/UDC")" = ci_hdrc.0 ] && grep -q "now runs ncm" "$T/out"'
usbmode -- ; rc=$?
check "it shows set and running"                 '[ $rc -eq 0 ] && grep -q "^set:      ncm " "$T/out" && grep -q "^running:  ncm  (ncm.usb0, bound)" "$T/out"'
usbmode -- rndis; rc=$?
check "rndis: the variable is deleted, the gadget follows" '[ $rc -eq 0 ] && [ ! -e "$T/env/usb_ethernet_mode" ] && [ -L "$G/configs/c.1/rndis.0" ] && [ "$(cat "$G/UDC")" = ci_hdrc.0 ]'
rm -f "$T/systemctl.log"; usbmode -- ecm --no-apply; rc=$?
check "--no-apply stores and restarts nothing"   '[ $rc -eq 0 ] && [ "$(cat "$T/env/usb_ethernet_mode")" = ecm ] && [ ! -e "$T/systemctl.log" ] && [ -L "$G/configs/c.1/rndis.0" ]'
usbmode NO_BIND=1 -- ncm; rc=$?
check "a gadget left unbound: exit 1, FAILED"    '[ $rc -eq 1 ] && grep -q "FAILED" "$T/err" && grep -q "NOT bound" "$T/err"'
echo ci_hdrc.0 > "$G/UDC"; usbmode -- rndis
usbmode NO_FUNC=ecm -- ecm; rc=$?
check "a function the kernel lacks: exit 1, FAILED, still bound" '[ $rc -eq 1 ] && grep -q "FAILED.*runs rndis" "$T/err" && [ "$(cat "$G/UDC")" = ci_hdrc.0 ]'
usbmode -- rndis; echo 'USB_ETHERNET_MODE=ecm' > "$T/default"
usbmode -- ncm; rc=$?
check "a higher place decides: exit 1, and it names it" '[ $rc -eq 1 ] && grep -q "the gadget will use ecm, from USB_ETHERNET_MODE in" "$T/err"'
rm -f "$T/default" "$T/systemctl.log"; usbmode -- rndis; rm -f "$T/systemctl.log"
usbmode FW_FAIL=1 -- ncm; rc=$?
check "fw_setenv failing: exit 1, nothing restarted" '[ $rc -eq 1 ] && [ ! -e "$T/systemctl.log" ] && [ -L "$G/configs/c.1/rndis.0" ]'
check "and it names the two other places"        'grep -q "usb_ethernet_mode=ncm .*in /boot/uEnv.txt" "$T/err" && grep -q "USB_ETHERNET_MODE=ncm .*in /etc/default/fishball-usb-gadget" "$T/err"'
s0=$SECONDS; usbmode FW_HANG=1 -- ncm --no-apply; rc=$?
check "fw_setenv hanging: exit 1, not a hang"    '[ $rc -eq 1 ] && [ $((SECONDS - s0)) -lt 15 ] && grep -q "fw_setenv failed" "$T/err"'
usbmode -- wifi; rc=$?
check "an unknown mode: usage, exit 2"           '[ $rc -eq 2 ] && grep -q "fishball-usb-mode ncm" "$T/err"'

echo "-- the other scripts"
check "fishball-usb-bind starts the DHCP server" 'grep -q "restart fishball-usb-dhcp.service" "$SBIN/fishball-usb-bind"'
check "fishball-usb-mode parses"                 '"$SH" -n "$SBIN/fishball-usb-mode"'
check "fishball-usb-gadget and fishball-usb-bind parse" '"$SH" -n "$SBIN/fishball-usb-gadget" && "$SH" -n "$SBIN/fishball-usb-bind"'
check "the gadget unit reads /etc/default/fishball-usb-gadget" 'grep -q "^EnvironmentFile=-/etc/default/fishball-usb-gadget$" "$HERE/../overlay/etc/systemd/system/fishball-usb-gadget.service"'
check "every script is executable"               '[ -x "$SBIN/fishball-usb-gadget" ] && [ -x "$SBIN/fishball-usb-mode" ] && [ -x "$SBIN/fishball-usb-dhcp" ]'

echo "-- the DHCP server"
if PYTHONDONTWRITEBYTECODE=1 python3 "$HERE/test_usb_dhcp.py" > "$T/py" 2>&1; then ok "test_usb_dhcp.py ($(tail -3 "$T/py" | grep -o 'Ran [0-9]* tests'))"
else bad "test_usb_dhcp.py"; cat "$T/py"; fi

echo
if [ "$fail" -eq 0 ]; then echo "all checks passed ($SH)"; else echo "FAILED ($SH)"; fi
# Once more with dash, the board's /bin/sh, unless this run was asked for one shell.
if [ -z "${TEST_SH:-}" ] && command -v dash >/dev/null; then
    TEST_SH=dash "${BASH_SOURCE[0]}" || fail=1
fi
exit "$fail"
