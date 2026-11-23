#!/bin/sh
# run on the board. Cases 1, 2 and 3, each with the attenuation read back DURING
# the stream - "muted afterwards" is worthless unless it was unmuted first.
set -u

# THE CHANNEL IS REQUIRED AND HAS NO DEFAULT.
#
# These scripts key a transmit port and raise it to -30 dB. One of this board's two
# ports may have an antenna on it. A script that picks which one for you because you
# forgot to say is the same class of defect as a gate that defaults to affirmed - it
# manufactures a choice nobody made. So: say it, every time.
#
#   0 = TX1A, the ad9361 channel 0 attenuator, DMA channels voltage0/voltage1
#   1 = TX2A, the ad9361 channel 1 attenuator, DMA channels voltage2/voltage3
PAIR="${1:-}"
case "$PAIR" in
  0|1) ;;
  *) echo "usage: sh cases123.sh <0|1>" >&2
     echo "  0 = TX1A (channel 0)    1 = TX2A (channel 1)" >&2
     echo "There is no default. Name the port you are about to key." >&2
     exit 1 ;;
esac
# The DMA channel pair that feeds this transmit chain. iio_writedev names these, and
# they are NOT the attenuator's channel number: pair 1 is voltage2/voltage3.
DMA_I="voltage$((PAIR * 2))"
DMA_Q="voltage$((PAIR * 2 + 1))"

# Whatever happens - abort, Ctrl-C, a failed assertion - leave the transmitter QUIET.
# These scripts raise TX to -30 dB, and a gain written after the starve watchdog has
# fired is not re-muted, so an abort after that point used to exit with -30 dB still on the
# attenuator and nothing that would ever undo it. `revoke` is ungated and forces both
# channels to maximum attenuation, so it is safe to call from a trap.
# PIDs the script started, so the exit trap can end them. Without this, any abort
# after the writer starts - including assert_quiet's, which is the one most likely to
# fire - left a live stream behind, and `reap` then correctly DECLINED to touch it
# because an owner still held the fd. The mute landed; the stream did not stop.
WRITER=""; FEEDER=""
_kill_mine() {
  for _p in $WRITER $FEEDER; do kill -9 "$_p" 2>/dev/null; done
  [ -n "$WRITER$FEEDER" ] && sleep 1        # let the fd close before reap looks
}

