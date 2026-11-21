---
icon: material/package-variant-closed
description: The SDR++ build that knows this board's second receiver, its FPGA decimator and the Fast TCP transport.
---

# Install the patched SDR++

Stock SDR++ does not know this board's second receiver or its FPGA.
[`tools/sdrpp/`](../../tools/sdrpp/README.md) builds SDR++ with a patch that
adds them to the PlutoSDR source panel.

![The patched PlutoSDR source panel: RX Port, FPGA /8 decimator, Bandwidth, Gain Mode, Gain, Quadrature tracking, RF DC tracking, Baseband DC tracking, Freq. corr. (ppm), and the status lines Board, Firmware and Temp.](../img/sdrpp-source-panel.png){ width="340" }

=== "Arch"

    ```bash
    # run from: tools/sdrpp/
    makepkg -f
    sudo pacman -U sdrpp-git-*-x86_64.pkg.tar.zst
    ```

=== "Another Linux"

    Build SDR++ from source at the same commit with the patch applied:

    ```bash
    # run from: wherever you build software
    git clone https://github.com/AlexandreRouma/SDRPlusPlus.git && cd SDRPlusPlus
    git checkout 8c9f5ee8fe405775bfcd62c8c8f8c0fc928a64af
    patch -p1 < /path/to/fishball7020-fpga-devkit/tools/sdrpp/plutosdr-fishball.patch
    cmake -B build -DCMAKE_BUILD_TYPE=Release && make -C build -j"$(nproc)"
    sudo make -C build install
    ```

    Its dependencies are SDR++'s own (`fftw`, `glfw`, `glew`, `volk`, `libiio`,
    `libad9361`, an audio library); its
    [build instructions](https://github.com/AlexandreRouma/SDRPlusPlus#building-on-linux--bsd)
    list them per distribution.

=== "macOS"

    ```bash
    # run from: the repo root, on the Mac
    tools/sdrpp/build-macos.sh --install-deps    # without the flag it names the missing Homebrew formulae and stops
    ~/.cache/fishball-sdrpp/sdrpp                # the launcher it writes
    ```

    It builds the same SDR++ commit with the same patch and the DAB+ decoder,
    and libiio 0.26 beside it, into `~/.cache/fishball-sdrpp` (or the
    directory you pass). No `sudo`; delete the directory to remove it.
    `--clean` deletes the build and starts over.

    - **Pick the board from the device menu** under the **PlutoSDR** source.
      There is no address field: the menu lists what libiio's scan finds.
    - **Start it with the launcher**, which also adds the **DAB Decoder**
      panel once.
    - **Tested** on one Apple Silicon Mac: it builds, starts, and loads the
      PlutoSDR source, the audio sink and the DAB+ decoder. Receiving in the
      window was not checked.

    What differs from the Arch package:
    [`tools/sdrpp/README.md`](../../tools/sdrpp/README.md#macos).

**You should see:** the PlutoSDR source panel with **RX Port**, **FPGA /8
decimator** and **Transport**, as in the picture.

What each control does: [SDR++](../sdrpp.md#this-boards-controls-the-patched-sdr).

**Next:** [stream 20 MS/s to SDR++](stream-20-msps.md) or
[listen to DAB+ radio](listen-to-dab.md).
