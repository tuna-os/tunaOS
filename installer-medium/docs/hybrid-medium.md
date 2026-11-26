# Hybrid medium

`repart/build-hybrid.sh` writes one file that boots as a CD and as a `dd`'d USB
disk (tunaOS#4913). `repart/verify-hybrid.sh` runs after the write and fails the
build unless the file has a GPT with an ESP and a UEFI El Torito boot image.

## How each lane boots

| Lane | Firmware reads | Root |
|---|---|---|
| USB (`dd`) | the GPT; the ESP | the kernel scans partitions; `PARTUUID` resolves |
| CD, `-cdrom`, ISO writers | the El Torito image, which is the full ESP | the `90medium-sr0` dracut module runs `losetup -r -P` on `/dev/sr0`, so the same `PARTUUID`s appear |

The kernel and initrd of the live entry sit on the ESP, because a CD boot
cannot see `/boot`. `add-live-entry.sh` stops the build when fewer than 100 MiB
stay free on the ESP after the copy. The NVIDIA initrd is about 224 MB.

## Third-party tools: not yet verified

This page has no result for these, and makes no claim about them. Run each
with the published medium of a promoted cell and write the outcome here.

| Tool | Mode | Check | Result |
|---|---|---|---|
| Ventoy | ISO mode | boots live, installer page shows | not run |
| Ventoy | `dm` (grub2) mapping | `PARTUUID` still resolves | not run |
| Fedora Media Writer, balenaEtcher | raw write | `sfdisk --json /dev/sdX` still lists a GPT | not run |
