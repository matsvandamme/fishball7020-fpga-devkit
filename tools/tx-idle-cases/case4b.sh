#!/bin/sh
# run on the board. Case 4b: a TCP client of iiod has its connection
# BLACK-HOLED mid-stream - no FIN, no RST, socket left ESTABLISHED. Over
# loopback, because this board's Ethernet cannot keep the DAC fed at 3.072 MSPS
# (measured: the starve watchdog mutes within seconds with no drop involved), and
# a case that starves before the drop measures starvation, not a drop.
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
  *) echo "usage: sh case4b.sh <0|1>" >&2
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
# RELAY belongs here too. It is not a client of the DAC, but it holds iiod's socket
# open, and an abort that left it running kept that connection ESTABLISHED - which is
# exactly the state this case creates deliberately, left behind by accident.
WRITER=""; FEEDER=""; RELAY=""
_kill_mine() {
  for _p in $WRITER $FEEDER $RELAY; do kill -9 "$_p" 2>/dev/null; done
  [ -n "$WRITER$FEEDER$RELAY" ] && sleep 1  # let the fds close before reap looks
}

_quiet_on_exit() {
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
  echo "      "./devkit tx-guard affirm $PAIR" before this script again." >&2
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
LOPD=$PHY/out_altvoltage1_TX_LO_powerdown
BUF=$DDS/buffer/enable
D=/tmp/drop4b; X=/tmp/exit4b; F=/tmp/fifo4b
up() { read _u _i < /proc/uptime; echo "$_u"; }
snap() { read _a0 < $A0; read _a1 < $PHY/out_voltage1_hardwaregain
         read _l < $LOPD; read _b < $BUF; read _u < $DDS/tx_dma_underflow_count
         printf '  up=%s atten0=%s atten1=%s LO_pd=%s buf=%s under=%s\n' \
            "$(up)" "$_a0" "$_a1" "$_l" "$_b" "$_u"; }

# THE DEFAULT, 250 ms. An earlier version of this script defaulted to 2000 and
# carried a comment claiming the board could not keep a network stream fed at the
# default - both retracted: the bottleneck was tcp-blackhole.py copying 64 KB at a
# time, and with --chunk 1048576 this runs at 250 ms. Leaving 2000 here meant the
# committed harness reproduced the superseded configuration while the table quoted
# the default. The previous value is restored on the way out, however this exits.
ORIG_STARVE=$(cat $DDS/tx_starve_timeout_ms)
# ONE handler for EXIT/INT/TERM. `trap` REPLACES a handler, it does not append, so the
# two separate traps this script used to install meant only the second ever ran - and
# the one that was lost was the mute. In the single harness that raises TX to -30 dB
# and holds it longest, the safety trap was dead code.
_on_exit() {
  trap '' INT TERM HUP PIPE QUIT 2>/dev/null   # no re-entry while we clean up
  echo "$ORIG_STARVE" > "$DDS/tx_starve_timeout_ms" 2>/dev/null
  _quiet_on_exit
}
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
trap '_on_exit' EXIT
trap '_on_exit; trap - EXIT; exit 130' INT
trap '_on_exit; trap - EXIT; exit 143' TERM HUP PIPE QUIT
echo ${STARVE_MS:-250} > $DDS/tx_starve_timeout_ms
iio_attr -u local: -c ad9361-phy voltage0 sampling_frequency ${RATE:-3071997} >/dev/null 2>&1
echo "starve_timeout_ms=$(cat $DDS/tx_starve_timeout_ms)  rate=$(cat $PHY/out_voltage_sampling_frequency)"
rm -f $D $X $F
echo "--- before anything ---"; snap
[ "$(cat $BUF)" = "0" ] || { echo "ABORT: a TX buffer is already enabled - reap it first"; exit 2; }
echo 0 > $DDS/tx_dma_underflow_count
dmesg -C

python3 /tmp/tcp-blackhole.py --to 127.0.0.1:30431 --listen 127.0.0.1:34340 \
    --drop-when $D --exit-when $X --sndbuf ${SNDBUF:-131072} --chunk ${CHUNK:-1048576} > /tmp/relay4b.log 2>&1 &
RELAY=$!
sleep 2
mkfifo $F
cat /dev/zero > $F 2>/dev/null & FEEDER=$!
iio_writedev -u ip:127.0.0.1:34340 -T 20000 -b 262144 -s 0 \
    cf-ad9361-dds-core-lpc "$DMA_I" "$DMA_Q" < $F > /dev/null 2>/tmp/we4b & WRITER=$!
echo "relay=$RELAY feeder=$FEEDER writer=$WRITER  (TCP client of iiod, via the relay)"

i=0
while :; do read _b < $BUF; [ "$_b" = "1" ] && break
  i=$((i+1)); [ $i -gt 120 ] && { echo "ABORT: buffer never enabled"; cat /tmp/we4b; exit 2; }
  sleep 0.25; done
kill -0 $WRITER 2>/dev/null || { echo "ABORT: writer died before streaming"; cat /tmp/we4b; exit 2; }
report_and_mute_after_enable   # checked, not asserted in prose
echo "--- buffer up, verified still muted ---"; snap

echo "--- raising through the gate ---"
# Capture the status BEFORE the `if`. Inside `then` after `! cmd`, $? is the status of
# the negation, which is always 0 - so the old line reported "exit 0" on every refusal,
# hiding which of the gate's codes (3 no affirmation, 4 unreadable, 10/11 mismatch) fired.
sh /tmp/tx-guard.sh set-gain "$PAIR" -30; GATE=$?
if [ $GATE -ne 0 ]; then
  echo "ABORT: the gate refused the raise (exit $GATE). Run "./devkit tx-guard affirm $PAIR"."
  echo "Without this the transmitter never goes live and every reading below would be"
  echo "a muted board agreeing with itself - which is how a refusal gets recorded as a"
  echo "measurement."
  kill -9 $WRITER $FEEDER 2>/dev/null; touch $D; sleep 0.5; touch $X; sleep 1
  kill -9 $RELAY 2>/dev/null; rm -f $F; exit 3
fi
# ONE snapshot, then drop at once. The stream stays healthy for a couple of
# seconds and no longer - this board cannot keep a network TX stream fed
# indefinitely at 3.072 MSPS - so spending that window on snapshots is what made
# the earlier attempts measure starvation instead of a drop.
echo "--- DURING the stream: LO_pd must be 0 and no starve mute yet ---"
snap
read L < $LOPD; SM=$(dmesg | grep -c "muting the transmitter")
if [ "$L" != "0" ] || [ "$SM" != "0" ]; then
  echo "ABORT: not live at the drop (LO_pd=$L starve_mutes=$SM) - this would measure starvation"
  kill -9 $WRITER $FEEDER 2>/dev/null; touch $D; sleep 0.5; touch $X; sleep 1; kill -9 $RELAY 2>/dev/null
  rm -f $F; exit 3
fi
echo "  LIVE at the drop: LO_pd=0, atten$PAIR=$(cat $AK), no starve mute yet"

# The drop, then poll for the mute WITHOUT sleeping. Everything is local here,
# so the elapsed time is measured from the touch itself.
read AB < $AK
echo "  atten0 immediately before the drop: $AB"
# Assert it is LOUD. LO_pd reads 0 whenever a buffer is enabled, whatever the
# attenuation, so the liveness guard above cannot catch a transmitter that is
# muted-but-streaming - and a muted board mutes again instantly, giving a delta of
# 0.00 s that looks like a perfect result.
case "$AB" in -89.75*)
  echo "ABORT: the transmitter is at maximum attenuation at the moment of the drop."
  echo "There is nothing to mute, so any delta measured here would be meaningless."
  kill -9 $WRITER $FEEDER 2>/dev/null; touch $D; sleep 0.5; touch $X; sleep 1
  kill -9 $RELAY 2>/dev/null; rm -f $F; exit 3;;
