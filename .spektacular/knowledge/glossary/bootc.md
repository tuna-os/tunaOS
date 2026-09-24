---
tags: [bootc]
---

# bootc

Bootable containers: an OCI image that is a whole OS, installed to disk and updated/rolled back atomically (`bootc upgrade`, `bootc switch`, `bootc rollback`). Every TunaOS image is a bootc image; non-bootc bases (Debian, Ubuntu, Arch, ...) are "bootcified" by their Containerfile.
