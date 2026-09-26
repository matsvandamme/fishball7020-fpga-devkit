#!/bin/sh
# run from: the board, or push it there from the host. The board is found by
# name, so DHCP may move it - see tools/board_addr.py:
#   B=$(python3 tools/board_addr.py)
#   sshpass -p analog ssh root@$B 'cat > /tmp/tx-guard.sh' < tools/tx-guard.sh
#   sshpass -p analog ssh root@$B 'sh /tmp/tx-guard.sh <command>'
#
#   affirm <0|1>        record that THAT TX port is terminated (antenna or 50
#                       ohm load). Per channel, because channel 0 is TX1A and
#                       channel 1 is TX2A - two separate SMA ports. Stored in
#                       /tmp (tmpfs), so it cannot survive a reboot.
#   revoke [0|1|both]   drop the affirmation(s) and force maximum attenuation.
#   status              affirmations, attenuation, buffer state.
#   set-gain <0|1> <dB> write TX attenuation on ONE channel. Refused unless
#                       that channel is affirmed. dB is a decimal in
#                       [-89.75, 0]; 0 is full output, -89.75 is quiet.
#   reap                disable a TX DMA buffer left enabled with no owning
#                       process.
#
# Exit codes, all commands: 0 success / nothing to do; 1 usage or refused on
# validation; 3 refused for want of an affirmation; 4 a write or verification
# failed (treat the port as possibly live); 10 reap disabled a stale buffer;
# 11 reap found an owner and left it alone.
#
# == LIMITS. This raises the floor. It is not a lock. ==
#
#  1. Tool-level gate, not enforcement. Anything writing
#     out_voltageN_hardwaregain directly bypasses it completely.
#
#  2. The affirmation is an ordinary file in world-writable tmpfs. Any process
#     can forge it with `touch`. A forged flag is indistinguishable from a real
#     one and `status` reports it as genuine - worse than the sysfs bypass,
#     because it manufactures a false record that a human vouched for a port.
#
#  3. Paths that change TX attenuation without passing this gate.
#
#     (a) A direct write to out_voltageN_hardwaregain. Nothing stops it.
#
#     (b) *** echo 1 > /sys/kernel/debug/iio/iio:device0/initialize ***
#         DBGFS_INIT (ad9361.c:8312-8323) re-runs ad9361_setup(), which at
#         ad9361.c:5243 applies pd->tx_atten - adi,tx-attenuation-mdB, 10000
#         on this board - to BOTH channels in 2rx2tx mode. From a muted
#         -89.75 dB that is a ~79.75 dB raise to -10 dB, roughly +9 dBm at
#         the SMA, with no unmute, no buffer enable and no affirmation.
#         firmware/patches/0011 changes that constant to maximum attenuation
#         and closes this. It is NOT BUILT AND NOT FLASHED, so on the running
#         board this path is live.
#
#     (c) ad9361_tx_mute(phy, 0) restores a cached attenuation. It is NOT a
#         hazard you can observe from here, and an earlier version of this
#         comment wrongly said it was. cf_axi_dds.c:1201 gates it on
#         ad9361_tx_is_muted(); ad9361_conv.c:120 and :641 do not, but both
#         are BALANCED pairs whose mute half re-caches the current value
#         first (ad9361.c:1294-1296), so they restore what is already in
#         force. The sample-rate route is also mutex-protected -
#         write_raw holds phy->lock across dig_tune (ad9361.c:8005-8060) and
#         read_raw takes the same lock at :7908 - so a read from this tool
#         blocks and only ever sees the post-restore value.
#
#     (d) The gated restore is ARMED by being quiet: both channels at max is
#         exactly what ad9361_tx_is_muted() accepts, so the next buffer
#         enable restores the last stream's gain. That is patch 0005's
#         documented intent ("set nothing, and your last gain comes back"),
#         not a defect - but it is worth knowing before you assume a muted
#         board stays muted. This tool reports the armed state.
#
#  4. Nothing runs `reap` automatically. No init script or cron installs it.
#
#  5. `reap` does NOT cover case C (buffer open but starved - see
#     tools/IDLE-CASES.md). It reports that state and leaves it alone, because
#     an owning process may legitimately be mid-stream.
#
# == WHAT PATCH 0015 CHANGED, AND WHAT IS LEFT FOR THIS SCRIPT ==
#
# This script was written when the firmware genuinely left a killed transmitter
# live. firmware/patches/0015 fixed that in the driver: the transmitter is
# muted when the converter stops being fed - 250 ms by default, measured at
# 0.27 s from a kill - which covers case B AND case C, the one limit 5 above
# says `reap` cannot reach.
#
# On firmware with 0015, `reap` is a backstop rather than the mechanism. Check
# which you are on before relying on either:
#
#     # run on the board
#     cat /sys/bus/iio/devices/iio:device2/tx_starve_timeout_ms   # absent = stock
#
# What this script still does that the firmware does not:
#
#   - `affirm` / `revoke` - records that a human says a port is terminated.
#     No firmware can know that; see the note below about there being no
#     coupler and no detector.
#   - `set-gain` refuses to raise a port that has not been affirmed.
#   - `reap` on stock firmware, or on a CYCLIC stream, which 0015 exempts on
#     purpose: the hardware repeats one buffer forever, so a kill looks exactly
#     like a normal return and "no data arriving" describes a healthy stream.
#     tx_cyclic_timeout_ms bounds that, and is off by default.
#
# What the firmware now does better, because it cannot be bypassed or forged:
# 0016 adds tx_disable, a latch enforced inside ad9361_set_tx_atten() that
# debugfs cannot clear - so unlike limit 1 above, writing hardwaregain directly
# does not get around it.
#
# Antenna presence on TX cannot be measured on this board - no coupler, no
# detector. An affirmation records a human's word, the only evidence there is.

