# Changing the board's IP address

Out of the box the board answers on **192.168.2.1** over its USB cable, and asks
your router for an address over the Ethernet socket. This page is how to change
either one, and how to find the board again afterwards.

Everything here was read out of the firmware's own startup scripts and then
checked against a running board. Where a claim comes from a script rather than a
measurement, the script is named so you can read it yourself.

**Jargon, once:** *DHCP* is a router handing out addresses automatically. A
*static* address is one you fix yourself and the router does not choose. A
*default route* (or *gateway*) is the address a device sends traffic to when the
destination is not on its own network — without one, a device can talk to its
neighbours but not to the internet. *U-Boot* is the small program that runs
before Linux and loads it.

## The one thing to understand first

**The board's addresses are not stored in any file on the SD card.** They live in
the **U-Boot environment**, a 128 KB block in the board's on-board QSPI flash
chip — a separate memory from the SD card entirely.

```bash
# run on the board
cat /etc/fw_env.config
#   /dev/mtd1    0x0000    0x20000    0x20000
cat /proc/mtd | grep mtd1
#   mtd1: 00020000 00010000 "qspi-uboot-env"
```

At every boot, `/etc/init.d/S40network` reads that environment with `fw_printenv`
and **generates** `/etc/network/interfaces`, `/etc/udhcpd.conf` and
`/opt/config.txt` from it. Two consequences follow, and they are the two mistakes
people make:

- **Editing `/etc/network/interfaces` does not survive a reboot.** It is a
  generated file. It is a perfectly good way to *test* a setting, and a
  guaranteed way to lose it.
- **The variables have defaults that are compiled into the script, not stored
  anywhere.** `fw_printenv ipaddr` reporting `"ipaddr" not defined` does not mean
  the board has no USB address; it means the script fell back to `192.168.2.1`.

Because the environment is in QSPI flash, **your address settings survive
reflashing the SD card** — including `./devkit flash --all`. That is usually
what you want, and occasionally very confusing.

## The variables

All of these are read by `S40network`. Only two of them concern the Ethernet
socket you plug into a router.

| Variable | Default if unset | What it sets |
|---|---|---|
| `ipaddr_eth` | *(unset)* | **The Ethernet socket. Set it for a static address; leave it unset for DHCP.** |
| `netmask_eth` | `255.255.255.0` | The Ethernet netmask, used only when `ipaddr_eth` is set |
| `ipaddr` | `192.168.2.1` | The board's own address on the USB cable (`usb0`) |
| `ipaddr_host` | `192.168.2.10` | The single address the board's DHCP server hands *your PC* over USB |
| `netmask` | `255.255.255.0` | The USB netmask |
| `hostname` | `pluto` | The hostname, and therefore the mDNS name `fishball.local` |
| `usb_ethernet_mode` | `rndis` | USB Ethernet flavour: `rndis`, `ncm` or `ecm` |
| `ssid_wlan`, `pwd_wlan`, `ipaddr_wlan` | *(unset)* | A USB Wi-Fi dongle, if you fit one |

**`ipaddr_eth` is a switch, not just an address.** `S40network` branches on
whether it has a value:

```sh
# from /etc/init.d/S40network, lightly trimmed
if [ -n "$ETH_IPADDR" ]; then
        echo "iface eth0 inet static"          >> $IFAC
        echo "\taddress $ETH_IPADDR"            >> $IFAC
        echo "\tnetmask $ETH_NETMASK"           >> $IFAC
else
        echo "iface eth0 inet dhcp"             >> $IFAC
fi
```

So "go back to DHCP" is not a separate setting — it is *deleting* `ipaddr_eth`.

## The short version

```bash
# run from: the repo root
./devkit net                 # what is it doing now?
./devkit net dhcp            # ask the router for an address (the default)
./devkit net static 192.168.1.50
./devkit net name fishball   # answer to fishball.local instead of fishball.local
./devkit net find            # locate it without knowing the address
```

`./devkit net dhcp` writes the environment, **reads it back before rebooting**,
and then finds the board again by name — because the switch throws away the
address you were connected on, and doing this by hand is how people discover
they have no way back. The rest of this page is what it does underneath and why.

## Route 1 — over ssh, with `fw_setenv` (the direct way)

