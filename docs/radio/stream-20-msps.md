---
icon: material/speedometer
description: The patched SDR++ and zc-stream give a live 20 MHz-wide view over the network.
---

# Stream 20 MS/s to SDR++

libiio carries about **10 MS/s** for one receiver over the network. The
**Fast TCP** transport carries **20 MS/s**, using 8-bit samples from
`zc-stream` on the board. It needs the patched SDR++ (`tools/sdrpp/`) and the
Debian root.

1. Once: install `zc-stream` on the board as a service. It then starts at every
   boot and waits, idle, for SDR++.

    ```bash
    # run from: the repo root, on your PC
    scp -r tools/stream-paths/zc-stream root@192.168.2.1:
    ```

    ```bash
    # run from: the board, in ~/zc-stream
    apt install gcc make libiio-dev
    make && make install
    systemctl enable --now zc-stream
    ```

2. In SDR++, stop, set **Transport** to **Fast TCP, 8-bit (zc-stream)**, pick
   a rate up to 20 MHz, and play. Leave **zc-stream port** at 5555: RX1 comes
   from port 5555 and RX2 from 5556.

| What it costs | |
|---|---|
| **dynamic range** | about 48 dB between the strongest and weakest signal you can see at once, instead of 72 dB. Set the gain so the strongest signal is near the top |
| **the network only** | it needs the board's address (an `ip:` device); over USB, use libiio |
| **one program receives at a time** | another program that tries to stream is refused with "Device or resource busy" |
| **up to 20 MS/s** | **pick 19 MS/s when every sample counts** |

Installing the patched SDR++, and the measurements:
[SDR++](../sdrpp.md#faster-the-fast-tcp-transport) ·
[faster streaming](../streaming-paths.md).
