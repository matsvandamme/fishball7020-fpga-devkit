# Building the firmware without installing Vivado

Vivado is AMD/Xilinx's FPGA design tool. It is about **50 GB** installed, takes
an hour to set up, and the build needs it for **20 to 70 minutes** every time.

If you are here to change a driver, the kernel, or something in the root
filesystem — and not to change the FPGA design itself — you can skip all of
that. This page explains how, and what the catch is.

---

## First, the idea

Building the firmware has two halves:

| Half | What it makes | How long | How often it changes |
|---|---|---|---|
| The FPGA design | the **bitstream** — the file that configures the FPGA | 20–70 min | almost never |
| Everything else | boot loader, Linux kernel, root filesystem, packaging | a few minutes | constantly |

Today, a full build redoes the slow half whether or not anything in it changed.
That is like recompiling a library you have never edited every time you build
your own program.

**An XSA is the finished FPGA design saved in one file.** Hand the build one,
and it skips the slow half:

```bash
# run from: firmware/
./scripts/build_all.sh --xsa /path/to/system_top.xsa
```

<details>
<summary>What "XSA" actually stands for, if you care</summary>

It is AMD/Xilinx's **hardware platform export** — the handoff file between the
FPGA design flow and the software flow. It is a zip, and you can look inside:

```bash
# run from: anywhere
unzip -l system_top.xsa
```