_quiet_on_exit() {
  trap '' INT TERM HUP PIPE QUIT 2>/dev/null   # no re-entry while we clean up
  _kill_mine
  # Do NOT swallow this. tx-guard.sh prints FORCE-QUIET WRITE FAILED / PORT MAY BE LIVE
  # and returns 4 when it could not mute, and an emergency mute that fails silently is
  # worse than none. Also say so if the script was never pushed to the board.
  if [ ! -f /tmp/tx-guard.sh ]; then
    echo "*** /tmp/tx-guard.sh is not on the board - NOTHING WAS MUTED ***" >&2; return
  fi
  sh /tmp/tx-guard.sh revoke both || echo "*** EMERGENCY MUTE FAILED (exit $?) - TREAT THE PORTS AS LIVE ***" >&2
  # revoke mutes but does not disable a buffer, and a killed writer leaves one enabled -
  # which then trips the next run's "buffer already enabled" precondition. reap mutes
  # first and only then disables, so it is safe here and leaves the board re-runnable.
  # `revoke` also REMOVES the affirmation, by design: an abort is exactly when someone
  # should look at the port again before it goes live. The cost is that the next run of
  # this script will be refused at the gate, so say it here rather than let it look like
  # a fault.
  echo "note: the affirmation was revoked with the mute. Re-run" >&2
  echo "      './devkit tx-guard affirm <channel>' before this script again." >&2
  sh /tmp/tx-guard.sh reap >/dev/null 2>&1
  case $? in
    4)  echo "*** REAP REPORTED A FAILURE - CHECK THE BOARD ***" >&2 ;;
    11) echo "*** A BUFFER IS STILL ENABLED WITH AN OWNER - the stream this script" >&2
        echo "*** started may still be running. Both channels are muted, but check ps." >&2 ;;
  esac
}
# A buffer enable is itself a raise - the kernel restores a cached attenuation on it -
# so "the transmitter is still muted" has to be CHECKED, not printed. The harnesses'
# own exit trap runs `revoke both`, which leaves both channels at maximum and therefore
# ARMS that restore for the next run, so this is the likely case, not the exotic one.
report_and_mute_after_enable() {
  # A buffer enable is itself a raise: the kernel restores a cached attenuation on it.
  # For a TOOL that means to stay silent, that is a fault and it should abort - see
  # tx_gate.assert_quiet_after_enable. For a HARNESS that is about to raise through the
  # gate anyway it is an expected, documented phenomenon, and aborting on it makes the
  # harness unusable twice in a row: the previous run's own gain is what is in the cache.
  # So: say it happened, mute, verify the mute, and carry on. An UNREADABLE attenuator
  # is still fatal, because then nothing can be said about the state at all.
  _restored=""
  for _c in 0 1; do
    if ! read _a < "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null; then
      echo "ABORT: could not read channel $_c's attenuation after the buffer enable" >&2
      exit 4
    fi
    case "$_a" in -89.75*) ;; *) _restored="$_restored ch$_c=$_a" ;; esac
  done
  if [ -n "$_restored" ]; then
    echo "  NOTE: the buffer enable restored a cached gain:$_restored"
    # The previous stream is the LIKELY source - the kernel caches at stream stop and
    # restores at the next enable - but this script cannot see who wrote that cache, and
    # any program on the board could have. State the observation, not the culprit.
    echo "  (the kernel restored a cached value on the enable; this script did not set it,"
    echo "   and cannot tell which program left it in the cache. Muting before continuing.)"
    for _c in 0 1; do echo -89.75 > "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null; done
    for _c in 0 1; do
      read _a < "$PHY/out_voltage${_c}_hardwaregain" 2>/dev/null || { echo "ABORT: unreadable" >&2; exit 4; }
      case "$_a" in -89.75*) ;; *) echo "ABORT: ch$_c would not mute (reads $_a)" >&2; exit 4 ;; esac
    done
    echo "  both channels verified back at -89.75 dB"
  fi
}


PHY=/sys/bus/iio/devices/iio:device0
# A0/A1 stay literal so the snapshots' labels never lie about which
# channel they are showing. AK is the one this run is keying.
AK=$PHY/out_voltage${PAIR}_hardwaregain
DDS=/sys/bus/iio/devices/iio:device2
A0=$PHY/out_voltage0_hardwaregain
A1=$PHY/out_voltage1_hardwaregain
LOPD=$PHY/out_altvoltage1_TX_LO_powerdown
BUF=$DDS/buffer/enable
# EXIT INT TERM IS NOT ENOUGH ON THIS BOARD. /bin/sh is dash, and dash does NOT run
# an EXIT trap when the shell dies on an untrapped fatal signal. Measured on this
# board: TERM runs the trap; HUP, PIPE and QUIT kill it outright and the trap never
# fires. These scripts are launched as `ssh fishball "sh /tmp/<script> <ch>"`, so a
# dropped session delivers HUP, and the first printf into the dead stdout takes PIPE -
# and the writer and feeder do NOT die with it, because their output is redirected.
# The board would sit at -30 dB streaming with nothing left to mute it.
# MEASURED ON THIS BOARD, not assumed: with the list below, TERM, HUP and PIPE all run
# the trap. QUIT does NOT - dash accepts the trap (it lists in `trap`) and then dies
# without running it, twice out of two. QUIT is kept because it costs nothing and works
# under a /bin/sh that is not dash, but do not count on it here: Ctrl-\ on this board
# leaves the transmitter up. Ctrl-C (INT) is trapped and is the one to use.
# A TRAPPED SIGNAL DOES NOT TERMINATE THE SHELL. The handler runs and then execution
# RESUMES at the next statement - demonstrated, not assumed. Round 7 widened this list
# from EXIT INT TERM to include HUP PIPE QUIT and did not add an exit, which turned
# "dies with TX up" into something worse: the handler muted and revoked, the script
# carried on to the next case, opened a TX buffer, and the kernel's cache restore put
# the port back at the last stream's -30 dB with the operator's session already gone.
# Revoking leaves both attenuators at exactly -89.75, which tx-guard.sh LIMIT 3 records
# as the state that ARMS that restore.
#
# So: EXIT does the mute, and every signal arm mutes and then EXITS. The handler masks
# the signals first, because with PIPE trapped on a dead stdout every remaining echo
# re-enters the handler.
trap '_quiet_on_exit' EXIT
trap '_quiet_on_exit; trap - EXIT; exit 130' INT
trap '_quiet_on_exit; trap - EXIT; exit 143' TERM HUP PIPE QUIT

