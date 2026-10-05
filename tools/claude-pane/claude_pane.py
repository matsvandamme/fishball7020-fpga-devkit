#!/usr/bin/env python3
"""The board in a Claude Code side pane: load it, install it, test it.

    # run from: anywhere
    ./devkit claude-pane              # where the plugin is, and how to load it
    ./devkit claude-pane install      # load it in every Claude Code session
    ./devkit claude-pane uninstall    # stop loading it
    ./devkit claude-pane test         # its manifest check and its tests (needs `claude`)

The plugin is this folder, tools/claude-pane/. In Claude Code, /fishball opens
the pane: the board's links (USB, Ethernet, libiio), die temperatures, radio
settings, CI and the local build. It only ever reads from the board.

`install` adds this folder to CLAUDE_CODE_PLUGIN_DIRS in the "env" block of
~/.claude/settings.json, which every Claude Code session reads; nothing else
in that file is changed, and a file that is not valid JSON is refused rather
than rewritten. To load it for one session instead:

    claude --plugin-dir tools/claude-pane
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
VAR = "CLAUDE_CODE_PLUGIN_DIRS"


def load_settings() -> dict:
    try:
        with open(SETTINGS) as f:
            text = f.read()
    except FileNotFoundError:
        return {}
    try:
        data = json.loads(text) if text.strip() else {}
    except ValueError as e:
        sys.exit(f"ERROR: {SETTINGS} is not valid JSON ({e}); fix it first, nothing was changed.")
    if not isinstance(data, dict):
        sys.exit(f"ERROR: {SETTINGS} is not a JSON object; nothing was changed.")
    return data


def dirs_of(data: dict) -> list[str]:
    value = (data.get("env") or {}).get(VAR, "")
    return [d for d in str(value).split(os.pathsep) if d]


def save(data: dict) -> None:
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    tmp = SETTINGS + ".devkit-tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, SETTINGS)


def same(a: str, b: str) -> bool:
    return os.path.realpath(os.path.expanduser(a)) == os.path.realpath(b)


def where() -> int:
    installed = any(same(d, HERE) for d in dirs_of(load_settings()))
    print(f"plugin:    {HERE}")
    print(f"installed: {'yes, every session loads it' if installed else 'no'} ({SETTINGS})")
    print()
    print(f"  one session:   claude --plugin-dir {HERE}")
    print("  every session: ./devkit claude-pane install")
    print("  then, in Claude Code: /fishball")
    return 0


def install() -> int:
    data = load_settings()
    dirs = dirs_of(data)
    if any(same(d, HERE) for d in dirs):
        print(f"Already installed: {VAR} in {SETTINGS} names {HERE}")
        return 0
    data.setdefault("env", {})[VAR] = os.pathsep.join(dirs + [HERE])
    save(data)
    print(f"Installed: added {HERE}")
    print(f"  to {VAR} in {SETTINGS}")
    print("  A Claude Code session started from now on loads it; /fishball opens the pane.")
    return 0


def uninstall() -> int:
    data = load_settings()
    dirs = dirs_of(data)
    kept = [d for d in dirs if not same(d, HERE)]
    if kept == dirs:
        print(f"Not installed: {VAR} in {SETTINGS} does not name {HERE}")
        return 0
    env = data["env"]
    if kept:
        env[VAR] = os.pathsep.join(kept)
    else:
        del env[VAR]
        if not env:
            del data["env"]
    save(data)
    print(f"Uninstalled: removed {HERE} from {VAR} in {SETTINGS}")
    return 0


def test() -> int:
    claude = shutil.which("claude")
    if not claude:
        sys.exit("ERROR: `claude` is not on PATH; install Claude Code to run the plugin's tests.")
    rc = subprocess.call([claude, "plugin", "validate", HERE])
    return rc or subprocess.call([claude, "plugin", "test", HERE])


def main(argv: list[str]) -> int:
    if any(a in ("-h", "--help", "help") for a in argv):
        print(__doc__.strip())
        return 0
    cmd = argv[0] if argv else ""
    actions = {"": where, "install": install, "uninstall": uninstall, "test": test}
    if cmd not in actions or len(argv) > 1:
        print(f"usage: ./devkit claude-pane [install|uninstall|test]", file=sys.stderr)
        return 2
    return actions[cmd]()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
