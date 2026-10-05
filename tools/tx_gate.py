#!/usr/bin/env python3
"""The one way a host-side tool in this repo may RAISE transmit output.

    from tx_gate import gated_set_atten, TxGateRefused, MUTE_DB

    gated_set_atten(0, -30.0)          # refused unless ch0 was affirmed
    gated_set_atten(0, MUTE_DB)        # quiet: always allowed, never gated

This is deliberately NOT a second gate. It pushes tools/tx-guard.sh to the board
and runs it there, so there is exactly one implementation of the affirmation
rule, one store for the affirmations (the board's /tmp, which is tmpfs, so a
reboot withdraws them) and one set of exit codes. An earlier attempt at this
shipped a parallel gate beside tx-guard.sh and it was the weaker of the two; see
IDLE-CASES.md.

TWO ROUTES TO THE SAME SCRIPT. Where bash runs (Linux, macOS) it goes through
`./devkit tx-guard`. On Windows, or with FISHBALL_TX_GATE=python, it does the
same itself over ssh with paramiko (installed in a venv, with the venv's own
pip): push tx-guard.sh,
run it, return its exit code. That uses ~/.ssh/fishball if it exists (what
`./devkit ssh-key` makes), else the root password ($BOARD_PASS, default
"analog"), at the address tools/board_addr.py finds ($BOARD overrides). From a
shell with no devkit:

    python tools/tx_gate.py status
    python tools/tx_gate.py affirm 0        # after looking at TX1A
    python tools/tx_gate.py revoke both

WHY A GATE AT ALL. This board has no directional coupler and no detector on
either transmit port, so whether an antenna is attached to TX cannot be measured
by any means. Nothing here detects anything. It requires a human to have said,
in a recorded and reboot-scoped way, that THAT port is terminated - which is the
only evidence that exists - and refuses to raise output otherwise.

WHAT IT DOES NOT DO. It is a tool-level gate, not enforcement. A program that
writes out_voltageN_hardwaregain itself walks straight past it, and the
affirmation is an ordinary file in world-writable tmpfs that any process can
forge. Read the LIMITS block at the top of tools/tx-guard.sh before trusting it
with anything. The enforcement that cannot be bypassed lives in the driver:
firmware/patches/0016's tx_disable latch.

QUIET IS NEVER GATED, and that is load-bearing. Muting must work when ssh is
down, when the affirmation is absent, and in a `finally:` block after something
has already gone wrong - so callers write MUTE_DB over their own connection and
do not come through here for it.
"""
from __future__ import annotations

import os
import pathlib
import shlex
import shutil
import subprocess
import sys

MUTE_DB = -89.75                 # maximum attenuation on the AD9361
_STEP_TOL = 0.26                 # the attenuator quantises to 0.25 dB; allow one step
_SSH_TIMEOUT = 30.0              # see the note in _run()
_DEVKIT = pathlib.Path(__file__).resolve().parent.parent / "devkit"
_GUARD_SH = pathlib.Path(__file__).resolve().parent / "tx-guard.sh"

