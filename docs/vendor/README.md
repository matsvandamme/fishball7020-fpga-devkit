# Vendor documents

The board maker's own documents (not this project's work), kept here so that
claims in this repository can be checked against their source, and the
datasheet figures this repository relies on. To look a part up, start at
[find a part on the schematic](../hw/find-a-part.md).

## `7020_936x_SDR-schematic.pdf`

The hardware schematic for this board.

| | |
|---|---|
| Original filename | `7020_936x_SDR原理图.pdf` (原理图 = "schematic") |
| Where it came from | the vendor's own download folder, `新版7020_AD936X_SDR资料/硬件资料/` |
| Created | 15 February 2025, Altium Designer |
| Pages | 13 |
| SHA-256 | `fd8da2ca…` — full sum below |

```
fd8da2caf829608d2afa75fe9863c44dba90eda61d9adfa91133287632a32780  7020_936x_SDR-schematic.pdf
```

Copyright remains the vendor's; the file is included unmodified, for reference.
The GPL-2.0 in this repository's `LICENSE` covers this project's own work, not
this file. If you are the vendor and would rather it were a link, open an issue
and it will be removed.

### Do not use the vendor's GitHub copy

The vendor also publishes a schematic on their own GitHub, as
[`hardware/schematic_PlutoSky.pdf`](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR/blob/main/hardware/schematic_PlutoSky.pdf).
**It is a different board revision and it does not describe this one.** It has
15 pages, was created in May 2025, and contains no `JP5`, no `3V3_IO1..4` and
none of the header nets this repository's sample-locked GPIO feature depends
on — its connectors are numbered `J1`–`J12` instead.

Every pin claim in this repository comes from the copy here: use it.

### Which sheets matter here

| Sheet | What it settles |
|---|---|
| **1** | `VCCO_13_1..4` (balls T8, U11, W7, Y10) tie to `VCC3V3` — why bank 13 is `LVCMOS33` |
| **5** | block `U1G`, "PL端BANK13" — which FPGA ball carries which `3V3_IO` net, and which nearby balls are *no connect* |
| **13** | connector `JP5` — which header pin carries which net, and that GND is on pins 2 and 20 |

[`../img/make_schematic_figures.py`](../img/make_schematic_figures.py) draws
annotated crops of those three sheets straight from this file. The figures are
in [the GPIO reference](../tx-gpio-bitmap.md#where-the-pin-numbers-come-from).

## Datasheet figures this repository relies on

Neither datasheet is included here (both are third-party copyright), so they
are cited by document, revision and table.

### AD9361 Data Sheet, Rev. G, Table 11 (Absolute Maximum Ratings)

| Parameter | Rating |
|---|---|
| RF Inputs (Peak Power) | **2.5 dBm** |
| Maximum Junction Temperature (TJMAX) | **110 °C** |
| Operating Temperature Range | −40 °C to +85 °C |
| Storage Temperature Range | −65 °C to +150 °C |

The first row is the limit every transmit decision in this repository is
checked against: nothing may reach the receive input above +2.5 dBm.

The junction limit is **110 °C**, and that is what `./devkit temps` reports as
the AD9361's absolute maximum. **150 °C is the *storage* maximum**, a different
row of the same table; do not use it as a junction limit.

Table 12 gives the 144-ball CSP_BGA thermal resistance as 32.3 °C/W in still
air, 27.8 °C/W at 2.5 m/s.

### DS190, Zynq-7000 SoC Data Sheet: Overview (v1.11.1, 2 July 2018), Table 7

| Grade | Junction temperature range |
|---|---|
| Commercial (C) | 0 °C to +85 °C |
| Extended (E) | 0 °C to +100 °C |
| Industrial (I) | −40 °C to +100 °C |

The same table lists which grades each device is sold in: for the
**XC7Z020, Commercial exists only in speed grade `-1`**. The `-2` this design
targets is Extended or Industrial, both +100 °C.

The fitted part's temperature grade is not recorded anywhere available (the
schematic and the factory inspection report both mark it only as
`XC7Z020-CLG400`). So the tooling warns at 85 °C, the *lowest rating the part
could have*, and reports 100 °C as the one it probably has. 85 °C is that
lower bound, not "the commercial rating" of this part. **The grade letter is
on the chip package; reading it off is the only way to settle it.**

### Not yet cited

**DS187** (XC7Z010/XC7Z020 DC and AC Switching Characteristics) would add the
Zynq's absolute-maximum ratings. DS190 gives the operating ranges, which is
what `./devkit temps` reports, so this is an addition rather than a gap.
