"""Every medium cell equals what the installer recipe probe says (tunaOS#4905).

installer-medium/evidence/images.json holds, per cell, the inputs the probe
reads from the published image (EFI payload names, kernel directories,
prepare-root.conf, os-release), the image digest and the read date.
installer-medium/evidence/scan-images.py writes it from the registry. The
tests rebuild each recorded tree and run the real probe,
live-iso/common/src/installer-recipe-backend.sh, with the btrfs opt-in of
#4921, so a stored result that the probe no longer gives fails here, and so
does a resolver row that differs from the probe.

Falsification: flip the bonito pin to composefs enabled and the cell must
become ext4 or composefs-native; drop the opt-in and the filesystem is xfs,
which the resolver refuses for a non-EL base.
"""

import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "live-iso/common/src/installer-recipe-backend.sh"
EVIDENCE = ROOT / "installer-medium/evidence/images.json"


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


config = module("c", ROOT / "scripts/lib/tunaos_config.py")
scan = module("scan_images", ROOT / "installer-medium/evidence/scan-images.py")
medium = config.installer_medium_policy()
RECORDS = json.loads(EVIDENCE.read_text())["images"]
MEASURED = [r for r in RECORDS if "facts" in r]


def probe(root: Path, allow_btrfs: bool = True):
    env = {**os.environ, "TUNAOS_INSTALLER_ALLOW_BTRFS": "1" if allow_btrfs else "0"}
    done = subprocess.run(["bash", str(PROBE), str(root)], capture_output=True, text=True, env=env)
    if done.returncode != 0:
        return None
    return dict(line.split("=", 1) for line in done.stdout.splitlines())


def test_the_evidence_file_covers_exactly_the_scan_candidates():
    assert [r["cell"] for r in RECORDS] == sorted(c["cell"] for c in medium.scan_candidates(config.load()))


@pytest.mark.parametrize("record", RECORDS, ids=lambda r: r["cell"])
def test_every_record_is_a_measurement_or_a_reason(record):
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", record["read"])
    if "probe" in record:
        assert "unverified" not in record
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", record["digest"])
        assert record["platform"].startswith("linux/")
    else:
        assert record["unverified"].strip()


@pytest.mark.parametrize("record", MEASURED, ids=lambda r: r["cell"])
def test_the_stored_result_is_what_the_probe_says_today(tmp_path, record):
    assert probe(scan.build_tree(record["facts"], tmp_path)) == record.get("probe")


@pytest.mark.parametrize("record", [r for r in MEASURED if "probe" in r], ids=lambda r: r["cell"])
def test_the_resolved_row_is_the_probe_result(record):
    rows = {row["cell"]: row for row in medium.resolve(config.load())}
    row = rows[record["cell"]]
    if row["status"] == "unverified":
        # The resolver may refuse a probe result (xfs for an unknown family,
        # a sealed EL10 image), and must then say why.
        assert row["reason"] and row["bootloader"] is None
        return
    got = record["probe"]
    assert row["source"] == "probe" and row["digest"] == record["digest"]
    assert row["bootloader"] == {"grub2": "grub", "systemd": "systemd-boot"}[got["bootloader"]]
    assert row["backend"] == ("composefs" if got["composeFsBackend"] == "true" else "ostree")
    assert row["filesystem"] == got["filesystem"]


def bonito_facts(composefs="no"):
    facts = json.loads(json.dumps(next(r for r in RECORDS if r["cell"] == "bonito:gnome")["facts"]))
    facts["prepare_root_conf"] = f"[composefs]\nenabled = {composefs}\n\n[sysroot]\nreadonly = true\n"
    return facts


def test_bonito_is_grub_ostree_btrfs(tmp_path):
    facts = bonito_facts()
    assert "usr/lib/bootupd/updates/EFI.json" in facts["files"]
    assert probe(scan.build_tree(facts, tmp_path)) == {
        "bootloader": "grub2",
        "composeFsBackend": "false",
        "filesystem": "btrfs",
    }


def test_without_the_opt_in_the_probe_says_xfs(tmp_path):
    assert probe(scan.build_tree(bonito_facts(), tmp_path), allow_btrfs=False)["filesystem"] == "xfs"


def test_a_sealed_image_on_a_kernel_without_the_verity_fix_is_ext4(tmp_path):
    facts = bonito_facts(composefs="yes")
    facts["kernels"] = ["7.3.4-200.fc44.x86_64"]
    assert probe(scan.build_tree(facts, tmp_path))["filesystem"] == "ext4"


def test_a_sealed_image_on_a_fixed_kernel_is_btrfs(tmp_path):
    facts = bonito_facts(composefs="yes")
    facts["kernels"] = ["7.4.0-rc2.fc45.x86_64"]
    assert probe(scan.build_tree(facts, tmp_path))["filesystem"] == "btrfs"


def test_whiteouts_remove_lower_layer_paths():
    layers = [
        [["kernel", "usr/lib/modules/6.1", ""], ["file", "usr/lib/efi/grub2/1/EFI/x/grubx64.efi", ""]],
        [["whiteout", "usr/lib/modules/6.1", ""], ["kernel", "usr/lib/modules/7.5", ""]],
        [["opaque", "usr/lib/efi", ""], ["text", "usr/lib/os-release", "ID=fedora\nNAME=x\n"]],
    ]
    facts = scan.facts_of(scan.merge(layers))
    assert facts == {"files": [], "kernels": ["7.5"], "os_release": "ID=fedora\n"}
