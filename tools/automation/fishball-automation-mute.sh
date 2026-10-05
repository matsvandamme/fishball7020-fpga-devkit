#!/bin/sh
# Run by systemd after the automation server stops, for any reason, a crash
# included: both transmitters to the floor. The server mutes before releasing
# a buffer itself; this is the backstop for when it could not.
for d in /sys/bus/iio/devices/iio:device*; do
    [ "$(cat "$d/name" 2>/dev/null)" = ad9361-phy ] || continue
    for c in 0 1; do echo -89.75 > "$d/out_voltage${c}_hardwaregain"; done
done
exit 0
