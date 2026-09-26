# The driver patches, rebased onto Linux 6.12

These are `main`'s eight transmitter-safety patches, applied to Analog Devices'
Linux 6.12 instead of the vendor's 5.15. Nothing here is new behaviour: the
point of the exercise was to find out whether the safety story survives a
ten-release kernel jump, and it does.

```bash
# run from: firmware-modern/src/linux
for p in ../../patches/*.patch; do git apply "$p" || break; done
```

Order matters — `git apply` them in filename order. Three chains edit each
other's added lines: `0004 → 0005 → 0012` and `0004 → 0015 → 0017`, and
`0016`/`0018` both touch `ad9361_set_tx_atten()`. Applying one out of turn fails
with a reject, not a wrong build, so the failure is at least loud.

## What the rebase actually cost

| patch | what it does | on 6.12 |
|---|---|---|
| `0004` | mute TX when no DMA stream is running | **new code** — see below |
| `0005` | don't clobber a gain set before streaming | context only |
| `0007` | `tx_sample_gpio_en` sysfs attribute | context only |
| `0012` | user LED follows the transmitter | context only |
| `0015` | mute when the DAC starves | **new code** — see below |
| `0016` | a `tx_disable` latch debugfs cannot clear | context only |
| `0017` | count transmit DMA underflows | context only |
| `0018` | refuse to transmit louder when the die is hot | context only |

**Six of the eight add byte-for-byte identical code.** That is checked rather
than claimed: extract the added lines of the 5.15 patch and of the 6.12 one and
diff them. Three patches needed hand-application because a hunk's context had
moved (`0004`, `0015`, `0017`), but only two needed different *code*:

- **`0004`** — `of_find_spi_device_by_node()` became static in 6.12, so a local
  two-line equivalent replaces it; and `cf_axi_dds_configure_buffer()` was
  rewritten upstream around `devm_iio_dmaengine_buffer_setup_with_ops()`, so the
  mute hooks attach differently.
- **`0015`** — which field carries the cyclic flag depends on
  `CONFIG_IIO_DMA_BUF_MMAP_LEGACY`. Both are handled.

## The upstream bug this found

ADI's 6.12 never assigns `indio_dev->setup_ops` in `cf_axi_dds_configure_buffer()`.
Up to 5.15 that function built the buffer by hand and ended with the assignment;
the move to `devm_iio_dmaengine_buffer_setup_with_ops()` dropped it, and that
helper's `ops` argument is an `iio_dma_buffer_ops` (submit/abort), not an
`iio_buffer_setup_ops`, so it does not do it either. gcc says so out loud:

```
warning: 'dds_buffer_setup_ops' defined but not used
```

With it unwired, `dds_buffer_preenable()` and `dds_buffer_postdisable()` never
run: `cf_axi_dds_start_sync()` is skipped when a transmit stream starts, and
`cf_axi_dds_datasel(st, -1, DATA_SEL_DDS)` is skipped when it stops, leaving the
DAC pointed at stale DMA data. `0004` restores the line, marked in the source as
not being part of the fishball changes. **Still to report upstream.**

## The buildroot halves are not here

`main`'s `0004` and `0012` each edit `buildroot/board/pluto/S21misc` as well as
the kernel — `tx_quiesce` and `tx_led`. Those halves are deliberately absent:
firmware-modern still boots `main`'s Buildroot rootfs, which
`firmware/scripts/setup.sh` has already patched, so carrying them here would
apply them twice.

**This is a trap for the Debian work.** A Debian rootfs that does not
reimplement `tx_quiesce` as a unit running before anything can stream leaves the
board at ADI's 10 dB of attenuation — roughly **+9 dBm out of an SMA** on a board
with a power amplifier. The device tree's `adi,tx-attenuation-mdB = <89750>`
covers probe; `tx_quiesce` is what covers everything up to the first stream.

## Measured after the rebase, not assumed

On the board, kernel 6.12.0, the same bitstream:

| | |
|---|---|
| `./devkit selftest` | 23 passed, 0 warnings, 0 failed |
| TX0 / TX1 at probe | **−89.75 dB** both |
| `tx_starve_timeout_ms` | 250 |
| `tx_cyclic_timeout_ms` | 0 |
| `tx_disable`, `tx_temp_limit`, `tx_sample_gpio_en`, `tx_dma_{under,over}flow_count` | present, 0 |
| `0016` behaviourally | latch set to 1, debugfs `initialize`, latch **still 1** and still −89.75 dB |
| digital loopback error | 0.0 dB, `dig_eye_passes` 157 |

The `0016` line is the one worth re-running by hand after any change to
`ad9361.c`: it is the only patch whose whole purpose is to survive something
else's reset path, so a green selftest does not exercise it.