up() { read _u _i < /proc/uptime; echo "$_u"; }
snap() { read _a0 < $A0; read _a1 < $A1; read _l < $LOPD; read _b < $BUF
         printf '  %-10s up=%s atten0=%s atten1=%s LO_pd=%s buf=%s\n' "$1" "$(up)" "$_a0" "$_a1" "$_l" "$_b"; }
wait_buf() { i=0; while :; do read _b < $BUF; [ "$_b" = "1" ] && return 0
             i=$((i+1)); [ $i -gt 80 ] && return 1; sleep 0.25; done; }
# Poll for the mute without sleeping, and report the kernel's own timestamp too.
wait_mute() { _t0="$1"; _m=""; while :; do read _a < $AK
    case "$_a" in -89.75*) read _b < $BUF; read _l < $LOPD; _m=$(up)
        printf '  muted %.2f s later; buffer/enable=%s LO_pd=%s\n' \
           "$(awk -v a="$_m" -v b="$_t0" 'BEGIN{print a-b}')" "$_b" "$_l"; return 0;; esac
    read _n _i < /proc/uptime
    [ "$(awk -v a="$_n" -v b="$_t0" 'BEGIN{print (a-b>15)?1:0}')" = 1 ] && {
        echo "  *** NOT MUTED within 15 s (atten$PAIR=$_a) ***"; return 1; }; done; }
iio_attr -u local: -c ad9361-phy voltage0 sampling_frequency ${RATE:-3071997} >/dev/null 2>&1
echo "starve_timeout_ms=$(cat $DDS/tx_starve_timeout_ms) rate=$(cat $PHY/out_voltage_sampling_frequency)"

############ case 1: NORMAL CLOSE - bounded write, exits by itself ############
echo; echo "=== CASE 1: normal close (local backend, -s bounded, exit 0) ==="
[ "$(cat $BUF)" = "0" ] || { echo "ABORT: buffer already enabled"; exit 2; }
snap before
F=/tmp/c1.fifo; rm -f $F; mkfifo $F
cat /dev/zero > $F 2>/dev/null & FEEDER=$!
# ~2 s of samples, so there is a stream to look at while it runs.
iio_writedev -b 32768 -s 9216000 cf-ad9361-dds-core-lpc "$DMA_I" "$DMA_Q" < $F >/dev/null 2>/tmp/c1.err & WRITER=$!
wait_buf || { echo "ABORT: buffer never came up"; cat /tmp/c1.err; exit 2; }
report_and_mute_after_enable    # the enable itself can have raised an attenuator; check before trusting it
if ! sh /tmp/tx-guard.sh set-gain "$PAIR" -30; then
    echo "  ABORT: the gate refused (run "./devkit tx-guard affirm $PAIR"). Without the"
    echo "  raise the transmitter never goes live, the poller matches on its first"
    echo "  read, and a refusal is recorded as 'muted after 0.00 s'."; exit 3
  fi
