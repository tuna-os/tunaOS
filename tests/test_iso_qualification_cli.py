import os
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "iso-e2e.sh"


def run_qualification(tmp_path, profile="plain", **environment):
    iso = tmp_path / "yellowfin-gnome-test.iso"
    manifest = tmp_path / "experience-manifest.json"
    iso.touch()
    manifest.write_text("{}", encoding="utf-8")
    env = os.environ | environment
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            str(iso),
            "--qualification",
            profile,
            "--manifest",
            str(manifest),
            "--output",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


@pytest.mark.parametrize("variable", ["FISHERMAN_OVERRIDE", "TBOX_E2E_IMAGE"])
def test_qualification_rejects_host_installer_or_image_injection(tmp_path, variable):
    proc = run_qualification(tmp_path, **{variable: "/tmp/injected"})
    assert proc.returncode == 1
    assert "qualification forbids FISHERMAN_OVERRIDE and TBOX_E2E_IMAGE" in proc.stderr


def test_qualification_rejects_unknown_profile_before_starting_qemu(tmp_path):
    proc = run_qualification(tmp_path, profile="automatic")
    assert proc.returncode == 1
    assert "--qualification must be plain or encrypted" in proc.stderr


def test_qualification_requires_manifest_before_starting_qemu(tmp_path):
    iso = tmp_path / "yellowfin-gnome-test.iso"
    iso.touch()
    proc = subprocess.run(
        ["bash", str(SCRIPT), str(iso), "--qualification", "plain"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "--qualification requires --manifest FILE" in proc.stderr
