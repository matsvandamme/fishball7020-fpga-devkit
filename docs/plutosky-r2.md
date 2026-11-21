---
icon: material/chip
description: The PlutoSky R2 is a different board from the R1 and has its own repository and documentation. How to tell the two apart, and what does not carry over.
---

# The PlutoSky R2

The PlutoSky R2 is a different board, and **nothing built or released here
works on it**: an R1 image boots Linux on an R2 with no radio, no Ethernet and
no USB. It has its own repository and its own documentation:

- **Repository:** [matsvandamme/plutosky-r2-fpga-devkit](https://github.com/matsvandamme/plutosky-r2-fpga-devkit)
- **Documentation:** [matsvandamme.github.io/plutosky-r2-fpga-devkit](https://matsvandamme.github.io/plutosky-r2-fpga-devkit/)

For one day, 2026-11-20, this repository built for both boards with a `--rev`
switch. That is gone from here; the R2 repository carries it on.

## Which board do you have

| | PlutoSky R1 / 7020-SDR: this repository | PlutoSky R2: the other one |
|---|---|---|
| Zynq package, printed on the chip | XC7Z020-**CLG400** | XC7Z020-**CLG484** |
| Vendor v0.38 firmware version | `v0.38-4-g95aad` | `v0.38-5-g76414` |
| QSPI flash | 16 MB (W25Q128) | 32 MB (W25Q256) |
| Extra socket | none | `10M_IN`, a 10 MHz reference input |
| `JP5` header | 2×10, **3.3 V** | 2×12, **1.8 V**, pin 1 is **5 V** |

`iio_attr -C -u ip:192.168.2.1 fw_version` prints the version on the vendor's
firmware.

With an R1 image on an R2 the kernel log shows three failures:

```text
ad9361 spi0.0: ad9361_spi_check : Unsupported PRODUCT_ID 0xFF
mdio_bus e000b000.ethernet-ffffffff: MDIO device at address 0 is missing.
macb e000b000.ethernet eth0: Could not attach PHY (-19)
```

## Build for the R2

From [its own repository](https://github.com/matsvandamme/plutosky-r2-fpga-devkit#build-it).
There is no R2 release yet, and the FPGA half of its build needs Vivado 2022.2.

## The sample-locked GPIO pins on the R2

The R2's firmware builds the same [sample-locked outputs](tx-gpio-bitmap.md),
on the same `JP5` pin numbers (7, 9, 11, 13), at **1.8 V** instead of 3.3 V and
on a header whose pin 1 is 5 V. **An R1 cable or circuit does not carry over.**
The pin table, and what has been tested, is in
[the R2's documentation](https://matsvandamme.github.io/plutosky-r2-fpga-devkit/plutosky-r2/#the-sample-locked-gpio-pins-on-the-r2).

## What this site says about the R2

Nothing beyond this page and the notes that point here. Every measurement,
photograph, pin number and rail voltage on this site is the R1's.