snap DURING
T0=$(up)
wait $WRITER; echo "  iio_writedev exited $? (it closed the stream itself)"
kill -9 $FEEDER 2>/dev/null
wait_mute "$T0"
snap after; rm -f $F

############ case 2: NETWORK client SIGKILLed - the FIN DOES arrive ############
echo; echo "=== CASE 2: network client killed (loopback iiod, socket closes: FIN) ==="
sh /tmp/tx-guard.sh reap >/dev/null 2>&1
snap before
F=/tmp/c2.fifo; rm -f $F; mkfifo $F
cat /dev/zero > $F 2>/dev/null & FEEDER=$!
iio_writedev -u ip:127.0.0.1 -T 20000 -b 262144 -s 0 cf-ad9361-dds-core-lpc "$DMA_I" "$DMA_Q" < $F >/dev/null 2>/tmp/c2.err & WRITER=$!
wait_buf || { echo "ABORT: buffer never came up"; cat /tmp/c2.err; exit 2; }
report_and_mute_after_enable    # the enable itself can have raised an attenuator; check before trusting it
if ! sh /tmp/tx-guard.sh set-gain "$PAIR" -30; then
    echo "  ABORT: the gate refused (run "./devkit tx-guard affirm $PAIR"). Without the"
    echo "  raise the transmitter never goes live, the poller matches on its first"
    echo "  read, and a refusal is recorded as 'muted after 0.00 s'."; exit 3
  fi
snap DURING
read L < $LOPD
if [ "$L" != "0" ]; then echo "  NOTE: LO already down - this network stream starved before the kill"; fi
echo "  socket before the kill:"; ss -tn 2>/dev/null | grep 30431 | head -2 | sed 's/^/    /'
T0=$(up); kill -9 $WRITER $FEEDER 2>/dev/null
wait_mute "$T0"
echo "  socket after:"; ss -tn 2>/dev/null | grep 30431 | head -2 | sed 's/^/    /' || echo "    (gone - iiod cleaned up)"
snap after; rm -f $F

############ case 3: STARVATION, client still alive and holding the buffer ####
echo; echo "=== CASE 3: starvation - buffer open, fed once, client ALIVE ==="
sh /tmp/tx-guard.sh reap >/dev/null 2>&1
snap before
F=/tmp/c3.fifo; rm -f $F; mkfifo $F
# Feeds 24 MB then goes quiet WITHOUT closing the fifo, so the writer blocks on
# read instead of seeing EOF: the buffer stays open with nothing arriving.
( head -c 25165824 /dev/zero; sleep 120 ) > $F 2>/dev/null & FEEDER=$!
iio_writedev -b 32768 -s 0 cf-ad9361-dds-core-lpc "$DMA_I" "$DMA_Q" < $F >/dev/null 2>/tmp/c3.err & WRITER=$!
wait_buf || { echo "ABORT: buffer never came up"; cat /tmp/c3.err; exit 2; }
report_and_mute_after_enable    # the enable itself can have raised an attenuator; check before trusting it
if ! sh /tmp/tx-guard.sh set-gain "$PAIR" -30; then
    echo "  ABORT: the gate refused (run "./devkit tx-guard affirm $PAIR"). Without the"
    echo "  raise the transmitter never goes live, the poller matches on its first"
    echo "  read, and a refusal is recorded as 'muted after 0.00 s'."; exit 3
  fi
snap DURING
T0=$(up)
wait_mute "$T0"
kill -0 $WRITER 2>/dev/null && echo "  the client is STILL ALIVE and still owns the buffer" || echo "  client exited"
snap after
kill -9 $WRITER $FEEDER 2>/dev/null; rm -f $F
sh /tmp/tx-guard.sh reap >/dev/null 2>&1
echo; echo "=== dmesg ==="; dmesg | grep "muting the transmitter" | tail -6
