---
icon: material/radio-tower
description: Short task pages for receiving, transmitting and writing your own code with the board.
---

# Use the radio

What do you want to do with the board? Each card is one short page. The long
pages with every measurement are under [Reference](#reference).

<div class="grid cards" markdown>

-   :material-sitemap-outline:{ .lg } **[Choose where your code runs](choose-where-code-runs.md)**


    Your PC, the board, the kernel or the FPGA: four questions decide it.

-   :material-language-python:{ .lg } **[Talk to the board from Python](talk-from-python.md)**


    Install `pyadi-iio` in a venv, then tune and receive in six lines.

-   :material-file-download-outline:{ .lg } **[Capture IQ to a file](capture-iq.md)**


    A self-describing SigMF recording, with a check for lost samples.

-   :material-waves:{ .lg } **[Watch a band in SDR++](watch-in-sdrpp.md)**


    Stock SDR++ playing an FM station, on any OS.

-   :material-speedometer:{ .lg } **[Stream 20 MS/s to SDR++](stream-20-msps.md)**


    The patched SDR++ and `zc-stream`: a live 20 MHz-wide view.

-   :material-airplane:{ .lg } **[Track aircraft (ADS-B)](track-aircraft.md)**


    One command, a 1090 MHz antenna, a live table of aircraft.

-   :material-call-split:{ .lg } **[Receive on both channels](receive-both-channels.md)**


    RX1 and RX2 sample-aligned, in one recording.

-   :material-repeat:{ .lg } **[Transmit a waveform on repeat](transmit-on-repeat.md)**


    A cyclic buffer: the board replays it at full rate, with the safe ordering.

-   :material-flash-outline:{ .lg } **[Send a burst on a trigger](burst-on-trigger.md)**


    A prepared buffer, played once per UDP datagram or GPIO edge.

-   :material-chart-bell-curve:{ .lg } **[Watch a sweep live](watch-a-sweep.md)**


    chirp-view: TX1 sweeps, RX1 receives it, live, through the 20 dB loop.

-   :material-matrix:{ .lg } **[Use MATLAB](use-matlab.md)**


    One command checks MATLAB; three rules keep levels and settings right.

-   :material-stethoscope:{ .lg } **[Check the radio is healthy](check-the-radio.md)**


    The self-test, with no cable and nothing transmitted.

</div>

## Reference

The full pages, with every measurement and caveat:
[your own project](../your-own-project.md) ·
[capturing IQ](../capturing-iq.md) ·
[SDR++](../sdrpp.md) ·
[ADS-B](../adsb.md) ·
[other SDR tools](../other-sdr-tools.md) ·
[MATLAB](../matlab.md) ·
[both receive channels](../both-receive-channels.md) ·
[cyclic buffers and triggers](../cyclic-buffers.md) ·
[chirp-view](../chirp-view.md) ·
[modulation gallery](../modulation-gallery.md) ·
[measured performance](../measured-performance.md) ·
[throughput and modulation](../modulation-and-throughput.md) ·
[faster streaming](../streaming-paths.md).
