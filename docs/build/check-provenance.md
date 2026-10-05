---
icon: material/scale-balance
description: How close the rebuild is to the factory firmware, and the commands to check it yourself.
---

# Compare with the factory firmware

```bash
# run from: the repo root
./devkit verify --target factory --board  # is the card running what you built?
iio_info -u ip:fishball.local | grep -E 'fw_version|hw_model'

# against a devicetree.dtb from a factory SD card (FACTORY/): only
# gpio-line-names (0008) and adi,tx-attenuation-mdB (0011) should differ
diff <(dtc -I dtb -O dts FACTORY/devicetree.dtb) \
     <(dtc -I dtb -O dts firmware/output/devicetree.dtb)
```

```bash
# run from: the board. The configuration the running kernel was built with
zcat /proc/config.gz
```

Compare that output between a factory board and your build.

**You should see:** the device trees differ only in `gpio-line-names` and
`adi,tx-attenuation-mdB`.

What is claimed about the reconstruction, and the evidence:
[provenance](../provenance.md).
