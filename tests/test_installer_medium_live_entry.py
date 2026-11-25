"""Live boot entries are pure text transforms (tunaOS#4907, #4913).

Falsification: a dropped rw, a kept installer entry, a wrong GRUB default,
or a misplaced live initrd fails here, before any root-only stage runs.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "medium_live_entry", ROOT / "installer-medium/live-entry.py"
)
entry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entry)

BLS = "title TunaOS\nversion 5\noptions rw quiet rhgb\n"
TYPE1 = "title TunaOS\nversion 5\nlinux /EFI/Linux/kernel\ninitrd /EFI/Linux/ramdisk.img\noptions rw quiet\n"


def test_grub_entry_goes_read_only_live():
    assert entry.live_entry(BLS) == (
        "title TunaOS Live (try or install)\nversion 1005\noptions quiet rhgb ro tunaos.live\n"
    )


def test_systemd_boot_entry_keeps_sort_key_and_takes_live_initrd():
    first = entry.live_entry(TYPE1, ["tunaos.live.installer=gnome-setup"])
    assert "sort-key" not in first
    assert "options quiet ro tunaos.live tunaos.live.installer=gnome-setup" in first
    live = entry.with_live_initrd(first, "/EFI/Linux/medium-live/live.initrd")
    options_at = live.index("options")
    assert live.index("initrd /EFI/Linux/medium-live/live.initrd") < options_at


def test_entry_without_options_fails():
    with pytest.raises(ValueError):
        entry.live_entry("title TunaOS\n")


def test_grubenv_points_at_live_entry():
    block = entry.grubenv("# GRUB Environment Block\n", "medium-live")
    assert len(block) == entry.GRUBENV_SIZE
    assert "saved_entry=medium-live" in block


def test_loader_conf_defaults_to_live():
    conf = entry.loader_conf("timeout 10\ndefault other\n", "medium-live.conf")
    assert "default medium-live.conf" in conf
    assert "timeout 5" in conf


def test_entry_paths_split_kernel_and_initrds():
    kernel, initrds = entry.entry_paths(TYPE1)
    assert kernel == "/EFI/Linux/kernel"
    assert initrds == ["/EFI/Linux/ramdisk.img"]