QUIET=-89.75
STEP_TOL=0.26          # AD9361 attenuator quantises to 0.25 dB; allow one step.
MAXLEN=16              # Bound the argument BEFORE anything else: a multi-page
                       # sysfs write is split by the kernel and its tail chunk
                       # can land as 0 dB (full output) from a string that
                       # reads as quiet to any numeric comparison here.

die()  { echo "tx-guard: $1" >&2; exit 1; }
# Exit 4: the radio could not be reached, so nothing was muted and the port may
# be live. Distinct from 1, which means the operator asked for something invalid.
die4() { echo "tx-guard: $1" >&2; echo "tx-guard: nothing was muted - TREAT THE PORT AS POSSIBLY LIVE" >&2; exit 4; }

find_dev() {
    for _d in /sys/bus/iio/devices/iio:device*; do
        [ "$(cat "$_d/name" 2>/dev/null)" = "$1" ] && { echo "$_d"; return 0; }
    done
    return 1
}

# Resolve by NAME, never by a hardcoded index - IIO enumeration can shift, and
# a wrong index makes `reap` report a false all-clear.
PHY=$(find_dev ad9361-phy) || die4 "no ad9361-phy found"
# NOT fatal: `revoke` is the emergency mute and needs only PHY. Commands that
# actually touch the DMA buffer check for it themselves.
TXDEV=$(find_dev cf-ad9361-dds-core-lpc) || TXDEV=""
[ -n "$TXDEV" ] && TXCHR="/dev/$(basename "$TXDEV")" || TXCHR=""
need_txdev() { [ -n "$TXDEV" ] || die4 "no cf-ad9361-dds-core-lpc found (needed for '$1')"; }

flag_for() { echo "/tmp/tx-antenna-affirmed.$1"; }

