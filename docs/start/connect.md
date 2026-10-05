---
icon: material/lan-connect
description: Two USB cables, one minute, then 192.168.2.1 or fishball.local.
---

# Connect and find the board

Two USB cables and about a minute, then the board answers at `192.168.2.1`
or `fishball.local`.

![The board's three sockets and where each goes: ETH to your router by DHCP, optional; DEBUG to a mains USB charger for power, not a laptop port; USB to your PC, which reaches the board at 192.168.2.1. The BOOT switch is set to SD, 0 0.](../img/start-connect-light.svg#only-light)
![The board's three sockets and where each goes: ETH to your router by DHCP, optional; DEBUG to a mains USB charger for power, not a laptop port; USB to your PC, which reaches the board at 192.168.2.1. The BOOT switch is set to SD, 0 0.](../img/start-connect-dark.svg#only-dark)

1. With the board unpowered, put the card in.
2. Check the **`BOOT`** DIP switch next to `RST`: both sliders away from `ON`
   (SD mode). Boards ship like that.
3. Connect **both** USB-C sockets: one to a **mains USB charger**, the other to
   your PC.
4. Wait about a minute.

![The BOOT DIP switch with both sliders away from ON: 0 0, SD card boot.](../img/boot-sd-00.jpg){ width="260" }

*Step 2: the BOOT switch in SD mode, both sliders away from `ON`.*

Then reach it:

| Route | Address |
|---|---|
| **The USB cable** (always works, the way back in) | `192.168.2.1` |
| **By name** (mDNS, over Ethernet or USB) | `fishball.local` |
| **Ethernet** | your router hands it an address (DHCP) |

```bash
# run from: your HOST
ssh root@192.168.2.1        # password: analog
iio_info -s                 # address, model and serial, [ip:fishball.local]
```

From a clone of the repository, `./devkit net find` locates it without knowing
the address.

**You should see:** a login prompt over ssh, and `iio_info -s` listing the board.
SDR software reaches it at `ip:fishball.local` or `ip:192.168.2.1`.

??? question "Nothing answers?"
    - Give it a full minute.
    - Check the `BOOT` switch and the mains charger.
    - Unplug and replug the USB cable to your PC.
    - Then see [troubleshooting](../troubleshooting.md) and the
      [networking reference](../networking.md).

**Next:** [check what it runs](check-the-firmware.md).
