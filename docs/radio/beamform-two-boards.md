---
icon: material/radar
description: Two boards on one GPS-disciplined reference as a four-element receive array - calibrate, find a direction, steer a beam.
---

# Beamform across two boards

A receive beamformer, built on [the automation server](../automation.md): two
boards on one reference clock become a line of four antennas (A:RX1, A:RX2,
B:RX1, B:RX2). A beacon plays on board A's TX1, the script calibrates the
array with the beacon straight ahead, then steers a beam from −90° to +90°
and reports where the beacon is.

The script is
[`tools/automation/examples/beamformer.py`](../../tools/automation/examples/beamformer.py);
it runs on one board, two boards, or more.

!!! warning "Run on one board so far"
    On 2026-10-05 it ran on one board, two elements, with the direction
    emulated on the bench (step 1): its numbers below are measured. The two-board
    steps have not been run on hardware yet. They follow from the
    [external reference](../hw/external-reference-clock.md) page, and every
    number in them that was not measured says so.

![Set-up: an LBE-1421 GPSDO's two outputs, both at 40 MHz, each go through a DC block and about 20 dB to the EXT_CLK of one board, board A and board B, each with R107 empty and R109 fitted. Board A's RX1 and RX2 and board B's RX1 and RX2 are four antennas in a line, half a wavelength apart (61 mm at 2450 MHz). Board A's TX1 feeds a beacon antenna broadside to the line, 1 m or more away. Both boards and the PC running beamformer.py are on the network.](../img/beamformer-setup-light.svg#only-light)
![Set-up: an LBE-1421 GPSDO's two outputs, both at 40 MHz, each go through a DC block and about 20 dB to the EXT_CLK of one board, board A and board B, each with R107 empty and R109 fitted. Board A's RX1 and RX2 and board B's RX1 and RX2 are four antennas in a line, half a wavelength apart (61 mm at 2450 MHz). Board A's TX1 feeds a beacon antenna broadside to the line, 1 m or more away. Both boards and the PC running beamformer.py are on the network.](../img/beamformer-setup-dark.svg#only-dark)

## Why one reference is not enough

A shared reference makes both boards' LOs and sample clocks run at exactly the
same rate. It does not line them up:

| What | Across two boards | What the script does |
|---|---|---|
| **LO frequency** | equal, once both run from one reference; on their own crystals they differ by a few ppm (about 5 kHz at 2.45 GHz) | the lock check measures each element's offset from the beacon |
| **LO phase** | a new, unknown value at every retune, rate change and reboot | calibrates with the beacon straight ahead; recalibrate after any of those |
| **When a capture starts** | different on each board: two network calls start milliseconds apart, and this design has no shared start (no AD9361 multi-chip sync) | reads each element's phase at the matched filter's peak, which does not depend on where in the capture the peak falls |

Within one board, RX1 and RX2 share an LO, so their phase difference survives
a retune: +149.5° and +149.8° in two runs that each configured the board
afresh. Across boards it does not.

## 1. Try it on one board

No second board and no antennas: the bench loops TX1 → 20 dB → RX1 and
TX2 → 30 dB → RX2. The beacon plays on both transmitters, and a phase step on
TX2 stands in for a wave arriving from each angle.

```bash
# run from: the repo root on your PC, after looking at both transmit ports
./devkit tx-guard affirm 0
./devkit tx-guard affirm 1
```

```bash
# run from: tools/automation
.venv/bin/python examples/beamformer.py --emulate=-60,-30,0,30,60
```

```bash
# run from: the repo root on your PC
./devkit tx-guard revoke both
```

**You should see**, measured on 2026-10-05:

```text
2 elements (RX1, RX2), 61.2 mm apart, LO 2450 MHz (wavelength 122.4 mm); beacon on board 1 TX1

Lock check, 5 snapshots, nothing moving:
   element     level    SNR    offset  coherence  phase spread
       RX1   -21.7 dBFS  65.3 dB    -0.0 Hz      1.000
       RX2   -31.3 dBFS  65.7 dB    -0.0 Hz      1.000       0.1 deg
calibrated at 0 degrees: RX1 +0.0 deg, RX2 +149.8 deg

Emulated directions (TX2's phase stands in for the angle):
     -60 deg: found  -60.1 deg (-0.1 from -60); beam SNR 65.4 dB, best single element 65.6 dB
     -30 deg: found  -30.0 deg (-0.0 from -30); beam SNR 65.2 dB, best single element 65.3 dB
      +0 deg: found   +0.1 deg (+0.1 from +0); beam SNR 65.5 dB, best single element 65.8 dB
     +30 deg: found  +30.1 deg (+0.1 from +30); beam SNR 65.3 dB, best single element 65.6 dB
     +60 deg: found  +59.7 deg (-0.3 from +60); beam SNR 65.1 dB, best single element 65.2 dB

mean SNR per element during the lock check: RX1 65.3 dB, RX2 65.7 dB
transmitters now: fishball.local TX1 -89.75 dB, TX2 -89.75 dB
```

It also writes `beamformer.csv`, `beamformer-check.svg` and
`beamformer-emulate.svg` where you run it:

![Two panels from the one-board run. Top: beam power against steering angle for the five emulated directions, -60, -30, 0, +30 and +60 degrees; each curve reaches 0 dB at its own angle and dips to between -2 and -6 dB elsewhere, and the -60 and +60 degree curves rise again towards the opposite end. Bottom: direction found against direction emulated; all five points sit on the diagonal, within 0.3 degrees.](../img/beamformer-emulate-light.svg#only-light)
![Two panels from the one-board run. Top: beam power against steering angle for the five emulated directions, -60, -30, 0, +30 and +60 degrees; each curve reaches 0 dB at its own angle and dips to between -2 and -6 dB elsewhere, and the -60 and +60 degree curves rise again towards the opposite end. Bottom: direction found against direction emulated; all five points sit on the diagonal, within 0.3 degrees.](../img/beamformer-emulate-dark.svg#only-dark)

What it shows, and what it does not:

- **The direction is found within 0.3°.** The calibration, the steering and the
  sign convention work end to end.
- **The beam's nulls are shallow** (−2 to −6 dB) because RX2's loop has 10 dB
  more attenuation: two unequal elements cannot cancel each other. Two elements
  also cannot tell a direction near −60° from one near +90° well.
- **No array gain here.** Two equal elements with independent noise gain 3 dB,
  four gain 6 dB (`tests/test_beamformer.py` checks the 6 dB on synthetic
  data). On this bench, at −40 dB, both elements reached about 65 dB SNR although
  their levels differ by 9.6 dB: the floor is not thermal noise but something
  both elements share, most likely the shared LO's phase noise, which adding
  them cannot average out. With the beacon at −80 dB the SNRs followed the levels
  (41.7 and 31.5 dB), and the beam came within −0.4 to +0.8 dB of the stronger
  element, as equal-gain combining of two elements 10 dB apart predicts.

## 2. Put both boards on one reference

**What you need:** a second board on the Debian root, the
[LBE-1421 GPSDO](https://www.leobodnar.com/shop/index.php?main_page=product_info&cPath=107&products_id=399)
with its GPS antenna, two DC blocks, two attenuators of about 20 dB, and SMA to
U.FL leads.

1. **Move R107 to R109 on both boards**, as on
   [the external reference page](../hw/external-reference-clock.md). From then on
   a board does not start its radio unless the reference is running at boot.
2. **Set both GPSDO outputs to 40 MHz** with Leo Bodnar's configuration tool.
   At 40 MHz the device tree's `clock-frequency` stays as it is.
3. **Cable each output through a DC block and about 20 dB to one board's
   `EXT_CLK`.** The outputs are 3.3 V CMOS from 50 Ω; `EXT_CLK` takes at most
   1.3 V p-p, AC-coupled. About 0.65 V p-p through 20 dB is an open-circuit
   calculation, not a measurement with this GPSDO: check it on a scope.
4. **Power the GPSDO first, and let it lock to GPS**, then power both boards.
5. **Give the second board its own name.** With only that board on the network:

    ```bash
    # run from: the repo root on your PC
    ./devkit net name fishball-b
    ```

    Then check the two do not share a MAC address
    ([networking](../networking.md)).

6. **Install the server on both.**

    ```bash
    # run from: the repo root on your PC
    BOARD=fishball.local ./devkit automation install
    BOARD=fishball-b.local ./devkit automation install
    ```

**You should see:** both boards boot with their radio up
(`./devkit automation status` on each). The lock check in step 3 is what shows
they share the reference.

## 3. Check the lock, cabled

Before any antenna: board A's TX1 → 20 dB → a four-way splitter → the four
receivers, with four cables of equal length. 20 dB and the splitter's 6 dB keep
each receiver below its +2.5 dBm limit even at the transmitter's full
(estimated) +19 dBm.

```bash
# run from: the repo root on your PC, after looking at board A's TX1A
BOARD=fishball.local ./devkit tx-guard affirm 0
```

```bash
# run from: tools/automation
.venv/bin/python examples/beamformer.py --boards fishball.local,fishball-b.local --check 10
```

Press Enter at the first prompt (equal cables are "broadside"), then Enter
once more for a scan, then `q`.

**You should see** in the lock check, on all four elements: an offset near
0 Hz, coherence near 1.000, and a phase spread of a few degrees at most; the
scan should find about 0°. That is what one board measured in step 1. On two
boards it has not been run yet.

??? question "B:RX1 and B:RX2 say NOT LOCKED"
    Their phase rotates against the beacon within one capture: board B is not
    on the GPSDO's reference. Check R107 and R109 on board B, the cable, and that
    the GPSDO was running before the board booted. Two independent 40 MHz
    crystals differ by a few ppm, about 5 kHz at 2.45 GHz; the script flags any
    element whose coherence falls below 0.9, which a 300 Hz offset already does
    (`tests/test_beamformer.py`).

## 4. Find a direction, over the air

1. **Four antennas in a line, 61 mm apart** (half a wavelength at 2450 MHz),
   in array order: A:RX1, A:RX2, B:RX1, B:RX2. Their cables should be equal
   in length; the calibration absorbs any difference, but only at one frequency.
2. **The beacon antenna on board A's TX1**, straight ahead of the middle of the
   line, at least 1 m away: the far field of a four-element, half-wavelength
   array starts at about 0.55 m. At −40 dB, the default, the beacon radiates
   about −21 dBm, from the estimated +19 dBm full scale; 2450 MHz is in the
   licence-free 2.4 GHz band.
3. **Record the leak first, and remove it.** Inside board A, TX1 leaks into
   its own receivers 48–60 dB down at 1–3 GHz
   ([measured](../measured-performance.md#the-boards-own-tx-to-rx-leak)); free
   space between two antennas 1 m apart at 2.45 GHz is 40 dB, so the leak can
   be within about 10–20 dB of the signal on A's elements. `--leak` records it
   with the beacon's antenna replaced by a 50 Ω load, and subtracts it from
   every snapshot.

    ```bash
    # run from: tools/automation
    .venv/bin/python examples/beamformer.py --boards fishball.local,fishball-b.local --leak --rx-gain 50
    ```

4. **Follow the prompts:** the load, the antenna back, the beacon straight
   ahead (calibration), then move the beacon and press Enter for each scan.
   Each scan prints the direction found and redraws `beamformer-scans.svg`.
   Positive angles are towards element 4.

Receive gain: `--rx-gain 50` is a starting point, not a measured setting; aim
for a level between about −40 and −15 dBFS in the lock check.

## How it works

| Step | What the script does |
|---|---|
| Beacon | A chirp from −2 to +2 MHz, 67 µs long, every 0.53 ms (8192 samples at 15.36 MS/s), uploaded once |
| Snapshot | the beacon plays; every board records RX1 and RX2 at once (one thread per board); the beacon stops and mutes |
| Per element | a matched filter per beacon period; the complex value at the peak, averaged over the 16 periods. The sweep is symmetric about the LO, so that value's phase does not move with a fractional-sample shift either (tested: under 2° for half a sample, against 23° for a 0 to +4 MHz sweep) |
| Lock check | per element: the offset from the beacon (phase step between periods), the coherence (\|mean\| / mean\|·\| of the per-period peaks), and the spread of its phase relative to element 1 over the snapshots |
| Calibration | each element's phase relative to element 1 with the beacon at 0°, averaged as unit phasors. Phase only: a weaker element is not amplified |
| Beam | delay-and-sum: the calibrated elements weighted by the steering vector for each angle, every 0.1° from −90° to +90°; the strongest angle is the direction |

## Change it

| To | Change |
|---|---|
| another band | `--lo-mhz 868`; the spacing follows (half a wavelength: 173 mm at 868 MHz) unless `--spacing-mm` sets it |
| more boards | `--boards a.local,b.local,c.local`: two elements per board, in that order, each board on the same reference |
| the beacon on another board or transmitter | `--beacon 2:1` (board 2, TX1) |
| a quieter or louder beacon | `--attenuation -60`; louder than −10 dB is refused unless `--pad` states at least 20 |

Every call and rule underneath: [the automation server](../automation.md#transmitting).
