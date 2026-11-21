#!/usr/bin/env python3
"""How the Python tools log in to the board. tools/lib/board-ssh.sh is the same
logic for the shell tools, and says why; keep the two in step.

    from board_ssh import ssh_argv, can_login, hint
    subprocess.run(ssh_argv(host) + ["uname -r"])

The key ./devkit ssh-key makes (${FISHBALL_SSH_KEY:-~/.ssh/fishball}) is tried
first when the file exists: alone and with BatchMode=yes, so ssh can ask for
nothing, not even the passphrase of a key that has one. Only when the board
answers and refuses it is there a second connection, without that key: ssh's
usual identities and the agent, wrapped in sshpass where that is installed so
the password (${BOARD_PASS:-analog}) answers, and with BatchMode=yes where it is
not - never a password prompt hanging a script; sshpass is not on a stock Mac.

That is two commands in the worst case, so ssh_argv() returns this file run as
a program, which makes the attempts: stdin, stdout and the exit status pass
through, and the first attempt's stderr is printed when it is the last word.

No known_hosts: every board is 192.168.2.1 over USB and each card has its own
host key. Python 3.8.
"""
import os
import shutil
import sys


def key_path():
    return os.environ.get("FISHBALL_SSH_KEY") or os.path.expanduser("~/.ssh/fishball")


def sshpass():
    """Is sshpass installed (so a password login is possible)?"""
    return shutil.which("sshpass") is not None


def can_login():
    """A key or sshpass is here. Touches no network."""
    return os.access(key_path(), os.R_OK) or sshpass()


def install_line():
    """The package manager's line for sshpass on this OS."""
    if sys.platform == "darwin":
        # Homebrew's own repository has not always carried sshpass; this tap is
        # the usual source when it does not.
        return ("brew install sshpass    (if Homebrew has no such formula: "
                "brew install hudochenkov/sshpass/sshpass)")
    return "sudo apt install sshpass"


def hint():
    """The two ways to make login work."""
    install = install_line()
    return ("No way to log in to the board without typing a password. Either:\n"
            "    ./devkit ssh-key            a key for this board; nothing to install\n"
            f"    {install}\n"
            "With sshpass the board's password is used (BOARD_PASS, default analog).")


def options(connect_timeout=10):
    return ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-o", f"ConnectTimeout={connect_timeout}"]


def refused(returncode, stderr):
    """Did the board ANSWER and refuse the login, as opposed to not answering?
    ssh says so with status 255; sshpass says nothing and exits 5 when the
    password it typed was refused, which a remote command can return as well -
    so ask this about a probe such as `true`."""
    if returncode == 255 and any(m in stderr for m in ("Permission denied", "Too many authentication failures",
                                                       "No more authentication methods")):
        return True
    return returncode == 5 and sshpass()


def attempts(target, password=None, connect_timeout=10):
    """The ssh command lines to try, in order, each up to and including
    user@host. The second is only for a board that refused the first."""
    base = ["ssh"] + options(connect_timeout)
    out = []
    if os.access(key_path(), os.R_OK):
        # IdentitiesOnly on this attempt: an agent holding many keys runs the
        # board's sshd out of attempts before it reaches the right one.
        out.append(base + ["-i", key_path(), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes", target])
    if sshpass():
        out.append(["sshpass", "-p", password or os.environ.get("BOARD_PASS", "analog")] + base + [target])
    else:
        out.append(base + ["-o", "BatchMode=yes", target])
    return out


def ssh_argv(host, password=None, connect_timeout=10, user="root"):
    """A command line that logs in as user@host; append the remote command."""
    argv = [sys.executable, os.path.abspath(__file__), "--connect-timeout", str(connect_timeout)]
    # Only a password that is not the one main() would use anyway: it shows in `ps`.
    if password and password != os.environ.get("BOARD_PASS", "analog"):
        argv += ["--password", password]
    return argv + [f"{user}@{host}"]


def main(argv):
    import subprocess
    password, timeout = None, 10
    while argv and argv[0] in ("--password", "--connect-timeout") and len(argv) > 1:
        if argv[0] == "--password":
            password = argv[1]
        else:
            timeout = int(argv[1])
        argv = argv[2:]
    if len(argv) < 2:
        print("usage: board_ssh.py [--connect-timeout N] [--password P] user@host command", file=sys.stderr)
        return 2
    tries = attempts(argv[0], password, timeout)
    if len(tries) == 2:
        # stdout and stdin straight through; stderr held, because it decides
        # whether there is a second attempt.
        r = subprocess.run(tries[0] + argv[1:], stderr=subprocess.PIPE)
        err = r.stderr.decode(errors="replace")
        if not (r.returncode == 255 and refused(r.returncode, err)):
            sys.stderr.write(err)
            return r.returncode
        # Refused before a session began: nothing ran, and stdin is unread.
    # The last attempt replaces this process, so a caller's timeout kills ssh.
    sys.stdout.flush()
    sys.stderr.flush()
    try:
        os.execvp(tries[-1][0], tries[-1] + argv[1:])
    except OSError as exc:
        print(f"{tries[-1][0]}: {exc}", file=sys.stderr)
        return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
