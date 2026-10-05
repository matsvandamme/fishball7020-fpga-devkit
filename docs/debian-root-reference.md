# The Debian root: how it works, and why

What the Debian root's units and settings do, and what goes wrong without
each. The quick start is [`firmware-modern/debian/`](../firmware-modern/debian/README.md);
to rebuild the root, see [rebuild the Debian root](build/rebuild-the-debian-root.md).
Why the board moved off Buildroot is in [`debian-rootfs.md`](debian-rootfs.md).

## Transmitter safety at boot

The AD9361 can transmit at about +19 dBm, so the transmitter is held at maximum
attenuation (−89.75 dB) from power-on until a program deliberately starts a
transmit stream:

| | covers |
|---|---|
| the device tree | probe: `adi,tx-attenuation-mdB = 89750`, applied near the end of `ad9361_setup()`. The TX calibration just before it transmits for a few milliseconds at every power-on ([`IDLE-CASES.md`](../IDLE-CASES.md)) |
| **`fishball-rf-quiesce.service`** | from boot until something opens a transmit buffer |
| the kernel | `patches/0004` mutes when a transmit buffer stops, `0015` when the DAC runs out of samples |

`fishball-rf-quiesce` waits up to 10 s for `ad9361-phy`, writes −89.75 dB to
both channels, reads them back, and sets the 60 s bound on unattended cyclic
transmits (`tx_cyclic_timeout_ms`, where the kernel has it). It is ordered before
`iiod`, the one process that opens transmit buffers unasked, and `iiod` has
`Requires=fishball-rf-quiesce.service`: **if the quiesce fails, `iiod` does not
start**. The board stays reachable over USB; `journalctl -b -u fishball-rf-quiesce -u iiod`
says why, and `systemctl start iiod` re-runs the quiesce first.

## The USB route

The USB cable carries a network link (`usb0`, the board at `192.168.2.1`), a
serial console and libiio, independently of Ethernet:

| Unit | Ordering | What it does |
|---|---|---|
| `fishball-usb-gadget.service` | `Before=iiod.service` | builds the USB gadget, mounts FunctionFS |
| `fishball-usb-bind.service` | `After=iiod.service` | attaches the gadget to the USB controller, brings usb0 up |
| `serial-getty@ttyGS0.service` | | a login console on the same cable |

**FunctionFS** lets `iiod` serve libiio over USB from userspace. The gadget can
be attached only after `iiod` has written its USB descriptors (earlier fails with
`EIO`), so `fishball-usb-bind` waits for `/dev/iio_ffs/ep1` and retries. With
`iiod` down it attaches the gadget without libiio, so `usb0` and the console
still come up. `iiod` gets `-F /dev/iio_ffs` from a wrapper, `fishball-iiod`,
that checks the gadget exists, so a failed gadget cannot stop `iiod`.

**The MAC addresses** derive from `sha1(hw_serial)`, as the factory `S23udc`
does, so your PC's interface name (for example `enx00e022338e2c`) and any
network profile bound to it stay the same. `hw_serial` lives in `/mnt/jffs2` on
the QSPI flash, so it survives reflashing the card.

## Board identity

`fishball-identity.service` mints `hw_serial` into `/mnt/jffs2` once and writes
`/etc/libiio.ini`, whose values libiio serves as IIO *context attributes* (read by
`tools/selftest/sdr_selftest.py` and the MCP server).

`fw_version` carries the release (`v2.1`) and `fw_build` the full `git describe`
(`v2.1-2-ge09d3add`), both from `/opt/VERSIONS`. They are separate because
MATLAB's ADALM-Pluto support package fails to connect when `fw_version` looks
like a `git describe` string ([`matlab.md`](matlab.md)).

### The login message

Every ssh or console login prints the VMAT logo, the boards this firmware is for
(PlutoSky R1, 7020-SDR, Fishball7020, Fish-Wan) and what the board is:
`/etc/update-motd.d/10-fishball` reads sysfs and files only, about 0.4 s.

| Line | Where it comes from |
|---|---|
| Firmware | `fishball_build` in `/boot/uEnv.txt` (the boot files) and `device-fw` in `/opt/VERSIONS` (the Debian root); a red line when the two differ |
| Release | the GitHub release those builds are, with a link to its page. A build is named by `git describe`, so `v2.3` is release v2.3, and `v2.0-9-g5ae29d94-dirty` is not a release: 9 commits after v2.0, built with uncommitted changes, linked to v2.0's page. One line per part when the boot files and the root differ |
| Kernel | `uname -r` and its build date |
| FPGA | `fishball_xsa`, `fishball_fpga` and `fishball_bitstream` in `/boot/uEnv.txt`, named from a table of known designs |
| Ethernet, USB cable | the addresses of `eth0` and `usb0`, as `ssh` and `ip:` URIs |
| Radio, Health | both transmit attenuators, the RX LO and rate, the AD9361 and FPGA temperatures, uptime, and a warning after any `Calibration TIMEOUT` (the sign of too little power) |
| Tune RX … Commands | the commands used most, and `fishball-help` for the rest: a cheat sheet grouped by job (look, receive, transmit, settings that survive a reboot, logs, services) |
| Tip | the next line of `/usr/share/fishball/tips.txt` at every login (a counter in `/var/lib/fishball/motd-tip`, so none repeats until all have shown); add your own there |

`firmware-modern/build_all.sh` stamps the four `fishball_*` lines into
`uEnv.txt`, so they travel wherever the boot files go: a release, `write-card`,
`write-card.cmd`, `./devkit flash`. U-Boot imports them as variables nothing
reads. Boot files built before the stamp show as "unstamped"; the FPGA line then
comes from hashing the bitstream partition of `/boot/BOOT.bin` with
`fishball-bootbin`, the same parser the build uses, cached in `/run`.