This is the mechanism every other route below goes through in the end.

**A fixed address on your router's network:**

```bash
# run on the board
fw_setenv ipaddr_eth 192.168.1.50
fw_setenv netmask_eth 255.255.255.0
reboot
```

**Back to DHCP** — `fw_setenv` with no value deletes the variable:

```bash
# run on the board
fw_setenv ipaddr_eth
fw_setenv netmask_eth
reboot
```

**Check before you reboot.** `fw_setenv` writes to flash immediately, and a typo
here is how you lose contact with the board:

```bash
# run on the board
fw_printenv ipaddr_eth netmask_eth
```

You can do the whole thing from your PC in one line:

```bash
# run from: your HOST, anywhere
ssh root@192.168.2.1 'fw_setenv ipaddr_eth 192.168.1.50 && fw_printenv ipaddr_eth'
# password: analog
```

A reboot is needed because `S40network` only regenerates the config at startup.
If you would rather not reboot, `/etc/init.d/S40network restart` re-reads the
environment and reconfigures every interface — which will drop your ssh session
if you are connected over the interface you just changed.

## Route 2 — the `config.txt` file on the board's USB drive

When the board's USB port is plugged into a PC it also appears as a small USB
flash drive, and that drive contains **`config.txt`**. This is the no-ssh,
no-terminal route, and it is the one to hand someone who is not comfortable in a
shell.

1. Plug the board's USB port into your PC. A drive called `PlutoSDR` appears.
2. Open `config.txt` in any text editor.
3. Edit the values you want, set `reset = 1` under `[ACTIONS]`, save.
4. **Eject the drive.** Nothing happens until you eject — that is what the board
   watches for.

The file looks like this, and the section to edit for a router connection is the
last one:

```ini
[NETWORK]
hostname = pluto
ipaddr = 192.168.2.1
ipaddr_host = 192.168.2.10
netmask = 255.255.255.0

[USB_ETHERNET]
ipaddr_eth =
netmask_eth = 255.255.255.0

[ACTIONS]
reset = 1
```

> **The section name is wrong for this board.** `ipaddr_eth` and `netmask_eth`
> sit under `[USB_ETHERNET]`, but on the Fishball7020 they configure the **RJ45
> gigabit socket** — the real Ethernet port, driven by the RTL8211F PHY. The name
> is inherited from the ADALM-Pluto, which has no Ethernet PHY at all, so the
> only way it could get an `eth0` was a USB Ethernet dongle. Same variable, same
> `eth0`, different hardware behind it. Edit it for the RJ45 socket regardless of
> what the heading says.

Leaving `ipaddr_eth` blank here is how you select DHCP, exactly as with
`fw_setenv`.

**This still forces a fixed address after `patches/0013`, and it is worth saying
why.** That patch changes how `S40network` *writes* the interface file; it does
not touch `update.sh` or the variables `config.txt` feeds it. Verified on
hardware by editing `ipaddr_eth` in a copy of `config.txt`, parsing it with
`update.sh`'s own `ini_parser` lifted out of the running firmware, and applying
the result exactly as `process_ini` does:

```bash
# run on the board
#   parsed ipaddr_eth  = 192.168.129.200
#   ... after the reboot:
#   address:  192.168.129.200/23
#   MAC:      00:0a:35:00:01:22   <- still the stable one, not a random one
```

The static stanza gets the `hwaddress` line too, because the driver randomises
the MAC whether the address is static or from DHCP. It does **not** get a
`hostname` line: DHCP option 12 is what a router lists you by, and a static
address never sends one. So a board you have pinned will show up in the router's
client list by MAC — there is no DHCP conversation in which to introduce itself.
mDNS still answers for it, so `fishball.local` works either way.

Under the hood, `/sbin/update.sh` compares the file's md5 against a stored copy,
parses the `[NETWORK]`, `[WLAN]`, `[SYSTEM]` and `[USB_ETHERNET]` sections, and
writes every value in one batch:

```sh
# from /sbin/update.sh
echo "ipaddr_eth $ipaddr_eth"   >> /opt/fw_set.tmp
echo "netmask_eth $netmask_eth" >> /opt/fw_set.tmp
fw_setenv -s /opt/fw_set.tmp
```

