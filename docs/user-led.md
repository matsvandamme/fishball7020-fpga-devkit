# Controlling the USER LED

The board has three LEDs between the `USB2.0` and `DEBUG` ports:

| LED | Driven by | Can you control it? |
|---|---|---|
| `PWR` | Power rail | No — hardwired |
| `DONE` | The FPGA's own configuration logic | No — it goes high when the bitstream loads |
| `USER` | Linux, through a PS GPIO pin | **Yes** — this page |

## How it's wired (and why that matters)

From the board's device tree:

```dts
leds {
    compatible = "gpio-leds";
    led0 {
        label = "led0:green";
        gpios = <0x09 0x00 0x00>;          /* controller, pin 0, active high */
        linux,default-trigger = "heartbeat";
    };
};
```

Phandle `0x09` resolves to `gpio@e000a000` — `xlnx,zynq-gpio-1.0`, the
**PS** GPIO controller. So the LED hangs off **MIO pin 0 on the ARM side**.

That has one important consequence:

> **You cannot drive this LED from your HDL.** MIO pins belong to the
> Processing System and are not routed into the Programmable Logic. It does
> not appear in `system_top.v` or `system_constr.xdc`, and no amount of
> block-design work will connect it. Driving it is a *software* job.

That `linux,default-trigger = "heartbeat"` line is what the *factory* firmware
uses — the kernel's heartbeat trigger, not your firmware. This repo's builds
leave the device tree exactly as it is and point the LED somewhere more useful
at boot instead; that is the next section.

## What it does by default here: it follows the transmitter

On a board that reaches about **+19 dBm**, a light that says "the CPU is alive"
is worth less than one that says **whether RF can leave the port**. So these
builds ship a kernel LED trigger called `tx-active`, and
[`S21misc`](../firmware/patches/0012-user-led-follows-the-transmitter.patch)
selects it at boot:

> **Lit** whenever either transmit chain is out of full attenuation.
> **Dark** when both sit at the −89.75 dB mute floor.

The trigger is driven from `ad9361_set_tx_atten()` in the AD9361 driver — the
one point every attenuation change passes through, whether that is the kernel's
own mute when a DMA stream is torn down (patches `0004`/`0005`) or a plain
sysfs write. There is no polling loop.

**Why the attenuator and not the DMA buffer.** Attenuation can be raised with
no buffer open at all: the driver accepts it and drives the real attenuator, so
a stream-only indicator would sit dark while the LO leaks out of the SMA. That
is the case worth having a light for. The trade is the mirror image — a DMA
stream running into a fully attenuated chain leaves the LED dark, because
nothing is actually getting out. Measured on hardware:

| State | LED |
|---|---|
| both channels muted, no buffer | dark |
| TX1 raised, no buffer | **lit** |
| TX2 raised, no buffer | **lit** |
| both raised | **lit** |
| gain set, then a DMA stream running | **lit** |
| DMA stream running, both channels still muted | dark |
| stream ends, kernel re-mutes | dark |

**To opt out** and keep the heartbeat, set a U-Boot variable and reboot:

```bash
# on the board
fw_setenv tx_led 0
```

Or just pick another trigger at runtime, as below — nothing stops you.

## Taking control from Linux

Everything happens under sysfs. On the board (serial console or SSH):

```sh
# on the BOARD
ls /sys/class/leds/
cd /sys/class/leds/led0:green
```

*(If the directory name differs, use whatever `ls` shows — it comes from the
`label` property above.)*

**Turn off the heartbeat and drive it yourself.** The trigger must be set to
`none` first, or the kernel keeps overwriting your value:

```sh
# on the board, in /sys/class/leds/led0:green
echo none > trigger
echo 1 > brightness        # on
echo 0 > brightness        # off
```

**See what else it can do automatically:**

```sh
# on the board, in /sys/class/leds/led0:green
cat trigger
```

The current trigger is shown in `[brackets]`. Useful ones include `none`,
`heartbeat`, `timer`, `oneshot`, plus activity triggers such as `mmc0` (SD
card access) and CPU triggers.

