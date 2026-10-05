---
icon: material/ip-network-outline
description: Pin the board to a fixed address, go back to DHCP, or change the name it answers to.
---

# Change the IP address or name

```bash
# run from: the repo root
./devkit net                          # what is it doing now?
./devkit net static 192.168.1.50      # pin it to one address (optional second argument: the netmask)
./devkit net dhcp                     # back to the router's address (the default)
./devkit net name mysdr               # answer to mysdr.local instead
```

`dhcp` and `static` read the setting back before rebooting, then find the
board again by name. **On the Debian firmware** they refuse and print the
command to run instead: there, the address is in `/etc/network/interfaces` and
the name is set with `hostnamectl set-hostname`.

| Good to know | |
|---|---|
| a static address has **no gateway and no DNS** (Buildroot) | the board reaches only its own subnet; a DHCP reservation in your router is usually the better answer |
| `192.168.2.1` on the USB cable never changes with these | it stays the way back in |
| on Buildroot the settings live in QSPI flash | they survive rewriting the card |

Every route, every variable and recovery from a lock-out:
[networking reference](../networking.md).