# tools/tx-guard.sh's documented exit codes.
_OK, _REFUSED_VALIDATION, _NO_AFFIRMATION, _WRITE_FAILED = 0, 1, 3, 4
_UNREACHABLE = 4                 # ./devkit tx-guard's own "could not reach the board"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    """Run the gate with a deadline, and turn a hang into a refusal.

    Bounded on purpose. These calls reach the board over ssh, and without a
    timeout a stalled connection blocks the caller indefinitely - which matters
    because a caller may already have a DMA buffer open, and a buffer enable is
    itself a raise. An unbounded wait there is an unbounded exposure window.
    A timeout is reported as a failure to reach the gate, never as permission.
    """
    try:
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=_SSH_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise TxGateError(
            f"the gate did not answer within {_SSH_TIMEOUT:g} s ({' '.join(cmd)}); "
            f"refusing to raise output") from exc


def _use_python() -> bool:
    """Which route: the devkit's (bash) or this module's own (paramiko)."""
    forced = os.environ.get("FISHBALL_TX_GATE", "").lower()
    if forced in ("python", "devkit"):
        return forced == "python"
    return os.name == "nt" or shutil.which("bash") is None


def _affirm_hint(channel: int) -> str:
    if _use_python():
        return f"python tools/tx_gate.py affirm {channel}"
    return f"./devkit tx-guard affirm {channel}"


def _guard_python(args: list[str]) -> subprocess.CompletedProcess:
    """What `./devkit tx-guard <args>` does, without bash: push, then run.

    Anything that stops the board being reached comes back as exit 4, which is
    also what ./devkit tx-guard returns for "could not reach the board", so
    callers cannot tell the routes apart - and an unreachable gate is never
    read as permission.
    """
    def fail(msg: str) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, _UNREACHABLE, "", msg + "\n")
    try:
        import paramiko
    except ImportError:
        return fail("the transmit gate needs paramiko on this machine "
                    "(install it in a venv, with the venv's own pip), "
                    "or bash and ./devkit")
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from board_addr import resolve
    host = resolve()
    key = pathlib.Path(os.environ.get("FISHBALL_SSH_KEY",
                                      pathlib.Path.home() / ".ssh" / "fishball"))
    client = paramiko.SSHClient()
    # No known_hosts, as in tools/flash.sh: every new card makes new host keys.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username="root", timeout=8,
                       key_filename=str(key) if key.is_file() else None,
                       password=os.environ.get("BOARD_PASS", "analog"),
                       allow_agent=False, look_for_keys=False)

        def run(command: str, stdin_data: bytes | None = None):
            stdin, stdout, stderr = client.exec_command(command, timeout=_SSH_TIMEOUT)
            if stdin_data is not None:
                stdin.write(stdin_data)
                stdin.channel.shutdown_write()
            out = stdout.read().decode(errors="replace")
            err = stderr.read().decode(errors="replace")
            return stdout.channel.recv_exit_status(), out, err

        rc, out, err = run("cat > /tmp/tx-guard.sh", _GUARD_SH.read_bytes())
        if rc != 0:
            return fail(f"could not push tx-guard.sh to {host}: {err.strip()}")
        rc, out, err = run("sh /tmp/tx-guard.sh " + " ".join(shlex.quote(a) for a in args))
        return subprocess.CompletedProcess(args, rc, out, err)
    except Exception as exc:                            # noqa: BLE001 - any failure
        return fail(f"could not reach the board at {host} to run the gate: {exc}")
    finally:
        client.close()


def _guard(args: list[str], devkit: pathlib.Path | None = None) -> subprocess.CompletedProcess:
    """Run tx-guard.sh on the board with these arguments, by whichever route."""
    if devkit is None and _use_python():
        return _guard_python(args)
    return _run([str(devkit or _DEVKIT), "tx-guard", *args])


class TxGateError(RuntimeError):
    """The gate did not write the attenuation that was asked for."""


class TxGateRefused(TxGateError):
    """No affirmation on record for that channel. Raising was refused."""


def assert_quiet_after_enable(read_db, where="buffer enable"):
    """Both attenuators must still read maximum. Raise if not, or if unreadable.

    `read_db(channel)` returns that channel's attenuation in dB, or raises.

    This is the check that stands in for the gate on a buffer enable that does not
    intend to raise anything. Enabling a TX DMA buffer is not neutral: the kernel's
    preenable hook powers the TX LO up and, when both attenuators read maximum -
    which is exactly the state a tool that means to stay silent leaves them in -
    restores a CACHED attenuation from the last stream. Measured at -61.5 dB on a
    board reading -89.75. A tool cannot ask an affirmation for that without
    breaking commands documented as never transmitting, so it checks instead.

    BOTH channels, because channel 1 is a separate SMA port and on this bench it is
    the one with an antenna on it. And an unreadable attenuator FAILS: resolving
    unknown toward quiet is the non-hazardous reading of the hazard being tested,
    which is the inversion tools/tx-guard.sh was rewritten to avoid and which its
    Python twin then reproduced.
    """
    for ch in (0, 1):
        try:
            got = read_db(ch)
        except Exception as exc:                       # noqa: BLE001 - any failure counts
            raise TxGateError(
                f"{where}: could not read channel {ch}'s attenuation ({exc}), so it "
                f"cannot be shown the buffer enable stayed quiet") from exc
        if got is None:
            raise TxGateError(
                f"{where}: channel {ch}'s attenuation read back empty; cannot show "
                f"the buffer enable stayed quiet")
        if got > MUTE_DB + _STEP_TOL:
            raise TxGateError(
                f"{where}: channel {ch} came up at {got} dB, not {MUTE_DB} - the "
                f"kernel's cache restore raised TX output on a buffer enable that "
                f"was meant to be silent")


def require_affirmation(channel: int, devkit: pathlib.Path | None = None) -> None:
    """Raise TxGateRefused unless that channel has an affirmation on record.

    For a tool that does its own attenuation writes - the selftest raises and
    lowers TX dozens of times during a ramp and a linearity sweep - asking the
    gate ONCE beats routing every write through set-gain over ssh. What the
    affirmation answers, whether that SMA port is terminated, does not change
    between writes. The trade is that this authorises the run rather than each
    write, so a tool using it must ask before its FIRST raise.
    """
    if channel not in (0, 1):
        raise ValueError(f"channel must be 0 (TX1A) or 1 (TX2A), not {channel!r}")
    p = _guard(["check", str(channel)], devkit)
    if p.returncode == _OK:
        return
    out = (p.stdout + p.stderr).strip()
    if p.returncode == _NO_AFFIRMATION:
        raise TxGateRefused(
            f"REFUSED: this raises TX output on TX{channel + 1}A and no affirmation "
            f"that the port is terminated is on record.\n"
            f"    Look at the port. Then, only if it is into a load, an antenna you "
            f"may legally drive, or an attenuated loopback:\n"
            f"        {_affirm_hint(channel)}\n"
            f"    It dies at the next reboot. Channel 0 is TX1A, channel 1 is TX2A.")
    raise TxGateError(
        f"could not ask the gate whether channel {channel} is affirmed "
        f"(tx-guard exit {p.returncode}); refusing to raise output\n{out}")


def gated_set_atten(channel: int, db: float, devkit: pathlib.Path | None = None) -> float:
    """Ask the gate to write TX attenuation on one channel. Return the read-back.

    `channel` is 0 for TX1A or 1 for TX2A - two separate SMA ports, which is
    why one affirmation cannot stand for both. `db` is negative attenuation in
    dB, -89.75 quiet and 0 full output.

    Raises TxGateRefused when that channel has no affirmation on record, and
    TxGateError on a validation refusal, a failed write, or a board that cannot
    be reached. Every one of those leaves the port quiet or the failure loud;
    none of them silently proceeds.
    """
    if channel not in (0, 1):
        raise ValueError(f"channel must be 0 (TX1A) or 1 (TX2A), not {channel!r}")
    # Two decimals: the attenuator quantises to 0.25 dB, and tx-guard.sh
    # refuses anything that is not a plain decimal - "%g" would hand it
    # "-1e-05" for a value near zero.
    val = f"{db:.2f}"
    p = _guard(["set-gain", str(channel), val], devkit)
    out = (p.stdout + p.stderr).strip()
    if p.returncode == _NO_AFFIRMATION:
        raise TxGateRefused(
            f"REFUSED: raising TX{channel + 1}A to {val} dB needs an affirmation that "
            f"that port is terminated, and none is on record.\n"
            f"    Look at the port. Then, only if it is into a load, an antenna you "
            f"may legally drive, or an attenuated loopback:\n"
            f"        {_affirm_hint(channel)}\n"
            f"    It dies at the next reboot. Channel 0 is TX1A, channel 1 is TX2A.\n"
            f"{out}")
    if p.returncode != _OK:
        raise TxGateError(
            f"the gate did not write {val} dB on channel {channel} "
            f"(tx-guard exit {p.returncode}); treat the port as suspect\n{out}")
    # tx-guard.sh reads the value back from sysfs and fails the write if it did
    # not land. Parse what it printed AND check it against what was asked for:
    # exit 0 plus a read-back line used to be accepted unconditionally, so a
    # value that had moved between the gate's compare and its report - the starve
    # watchdog firing in that gap puts it at maximum - came back as a success
    # carrying a number nobody had checked.
    for line in out.splitlines():
        if "attenuation verified at" in line:
            try:
                got = float(line.rsplit("at", 1)[1].split()[0])
            except (IndexError, ValueError) as exc:
                raise TxGateError(
                    f"could not parse the gate's read-back from {line!r}") from exc
            if abs(got - db) > _STEP_TOL:
                raise TxGateError(
                    f"the gate reported success at {got} dB but {val} dB was asked "
                    f"for on channel {channel}; treat the port as suspect\n{out}")
            return got
    raise TxGateError(f"the gate reported success without a read-back:\n{out}")


if __name__ == "__main__":
    # The gate from any shell, Windows included: the same commands and exit
    # codes as `./devkit tx-guard` (affirm, revoke, status, check, set-gain, reap).
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        sys.exit(0)
    result = _guard(sys.argv[1:])
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    sys.exit(result.returncode)
