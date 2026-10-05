# SDR++ with this board's controls (Arch)

[SDR++](https://www.sdrpp.org/)'s PlutoSDR source reads RX1 only and knows
nothing of this board's FPGA. This directory builds SDR++ as an Arch package
with a patch that adds, to that source:

- **More sample rates**: the common SDR rates in the list (2.048, 2.304, 3.072,
  6.144 MHz …), and a **Custom (kHz)** field for any rate the hardware takes.
- **RX Port**: RX1 or RX2, one at a time.
- **FPGA /8 decimator**: rates from 250 kS/s to 7.68 MS/s, filtered in the FPGA,
  so the link carries an eighth of what the AD9361 samples.
- **IQ, RF DC and baseband DC correction**: the AD9361's own tracking loops, on
  or off.
- **Freq. corr. (ppm)**: the 40 MHz reference's correction (`xo_correction`),
  for the value `./devkit clock measure` finds.
- **A status line**: board model, firmware, and both die temperatures, while
  streaming.
- **Transport**: libiio, or **Fast TCP, 8-bit** from
  [`zc-stream`](../stream-paths/zc-stream/README.md) on the board, for up to
  20 MS/s over the network. Every control above still goes through libiio.
- **A stuck radio is put back**: if a rate or filter change leaves the AD9361
  in `alert` (receivers off, every sample frozen), starting puts it back in `fdd`
  and says so in the log.

How to use them, with screenshots and measured settings:
[Using SDR++ with this board](../../docs/sdrpp.md).

## Quick start

```bash
# run from: tools/sdrpp/
makepkg -f                                   # builds sdrpp-git-…-10-x86_64.pkg.tar.zst
sudo pacman -U sdrpp-git-*-x86_64.pkg.tar.zst
```

Build on a disk with a few GB free, not on a small `/tmp`: `makepkg` packages
an empty `libsdrpp_core.so` if stripping runs out of space, and only says so in
the middle of its log.

## What the patch changes

| control | writes |
|---|---|
| sample rate, Custom (kHz) | the `ad9361-phy` rate; with /8 the FPGA rate is an eighth of the rate the chip actually took (it rounds some by 1 Hz, e.g. 16383999) |
| RX Port | gain and gain mode on `ad9361-phy` `voltage0` (RX1) or `voltage1` (RX2); samples from `cf-ad9361-lpc` `voltage0/1` or `voltage2/3` |
| FPGA /8 decimator | `ad9361-phy` rate = 8 × the chosen rate; `cf-ad9361-lpc` `voltage0` `sampling_frequency` = an eighth of it, read back. Bypassed again when streaming stops |
| IQ / RF DC / baseband DC correction | `quadrature_tracking_en`, `rf_dc_offset_tracking_en`, `bb_dc_offset_tracking_en` |
| Freq. corr. (ppm) | `ad9361-phy` `xo_correction` = 40 MHz × (1 + ppm/10⁶); left at the board's own value until you move it |
| status line | context attributes `hw_model`, `fw_build` (or `fw_version`); `ad9361-phy` `temp0`, `xadc` `temp0`, once a second |
| libiio blocks | 1/20 s of samples per refill (at most 1 M, SDR++'s stream size), 8 queued on the board; SDR++'s own 1/200 s blocks delivered 83% of 7.68 MS/s over Wi-Fi, these 99.9%, and 10 MS/s in full |
| Gain | `hardwaregain` on the selected receiver, live; in an automatic mode, moving the slider writes `gain_control_mode` `manual` first, and the slider shows the chip's `hardwaregain` once a second |
| AD9361 state (ENSM) | after the rate and filter at start, and after a bandwidth change while streaming: `ensm_mode` read; `alert`, `wait` or `sleep` is set back to `fdd` and read back, and a chip that stays out of `fdd` stops the start with an error. Pin-control modes are left alone. The rate and `ad9361_set_bb_rate` errors are logged with their codes |
| Transport: Fast TCP | nothing: it reads samples from `zc-stream -D -8` over TCP, RX1 on the zc-stream port (5555) and RX2 on the next, int8 ÷ 2048 so levels match libiio's int16 ÷ 32768. Only for an `ip:` device |

Sample rate, filter, RF bandwidth and port selection are shared by both
receivers and stay on RX1's channel. On a one-receiver Pluto, selecting RX2 logs
an error and does not start; on an FPGA without the decimator, the /8 option
logs an error, says so under the checkbox, and does not start. Every setting is
saved per device.

## What the PKGBUILD is

The AUR `sdrpp-git` recipe, pinned to commit `8c9f5ee8`, with the Airspy and
AirspyHF sources turned off and the PortAudio sink on, so it builds with only the
libraries listed in `makedepends` (HackRF, RTL-SDR, libiio, libad9361, RtAudio,
PortAudio). It installs the same 26 plugins as an unpatched build of that
commit, plus a DAB+ decoder.

**The DAB+ decoder** is [F4JTV's `dab_decoder`](https://github.com/F4JTV/dab_decoder)
(GPL-2), pinned to `699da262`, built on [welle.io](https://github.com/AlbrechtL/welle.io)'s
receiver pinned to `512558d1`. It replaces SDR++'s own `dab_decoder`, which is
unfinished at this commit, and adds `faad2` (HE-AAC) and `mpg123` (MP2) to the
dependencies. Usage: [docs/sdrpp.md](../../docs/sdrpp.md#dab-radio).