**Blink at your own rate**, with no code at all:

```sh
# on the board, in /sys/class/leds/led0:green
echo timer > trigger
echo 100 > delay_on        # milliseconds lit
echo 900 > delay_off       # milliseconds dark
```

**Flash it on SD-card activity:**

```sh
# on the board, in /sys/class/leds/led0:green
echo mmc0 > trigger
```

## Using it as a status light in your own program

From a shell script:

```sh
# on the board - save this as a file, then run it
#!/bin/sh
LED=/sys/class/leds/led0:green
echo none > $LED/trigger
while true; do
    if my_application_is_healthy; then
        echo 1 > $LED/brightness
    else
        echo 0 > $LED/brightness; sleep 0.2; echo 1 > $LED/brightness
    fi
    sleep 1
done
```

From C, it's just a file write:

```c
int fd = open("/sys/class/leds/led0:green/brightness", O_WRONLY);
write(fd, "1", 1);
```

Remember the root filesystem is a **ramdisk** — a script you write on the
board vanishes at reboot unless you either put it in `/mnt/jffs2` or, better,
add it to `firmware/patches/` so it becomes part of every build.

## Making your own setting the default at boot

The obvious route — editing `linux,default-trigger` in
`zynq-pluto-sdr-fishball.dts` — is the **wrong** one here. That device tree
recompiles byte-for-byte identical to the factory board's, which is a
load-bearing provenance claim for this repo ([how it was
verified](provenance.md)); changing it to set an LED throws that away for no
good reason.

Do it the way patch `0012` does instead: pick the trigger from `S21misc`, the
rootfs init script, which leaves the `.dtb` untouched.

```sh
# in firmware/src/buildroot/board/pluto/S21misc, inside the start case
echo timer > /sys/class/leds/led0:green/trigger
```

Then capture it as a patch so it survives a clean `setup.sh`, numbering it
after the highest existing one:

```bash
# run from: firmware/src
diff -u <pristine copy of S21misc> buildroot/board/pluto/S21misc \
    > ../patches/0013-my-led-default.patch
```

Generate it against a *pristine copy* rather than with `git diff` — `S21misc`
is already touched by patches `0004` and `0012`, so a plain `git diff` would
sweep their changes into yours. Other useful trigger values are `timer`,
`mmc0`, `none` and `default-on`.

## If you want an LED your FPGA logic drives directly

The `USER` LED can't do this, so you need a pin that actually reaches the PL.
The easiest ones are the four 3.3 V header pins the sample-locked GPIO feature
already maps — JP5 pins 7/9/11/13, balls V10/U9/U10/T9, bank 13, `LVCMOS33`
(see [tx-gpio-bitmap.md](tx-gpio-bitmap.md#the-pins)). With that feature off
they are ordinary Linux GPIO 978–981, so an LED on one of them needs **no HDL
at all**: wire LED + resistor from the pin to GND (pin 2 or 20) and drive it
from `/sys/class/gpio`. To drive one from your own fabric logic instead, take
the pin over in `system_bd.tcl` the way `tx_gpio_bitmap` does.

Any other header pin needs the **board schematic** first — don't guess, since
driving a pin that turns out to be an input or tied elsewhere can damage the
board. The constraint pattern is the same as every other line in the file:

```tcl
# in firmware/src/hdl/projects/pluto/system_constr.xdc
set_property -dict {PACKAGE_PIN <ball> IOSTANDARD LVCMOS33} [get_ports my_led]
```

Add a matching `output my_led` to `system_top.v`, drive it from your logic,
and rebuild. A counter off `axi_ad9361/l_clk` makes a good first test — see
[Add your own HDL](building.md#add-your-own-hdl).

**The pragmatic middle ground:** if you just want the `USER` LED to reflect
something happening inside the PL, expose that state in an AXI register your
logic already writes, and have a small userspace loop read it and set
`brightness`. The PS does the driving; your HDL decides when.