You will see `system_top.bit` (the bitstream) and `ps7_init.c` (code that sets
up the processor's memory controller, clocks and pin multiplexing). Those two
are what the rest of the build needs.
</details>

## Is this for you?

**Yes, if any of these sound like you:**

- *"I keep re-cloning this repo."* The build's working folder, `firmware/src/`,
  is downloaded fresh and deliberately not stored in git — so the Vivado
  project is thrown away every time you set up again. The XSA is the only piece
  of that 70-minute build you can keep.
- *"I only care about Linux, not the FPGA."* You can install **Vitis alone**
  and never install Vivado.
- *"I am chasing a bug."* Rebuilding the FPGA design between attempts changes
  two things at once. An XSA freezes the hardware so only your software differs.

**No, if:**

- You want to change the FPGA design. Then you need Vivado — that is the tool
  that makes the bitstream.
- You only want to change the kernel and flash it. You do not need this page at
  all: see [Change the kernel](building.md#change-the-kernel), rebuild `uImage`
  alone in a few minutes and flash it with `./devkit flash --kernel-only`.

## The one thing that surprises people

**This skips Vivado. It does NOT skip Vitis.**

Vitis is the *software* half of the Xilinx toolchain, and the build needs it to
compile the **FSBL** — the First Stage Boot Loader, the very first code the ARM
processor runs. The FSBL has to bring up the memory controller before anything
else can run, and the settings for that are specific to the FPGA design. They
live inside the XSA as `ps7_init.c`, and Vitis compiles them.

So the shopping list is:

| | Needed? |
|---|---|
| Vivado (~50 GB) | **no**, with `--xsa` |
| Vitis 2022.2 | **yes**, always |
| The Linaro cross-compiler | yes — the build makes it for you |

`./devkit doctor` will tell you this too: without Vivado it now prints a
warning that points here, rather than refusing to go on. Without Vitis it still
fails, because there is genuinely no build without it.

## Where to get an XSA

**Option 1 — save your own.** If you have ever run a full build, you already
have one. Copy it somewhere safe *before* your next `./devkit setup` wipes it:

```bash
# run from: the repo root
cp firmware/src/hdl/projects/pluto/system_top.xsa ~/fishball-platform.xsa
```

That one file is the durable result of the whole 70 minutes.

**Option 2 — download it from a release.** Every release here ships
`system_top.xsa` beside the five SD-card files, with its checksum in
`SHA256SUMS`. It is the platform those exact files were built from, so a
rebuild starts from the same hardware design:

```bash
# run from: anywhere, with the gh CLI
gh release download --repo matsvandamme/fishball7020-fpga-devkit \
   --pattern 'system_top.xsa' --pattern 'SHA256SUMS'
sha256sum -c SHA256SUMS --ignore-missing
```

Releases are built from source on a machine with a board attached and verified
against it before publishing — the workflow refuses to publish a release whose
own firmware was built with `--xsa`, so a release platform is never a copy of
somebody else's.

It is about **880 KB**: a zip whose members come to 6.9 MB uncompressed, most
of that the bitstream, which compresses well because unused fabric is zeros.

**Option 3 — get one from somebody else.** Anyone who has built this repo can
send you theirs. Read the honesty section at the bottom before you do.

## Doing it

```bash
# run from: firmware/
./scripts/build_all.sh --xsa ~/fishball-platform.xsa
```

Add `--hdl-only` if your kernel, boot loader and root filesystem are already
built and you only want to repackage:

```bash
# run from: firmware/
./scripts/build_all.sh --hdl-only --xsa ~/fishball-platform.xsa
```

The first stage will say what it is doing:

```
=== [1/7] Importing a pre-built XSA (Vivado not invoked) ===
    hardware platform: .../system_top.xsa
    bitstream:         2390808 bytes
    provenance:        .../output/xsa-provenance.txt
    NOTE: this design was not implemented here, so there is no timing
          report to check. ./scripts/verify_output.sh will say so.
```

Everything after that is the ordinary build, unchanged.

## Checking it worked

```bash
# run from: firmware/
./scripts/verify_output.sh
```

With an imported platform it tells you plainly that the bitstream was not built
here, prints its md5, and lists the IP blocks that are **actually in the
bitstream** — read from the platform's own records, not from the source code in
your tree:

```
bitstream was IMPORTED, not built here:
  bitstream md5 6bf9c28daf976ead441dff1e4bd2af9c
IP in the bitstream, from its own system.hwh (not from source):
  axi_ad9361 ... gpio_bitmap_o ... tx_upack
  -> sample-locked GPIO IS in this bitstream
timing: NOT AVAILABLE - this design was not implemented here.
```

That last line matters. Normally the verifier checks that the design meets
timing. It cannot, because the design was implemented on somebody else's
machine — so it says so, rather than failing (which would imply something is
wrong) or passing quietly (which would imply it checked).

`output/xsa-provenance.txt` records where the file came from, its md5, and that
IP list, so a board can be traced back to the platform it was built from.

## Does it really produce the same firmware?

Yes, and it is checkable. Building from an XSA exported by a Vivado run produces
a **byte-identical `BOOT.bin`**:

```
BOOT.bin from the Vivado build: 3fb710d8f990cec8f14d5ca61ca2ddb7
BOOT.bin from --xsa:           3fb710d8f990cec8f14d5ca61ca2ddb7
```

The bitstream inside the XSA is likewise byte-identical to the one a Vivado
build copies out of its run directory (md5 `6bf9c28d…`), which is why this works
at all — the XSA is the *designed* handoff point, not a shortcut around one.

## What can go wrong, and what it looks like

The import refuses anything it cannot vouch for, with one clear sentence:

| If you pass | You get |
|---|---|
| Something that is not a zip | `ERROR: … is not a readable zip archive.` |
| An XSA exported without the bitstream | `ERROR: … contains no system_top.bit.` |
| An XSA for a different chip | `ERROR: that XSA is not for this board's part (xc7z020clg400-2).` |
| An XSA from a different Vivado version | `ERROR: that XSA was written by a different tool version.` |

The last two matter more than they look: a mismatched platform would otherwise
sail into the FSBL build and fail there, where the error is about `xsct` and
not about the file you passed.

## Being honest about what you have given up

This is the part worth reading twice.

**Your own XSA is a cache.** You built it, from sources you can read, on your
machine. Nothing is lost.

**Someone else's XSA is a binary you cannot read.** You can list what is in it,
you can check it is for the right chip, and you can confirm it produces the
`BOOT.bin` you flash. You cannot confirm it matches any particular source code,
because a bitstream cannot be decompiled back into a design.

That is precisely the situation this repository exists to get you *out* of —
the README's own words are that vendor firmware "does not include editable HDL
sources, which is the gap this repo fills". So:

- Use your own XSA freely.
- Treat someone else's the way you would treat any binary from a stranger.
- If it matters, build the design yourself once, and keep the XSA.

## See also

- [Building your own firmware](building.md) — the full build, including Vivado
- [Change the kernel](building.md#change-the-kernel) — if that is all you want
- [The block design](block-design.md) — what is actually in the bitstream