It then reboots if `reset = 1`, and drops a file called `SUCCESS_ENV_UPDATE` on
the drive if the write worked — or `FAILED_INVALID_UBOOT_ENV` if it did not.
Check for those before assuming it took.

## Route 3 — `uEnv.txt` on the SD card: why this does *not* work

This is the trap, and it is worth spelling out because `uEnv.txt` is the obvious
file to reach for. It sits on the SD card, it is plain text, and it already
contains exactly the lines you want to change:

```bash
# run from: your HOST, in firmware/
grep -E '^(ipaddr|netmask|hostname)' output/uEnv.txt
#   ipaddr=192.168.2.1
#   ipaddr_host=192.168.2.10
#   netmask=255.255.255.0
```

**Editing those does nothing to the running Linux system.** U-Boot reads
`uEnv.txt` into the environment it holds *in RAM*:

```sh
# from uEnv.txt itself
importbootenv=echo Importing environment from SD ...; env import -t ${loadbootenv_addr} $filesize
```

`env import` never writes flash — there is no `saveenv` anywhere in the SD boot
path. So the values exist for as long as U-Boot is running, are used for U-Boot's
own networking (`tftp` and friends), and are gone by the time Linux starts.
Linux's `fw_printenv` reads `/dev/mtd1`, which `env import` did not touch.

You can watch the two disagree on a running board:

```bash
# run from: your HOST
grep '^ipaddr=' firmware/output/uEnv.txt      # ipaddr=192.168.2.1
ssh root@192.168.2.1 'fw_printenv ipaddr'     # ## Error: "ipaddr" not defined
```

The SD card says `192.168.2.1`, the environment Linux reads has no such
variable, and the board is *nevertheless* on `192.168.2.1` — because
`S40network`'s built-in default is the same number. Every symptom of "I edited
uEnv.txt and it worked" is produced by a file that was never read.

If you genuinely want an SD-card edit to stick, you have to make U-Boot save it,
from the U-Boot console over the serial port:

```
# at the U-Boot prompt, serial console, 115200 baud
setenv ipaddr_eth 192.168.1.50
saveenv
boot
```

That writes QSPI, so it is really Route 1 with extra steps. Use `fw_setenv`.

## Route 4 — `/mnt/jffs2/autorun.sh`, for what static mode leaves out

**A static Ethernet address on this board has no default route and no DNS.** This
is not a bug you have hit; it is what the generated config contains. Look again
at the static branch of `S40network` above: it writes `address` and `netmask`,
and there is no `gateway` line, and nothing writes `/etc/resolv.conf`.

Measured on a board with `ipaddr_eth=192.168.129.200`:

```bash
# run on the board
ip route
#   192.168.2.0/24     dev usb0 scope link  src 192.168.2.1
#   192.168.128.0/23   dev eth0 scope link  src 192.168.129.200
cat /etc/resolv.conf     # No such file or directory
ping -c1 8.8.8.8         # fails: no route
```

Two link-scope routes, no `default via` anything. The board can reach its own
subnet and nothing else. For SDR work that is usually irrelevant — libiio talks
to it directly and your PC is on the same subnet — but `ntpd`, `git`, `wget` and
anything that resolves a name will all fail, and the reason is not obvious.

**DHCP does not have this problem.** udhcpc's script sets both:

```sh
# from /usr/share/udhcpc/default.script
route add default gw $i dev $interface
...
echo "nameserver $i" >> "$RESOLV_CONF"
```

So: if you want a fixed address *and* internet access, either give the board a
DHCP reservation on the router (fixed address, DHCP mechanism — the best answer
for most people), or add what static mode omits to the one file that persists:

```bash
# run on the board
cat >> /mnt/jffs2/autorun.sh <<'EOF'
ip route add default via 192.168.1.1
echo "nameserver 192.168.1.1" > /etc/resolv.conf
EOF
```

`/mnt/jffs2` is the board's only writable, persistent partition, and
`autorun.sh` runs at every boot. It survives reflashing the kernel, device tree
and bitstream. It is also the first place to look when the board behaves in a way
the firmware source cannot explain — see
[troubleshooting](troubleshooting.md).

