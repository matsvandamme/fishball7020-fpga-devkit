#!/usr/bin/env bash
#
# Simulate the repo's custom HDL and check it against a golden model.
#
#     ./sim/run_sim.sh            # run from firmware/
#     ./sim/run_sim.sh --mutate   # also prove the testbenches can fail
#
# Needs Icarus Verilog only:  sudo apt install iverilog
#
# Why this exists: without it, the only way to find out whether an HDL change
# is correct is a ~20 minute Vivado build followed by a flash and a reboot.
# This takes about a second, and it catches the class of mistake that a
# synthesis run cannot - logic that builds and meets timing but computes the
# wrong thing.
#
set -uo pipefail

MUTATE=0
FW=""
for arg in "$@"; do
    case "$arg" in
        --mutate) MUTATE=1 ;;
        -h|--help) sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
        -*) echo "unknown option: $arg (try --help)" >&2; exit 2 ;;
        *) FW=$arg ;;
    esac
done
[ -n "$FW" ] || FW=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SIM=$FW/sim
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if ! command -v iverilog >/dev/null; then
    echo "iverilog is not installed.  sudo apt install iverilog" >&2
    exit 2
fi

fail=0

# A design under test is in src/ only once its patch has been applied. Take it
# from there when it is, and otherwise lift it straight out of the patch file -
# checking that the channelizer is correct should not require you to have opted
# into the channelizer.
#
#   fetch <module> <patchfile>   ->  $WORK/<module>.v, and sets $origin
#
# The patch lives at the top level of patches/ once a module is a shipped
# feature, and under patches/optional/ while it is still a worked example, so
# look in both rather than hard-coding either.
fetch() {
    local module=$1 patch=$2
    local dut=$FW/src/hdl/projects/pluto/$module.v
    local patchfile=$FW/patches/$patch
    [ -r "$patchfile" ] || patchfile=$FW/patches/optional/$patch
    if [ -r "$dut" ]; then
        cp "$dut" "$WORK/$module.v"
        origin="src/ (the patch is applied)"
    elif [ -r "$patchfile" ]; then
        awk -v want="+++ b/hdl/projects/pluto/$module.v" '
            $0 == want           { grab = 1; next }
            grab && /^diff --git/ { grab = 0 }
            grab && /^\+/         { print substr($0, 2) }
        ' "$patchfile" > "$WORK/$module.v"
        [ -s "$WORK/$module.v" ] || { echo "could not extract $module from $patchfile" >&2; exit 2; }
        origin="${patchfile#$FW/} (extracted; the patch is not applied)"
    else
        echo "cannot find $module.v in src/ or in patches/optional/" >&2
        exit 2
    fi
}

#   simulate <module>            ->  compiles tb_<module>.v + the module, runs it
simulate() {
    local module=$1
    echo "== $module =="
    echo "   source: $origin"
    # -Wall catches width mismatches and implicit nets, which is most of what
    # goes wrong in Verilog that nobody simulates.
    if ! iverilog -g2005 -Wall -o "$WORK/tb_$module" \
         "$SIM/tb_$module.v" "$WORK/$module.v" 2>&1 | sed 's/^/   /' ; then
        fail=1
    fi
    [ -x "$WORK/tb_$module" ] || { echo "   compilation failed"; exit 1; }
    # vvp exits 0 even when the testbench reports mismatches, so judge on what
    # the testbench actually said rather than on its exit status.
    vvp "$WORK/tb_$module" | tee "$WORK/out.txt" | sed 's/^/   /'
    grep -q "^  PASS" "$WORK/out.txt" || fail=1
    grep -q "FAIL"    "$WORK/out.txt" && fail=1
}

fetch ad_fs4_ddc      0003-wbfm-channelizer.patch
simulate ad_fs4_ddc
echo
fetch tx_gpio_bitmap  0006-tx-sample-nibble-to-gpio.patch
simulate tx_gpio_bitmap

# --mutate: prove the testbenches can actually fail.
#
# A green test suite means nothing until you have watched it go red. Each
# mutant below is a plausible mistake - the phase counter moved out of the
# valid guard is the one that costs a rebuild and a flash to find on hardware -
# and the testbench must reject every one of them. If a mutant survives, the
# corresponding check is decorative and should be fixed.
if [ $MUTATE -eq 1 ]; then
    echo
    echo "== mutation check: the testbenches must reject each of these =="
    survived=0
    module=""
    mutate() {
        local name=$1 sedexpr=$2
        sed "$sedexpr" "$WORK/$module.v" > "$WORK/mutant.v"
        if cmp -s "$WORK/$module.v" "$WORK/mutant.v"; then
            echo "   SKIP  $name (mutation did not apply)"; survived=$((survived+1)); return
        fi
        rm -f "$WORK/mtb"                       # never rerun the PREVIOUS mutant
        if ! iverilog -g2005 -o "$WORK/mtb" "$SIM/tb_$module.v" "$WORK/mutant.v" 2>/dev/null; then
            echo "   caught    $name (does not even compile)"; return
        fi
        if vvp "$WORK/mtb" 2>/dev/null | grep -q "^  PASS"; then
            echo "   SURVIVED  $name  <- the testbench does not catch this"
            survived=$((survived+1))
        else
            echo "   caught    $name"
        fi
    }

    module=ad_fs4_ddc
    echo "   -- $module"
    mutate "phase advances every clock, not every sample" \
           's/^      phase <= phase + 2.d1;/      \/\/removed/'
    mutate "sign error in the -j quadrant"      's/q_out <= -i_in/q_out <= i_in/'
    mutate "I and Q swapped in the +j quadrant" 's/i_out <= -q_in; q_out <=  i_in/i_out <= i_in; q_out <= -q_in/'
    mutate "valid_out not registered"           's/valid_out <= valid_in;/valid_out <= 1'"'"'b1;/'

    module=tx_gpio_bitmap
    echo "   -- $module"
    mutate "nibble captured every clock, not every sample" \
           's/end else if (valid_in == 1.b1) begin/end else begin/'
    mutate "pins left tristated while the flag is set" \
           's/{NBITS{1.b0}} : gpio_t_in/gpio_t_in : gpio_t_in/'
    mutate "the mux is the wrong way round" \
           's/? sample_d : gpio_o_in/? gpio_o_in : sample_d/'
    mutate "the sample is not registered at all" \
           's/? sample_d : gpio_o_in/? sample_in : gpio_o_in/'
    mutate "only one synchroniser stage on the flag" \
           's/(flag_s == 1.b1)/(flag_m == 1'"'"'b1)/g'
    mutate "a datapath reset leaves a stale nibble on the pins" \
           's/^      sample_d <= {NBITS{1.b0}};/      sample_d <= sample_d;/'

    if [ $survived -ne 0 ]; then
        echo "   $survived mutant(s) survived - the testbench is weaker than it looks"
        fail=1
    else
        echo "   all mutants caught"
    fi
fi

echo
if [ $fail -eq 0 ]; then echo "SIMULATION OK"; else echo "SIMULATION FAILED"; fi
exit $fail
