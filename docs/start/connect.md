---
icon: material/lan-connect
description: Two USB cables, one minute, then 192.168.2.1 or fishball.local.
---

# Connect and find the board

1. With the board unpowered, put the card in.
2. Check the **`BOOT`** DIP switch next to `RST`: both sliders away from `ON`
   (SD mode). Boards ship like that.
3. Connect **both** USB-C sockets: one to a **mains USB charger**, the other to
   your PC.
4. Wait about a minute.

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