> **A DHCP reservation is usually the right answer.** Leave `ipaddr_eth` unset,
> and tell your router to always give this board the same address. You get a
> predictable address, a working gateway, working DNS, and nothing to undo on
> the board if you move it to another network.

## Route 5 — temporary, no reboot, nothing written

For trying an address before committing to it. None of this survives a reboot,
which is exactly the point:

```bash
# run on the board
ip addr add 192.168.1.50/24 dev eth0     # add a second address, keep the old one
ip route add default via 192.168.1.1     # give it a gateway too
```

To put things back, `ip addr del 192.168.1.50/24 dev eth0`, or just reboot.

## What DHCP exposes, and what it does not

Worth knowing before you switch, because **a static address on this board has no
default route — which means it cannot reach the internet at all.** DHCP supplies
a gateway, so the board goes from no internet access to full outbound access.
That is usually what you want; it is also a change in posture.

Measured on a board in DHCP mode:

- **Outbound: everything.** ICMP, DNS and HTTP to the internet all succeed. No
  service on the board uses it — there is no `ntpd`, no `cron`, and nothing that
  phones home — but the path is open.
- **Inbound from the internet: no route in**, as long as your router is doing
  ordinary NAT. Every address the board holds is RFC1918, and **the kernel has
  no IPv6 stack at all**, which closes the usual accidental-exposure path (a
  globally routable v6 address behind a router with no v6 firewall).
- **Inbound from your LAN: wide open, and this is the part that matters.**

| Port | Service | Authentication |
|---|---|---|
| 22/tcp | dropbear, root shell | password `analog` — the documented default |
| 30431/tcp | `iiod` | **none** |
| 80/tcp | httpd, the info page | none; discloses serial, MACs, kernel and firmware versions |
| 5353/udp | avahi (mDNS) | n/a |
| 67/udp | udhcpd | limited to `usb0` by its config, so it will not serve your LAN |

There is **no packet filter on the board** — no netfilter tables are registered.

`iiod` is the one to think about: it has no authentication and no way to add
any, so anyone who can reach port 30431 can tune, receive **and transmit**. On a
board with a power amplifier that is an RF-emissions question, not only a data
one. Network isolation is the only control — a segregated VLAN, or the router's
firewall.

If you would rather the board could not reach the internet, a static address is
the blunt way to get that: no gateway is written, so it talks to its own subnet
and nothing else. Its missing default route is a limitation for `opkg` and an
accidental feature here.

**Changing the root password does not survive a reboot on its own.** `/etc` is
in the ramdisk. `S21misc` restores `/mnt/jffs2/etc/{passwd,shadow,group}` at
boot, but only when `password.md5` alongside them verifies — so persisting a new
password means copying those files there and writing that checksum.

## Finding the board again

If you changed to DHCP, or set a static address on a network you then changed,
you need to find the board. In rough order of how well these work:

**1. It is still on 192.168.2.1 over USB.** `ipaddr_eth` only touches `eth0`.
The USB interface keeps its own static address no matter what you did to
Ethernet, so a USB cable is always the way back in. This is the recovery route.

**2. mDNS — the board announces itself as `fishball.local`.** It runs an
avahi daemon, so no scanning is needed:

```bash
# run from: your HOST
avahi-resolve -n fishball.local
#   fishball.local	192.168.129.142
```

The name follows the `hostname` variable. A board built before
`firmware/patches/0013` answers to `pluto.local` instead — that was buildroot's
default, kept from the ADALM-Pluto. `./devkit net name <host>` changes it on a
running board without a rebuild, and setting it back to `pluto` restores
compatibility with tooling that looks for `pluto.local`.

### The router shows a MAC address instead of a name

Two separate things, and neither is the mDNS name above. The name a router
displays comes from **DHCP option 12**, which the stock firmware never sends —
udhcpc runs with no hostname option, so the router has nothing to list but the
MAC.

Worse, that MAC is not stable. The device tree carries no `local-mac-address`,
so the driver says so and improvises:

```
macb e000b000.ethernet: invalid hw address, using random
```

A fresh random MAC every boot means the router sees a **new device** each time,
hands out a new lease, and a DHCP reservation is impossible. Two consecutive
boots here took `.139` and then `.140` for exactly this reason.