# The emergency mute. It must never fail silently - it is the last line.
force_quiet() {
    _fq=0
    for _c in 0 1; do
        echo "$QUIET" > "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null \
            || { echo "tx-guard: FORCE-QUIET WRITE FAILED ch$_c" >&2; _fq=1; continue; }
        _r=$(cat "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null); _r="${_r%% *}"
        if [ -z "$_r" ] || [ "$(awk -v b="$_r" -v q="$QUIET" -v t="$STEP_TOL" 'BEGIN{d=b-q; if(d<0)d=-d; print (d<=t)?1:0}')" != "1" ]; then
            echo "tx-guard: FORCE-QUIET UNVERIFIED ch$_c (read '$_r') - PORT MAY BE LIVE" >&2; _fq=1
        fi
    done
    return $_fq
}

# Write one channel and PROVE it landed. Any failure drives BOTH channels to
# maximum attenuation rather than leaving whatever landed on the hardware.
write_atten() {
    _ch="$1"; _v="$2"
    if ! echo "$_v" > "$PHY/out_voltage${_ch}_hardwaregain" 2>/dev/null; then
        echo "tx-guard: WRITE FAILED ch$_ch - forcing quiet" >&2
        force_quiet || echo "tx-guard: *** FAIL-SAFE ALSO FAILED - ASSUME TX IS LIVE ***" >&2
        return 1
    fi
    _rb=$(cat "$PHY/out_voltage${_ch}_hardwaregain" 2>/dev/null)
    _num="${_rb%% *}"
    if [ -z "$_num" ]; then
        echo "tx-guard: EMPTY READBACK ch$_ch - forcing quiet" >&2
        force_quiet || echo "tx-guard: *** FAIL-SAFE ALSO FAILED - ASSUME TX IS LIVE ***" >&2
        return 1
    fi
    case "$_num" in ''|*[!0-9.eE+-]*) echo "tx-guard: UNPARSABLE READBACK '$_rb' ch$_ch - forcing quiet" >&2
        force_quiet || echo "tx-guard: *** FAIL-SAFE ALSO FAILED - ASSUME TX IS LIVE ***" >&2
        return 1;; esac
    _ok=$(awk -v a="$_v" -v b="$_num" -v t="$STEP_TOL" 'BEGIN{d=a-b; if(d<0)d=-d; print (d<=t)?1:0}')
    if [ "$_ok" != "1" ]; then
        echo "tx-guard: READBACK MISMATCH ch$_ch: wrote $_v, read $_rb - forcing quiet" >&2
        force_quiet || echo "tx-guard: *** FAIL-SAFE ALSO FAILED - ASSUME TX IS LIVE ***" >&2
        return 1
    fi
    return 0
}

valid_channel() { case "$1" in 0|1) return 0;; *) return 1;; esac; }

