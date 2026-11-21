# Build the FSBL from embeddedsw, without xsct. See README.md.
#
# Both targets' build_all.sh run it. To run it directly:
#     make -C firmware/fsbl            # stage, build the BSP, link fsbl.elf
#     make -C firmware/fsbl compare    # and diff against the xsct-built one
#
# CROSS defaults to the DISTRO cross-compiler, which is the point of all this:
# with it, nothing in this build comes from Xilinx except the sources.
#     sudo apt install gcc-arm-none-eabi libnewlib-arm-none-eabi
#
# The compiler that ships inside Vitis still works and is worth keeping for one
# purpose: with it, this build reproduces the FSBL Vitis makes BYTE-FOR-BYTE, so
# any difference is a bug here rather than in the toolchain. That is the
# equivalence anchor, and it is how this build was first validated:
#     make -C firmware/fsbl CROSS=$(VITIS_CROSS) compare   ->  IDENTICAL

FSBL_DIR := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
REPO     := $(abspath $(FSBL_DIR)/../..)
BUILD    ?= $(REPO)/firmware/src/hdl/fsbl/build
XILINX_DIR ?= /tools/Xilinx
VITIS_CROSS := $(XILINX_DIR)/Vitis/2022.2/gnu/aarch32/lin/gcc-arm-none-eabi/bin/arm-none-eabi-
CROSS    ?= arm-none-eabi-
GOLDEN   ?= $(HOME)/fishball-fsbl-golden-2022.2

BSP  := $(BUILD)/bsp/ps7_cortexa9_0
APP  := $(BUILD)/app

# The Eclipse "Debug" configuration, which is what actually ships. embeddedsw's
# own app Makefile uses -O2 with --gc-sections and a leading -lrsa; the FSBL in
# BOOT.bin is built from fsbl/Debug instead, at -O0 -g3 with neither. Matching
# the shipped binary means matching these, not embeddedsw's defaults.
APP_CFLAGS := -Wall -O0 -g3 -c -fmessage-length=0 -mcpu=cortex-a9 -mfpu=vfpv3 \
              -mfloat-abi=hard -MMD -MP
APP_LDFLAGS := -mcpu=cortex-a9 -mfpu=vfpv3 -mfloat-abi=hard -Wl,-build-id=none \
               -specs=$(APP)/Debug/Xilinx.spec
APP_LIBS := -Wl,--start-group,-lxil,-lgcc,-lc,--end-group \
            -Wl,--start-group,-lxilffs,-lxil,-lgcc,-lc,--end-group \
            -Wl,--start-group,-lrsa,-lxil,-lgcc,-lc,--end-group

.PHONY: all stage bsp app compare clean
all: app

stage:
	@ESW="$(ESW)" XSA="$(XSA)" BUILD="$(BUILD)" $(FSBL_DIR)/stage.sh

# The lifted BSP Makefile hardcodes "COMPILER=arm-none-eabi-gcc" inside its own
# rules, so passing COMPILER= on the command line does nothing - it has to be
# found on PATH. That is precisely what Vitis does (Vivado's settings64.sh puts
# its gnu/aarch32 bin directory there), so putting the cross-toolchain on PATH
# here keeps the lifted file verbatim instead of forking it.
CROSS_BIN := $(dir $(CROSS))

bsp: stage
	@echo "=== [bsp] embeddedsw's own Makefiles, the ones xsct shells out to ==="
	@PATH="$(CROSS_BIN):$$PATH" $(MAKE) --no-print-directory -C $(BUILD)/bsp

app: bsp
	@echo "=== [app] fsbl.elf ==="
	@export PATH="$(CROSS_BIN):$$PATH"; cd $(APP)/Debug && mkdir -p src && \
	for c in ../src/*.c; do \
	    $(CROSS)gcc $(APP_CFLAGS) -I$(BSP)/include -o src/$$(basename $$c .c).o $$c || exit 1; \
	done && \
	for s in ../src/*.S; do \
	    [ -e "$$s" ] || continue; \
	    $(CROSS)gcc $(APP_CFLAGS) -I$(BSP)/include -o src/$$(basename $$s .S).o $$s || exit 1; \
	done && \
	$(CROSS)gcc $(APP_LDFLAGS) -Wl,-T -Wl,../src/lscript.ld -L$(BSP)/lib \
	    -o fsbl.elf $$(ls src/*.o | sort) $(APP_LIBS)
	@echo "  $(APP)/Debug/fsbl.elf  $$(wc -c < $(APP)/Debug/fsbl.elf | tr -d '[:space:]') bytes"

# The equivalence test. Compare the LOADABLE IMAGE, not the ELF: -g3 DWARF
# carries absolute build paths and will always differ, while the loadable image
# is exactly what bootgen puts into BOOT.bin's bootloader partition.
compare:
	@ours=$(APP)/Debug/fsbl.elf; theirs=$(GOLDEN)/fsbl/Debug/fsbl.elf; \
	[ -r "$$theirs" ] || { echo "no golden FSBL at $$theirs" >&2; exit 1; }; \
	$(CROSS)objcopy -O binary $$ours  /tmp/fsbl-ours.bin; \
	$(CROSS)objcopy -O binary $$theirs /tmp/fsbl-theirs.bin; \
	echo "  ours   $$(md5sum /tmp/fsbl-ours.bin   | cut -d' ' -f1)  $$(wc -c < /tmp/fsbl-ours.bin | tr -d '[:space:]') bytes"; \
	echo "  vitis  $$(md5sum /tmp/fsbl-theirs.bin | cut -d' ' -f1)  $$(wc -c < /tmp/fsbl-theirs.bin | tr -d '[:space:]') bytes"; \
	if cmp -s /tmp/fsbl-ours.bin /tmp/fsbl-theirs.bin; then echo "  IDENTICAL"; else \
	  echo "  differ - expected with the distro toolchain; check it is only the"; \
	  echo "  newlib atexit machinery and that OCM still fits:"; \
	  $(CROSS)size $$ours $$theirs; \
	  echo "  OCM region ps7_ram_0 is 196608 bytes"; fi

clean:
	rm -rf $(BUILD)
