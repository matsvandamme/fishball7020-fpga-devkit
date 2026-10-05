---
icon: material/led-outline
description: By default the USER LED is lit while a transmitter is live. Change that, or drive it yourself.
---

# Control the USER LED

On these builds the `USER` LED **follows the transmitter**: lit whenever either
transmit chain is out of full attenuation, dark when both sit at the −89.75 dB
mute floor. The factory firmware blinks a heartbeat instead.

## Drive it yourself

Set the trigger to `none` first, or the kernel keeps overwriting your value:

```sh
# run from: the board
cd /sys/class/leds/led0:green      # or whatever `ls /sys/class/leds/` shows
echo none > trigger
echo 1 > brightness                # on; 0 for off
cat trigger                        # the available triggers; the current one in [brackets]
echo timer > trigger               # blink at your own rate:
echo 100 > delay_on                #   milliseconds lit
echo 900 > delay_off               #   milliseconds dark
```

**To keep the heartbeat instead of `tx-active`**, set a U-Boot variable and reboot:

```bash
# run from: the board (Buildroot or Debian)
fw_setenv tx_led 0
```

| What it shows by default | LED |
|---|---|
| both channels muted, no buffer | dark |
| TX1, TX2 or both raised, no buffer | **lit** |
| gain set, then a DMA stream running | **lit** |
| DMA stream running, both channels still muted | dark |

| Good to know | |
|---|---|
| a setting made on the board | vanishes at reboot on **Buildroot**; on **Debian** run it at boot from a systemd unit (`/mnt/jffs2/autorun.sh` is not run there) |
| **your HDL cannot drive this LED** | it is on PS MIO pin 0, not routed into the programmable logic |
| an LED your FPGA logic drives | use a free JP5 pin, with a resistor to ground ([wire to JP5](wire-to-jp5.md)) |

**Reference:** [the USER LED](../user-led.md): wiring, making a trigger the
boot-time default, an LED driven from the fabric.
