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
board on the USB cable and on the home network at once:

```text
# in Claude Code: the /fishball pane, captured from the terminal
◥◥ VMAT
◥◥ Fishball7020 · Zynq 7020 + AD9361

[ Refresh ] updated 1s ago · next in 6s

📡 Board 1s ago
🔌 USB      ● fishball.local (192.168.2.1)
🌐 Ethernet ● 192.168.129.168
🔗 libiio   ● usb:3.41.4
FISH Ball PlutoSDR Rev.A (Z7020/AD9361)
⏱ up 16m · ⚡ load 0.60 0.48 0.27
🌡 die temperatures (warm 68, hot 80 °C)
Zynq    76.7°C ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━──────
         76–77                                                    ▄▄▄▃▄▄▄▆▅
AD9361  55.3°C ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━─────────────────────
         54–55                                                    ▄▅▅▅▅▅▅▄▅
trend: last 9 readings over 1m, each on its own scale
board v2.3-68-g210a363b
local v2.3-68-g210a363-dirty
✓ the board runs the local build
kernel 6.12.0-g61ef303acadc-dirty
read via iiod 192.168.2.1

📻 Radio 1s ago
RX LO 2400.000 MHz
TX LO 2400.000 MHz
rate 30.720 MSPS
BW rx 18.000 MHz · tx 18.000 MHz
ch0 rx 71 dB (slow_attack) · tx −89.75 dB
ch1 rx 71 dB (slow_attack) · tx −89.75 dB

🐙 GitHub 1m ago
★ 13 · ⑂ 4 · PRs 0 · issues 0 · CI on main
✓ Docs 54m ago
✓ Hardware 54m ago
✓ Host tools 54m ago
✓ Verify patches apply cleanly 9h ago
✓ Verify the Debian root 6h ago
✓ Verify the modern firmware 7h ago
● runner omarchy-fishball online
```

Each die has a gauge (how hot it is now, on a 0 to 85 °C scale) and, under it,
a trend: one bar per recent reading, newest on the right, scaled between the
lowest and highest reading shown at its left.

The line under the prompt keeps a summary while the pane is closed, naming
every link that is up: `fishball ● USB+Ethernet 77°C CI ✓`.

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
