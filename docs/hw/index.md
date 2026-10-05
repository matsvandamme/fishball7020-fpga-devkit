---
icon: material/chip
description: Ports, header pins, the USER LED, the reference clock and the schematic, one question per page.
---

# Hardware and I/O

What is on the board and how to wire to it, one question per page.

<div class="grid cards" markdown>

-   :material-connection:{ .lg } **[Which port is which](which-port-is-which.md)**

    ---

    The four SMAs, the U.FL sockets, the two USB-C sockets. Trust the silkscreen, not the case.

-   :material-pin-outline:{ .lg } **[Wire something to the JP5 header](wire-to-jp5.md)**

    ---

    Four free 3.3 V pins, where ground is, and what not to touch.

-   :material-toggle-switch-outline:{ .lg } **[Toggle a GPIO pin from Linux](toggle-a-gpio.md)**

    ---

    Read or drive the four free pins from the board or from your PC.

-   :material-sine-wave:{ .lg } **[Make pins follow the transmit samples](pins-follow-transmit.md)**

    ---

    Clocks, triggers and markers locked to the transmitted waveform.

-   :material-led-outline:{ .lg } **[Control the USER LED](control-the-user-led.md)**

    ---

    By default it is lit while a transmitter is live. Change that, or drive it yourself.

-   :material-clock-outline:{ .lg } **[Use an external reference clock](external-reference-clock.md)**

    ---

    Move `R107` to `R109`, then feed `EXT_CLK` within the AD9361's limits.

-   :material-check-circle-outline:{ .lg } **[Check which reference the radio uses](check-the-reference.md)**

    ---

    Lock bits, a frequency measurement, and `xo_correction`.

-   :material-file-document-outline:{ .lg } **[Find a part on the schematic](find-a-part.md)**

    ---

    Which PDF to trust, which sheets matter, and the ratings everything is checked against.

</div>

## Reference

The long pages, with every table and measurement:

- [What is on the board](../hardware.md): devices, clocks, connectors, supply rails.
- [GPIO](../gpio.md): the three ways to drive a pin, and the full line map.
- [Sample-locked GPIO](../tx-gpio-bitmap.md): the feature, how it is built, what was measured.
- [The USER LED](../user-led.md): wiring, the `tx-active` trigger, boot-time defaults.
- [Vendor schematic](../vendor/README.md): the schematic's provenance and the datasheet figures.
