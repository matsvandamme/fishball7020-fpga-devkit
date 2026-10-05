---
icon: material/monitor-dashboard
description: A Claude Code pane with the board's links, temperatures, radio settings and CI, refreshing on its own.
---

# Watch the board from Claude Code

[Claude Code](https://claude.com/claude-code) is Anthropic's AI coding
assistant, run in a terminal. The devkit ships a plugin for it, an add-on it
loads at start: type `/fishball` and a pane beside the conversation shows the
board while you work. It only reads; it never changes a radio setting or
transmits.

```bash
# run from: the repo root
./devkit claude-pane start
```

That starts Claude Code in the repo with the plugin loaded and the pane open.
Options after `start` go to Claude Code: `./devkit claude-pane start --model sonnet`.

To have every Claude Code session load the plugin, so that `/fishball` opens
the pane wherever you start it, install it once:

```bash
# run from: the repo root
./devkit claude-pane install
```

**You should see:** the board's links, both die temperatures and the radio's
settings within a few seconds, then CI on `main`. A real pane, with the
board on the USB cable:

```text
# in Claude Code: the /fishball pane, captured from the terminal
◥◥ VMAT
◥◥ Fishball7020 · Zynq 7020 + AD9361

[ Refresh ] updated 0s ago · next in 7s

📡 Board 0s ago
🔌 USB      ● fishball.local (192.168.2.1)
🌐 Ethernet ○ not found
🔗 libiio   ● usb:3.37.4
FISH Ball PlutoSDR Rev.A (Z7020/AD9361)
⏱ up 10m · ⚡ load 0.11 0.09 0.04
🌡 die temperatures (warm 68, hot 80 °C)
Zynq   ▕█████████████████████████░░░░░▏ 70.3°C
AD9361 ▕███████████████████░░░░░░░░░░░▏ 53.5°C
board v2.0-9-g5ae29d94-dirty
local v2.3-67-gd9cc430-dirty
△ board is 256 commits behind local
kernel 6.12.0-g61ef303acadc-dirty
read via iiod 192.168.2.1

📻 Radio 4s ago
RX LO 2400.000 MHz
TX LO 2400.000 MHz
rate 30.720 MSPS
BW rx 18.000 MHz · tx 18.000 MHz
ch0 rx 71 dB (slow_attack) · tx −89.75 dB
ch1 rx 71 dB (slow_attack) · tx −89.75 dB

🐙 GitHub 4s ago
★ 13 · ⑂ 4 · PRs 0 · issues 0 · CI on main
✓ Dependency Graph 16h ago
✓ Docs 3h ago
✓ Hardware 3h ago
✓ Host tools 3h ago
✓ Verify patches apply cleanly 7h ago
✓ Verify the Debian root 4h ago
✓ Verify the modern firmware 6h ago
● runner omarchy-fishball online
```

The line under the prompt keeps a summary while the pane is closed:
`fishball ● USB 70°C CI ✓`.

??? question "Every link is ○?"
    The board is off, still booting (about 40 s), or on a USB port that cannot
    power it. [How it finds the board](../claude-code-pane.md#how-it-finds-the-board)
    goes through each case.

??? question "Nothing happens when you type /fishball?"
    Claude Code loads plugins when it starts: quit it and start it again after
    `install`. `./devkit claude-pane` says whether the plugin is installed;
    `./devkit claude-pane start` works without installing it.

??? question "It says `claude` is not on PATH?"
    Install [Claude Code](https://claude.com/claude-code) first, then open a
    new terminal so the `claude` command is found.

Everything it shows, how it works and its settings:
[the board in a Claude Code pane](../claude-code-pane.md). To let Claude act on
the radio as well: [let Claude use the radio](let-claude-use-the-radio.md).
