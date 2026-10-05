# Tab completion for ./devkit
#
#   source <(./devkit completion)      # this shell, one command, no files
#   ./devkit completion install        # every new shell, from then on
#
# Either is one command. There is no zero-command option: a shell will not
# load completions out of a directory it has never been told about, which is
# a security property rather than an oversight.
#
# Works with zsh too, after `autoload -U bashcompinit && bashcompinit`.
#
# It completes subcommands, then that subcommand's own flags - so you do not
# have to remember that --dtb-only exists on flash and not on build. --xsa
# completes .xsa files, and `net static` completes nothing because the next
# thing it wants is an address only you know.

_devkit_complete() {
    local cur prev cmd
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    cmd="${COMP_WORDS[1]}"

    local subcommands="doctor setup sim build verify flash write-card selftest gpio-check
                       net temps loopback adsb automation claude-pane status container uboot-contract matlab clock completion ssh-key tx-guard help"

    # The first word after ./devkit
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=($(compgen -W "$subcommands --help --version" -- "$cur"))
        return
    fi

    # ./devkit help <command>
    if [ "$cmd" = help ]; then
        [ "$COMP_CWORD" -eq 2 ] && COMPREPLY=($(compgen -W "${subcommands/help/} --all" -- "$cur"))
        return
    fi

    # --xsa wants a hardware platform, so offer those rather than every file.
    if [ "$prev" = "--xsa" ]; then
        COMPREPLY=($(compgen -f -X '!*.xsa' -- "$cur") $(compgen -d -- "$cur"))
        return
    fi

    # --target picks which firmware: modern (the default) or factory (#9).
    if [ "$prev" = "--target" ]; then
        COMPREPLY=($(compgen -W "modern factory" -- "$cur"))
        return
    fi

    # Which target is this command line for? It changes which flags exist:
    # build: --hdl-only is factory's; --boot-only, --rootfs-only, --all modern's.
    # flash: --all/--rootfs-only are factory's.
    local tgt="${DEVKIT_TARGET:-modern}" w
    for w in "${COMP_WORDS[@]}"; do
        case "$w" in --target=modern) tgt=modern ;; --target=factory) tgt=factory ;; esac
    done
    local i; for ((i = 1; i < COMP_CWORD; i++)); do
        [ "${COMP_WORDS[i]}" = "--target" ] && case "${COMP_WORDS[i+1]}" in
            modern|factory) tgt="${COMP_WORDS[i+1]}" ;; esac
    done

    # --pad wants a number of dB; suggest the ones that are actually sensible.
    # 20 dB is the documented minimum for a loopback on this board.
    if [ "$prev" = "--pad" ]; then
        COMPREPLY=($(compgen -W "20 30 40 50" -- "$cur"))
        return
    fi

    case "$cmd" in
        build)
            if [ "$tgt" = modern ]; then
                COMPREPLY=($(compgen -W "--target --xsa --boot-only --rootfs-only --all
                                         --preflight-only --help" -- "$cur"))
            else
                COMPREPLY=($(compgen -W "--target --hdl-only --xsa --preflight-only --help" -- "$cur"))
            fi ;;
        flash)
            if [ "$tgt" = modern ]; then
                COMPREPLY=($(compgen -W "--target --boot-only --kernel-only --dtb-only --no-reboot --help" -- "$cur"))
            else
                COMPREPLY=($(compgen -W "--target --all --boot-only --kernel-only --dtb-only
                                         --rootfs-only --no-reboot --help" -- "$cur"))
            fi ;;
        verify)
            COMPREPLY=($(compgen -W "--target --board --help" -- "$cur")) ;;
        setup|doctor|status)
            COMPREPLY=($(compgen -W "--target --help" -- "$cur")) ;;
        write-card)
            # Offer removable disks only - the same thing write-card itself insists on.
            local disks=""
            for d in /sys/block/*; do [ "$(cat "$d/removable" 2>/dev/null)" = 1 ] && disks="$disks /dev/${d##*/}"; done
            COMPREPLY=($(compgen -W "--target --dry-run --image --size --help $disks" -- "$cur")) ;;
        selftest)
            COMPREPLY=($(compgen -W "--ssh --loopback --pad --channel --quick
                                     --baseline --save-baseline --json
                                     --no-colour --help" -- "$cur")) ;;
        temps)
            COMPREPLY=($(compgen -W "--watch --json --interval --uri --help" -- "$cur")) ;;
        uboot-contract)
            COMPREPLY=($(compgen -W "--save --help" -- "$cur")) ;;
        tx-guard)
            # Per CHANNEL throughout: 0 is TX1A and 1 is TX2A, two separate SMA
            # ports, so there is no single "both" for anything that RAISES output.
            # revoke does offer it, because muting both is the safe direction.
            if [ "$COMP_CWORD" -eq 2 ]; then
                COMPREPLY=($(compgen -W "status affirm revoke check set-gain reap" -- "$cur"))
            elif [ "$COMP_CWORD" -eq 3 ]; then
                case "$prev" in
                    affirm|check|set-gain) COMPREPLY=($(compgen -W "0 1" -- "$cur")) ;;
                    revoke)                COMPREPLY=($(compgen -W "0 1 both" -- "$cur")) ;;
                esac
            fi ;;
        loopback)
            # on/off, and nothing else is a sensible thing to type here.
            if [ "$COMP_CWORD" -eq 2 ]; then
                COMPREPLY=($(compgen -W "on off --json --uri --help" -- "$cur"))
            else
                COMPREPLY=($(compgen -W "--json --uri --help" -- "$cur"))
            fi ;;
        automation)
            COMPREPLY=($(compgen -W "install status clock capture smoke mute test uninstall help --measure --seconds --samples --channels" -- "$cur")) ;;
        claude-pane)
            COMPREPLY=($(compgen -W "start install uninstall test help" -- "$cur")) ;;
        adsb)
            case "$prev" in
                --replay) COMPREPLY=($(compgen -f -X '!*.sigmf-meta' -- "$cur")); compopt -o plusdirs 2>/dev/null ;;
                --channel) COMPREPLY=($(compgen -W "1 2" -- "$cur")) ;;
                --gain) COMPREPLY=($(compgen -W "agc 15 20 25 30" -- "$cur")) ;;
                *) COMPREPLY=($(compgen -W "--channel --gain --text --json --seconds --record
                                            --replay --fast --loop --rate --freq --min-snr
                                            --lat --lon --uri --help" -- "$cur")) ;;
            esac ;;
        net)
            # Only one level: `net static` then wants an address, and `net name`
            # a hostname - neither is ours to guess.
            if [ "$COMP_CWORD" -eq 2 ]; then
                COMPREPLY=($(compgen -W "show dhcp static name find" -- "$cur"))
            fi ;;
        container)
            # build-image and install are the container's own; everything
            # else is passed through to devkit running inside it.
            if [ "$COMP_CWORD" -eq 2 ]; then
                COMPREPLY=($(compgen -W "build-image install $subcommands" -- "$cur"))
            elif [ "${COMP_WORDS[2]}" = "install" ]; then
                COMPREPLY=($(compgen -f -X '!*.bin' -- "$cur") $(compgen -d -- "$cur"))
            fi ;;
        sim)
            COMPREPLY=($(compgen -W "--mutate --help" -- "$cur")) ;;
        gpio-check)
            COMPREPLY=($(compgen -W "--help" -- "$cur")) ;;
        *)
            COMPREPLY=($(compgen -W "--help" -- "$cur")) ;;
    esac
}

complete -F _devkit_complete devkit ./devkit
