# chirp-view: a sweep on TX1, watched and heard live on RX1

A program for your PC. It makes TX1 play a sweep from a cyclic buffer, over
and over, and shows RX1 receiving it through the bench loop (TX1 → 20 dB
attenuator → RX1): a live spectrum, a waterfall, the loop's response, and the
sweep it sent. The speakers play the received sweep as a whistle. A panel
starts and stops the transmitter and changes the sweep while it runs.

In **Pulsed chirp** mode it also shows the received pulse compressed by a
matched filter, as a radar does: peak width, sidelobes, and the shift when you
add a cable to the loop.

What you see, the eight sweep modes, and how it works:
[docs/chirp-view.md](../../docs/chirp-view.md).

```bash
# run from: tools/chirp-view on your PC
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python chirp_view.py                  # 7 MHz up-sweep every 0.8 s around 868 MHz, 20 MS/s
.venv/bin/python chirp_view.py --fullscreen     # Esc or Q quits, muting TX1 first
.venv/bin/python chirp_view.py --check          # build the sweep and check it, no board needed
.venv/bin/python chirp_view.py --channel 2      # the second pair: TX2 -> pad -> RX2, TX1 muted
.venv/bin/python chirp_view.py --reference loops   # pulse ranging timed against RX2: lost samples cannot move it
```

**Fit at least 20 dB of attenuation between TX1 and RX1** before you start: the
board puts out about +19 dBm and RX1 survives +2.5 dBm.
[Transmitter safety](../../docs/transmitter-safety.md) has the reasons.

20 MS/s needs [`zc-stream`](../stream-paths/zc-stream/README.md) installed on
the board as a service. Without it, run at 4.8 MS/s through libiio:
`--rate 4.8e6 --span 1e6 --period 3`.

`mirror_test.py` measures the radio's IQ image (the mirror of the sweep) with a
single tone, separating what the transmitter and the receiver each produce.
