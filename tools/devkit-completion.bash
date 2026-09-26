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

    local subcommands="doctor setup sim build verify flash selftest gpio-check
                       net temps loopback status container"

    # The first word after ./devkit
    if [ "$COMP_CWORD" -eq 1 ]; then
        COMPREPLY=($(compgen -W "$subcommands --help" -- "$cur"))
        return
    fi

    # --xsa wants a hardware platform, so offer those rather than every file.
    if [ "$prev" = "--xsa" ]; then
        COMPREPLY=($(compgen -f -X '!*.xsa' -- "$cur") $(compgen -d -- "$cur"))
        return
    fi

    # --pad wants a number of dB; suggest the ones that are actually sensible.
    # 20 dB is the documented minimum for a loopback on this board.
    if [ "$prev" = "--pad" ]; then
        COMPREPLY=($(compgen -W "20 30 40 50" -- "$cur"))
        return
    fi

    case "$cmd" in
        build)
            COMPREPLY=($(compgen -W "--hdl-only --xsa --preflight-only --help" -- "$cur")) ;;
        flash)
            COMPREPLY=($(compgen -W "--all --boot-only --kernel-only --dtb-only
                                     --rootfs-only --no-reboot --help" -- "$cur")) ;;
        verify)
            COMPREPLY=($(compgen -W "--board --help" -- "$cur")) ;;
        selftest)
            COMPREPLY=($(compgen -W "--ssh --loopback --pad --channel --quick
                                     --baseline --save-baseline --json
                                     --no-colour --help" -- "$cur")) ;;
        temps)
            COMPREPLY=($(compgen -W "--watch --json --interval --uri --help" -- "$cur")) ;;
        loopback)
            # on/off, and nothing else is a sensible thing to type here.
            if [ "$COMP_CWORD" -eq 2 ]; then
                COMPREPLY=($(compgen -W "on off --json --uri --help" -- "$cur"))
            else
                COMPREPLY=($(compgen -W "--json --uri --help" -- "$cur"))
            fi ;;
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
