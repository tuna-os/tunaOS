#!/usr/bin/env python3
"""Put a GRUB stub into the ISO 9660 file system of the hybrid image (tunaOS#4970).

Usage: installer-medium/repart/iso-grub-stub.py IMAGE VENDOR

On a CD boot the firmware starts shim and GRUB from the El Torito image. The
signed GRUB then looks for its configuration at (cd0)/EFI/VENDOR/grub.cfg,
where (cd0) is the whole disc: the ISO 9660 file system that systemd-repart
wrote. That file system is empty, so GRUB stops at its prompt. GRUB does read
the GPT of the disc, as (cd0,gpt1) and so on (measured on a test disc with
the GRUB of albacore:gnome, 2026-11-25: `echo $prefix` = (cd0)/EFI/almalinux,
`ls` = (cd0) (cd0,gpt2) (cd0,gpt1)). This stub goes on with the grub.cfg of
the ESP. A USB boot never reads it: there the prefix is on the ESP.

The writer adds EFI/VENDOR/GRUB.CFG to the root directory, in sectors that
are empty and before the first partition. It changes no other byte. GRUB
matches plain ISO 9660 names without case.
"""

import struct
import sys
from pathlib import Path

SECTOR = 2048
PVD = 16
FIRST_FREE = 64
MAX_NAME = 31


def both16(value):
    return struct.pack("<H", value) + struct.pack(">H", value)


def both32(value):
    return struct.pack("<I", value) + struct.pack(">I", value)


def record(name, extent, size, directory):
    """One ISO 9660 directory record."""
    pad = b"" if len(name) % 2 else b"\0"
    body = (
        b"\0"
        + both32(extent)
        + both32(size)
        + b"\x7e\x0b\x19\0\0\0\0"
        + bytes([2 if directory else 0, 0, 0])
        + both16(1)
        + bytes([len(name)])
        + name
        + pad
    )
    return bytes([len(body) + 1]) + body


def directory(own, parent, entries):
    data = record(b"\0", own, SECTOR, True) + record(b"\1", parent, SECTOR, True)
    data += b"".join(entries)
    if len(data) > SECTOR:
        raise ValueError("a directory does not fit one sector")
    return data.ljust(SECTOR, b"\0")


def config(vendor):
    return (
        "# tunaOS installer medium, CD boot: go on with the GRUB configuration of the ESP.\n"
        f"set config=($root,gpt1)/EFI/{vendor}\n"
        "set prefix=$config\n"
        "configfile $config/grub.cfg\n"
    ).encode()


def add_stub(image, vendor, first_partition):
    """Write the stub into `image` (a writable binary file object)."""

    def read(sector, count=1):
        image.seek(sector * SECTOR)
        return image.read(count * SECTOR)

    pvd = read(PVD)
    if pvd[:6] != b"\x01CD001":
        raise ValueError("no ISO 9660 primary volume descriptor")
    root, size = (struct.unpack_from("<I", pvd, 156 + at)[0] for at in (2, 10))
    name = vendor.upper().encode("ascii")
    if not 0 < len(name) <= MAX_NAME or not all(c.isalnum() or c in "-_" for c in vendor):
        raise ValueError(f"not a directory name for ISO 9660: {vendor!r}")
    body = config(vendor)
    efi, sub, data = FIRST_FREE, FIRST_FREE + 1, FIRST_FREE + 2
    last = data + (len(body) - 1) // SECTOR
    if (last + 1) * SECTOR > first_partition:
        raise ValueError("no room before the first partition")
    if any(read(FIRST_FREE, last - FIRST_FREE + 1)):
        raise ValueError("the sectors of the stub are in use")
    # The size of the root directory is the size of its records (68 bytes for
    # the empty one of systemd-repart), not a whole sector.
    if size > SECTOR:
        raise ValueError("the root directory has more than one sector")
    listing, used = read(root), 0
    while used < size:
        length = listing[used]
        if length < 34:
            raise ValueError("a broken record in the root directory")
        entry = listing[used : used + length]
        if entry[33 : 33 + entry[32]].upper() == b"EFI":
            raise ValueError("the ISO 9660 file system has an EFI directory")
        used += length
    new = record(b"EFI", efi, SECTOR, True)
    if used + len(new) > SECTOR:
        raise ValueError("the root directory is full")
    grown = both32(used + len(new))
    writes = [
        (root * SECTOR + used, new),
        (efi * SECTOR, directory(efi, root, [record(name, sub, SECTOR, True)])),
        (sub * SECTOR, directory(sub, efi, [record(b"GRUB.CFG;1", data, len(body), False)])),
        (data * SECTOR, body),
        # The new size: in the volume descriptor, and in the records that the
        # root directory has of itself and of its parent, which is itself.
        (PVD * SECTOR + 156 + 10, grown),
        (root * SECTOR + 10, grown),
        (root * SECTOR + listing[0] + 10, grown),
    ]
    for offset, blob in writes:
        image.seek(offset)
        image.write(blob)


def first_partition(image):
    """Byte offset of the first GPT partition."""
    image.seek(512)
    header = image.read(92)
    if header[:8] != b"EFI PART":
        raise ValueError("no GPT")
    table, count, size = struct.unpack_from("<QII", header, 72)
    starts = []
    image.seek(table * 512)
    for _ in range(count):
        entry = image.read(size)
        if any(entry[:16]):
            starts.append(struct.unpack_from("<Q", entry, 32)[0])
    if not starts:
        raise ValueError("the GPT has no partition")
    return min(starts) * 512


def main(argv):
    if len(argv) != 3:
        raise SystemExit("usage: iso-grub-stub.py IMAGE VENDOR")
    with Path(argv[1]).open("r+b") as image:
        add_stub(image, argv[2], first_partition(image))
    print(f"iso-grub-stub: EFI/{argv[2]}/grub.cfg in the ISO 9660 file system of {argv[1]}")


if __name__ == "__main__":
    main(sys.argv)
