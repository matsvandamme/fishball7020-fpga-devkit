#!/bin/bash
# Measure receive throughput on the board, one kernel at a time, with a method
# that does not change between runs.
#
#     # run from: the repo root
#     ./tools/throughput-ab.sh                    # one round on whatever is booted
#     BOARD=192.168.1.50 ./tools/throughput-ab.sh
#
# WHY THIS EXISTS, and why it is a script rather than a paragraph.
#
# The local figures in docs/modulation-and-throughput.md were measured with
# iio_readdev at 33.6 Msamples, and iio_readdev's process start and its buffer
# allocation sit INSIDE the timed window. At 61.44 MS/s that run is 0.7 s, so a
# sixth of the measurement is fixed cost. Run the identical command with four
# times the samples and the same board reports 20% more.
#
# That is enough to invent a regression. It nearly did: re-measuring after the
# 6.12 rebase gave 183 MB/s against the 199 recorded for 5.15, which reads as a
# 7% loss until you notice the long run gives 220.
#
# So this script fixes everything that can drift - tool, buffer size, sample
# rate, sample counts, repeats - and reports both a short and a long run, because
# the difference between them IS the measurement's own overhead.
#
# It reads only. Nothing here opens a transmit buffer, which matters on a kernel
# without firmware-modern/patches/0019: there, an unmute restores a cache that
# clear_state() may have zeroed, and zero attenuation is full output.
#
# WHAT THE A/B FOUND, 2026-09-27, interleaved 6.12 -> 5.15 -> 6.12 on one board:
# the kernel makes no difference at all. Every figure matched across all three
# rounds, and the run-to-run scatter within one kernel (341.8-346.4 MB/s) was
# larger than any difference between them. Neither kernel reproduces the recorded
# 199.3 / 369.4 at 33.6 Msamples; both give 183 / 346 there and 220 / 431 at
# 134.4 M. The published numbers differ by METHOD, not by kernel.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOARD="${BOARD:-$(python3 "$HERE/board_addr.py" 2>/dev/null || echo 192.168.2.1)}"

# Login is tools/lib/board-ssh.sh: the key ./devkit ssh-key makes, then the
# password through sshpass where that is installed.
BOARD_SSH_CONNECT_TIMEOUT=8
. "$HERE/lib/board-ssh.sh"
board_ssh_require || exit 1

board_ssh "$BOARD" 'sh -s' <<'EOF'
P=/sys/bus/iio/devices/iio:device0
for d in /sys/bus/iio/devices/iio:device*; do
    [ "$(cat $d/name)" = "xadc" ] && XADC=$d
done
echo "kernel:  $(uname -r)"
echo "muted:   TX0 $(cat $P/out_voltage0_hardwaregain)  TX1 $(cat $P/out_voltage1_hardwaregain)"
ORIG=$(cat $P/in_voltage_sampling_frequency)
echo 61440000 > $P/in_voltage_sampling_frequency
echo "rate:    $(cat $P/in_voltage_sampling_frequency) Hz  (restored to $ORIG at the end)"
# Temperature is recorded because a hot board is the one plausible way these
# numbers could move without the software changing.
echo "temps:   zynq $(awk '{printf "%.1f", ($1+o)*s/1000}' o=$(cat $XADC/in_temp0_offset) s=$(cat $XADC/in_temp0_scale) $XADC/in_temp0_raw) C   ad9361 $(awk '{printf "%.1f", $1/1000}' $P/in_temp0_input) C"
echo
printf "  %-4s %-11s %-4s %6s %11s %11s\n" chans samples run secs "MB/s" "MS/s per ch"
for N in 33600000 134400000; do
  for chans in "voltage0 voltage1" "voltage0 voltage1 voltage2 voltage3"; do
    case "$chans" in *voltage2*) d=2; lab=2ch;; *) d=1; lab=1ch;; esac
    for r in 1 2 3; do
      S=$(cut -d' ' -f1 /proc/uptime)
      iio_readdev -b 1048576 -s $N cf-ad9361-lpc $chans > /dev/null 2>&1
      E=$(cut -d' ' -f1 /proc/uptime)
      awk -v s="$S" -v e="$E" -v n="$N" -v d="$d" -v lab="$lab" -v r="$r" 'BEGIN{
        t=e-s; if(t<=0)t=0.001;
        printf "  %-4s %-11d %-4s %6.2f %11.1f %11.1f\n", lab, n, r, t, n*4*d/t/1048576, n/t/1e6 }'
    done
  done
done
echo $ORIG > $P/in_voltage_sampling_frequency
echo
echo "rate restored: $(cat $P/in_voltage_sampling_frequency) Hz"
EOF
cat <<'NOTE'

Read the two sample counts as one measurement, not two. The gap between them is
this tool's own startup cost, not the board changing its mind - so quote the long
run, and compare against someone else's figure only at the SAME sample count.
NOTE
