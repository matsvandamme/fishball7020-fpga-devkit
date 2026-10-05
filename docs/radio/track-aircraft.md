---
icon: material/airplane
description: One command, a 1090 MHz antenna, and a live table of aircraft overhead.
---

# Track aircraft (ADS-B)

Aircraft broadcast who and where they are on **1090 MHz**. `./devkit adsb`
receives them with the board, decodes them on your PC and shows one row per
aircraft. It **never transmits**.

1. Put a **1090 MHz antenna** on **RX1A** (or RX2A, then add `--channel 2`),
   outdoors or at a window with a view of the sky. Aircraft are line of
   sight: walls and hills cost more range than anything else.
2. Power the board from a **mains charger**: on bus power it hangs under a
   sustained 4 MSPS stream, which is all this tool does.
3. Run:

```bash
# run from: the repo root, on your host PC (not the board)
./devkit adsb                  # the antenna on RX1A
./devkit adsb --channel 2      # the antenna on RX2A
```

**You should see:** a table of aircraft with callsign, altitude, speed and
position, above a log of every message. Daytime near any airway usually gives
several within a minute, with an outdoor antenna.

```bash
# run from: the repo root
./devkit adsb --text                     # messages, plus a table every 10 s
./devkit adsb --record flight            # flight.sigmf-data + .sigmf-meta
./devkit adsb --replay flight.sigmf-meta # no board needed
```

**The table stays empty?**

| Symptom | Fix |
|---|---|
| **`LINK TOO SLOW`** | `--uri ip:192.168.2.1`, or `export BOARD=192.168.2.1` |
| **`NO SAMPLES for N s`** | power it from a mains charger, then check `./devkit status` |
| **`rejected` rises, nothing `CRC ok`** | check the antenna and its cable, then try a few dB less or more gain |
| **"something else holds the receiver"** | close SDR++ or the capture; only one program can stream at a time |

Settings, positions and how the decoder works: [ADS-B](../adsb.md).
