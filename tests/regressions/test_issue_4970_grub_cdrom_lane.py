"""tunaOS#4970: a CD boot of a GRUB cell stops at `grub>`; GRUB cells run USB only.

Falsification: behavioural -- runs the real `boots_for` with a GRUB cell and
`--boot both`; on the unfixed tree it returns ["cdrom", "usb"], not ["usb"].
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_grub_cell_has_no_cdrom_lane():
    spec = importlib.util.spec_from_file_location("run_e2e_4970", ROOT / "scripts/installer-e2e/run_e2e.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    args = type("A", (), {"boot": "both", "bootloader": "grub"})()
    assert mod.boots_for(args) == ["usb"]
