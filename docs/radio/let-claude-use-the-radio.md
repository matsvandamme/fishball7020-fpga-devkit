---
icon: material/robot-happy-outline
description: Connect the MCP server and ask Claude to tune, scan, capture and, inside a safety gate, transmit.
---

# Let Claude use the radio

The sibling [MCP server](../mcp-server.md) turns the board into tools that
Claude can call. Ask in plain words, "what is on the air around 433 MHz?",
and Claude tunes the board, scans the band and answers from what it measured.

1. Install the server and register it with Claude Code, once.

    ```bash
    # run from: wherever you want the server to live (e.g. ~)
    git clone https://github.com/matsvandamme/Fishball7020-mcp.git
    cd Fishball7020-mcp
    python3 -m venv .venv
    .venv/bin/pip install -e .
    claude mcp add -s user fishball-sdr -- "$PWD/.venv/bin/fishball-sdr-mcp"
    ```

2. Start Claude Code. From the devkit, this also opens the
   [board pane](watch-from-claude-code.md):

    ```bash
    # run from: the repo root
    ./devkit claude-pane start
    ```

3. Ask it something.

    ```text
    # run in: Claude Code, at its prompt
    What is the radio set to?
    ```

**You should see:** Claude calls `sdr_get_status` and answers from what it
returns. What the tool returned on a board at 2.4 GHz:

```text
# in Claude Code: what sdr_get_status returned, captured from the board
## Radio status

| | |
|---|---|
| Board | FISH Ball PlutoSDR Rev.A (Z7020/AD9361) (fw v2.0) |
| RX LO | 2.4 GHz |
| Converter rate | 30.72 MHz |
| Delivered rate | 30.72 MHz |
| FPGA channel filter | bypassed (÷1) |
| RF bandwidth | 18 MHz |
| Gain | 71.000000 dB (slow_attack) |
| RSSI | 117.50 dB |
| Die temperature | 54.4 °C |
| ENSM mode | fdd |
```

**It can transmit.** Transmitting is on by default, inside a gate that refuses
anything outside the EU licence-free bands or over their power limits. Read
[transmitting](../mcp-server.md#transmitting) before you ask for it, and never
cable a transmit port to a receive port without at least 20 dB of attenuation.

??? question "Claude does not offer the radio tools?"
    Run `claude mcp list`. If `fishball-sdr` is missing, it was registered
    without `-s user`, for another folder only: register it again with
    `-s user`, then restart Claude Code.

??? question "A tool says the device is busy?"
    Another program, such as SDR++, holds the radio's buffer. Close it, or run
    `tools/board-busy.sh` from the repo root to see what holds it.

What else to ask, its settings and how to turn transmitting off:
[the MCP server](../mcp-server.md).
