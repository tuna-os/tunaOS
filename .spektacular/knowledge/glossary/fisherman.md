---
tags: [fisherman, install]
---

# fisherman

The disk installer that runs inside the live system: takes a recipe (disk, image, encryption) and does partition, LUKS/TPM, `bootc install`, flatpaks, hostname, users. Use it instead of calling `bootc install to-disk` directly. Sourced from `tuna-os/fisherman` (checked by `scripts/check-installer-fisherman-pins.py`).
