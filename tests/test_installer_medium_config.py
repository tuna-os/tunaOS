"""Installer medium cells in tunaos.toml resolve the #4907/#4913 matrix (tunaOS#4907).

Falsification: an EL10 cell on btrfs, a non-EL cell on xfs, an unknown
variant, flavor or sibling desktop, a duplicate cell, a branch ref instead
of a commit, or a chunk above the 256 MiB contract cap all fail validation.
"""

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


config = module("installer_medium_config", ROOT / "scripts/lib/tunaos_config.py")
medium = config.installer_medium_policy()


def test_done_when_cells_resolve():
    source = config.load()
    assert medium.cell(source, "albacore:gnome") == {
        "cell": "albacore:gnome",
        "filesystem": "xfs",
        "bootloader": "grub",
        "backend": "ostree",
    }
    assert medium.cell(source, "tromso:kde") == {
        "cell": "tromso:kde",
        "filesystem": "btrfs",
        "bootloader": "systemd-boot",
        "backend": "composefs",
    }


def test_pin_is_a_main_commit_past_encrypted_root():
    source = config.load()
    policy = source["installer_medium"]
    assert policy["systemd_repo"] == "https://github.com/systemd/systemd.git"
    assert len(policy["systemd_ref"]) == 40
    assert policy["chunk_bytes"] <= medium.MAX_CHUNK_BYTES


def test_unknown_cell_lookup_fails():
    with pytest.raises(medium.MediumError):
        medium.cell(config.load(), "bonito:gnome")


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p.update(schema_version=2),
        lambda p: p.update(systemd_repo="git@github.com:systemd/systemd.git"),
        lambda p: p.update(systemd_ref="main"),
        lambda p: p.update(systemd_ref="5371d8fe"),
        lambda p: p.update(chunk_bytes=1 << 20 - 1),
        lambda p: p.update(chunk_bytes=(256 << 20) + 1),
        lambda p: p.update(cells=[]),
        lambda p: p["cells"].append(copy.deepcopy(p["cells"][0])),
        lambda p: p["cells"][0].update(cell="no-such-variant:gnome"),
        lambda p: p["cells"][0].update(cell="albacore:no-such-flavor"),
        lambda p: p["cells"][0].update(cell="tromso:gnome"),
        lambda p: p["cells"][0].update(cell="not-a-cell"),
        lambda p: p["cells"][0].update(filesystem="btrfs"),
        lambda p: p["cells"][0].update(bootloader="shim"),
        lambda p: p["cells"][0].update(backend="zfs"),
        lambda p: p["cells"][1].update(filesystem="xfs"),
    ],
)
def test_invalid_medium_declarations_fail_closed(change):
    source = config.load()
    change(source["installer_medium"])
    with pytest.raises((medium.MediumError, config.ConfigError)):
        config.validate(source)