# The kernel restores the cached gain at the next buffer enable only when BOTH
# attenuators read max. Report that state - it is the armed one.
# 0 = armed (both at max), 1 = not armed, 2 = UNKNOWN (a read failed).
# Never resolve unknown toward "not armed": that is the non-hazardous reading
# of the tool's own primary hazard.
#
# EXACT comparison, deliberately not STEP_TOL. This models the kernel predicate
# ad9361_tx_is_muted() (ad9361.c:1321-1325), which requires both attenuators to
# equal MAX_TX_ATTENUATION_DB exactly. One 0.25 dB step off max disarms the
# restore, so a tolerance here would report ARMED for a state the kernel reads
# as not muted. STEP_TOL answers a different question - "did my write land" -
# where the hardware quantum genuinely applies.
cache_restore_armed() {
    # Read BOTH channels before deciding. An earlier version returned "not
    # armed" as soon as one channel was off max, short-circuiting before it
    # ever tried the other - so an unreadable second attenuator was silently
    # reported as a known-safe state. Unknown must win over not-armed.
    _any_unreadable=0; _all_max=1
    for _c in 0 1; do
        _a=$(cat "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null); _a="${_a%% *}"
        if [ -z "$_a" ]; then _any_unreadable=1; continue; fi
        [ "$(awk -v b="$_a" -v q="$QUIET" 'BEGIN{print (b==q)?1:0}')" = "1" ] || _all_max=0
    done
    [ "$_any_unreadable" = "1" ] && return 2
    [ "$_all_max" = "1" ] && return 0
    return 1
}

warn_if_armed() {
    cache_restore_armed; _ca=$?
    if [ "$_ca" = "2" ]; then
        echo "tx-guard: WARNING - could not read the attenuators; cannot tell whether" >&2
        echo "tx-guard: the cache restore is armed (LIMIT 3). Treat TX as suspect." >&2
        return 0
    fi
    if [ "$_ca" = "0" ]; then
        echo "tx-guard: NOTE - both channels are at max attenuation, which is the"
        echo "tx-guard: state that ARMS the kernel cache restore (LIMIT 3). The next"
        echo "tx-guard: buffer enable may lift attenuation to the last stream's gain."
    fi
}

cmd="${1:-status}"

case "$cmd" in
  affirm)
    ch="$2"; valid_channel "$ch" || die "affirm needs a channel: 0 (TX1A) or 1 (TX2A)"
    # Write to a temp file and move it into place. A bare `> $FLAG` truncates
    # the target before printf runs, so a failed write would leave an EMPTY
    # flag that `[ -f ]` accepts - a failed affirm would open the gate.
    _tmp="$(flag_for "$ch").tmp.$$"
    if ! printf 'affirmed-at=%s\nchannel=%s\nby=%s\n' \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$ch" "${USER:-root}" > "$_tmp" 2>/dev/null \
       || [ ! -s "$_tmp" ]; then
        rm -f "$_tmp"; die "could not write affirmation - gate stays closed"
    fi
    mv -f "$_tmp" "$(flag_for "$ch")" || { rm -f "$_tmp"; die "could not install affirmation"; }
    echo "tx-guard: channel $ch affirmed as terminated. Dies at reboot (/tmp is tmpfs)."
    ;;
  revoke)
    [ $# -le 2 ] || die "revoke takes at most one argument (0, 1 or both); got: $*"
    ch="${2:-both}"
    case "$ch" in 0|1) _targets="$ch";; both) _targets="0 1";; *) die "revoke takes 0, 1 or both";; esac
    # Verify each flag is actually GONE. rm -f can fail (e.g. a directory at
    # that path) and reporting a closed gate that is still open is the exact
    # failure this command exists to prevent.
    for _t in $_targets; do
        rm -f "$(flag_for "$_t")" 2>/dev/null
        [ -e "$(flag_for "$_t")" ] && { echo "tx-guard: COULD NOT REMOVE ch$_t affirmation - GATE STILL OPEN" >&2; force_quiet; exit 4; }
    done
    force_quiet
    ok=1
    for c in 0 1; do
      rb=$(cat "$PHY/out_voltage${c}_hardwaregain" 2>/dev/null); n="${rb%% *}"
      [ -n "$n" ] && [ "$(awk -v b="$n" -v q="$QUIET" -v t="$STEP_TOL" 'BEGIN{d=b-q; if(d<0)d=-d; print (d<=t)?1:0}')" = "1" ] || ok=0
    done
    if [ "$ok" = "1" ]; then
      echo "tx-guard: revoked ch$ch; both channels verified quiet at $QUIET dB."
      warn_if_armed
    else
      echo "tx-guard: revoked but COULD NOT VERIFY mute - check the board" >&2; exit 4
    fi
    ;;
  status)
    for c in 0 1; do
      f=$(flag_for "$c")
      if [ -s "$f" ]; then
        echo "ch$c affirmation: PRESENT (a forged file is indistinguishable)"
        # Content is attacker-controllable (LIMIT 2): strip anything that is not
        # plain printable ASCII before showing it, so a forged flag cannot inject
        # terminal escapes or fake tool output into this report.
        tr -cd '\11\40-\176\n' < "$f" | sed 's/^/    | /'
        echo "    (content above is unverified input, not a tool assertion)"
      else echo "ch$c affirmation: ABSENT (raising ch$c will be refused)"; fi
    done
    for _c in 0 1; do
      _av=$(cat "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null)
      if [ -n "$_av" ]; then echo "atten$_c: $_av"
      else echo "atten$_c: UNREADABLE"; _status_bad=1; fi
    done
    if [ -n "$TXDEV" ]; then
      _be=$(cat "$TXDEV/buffer/enable" 2>/dev/null)
      if [ -n "$_be" ]; then echo "tx buffer/enable: $_be"
      else echo "tx buffer/enable: UNREADABLE - TX buffer state unknown"; _status_bad=1; fi
    else
      echo "tx buffer/enable: TX DMA device not found - state unknown"; _status_bad=1
    fi
    cache_restore_armed; _ca=$?
    case "$_ca" in
      0) echo "cache restore: ARMED (both channels at max - see LIMIT 3)";;
      1) echo "cache restore: not armed (a channel is off max)";;
      *) echo "cache restore: UNKNOWN - attenuator read failed"; _status_bad=1;;
    esac
    [ "${_status_bad:-0}" = "1" ] && exit 4
    exit 0
    ;;
  set-gain)
    ch="$2"; val="$3"
    valid_channel "$ch" || die "set-gain needs a channel first: 0 (TX1A) or 1 (TX2A)"
    [ -n "$val" ] || die "set-gain needs a value in dB, e.g. 'set-gain 0 -30'"
    # LENGTH FIRST - before any numeric reasoning. A value long enough to span
    # a page is split by the sysfs write path and its tail can apply as 0 dB.
    [ "${#val}" -le "$MAXLEN" ] || die "REFUSED - value is ${#val} chars, max $MAXLEN"
    echo "$val" | grep -Eq '^-?[0-9]{1,3}(\.[0-9]{1,4})?$' \
      || die "REFUSED - '$val' is not a plain decimal; expected e.g. -30 or -89.75"
    inrange=$(awk -v v="$val" 'BEGIN{print (v>=-89.75 && v<=0)?1:0}')
    [ "$inrange" = "1" ] || die "REFUSED - '$val' is outside [-89.75, 0]"
    louder=$(awk -v v="$val" -v q="$QUIET" 'BEGIN{print (v>q)?1:0}')
    # -s not -f: an empty flag is not an affirmation.
    if [ "$louder" != "0" ] && [ ! -s "$(flag_for "$ch")" ]; then
      echo "tx-guard: REFUSED - $val dB raises TX output on channel $ch and no" >&2
      echo "tx-guard: affirmation for THAT channel is on record. Channel 0 is" >&2
      echo "tx-guard: TX1A, channel 1 is TX2A - separate ports. Run" >&2
      echo "tx-guard: 'affirm $ch' only after confirming that port is terminated." >&2
      exit 3
    fi
    # Full-output warning: this board reaches about +19 dBm, and the receive
    # port is rated +2.5 dBm (docs/transmitter-safety.md). Through a 20 dB loop
    # that is only ~3.5 dB of margin at 0 dB attenuation.
    near_full=$(awk -v v="$val" 'BEGIN{print (v>-10)?1:0}')
    if [ "$near_full" = "1" ]; then
      echo "tx-guard: CAUTION - $val dB is within 10 dB of FULL OUTPUT (~+19 dBm)." >&2
      echo "tx-guard: Into a 20 dB loop that is about 3.5 dB under the +2.5 dBm" >&2
      echo "tx-guard: receive-port rating. Confirm the attenuation in the path." >&2
    fi
    if write_atten "$ch" "$val"; then
      echo "tx-guard: ch$ch attenuation verified at $(cat "$PHY/out_voltage${ch}_hardwaregain")"
      # NOT `[ ... ] && echo` here: as the last statement of this branch a false
      # test would leak exit 1, reporting failure on every successful quiet write.
      # Warn on the ARMED condition (both channels at max), not on loudness -
      # a loud value leaves is_muted() false and is the case that is NOT armed.
      warn_if_armed
      cache_restore_armed; [ $? = 2 ] && exit 4
      exit 0
    else
      exit 4
    fi
    ;;
  reap)
    need_txdev reap
    en=$(cat "$TXDEV/buffer/enable" 2>/dev/null)
    if [ -z "$en" ]; then
      echo "tx-guard: could not read $TXDEV/buffer/enable - TX state UNKNOWN" >&2
      force_quiet || echo "tx-guard: *** FAIL-SAFE ALSO FAILED - ASSUME TX IS LIVE ***" >&2
      exit 4
    fi
    if [ "$en" != "1" ]; then echo "tx-guard: buffer not enabled, nothing to reap"; exit 0; fi
    owner=""
    for p in /proc/[0-9]*; do
      for fd in "$p"/fd/*; do
        [ -e "$fd" ] || continue
        [ "$(readlink "$fd" 2>/dev/null)" = "$TXCHR" ] && { owner="${p#/proc/}"; break; }
      done
      [ -n "$owner" ] && break
    done
    # HEURISTIC: an open fd on the TX chardev is evidence of an owner, not
    # proof. A process can hold it open without having enabled the buffer, and
    # in principle a buffer can be enabled by a process that has since closed
    # it. Erring toward leaving a possibly-live stream alone.
    if [ -n "$owner" ]; then
      echo "tx-guard: buffer enabled, fd held by pid $owner - leaving alone (heuristic)."
      echo "tx-guard: if that owner is not streaming this is IDLE-CASES.md case C,"
      echo "tx-guard: NOT mitigated here - TX stays unmuted while that fd is held."
      echo "tx-guard: NOTE: a KILLED owner does not mute anything (measured case B);"
      echo "tx-guard: it just stops holding the fd. If you kill it, RE-RUN reap -"
      echo "tx-guard: it will then take the stale-buffer branch and mute."
      exit 11
    fi
    echo "tx-guard: STALE buffer - enabled with no owning process."
    # Mute BEFORE disabling. The kernel's postdisable hook snapshots whatever
    # attenuation it finds into the cache (ad9361.c:1294-1296) and then sets
    # max. Disabling first would therefore cache the dead stream's LOUD value
    # and leave the restore armed with it - this tool would be creating the
    # hazard it exists to remove. Muting first makes the cached value max, so
    # the later restore is a no-op. The kernel still mutes both channels to max
    # on stream stop exactly as before; only the snapshotted value changes.
    if force_quiet; then
        _premute=0; echo "tx-guard: muted first, now disabling the buffer."
    else
        _premute=1
        echo "tx-guard: *** PRE-DISABLE MUTE FAILED - ASSUME TX IS LIVE ***" >&2
        echo "tx-guard: PRE-DISABLE MUTE FAILED; the kernel will now cache the"
        echo "tx-guard: dead stream's gain. Disabling anyway, but this is NOT a"
        echo "tx-guard: clean reap."
    fi
    if ! echo 0 > "$TXDEV/buffer/enable" 2>/dev/null; then
      echo "tx-guard: COULD NOT DISABLE a stale enabled buffer" >&2
      force_quiet || echo "tx-guard: *** FAIL-SAFE ALSO FAILED - ASSUME TX IS LIVE ***" >&2
      exit 4
    fi
    sleep 1
    en2=$(cat "$TXDEV/buffer/enable" 2>/dev/null)
    # Check BOTH ports: channel 0 is TX1A, channel 1 is TX2A.
    ok=1
    for c in 0 1; do
      a=$(cat "$PHY/out_voltage${c}_hardwaregain" 2>/dev/null); an="${a%% *}"
      echo "tx-guard: atten$c=$a"
      [ -n "$an" ] && [ "$(awk -v b="$an" -v q="$QUIET" -v t="$STEP_TOL" 'BEGIN{d=b-q; if(d<0)d=-d; print (d<=t)?1:0}')" = "1" ] || ok=0
    done
    echo "tx-guard: buffer/enable=$en2"
    if [ "$en2" = "0" ] && [ "$ok" = "1" ]; then
      echo "tx-guard: reap verified - buffer down, both channels muted."
      warn_if_armed
      # The pre-disable mute is load-bearing: if it failed, the kernel cached
      # the dead stream's loud gain, so this is not a clean reap regardless of
      # what the attenuators read now.
      [ "${_premute:-0}" = "1" ] && exit 4
      exit 10
    fi
    echo "tx-guard: REAP DID NOT TAKE - forcing quiet" >&2; force_quiet; exit 4
    ;;
  *) die "unknown command '$cmd' (affirm|revoke|status|set-gain|reap)" ;;
esac
