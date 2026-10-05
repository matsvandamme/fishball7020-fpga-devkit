#!/usr/bin/env bash
# Is anyone streaming on the board? And, with --wait, wait until nobody is.
#
# The board has one receive and one transmit DMA buffer. A program that holds
# one (SDR++, chirp-view, a capture, a zc-stream client, a CI run) makes every
# other program's attempt fail with "Device or resource busy" (EBUSY). This
# reads the two buffers' enable flags on the board, and names the processes
# holding the radio's device files, so a busy board is reported as busy rather
# than as a failed test.
#
#   # run from: the repo root on your PC
#   tools/board-busy.sh                   # report; exit 0 if free, 3 if busy
#   tools/board-busy.sh --wait 1200       # wait up to 20 min for the board to be free
#   tools/board-busy.sh --wait 1200 --quiet 60   # ...and free for 60 s in a row
#
# Free means both buffers off for --quiet seconds in a row (default 30): apps
# like SDR++ and chirp-view close and reopen their buffer when settings change,
# and a single idle reading in that gap is not the board being free.
#
# Exit status: 0 free, 3 busy (or still busy when --wait ran out), 2 board not
# reachable. BOARD overrides the address (default fishball.local); ssh uses a
# key when there is one (./devkit ssh-key), else BOARD_PASS through sshpass.
set -u

WAIT=0 QUIET=30 POLL=10
while [ $# -gt 0 ]; do
    case "$1" in
        --wait)  WAIT="$2"; shift 2 ;;
        --quiet) QUIET="$2"; shift 2 ;;
        -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
    esac
done

BOARD="${BOARD:-fishball.local}"
PASS="${BOARD_PASS:-analog}"
OPTS=(-o ConnectTimeout=5 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

on_board() {
    ssh "${OPTS[@]}" -o BatchMode=yes "root@$BOARD" "$1" 2>/dev/null && return 0
    command -v sshpass >/dev/null || return 255
    sshpass -p "$PASS" ssh "${OPTS[@]}" "root@$BOARD" "$1"
}

# One line per busy buffer, then one per process holding a radio device file.
# Empty output: free.
PROBE='
for d in /sys/bus/iio/devices/iio:device*; do
    n=$(cat $d/name)
    case $n in cf-ad9361-lpc|cf-ad9361-dds-core-lpc) ;; *) continue ;; esac
    [ "$(cat $d/buffer/enable 2>/dev/null)" = 1 ] || continue
    [ $n = cf-ad9361-lpc ] && echo "receive buffer on" || echo "transmit buffer on"
done
for f in /proc/[0-9]*/fd/*; do
    case $(readlink $f 2>/dev/null) in /dev/iio:device*) p=${f#/proc/}; p=${p%%/*}
        echo "held by pid $p: $(tr "\0" " " < /proc/$p/cmdline | cut -c1-80)" ;;
    esac
done | sort -u
echo .'

probe() {
    local out
    out=$(on_board "$PROBE") || return 2
    printf '%s' "${out%.}"
}

start=$(date +%s) free_since=""
while :; do
    state=$(probe); rc=$?
    if [ $rc -eq 2 ]; then
        echo "board-busy: no answer from $BOARD over ssh" >&2
        exit 2
    fi
    now=$(date +%s)
    if [ -z "$state" ]; then
        [ -z "$free_since" ] && free_since=$now
        if [ "$WAIT" -eq 0 ] || [ $((now - free_since)) -ge "$QUIET" ]; then
            echo "board-busy: $BOARD is free"
            exit 0
        fi
    else
        free_since=""
        [ "$WAIT" -eq 0 ] && { echo "board-busy: $BOARD is busy:"; echo "$state" | sed 's/^/  /'; exit 3; }
        echo "board-busy: busy after $((now - start)) s, waiting:"; echo "$state" | sed 's/^/  /'
    fi
    if [ $((now - start)) -ge "$WAIT" ]; then
        echo "board-busy: $BOARD not free for $QUIET s in a row within $WAIT s" >&2
        exit 3
    fi
    sleep "$POLL"
done
