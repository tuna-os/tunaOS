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


def test_load_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        MODULE.load(path)


def test_load_non_dict_json(tmp_path):
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="manifest must be a JSON object"):
        MODULE.load(path)


def test_validate_missing_required_fields():
    data = manifest()
    del data["variant"]
    with pytest.raises(ValueError, match="missing fields: variant"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("field", ["variant", "flavor"])
@pytest.mark.parametrize("invalid_value", [123, "", "   "])
def test_validate_invalid_string_fields(field, invalid_value):
    data = manifest(**{field: invalid_value})
    with pytest.raises(ValueError, match=f"{field} must be a non-empty string"):
        MODULE.validate(data, "test")


def test_validate_invalid_source_image_digest():
    data = manifest(source_image_digest="invalid_digest")
    with pytest.raises(ValueError, match="source_image_digest must be a sha256 digest"):
        MODULE.validate(data, "test")


def test_validate_unsupported_installer_app_id():
    data = manifest(installer_app_id="org.invalid.Installer")
    with pytest.raises(ValueError, match="unsupported installer_app_id"):
        MODULE.validate(data, "test")


def test_main_single_valid_manifest(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), str(path)])
    assert MODULE.main() == 0
    captured = capsys.readouterr()
    assert f"ok - validated {path}" in captured.out


def test_main_compare_matching(tmp_path, monkeypatch, capsys):
    path1 = tmp_path / "m1.json"
    path2 = tmp_path / "m2.json"
    path1.write_text(json.dumps(manifest()), encoding="utf-8")
    path2.write_text(json.dumps(manifest()), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), str(path1), "--compare", str(path2)])
    assert MODULE.main() == 0
    captured = capsys.readouterr()
    assert f"ok - {path1} matches {path2}" in captured.out


def test_main_compare_mismatch(tmp_path, monkeypatch, capsys):
    path1 = tmp_path / "m1.json"
    path2 = tmp_path / "m2.json"
    path1.write_text(json.dumps(manifest()), encoding="utf-8")
    path2.write_text(json.dumps(manifest(flavor="kde")), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), str(path1), "--compare", str(path2)])
    assert MODULE.main() == 1
    captured = capsys.readouterr()
    assert "error: parity mismatch in: flavor" in captured.err


def test_main_invalid_manifest_returns_error(tmp_path, monkeypatch, capsys):
    path = tmp_path / "invalid.json"
    path.write_text("invalid json content", encoding="utf-8")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), str(path)])
    assert MODULE.main() == 1
    captured = capsys.readouterr()
    assert "error:" in captured.err

