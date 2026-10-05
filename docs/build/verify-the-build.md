---
icon: material/clipboard-check-outline
description: ./devkit verify checks a build before you flash it; --board checks the board runs it.
---

# Check the build

```bash
# run from: the repo root
./devkit verify                                   # modern: is the build sane?
./devkit verify --board                           # ...and is the board running it?
./devkit verify --target factory                  # factory: is the build sane?
./devkit verify --target factory --board          # ...and is the board running it?
./devkit verify --target factory --require-board  # the same, but FAIL if the board is stale or unreadable
```

| It checks | Why |
|---|---|
| the five files are present and not trivially small | |
| the bitstream is compressed | an uncompressed one overflows the FSBL's on-chip memory and `BOOT.bin` silently fails to boot |
| timing is met, and what is in the design (DSP48s, LUTs) | |
| (modern) `firmware-modern/verify_dtb.py` audits the built device tree, 16 checks | device-tree mistakes usually build and boot |
| `--board`: every file on the card against `output/`, by checksum | a card holding a different build of the same size looks entirely normal |

**You should see** (factory target), among the rest:

```
== bitstream ==
  PASS  compressed (2371856 B < 3.9 MB uncompressed)
== timing ==
  PASS  no failing setup endpoints
        WNS 0.215 ns over 54211 endpoints
```

!!! note "`--board` reports, it does not fail"
    It reports without changing the exit status. Use `--require-board` in a
    script that must fail on a stale card.

## Timing reports gone after an import

Importing an XSA deletes `timing.rpt` and `utilization.rpt`, so `verify` says
timing is not available. On a tree that was built from source with Vivado,
regenerate them in about a minute:

```bash
# run from: the repo root
cat > firmware/src/hdl/projects/pluto/regen.tcl <<'EOF'
open_project pluto.xpr
open_run impl_1
report_utilization -file utilization.rpt
report_timing_summary -file timing.rpt
EOF
./devkit container shell -c "source tools/env-vivado.sh && cd firmware/src/hdl/projects/pluto \
    && vivado -mode batch -nojournal -nolog -source regen.tcl"
```

**Next:** [put it on the board](flash-your-build.md).