`firmware/patches/0013` fixes both, by adding two lines to the interface stanza
that `S40network` already generates:

```
iface eth0 inet dhcp
	hostname fishball
	hwaddress ether 00:0a:35:00:01:22
```

busybox ifupdown turns `hostname` into `udhcpc -x hostname:` and `hwaddress`
into an `ip link set addr` before the interface comes up. The MAC is the one
U-Boot already uses for its own networking (`fw_printenv ethaddr`), so the board
keeps one identity from bootloader to Linux; if `ethaddr` is unset the line is
omitted and nothing changes.

> **If you run two of these boards on one network**, check they do not share an
> `ethaddr` — it lives in each board's QSPI environment, but nothing here can
> tell you whether the factory wrote the same value to every unit. `fw_setenv
> ethaddr <mac>` gives one of them a different address.

**3. libiio finds it by itself.** The board advertises the IIO service over
DNS-SD, and `iio_info -s` picks it up without you knowing any address:

```bash
# run from: your HOST
iio_info -s
#   1: 192.168.129.200 (FISH Ball PlutoSDR Rev.A (Z7020-AD9361)),
#      serial=b8f4c99de8525565d3f4fe3c917ad834 [ip:fishball.local]
```

That is the single most useful command here: it gives you the address, the
model, the serial, and confirms the radio service is actually up. You can then
use `ip:fishball.local` as a libiio URI directly and never hard-code an address.

```bash
# run from: your HOST
avahi-browse -tpr _iio._tcp
#   =;...;iiod on pluto;_iio._tcp;local;fishball.local;192.168.129.200;30431;
```

**4. The serial console always works.** The FT2232H gives you a console at
115200 baud on one of its two ports, independent of any network setting. This is
the answer when you have set a static address that collides with something and
the board is unreachable on both USB and Ethernet.

**5. Your router's DHCP lease table.** The board's MAC is in the
`ethaddr` variable and begins with Xilinx's `00:0a:35` prefix, which makes it
easy to spot in a list of leases.

**6. `/opt/ipaddr-<interface>`, with a caveat.** The mdev hotplug hook
`ifupdown.sh` writes the address of each interface it brings up, and
`update.sh` copies those files onto the USB drive so you can read the board's
address off a flash drive with no terminal at all. The caveat is real: the file
only appears for interfaces brought up *by hotplug*. On a board whose `eth0` was
configured statically at boot by `ifup -a`, `/opt/ipaddr-usb0` exists and
`/opt/ipaddr-eth0` does not. Do not rely on it for Ethernet.

## If you have locked yourself out

In order of effort:

1. **USB cable, `ssh root@192.168.2.1`.** Undo it with `fw_setenv`. This works
   unless you changed `ipaddr` as well.
2. **`config.txt` on the USB drive** (Route 2). Needs no shell and no network —
   set the values, `reset = 1`, eject.
3. **Serial console**, 115200 baud. Log in, `fw_setenv`, reboot.
4. **U-Boot console**, same serial port, interrupt the 3-second boot delay.
   `setenv ipaddr_eth`, `saveenv`, `boot`.

What will *not* help: reflashing the SD card. The addresses are in QSPI flash and
a fresh SD card does not touch them.

## Where the settings live, in one picture

```
QSPI flash /dev/mtd1 "qspi-uboot-env"        <- the only persistent store
   |  fw_setenv (ssh)          Route 1
   |  update.sh <- config.txt  Route 2   (USB drive, no shell needed)
   |  saveenv (U-Boot console) Route 3's honest version
   v
S40network reads it with fw_printenv, at every boot
   |
   +-> /etc/network/interfaces   generated, do not edit
   +-> /etc/udhcpd.conf          generated (the USB-side DHCP server)
   +-> /opt/config.txt           generated (what you see on the USB drive)

SD card uEnv.txt  -> U-Boot's RAM environment only -> discarded before Linux
/mnt/jffs2/autorun.sh -> runs after all of the above; the place for a gateway
```

## Related

- [Flashing the board](flashing.md) — which does *not* change these settings
- [Troubleshooting](troubleshooting.md) — `/mnt/jffs2` and other invisible state
- [Capturing IQ](capturing-iq.md) — using `ip:fishball.local` instead of an address
