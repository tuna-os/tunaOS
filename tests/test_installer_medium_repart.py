"""Repart definitions mirror the raw image partition by partition (tunaOS#4913).

Falsification: a missing CopyBlocks source, a resized root that is not the
last partition, or a carried-over BIOS boot partition fails here, before CI
spends a repart run.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("medium_gen_definitions", ROOT / "installer-medium/repart/gen-definitions.py")
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)

ESP = "C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
BOOT = "0FC63DAF-8483-4772-8E79-3D69D8477DE4"
ROOT_TYPE = "4F68BCE3-E8CD-4DB1-96E7-FBCAF984B709"
BIOS = "21686148-6449-6E6F-744E-656564454649"


def table(*parts):
    return {"partitiontable": {"sectorsize": 512, "partitions": [
        {"node": f"/dev/loop0p{i}", "start": 2048 * i, "size": 1024 * i,
         "type": ptype, "uuid": f"11111111-2222-3333-4444-{i:012d}", "name": name}
        for i, (ptype, name) in enumerate(parts, start=1)]},
    }


def test_grub_medium_copies_esp_boot_and_grows_root():
    defs = dict(gen.definitions(table((BIOS, "BIOS-BOOT"), (ESP, "EFI-SYSTEM"), (BOOT, "boot"), (ROOT_TYPE, "root"))))
    assert sorted(defs) == ["01-copy.conf", "02-copy.conf", "03-copy.conf"]
    assert "Type=" + ESP in defs["01-copy.conf"]
    assert "CopyBlocks=/dev/disk/by-partuuid/11111111-2222-3333-4444-000000000002" in defs["01-copy.conf"]
    assert "SizeMinBytes=" in defs["01-copy.conf"] and "SizeMinBytes=" in defs["02-copy.conf"]
    assert "SizeMinBytes=" not in defs["03-copy.conf"]


def test_systemd_boot_medium_without_boot_partition():
    defs = dict(gen.definitions(table((ESP, "EFI-SYSTEM"), (ROOT_TYPE, "root"))))
    assert sorted(defs) == ["01-copy.conf", "02-copy.conf"]
    assert "SizeMinBytes=" not in defs["02-copy.conf"]


def test_empty_table_fails():
    with pytest.raises(ValueError):
        gen.definitions({"partitiontable": {"sectorsize": 512, "partitions": []}})
