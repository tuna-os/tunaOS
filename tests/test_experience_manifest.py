import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify-experience-manifest.py"
SPEC = importlib.util.spec_from_file_location("experience_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def manifest(**overrides):
    value = {
        "variant": "yellowfin",
        "flavor": "gnome",
        "source_image_digest": "sha256:" + "a" * 64,
        "installer_app_id": "org.bootcinstaller.Installer",
        "screens": MODULE.REQUIRED_SCREENS,
        "luks": True,
        "installed_boot": True,
        "desktop_contract": True,
    }
    value.update(overrides)
    return value


def test_accepts_complete_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()))
    assert MODULE.main.__name__ == "main"
    MODULE.validate(MODULE.load(path), str(path))


@pytest.mark.parametrize("field", ["luks", "installed_boot", "desktop_contract"])
def test_requires_successful_install_contract(field):
    with pytest.raises(ValueError, match=field):
        MODULE.validate(manifest(**{field: False}), "test")


def test_rejects_wrong_screen_order():
    with pytest.raises(ValueError, match="screens"):
        MODULE.validate(manifest(screens=["welcome", "disk", "summary"]), "test")


def test_compare_reports_digest_mismatch():
    left = manifest()
    right = manifest(source_image_digest="sha256:" + "b" * 64)
    assert MODULE.compare(left, right) == ["source_image_digest"]
