# Transmitter safety

What the firmware does to keep the transmitter quiet when you are not using it,
and the power budget you need to know before you cable a transmit port to
anything. The short version is in the [README](../README.md#before-you-ever-transmit).

**Stock firmware leaves the transmitter running.** Measured at power-on, the
AD9361 comes up in ENSM `fdd` with the TX synthesiser going and only 10 dB of
attenuation, so the port emits LO leakage continuously even though nothing is
in the DAC DMA and nobody has asked it to transmit. When a transmission ends,
ADI's driver reverts to a silent DDS but leaves the chain biased.

Idling like that is not in itself a damage risk, since at maximum attenuation
the output is negligible (−89.75 dB below full scale). But there is no reason
to keep a transmitter energised that you are not using. It warms a die already
above 50 °C, and on the **PA variant it is not a trivial amount of power**.

**Do not transmit at power into an unterminated port.** An open or shorted
connector reflects everything back into the output stage. Neither the AD9361
datasheet (TX specified into a matched 100 Ω load, ~6.5 dBm max) nor the
PGA-102+ PA datasheet (~+17.5 dBm here) states any tolerance for an output
open, short or high VSWR, so treat it as unspecified and always terminate. The
receiver does have a hard number: **+2.5 dBm is the AD9361's absolute-maximum
RF input**. That is why every loopback here goes through an attenuator.

**This build fixes it in firmware.** `patches/0004` hooks the TX buffer
lifecycle the DAC driver already has:

| Event | What happens |
|---|---|
| boot (`S21misc`) | TX attenuated to maximum — quiet before anything streams |
| a TX buffer starts streaming | TX unmuted — your gain if you set one, else the last you used |
| the buffer stops | TX muted and the synthesiser powered down, automatically |

It calls `ad9361_tx_mute()`, ADI's own exported helper, which was already in
the tree but called from nowhere. `patches/0005` exists because restoring the
cached attenuation *unconditionally* turned out to be a trap of its own.
Setting a gain and then starting the stream is the obvious order to do things
in, and the unmute would overwrite that gain a moment later with the previous
transmission's value, so asking for −10 dB could put −60 dB on the wire. The
unmute now restores the cache only if nothing has been set since the mute,
which makes both orders work:

| What you do | What you get |
|---|---|
| set a gain, then start the stream | the gain you set |
| start the stream having set nothing | the last gain you used |

If you have a watchdog script polling `buffer/enable` to re-apply a gain, you
no longer need it — check `/mnt/jffs2/autorun.sh`, since that partition is
persistent and survives reflashing. `tools/selftest/sdr_selftest.py --ssh`
lists what is there.

The reason this holds even when things go wrong is that the IIO core runs the
buffer's `postdisable` hook on teardown **even if the application crashed or
was killed**, since teardown happens on file close. No userspace watchdog can
promise that. The TX mute needed no device tree change of its own, as the
driver reaches the phy through the DDS node's existing `clocks` phandle.

Measured over a 50 dB attenuated loopback, **the mute costs no output power**:
commanded and applied attenuation matched to 0.01 dB at every point including
0 dB, and received level tracked commanded gain across 40 dB within 1.9 dB.

> ### A TX→RX loopback without an attenuator will destroy your receiver
>
> The receiver is the fragile end — rated to roughly **+2.5 dBm** — and **this
> board is sold in a variant with a power amplifier on transmit**, which most
> Pluto advice does not account for. The PA is a Mini-Circuits
> [**PGA-102+**](https://www.minicircuits.com/pdfs/PGA-102+.pdf):
>
> | GHz | 0.05 | 0.8 | 2.0 | 3.0 | 4.0 | 6.0 |
> |---|---|---|---|---|---|---|
> | **Gain (dB)** | **17.7** | 15.9 | 14.0 | 12.5 | 11.5 | 10.4 |
>
> with P1dB around **+17.5 dBm**. Plan for **about +19 dBm** flat out, roughly
> **16 dB above what its own receive port survives**. That figure is the
> self-test's estimate, scaled up from a quieter measurement and stopped at the
> amplifier's compression point; nobody has put a power meter on the port.
>
> <sub>This table and these figures are the canonical copy; `tools/selftest/README.md`
> and the agent skill point here. Update them here first.</sub>
>
> **Fit at least 20 dB of attenuation** in any loopback. More is safe too, but
> for *measuring* the board, 20 dB is also the best choice: the board leaks some
> transmit signal straight into its own receiver, and with 50 dB in the cable
> that leak is as strong as the loop above about 1.5 GHz
> ([details](measured-performance.md#the-boards-own-tx-to-rx-leak)). Start
> at maximum attenuation and raise power in steps.
> [`tools/selftest/`](../tools/selftest/README.md) does all of this and never
> transmits with less than 35 dB of its own attenuation. The non-PA variant is 10–18 dB
> quieter — check which you have before relying on that.
