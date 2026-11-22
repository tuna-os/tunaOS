#!/usr/bin/env python3
"""Repart definitions that mirror the medium onto the hybrid image (tunaOS#4913).

Reads `sfdisk --json` of the raw image (the one `bootc install to-disk` just
wrote) and writes one definition per partition into DEFSDIR: ESP and /boot
keep their size, the root takes the rest of the disk, every partition copies
the medium's blocks with CopyBlocks= named by PARTUUID. This ports Utah's
utah-live-definitions from install time to build time: the medium root stays
plain (encryption happens at install), and the BIOS boot partition is skipped
(UEFI-only target).
"""

import json
import sys
from pathlib import Path

BIOS_TYPE = "21686148-6449-6e6f-744e-656564454649"


def definitions(table):
    pt = table["partitiontable"]
    sector = int(pt.get("sectorsize", 512))
    kept = [
        p
        for p in sorted(pt["partitions"], key=lambda p: int(p["start"]))
        if p["type"].lower() != BIOS_TYPE
    ]
    if not kept:
        raise ValueError("partition table is empty")
    defs = []
    for index, part in enumerate(kept, start=1):
        lines = [
            "[Partition]",
            f"Type={part['type']}",
            f"CopyBlocks=/dev/disk/by-partuuid/{part['uuid'].lower()}",
        ]
        if part.get("name"):
            lines.append(f"Label={part['name']}")
        if part is not kept[-1]:
            size = int(part["size"]) * sector
            lines += [f"SizeMinBytes={size}", f"SizeMaxBytes={size}"]
        defs.append((f"{index:02d}-copy.conf", "\n".join(lines) + "\n"))
    return defs


def main(argv):
    if len(argv) != 3:
        raise SystemExit("usage: gen-definitions.py SFDISK_JSON DEFSDIR")
    table = json.loads(Path(argv[1]).read_text())
    out = Path(argv[2])
    out.mkdir(parents=True, exist_ok=True)
    for name, text in definitions(table):
        (out / name).write_text(text)
        print(f"{name}: {' '.join(text.splitlines())}")


if __name__ == "__main__":
    main(sys.argv)