esac
T0=$(up)
touch $D
kill -9 $WRITER $FEEDER 2>/dev/null
MUTED=""; BUFAT=""; LOAT=""
while :; do
  read A < $AK
  case "$A" in -89.75*) read BUFAT < $BUF; read LOAT < $LOPD; MUTED=$(up); break;; esac
  read N _ < /proc/uptime
  [ "$(awk -v a="$N" -v b="$T0" 'BEGIN{print (a-b>20)?1:0}')" = 1 ] && break
done
echo "--- DROPPED at board uptime $T0, client killed ---"
if [ -n "$MUTED" ]; then
  echo "  MUTED $(awk -v a="$MUTED" -v b="$T0" 'BEGIN{printf "%.2f", a-b}') s after the drop"
  echo "  buffer/enable at the mute: $BUFAT     <- 1 = the kernel watchdog, not teardown"
  echo "  TX_LO_powerdown at the mute: $LOAT"
else
  echo "  *** NOT MUTED within 20 s ***"
fi
echo "--- the kernel's OWN timestamp for the mute, against the drop at $T0 ---"
dmesg | grep "muting the transmitter" | tail -2
KTS=$(dmesg | grep "muting the transmitter" | tail -1 | sed 's/^\[ *\([0-9.]*\)\].*/\1/')
if [ -n "$KTS" ]; then
  # printk and /proc/uptime are NOT the same clock - printk runs about 0.077 s
  # behind on this board - so this line is corroboration that the watchdog is what
  # fired, NOT a delta. The delta above is uptime-against-uptime.
  echo "  kernel's own log line at printk $KTS (a different clock from /proc/uptime;"
  echo "  printk lags by about 0.077 s here, so do not subtract these two)"
fi
# The watchdog fires TIMEOUT after the last submitted block, and the last block
# precedes the drop, so 0 < delta <= timeout always. A delta at or near ZERO means
# the mute was already pending when the trigger was pulled.
if [ -n "$MUTED" ]; then
  echo "  criterion: 0 < delta <= $(cat $DDS/tx_starve_timeout_ms) ms expected;"
  echo "  a delta at or near ZERO disqualifies the run - the stream had already starved."
fi
echo "--- iiod's sockets AT/AFTER the mute (relay still holding them open) ---"
ss -tnp 2>/dev/null | grep 30431 || echo "  (no connection on 30431)"
snap
echo "--- now close the sockets; iiod should tear the buffer down ---"
touch $X; sleep 3; snap
ss -tnp 2>/dev/null | grep 30431 || echo "  (no connection on 30431)"
echo "--- dmesg ---"; dmesg | grep "muting the transmitter"
echo "--- relay log ---"; cat /tmp/relay4b.log
rm -f $F