`/opt/VERSIONS` records what was built: the `device-fw` line, the Debian release,
the build time and every installed package version.
`/usr/share/fishball/packages.txt` records what was asked for, and why. The base
image is pinned by digest and packages come from a fixed snapshot.debian.org date
(`BASE` and `DEBIAN_SNAPSHOT` in the `Containerfile`). The board keeps the normal
Debian sources, so `apt update` there gets current packages.

## No identity in the image

`rootfs.tar` is a release asset, so anything in it is on every board flashed
from it.

- **SSH host keys** are deleted from the image, or every board would share one
  published private key.
- **`/etc/machine-id`** is empty, which tells systemd this is a first boot.
  `/var/lib/dbus/machine-id` is a symlink to it.

| | generates host keys when |
|---|---|
| `sshd-keygen.service` (Debian's) | `ConditionFirstBoot` is true |
| `fishball-sshd-keygen.service` | `/etc/ssh/ssh_host_ed25519_key` is missing |

On a freshly written card Debian's unit does not fire, so
`fishball-sshd-keygen` is what generates the keys. Keep it. Both run
`ssh-keygen -A`, which only creates missing keys.

## Differences from Buildroot and from a container image

Each of these fails quietly or blames the wrong thing, so the fix is in the image.

| symptom | cause | what the image does |
|---|---|---|
| no network, `networking.service` failed | systemd renames `eth0` to `end0`; Buildroot did not | `net.ifnames=0` on the kernel command line |
| avahi publishes the wrong hostname | podman bind-mounts `/etc/hostname` and `/etc/hosts` during a build, so writes to them never reach the image | both files are in `overlay/` |
| host streaming capped at 16 MB buffers | libubootenv's `fw_printenv` exits 0 with empty output for an unset variable, so an `\|\| default` never fires | `fishball-identity` treats empty output as unset |
| ssh dies partway through a tool run, "Permission denied" | OpenSSH 9.8+ `PerSourcePenalties` blocks an address that opens many short connections, which the host tools do | turned off in `sshd_config.d/fishball-penalties.conf` |
| PAM refuses a correct password | the board has no real-time clock and boots with a date before the image was built, so the password looks changed in the future | the root password is dated 1970-01-02 (`chage -d 1 root`) |
| `apt update` rejects Release files as "not valid yet" | the same wrong clock | `systemd-timesyncd` is installed in the image, so the clock is set before `apt` runs |
| installed services never start | the Debian container image ships `/usr/sbin/policy-rc.d`, which blocks service starts | it is deleted |

## Shutdown and reboot

Without these, a reboot can stall for minutes in stop jobs and then not reset:

- `etc/network/interfaces` uses `allow-hotplug eth0`, not `auto eth0`, so
  `networking.service` does not wait for a cable.
- `etc/systemd/system.conf.d/fishball.conf` sets `DefaultTimeoutStopSec=20s` and
  `RebootWatchdogSec=60s`, so the Zynq watchdog resets the board if shutdown
  stalls anyway.
- **`systemd-logind` is masked.** Nothing on the board uses it, and it could spin
  at start-up and restart forever, starving PID 1. A start-limit drop-in stays
  alongside for anyone who unmasks it.

A boot to login takes about 14 s and a reboot about 45 s.

**Logs are in the systemd journal, not in `/var/log/*.log`.** There is no syslog
daemon, so `/var/log` holds only the journal (`/var/log/journal/`, persistent,
capped at 32 MB, flushed to the card every 10 minutes) and a few package logs.
Read it with `journalctl -b` (this boot), `-f` (live), `-u iiod` (one service),
`-k` (the kernel), `-b -1` (the previous boot) or `-p warning` (problems only).
The board has no real-time clock, so timestamps before the network clock syncs
can be wrong; do not subtract times across boots.

**Pulling the power corrupts the journal.** journald keeps corrupt archives as
`*.journal~`, `journalctl` stops reading at the first one, and they count against
the 32 MB limit:

```bash
# run from: the board
journalctl --disk-usage
rm -f /var/log/journal/*/system@*.journal~
```

## A rare boot hang: RCU stops early in boot

| | |
|---|---|
| symptom | after a reboot the board never comes back (no USB device, console or network), but the USER LED keeps blinking steadily: the kernel heartbeat, so the kernel runs and userspace has stalled. Seen once in about 25 boots |
| the journal of that boot (`journalctl -b -1 -k` after a power cycle) | `WARNING ... at kernel/rcu/tree.c:3094 call_rcu` about 9 s in, then `INFO: task (mount) blocked for more than 20 seconds` (mounting `/mnt/jffs2`) and `dev-ttyGS0.device` timing out |
| cause | **RCU** (read-copy-update) is how the kernel frees shared data safely; once it stops, anything waiting on it waits forever. Why it stops, a kernel bug or a hardware glitch, is unknown |
| fix | power-cycle. The serial console on the `DEBUG` port would show the boot as it hangs |

**If it happens again**, save the evidence first:

```bash
# run from: the board, after the power cycle
journalctl -b -1 -k --no-pager > /root/hang-$(date +%s).txt
```

## SD card writes

The Debian root writes to the card (Buildroot ran from RAM). Every mount is
`noatime`, the root is `commit=30` (at most 30 s of writes lost to a power cut,
silently), and journald is capped at 32 MB and syncs every 10 minutes. **Run
`sync` after deploying anything you care about.** `apt` works but `dpkg` takes
minutes on the dual Cortex-A9.
