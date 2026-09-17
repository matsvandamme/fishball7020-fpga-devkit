# Vendor documents

Not our work. These are the board maker's own documents, kept here so that
claims in this repository can be checked against their source without hunting
down a download link that may not outlive the board.

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

Copyright remains the vendor's. It is included unmodified, for reference. The
GPL-2.0 in this repository's `LICENSE` covers our work, not this file. If you
are the vendor and would rather it were a link, open an issue and it goes.

### Read this before you use a different copy

The vendor also publishes a schematic on their own GitHub, as
[`hardware/schematic_PlutoSky.pdf`](https://github.com/OpenSourceSDRLab/PlutoSky_7020_AD936X_SDR/blob/main/hardware/schematic_PlutoSky.pdf).
**It is a different board revision and it does not describe this one.** It has
15 pages, was created in May 2025, and contains no `JP5`, no `3V3_IO1..4` and
none of the header nets this repository's sample-locked GPIO feature depends
on — its connectors are numbered `J1`–`J12` instead.

So if you are checking the pin assignment, use the copy here. Every pin claim
in this repository was read off **this** PDF.

### Which sheets matter here

| Sheet | What it settles |
|---|---|
| **1** | `VCCO_13_1..4` (balls T8, U11, W7, Y10) tie to `VCC3V3` — why bank 13 is `LVCMOS33` |
| **5** | block `U1G`, "PL端BANK13" — which FPGA ball carries which `3V3_IO` net, and which nearby balls are *no connect* |
| **13** | connector `JP5` — which header pin carries which net, and that GND is on pins 2 and 20 |

[`../img/make_schematic_figures.py`](../img/make_schematic_figures.py) draws
annotated crops of those three sheets straight from this file. The figures are
in the [README](../../README.md#the-pins).
