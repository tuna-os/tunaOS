import copy
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify-experience-manifest.py"
SPEC = importlib.util.spec_from_file_location("experience_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _digest(char="a"):
    return "sha256:" + char * 64


def _observed_record(char="a"):
    digest = _digest(char)
    return {
        "installed_boot": True,
        "desktop_contract": True,
        "source_digest": digest,
        "booted_digest": digest,
        "target_imgref": "ghcr.io/tuna-os/yellowfin:latest",
        "duration_s": 123.0,
    }


def manifest(**overrides):
    value = {
        "schema": "QualificationEvidence/v1",
        "variant": "yellowfin",
        "flavor": "gnome",
        "platform": "x86_64",
        "cpu_baseline": "x86-64-v2",
        "hardware_scope": "qemu",
        "qualifiedAt": "2026-10-19T00:00:00Z",
        "receiptDigest": _digest("e"),
        "resolved_inputs": {
            "source": _digest("a"),
            "overlay": _digest("b"),
            "installer": _digest("c"),
            "engine": _digest("d"),
            "media": _digest("f"),
        },
        "browser": {
            "name": "chromium",
            "version": "130.0",
            "memory_gib": 8,
            "free_disk_gib": 20,
        },
        "offline_network_disabled": True,
        "observed": {
            "plain": _observed_record("a"),
            "encrypted": _observed_record("a"),
        },
        "measurements": {
            "cold": {"duration_s": 600.0},
            "warm": {"duration_s": 300.0},
        },
    }
    value.update(overrides)
    value["receiptDigest"] = MODULE._receipt_digest(value)
    return value


def test_accepts_valid_v1_manifest(tmp_path):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(manifest()), encoding="utf-8")
    MODULE.validate(MODULE.load(path), str(path))


def test_rejects_old_bare_boolean_manifest():
    old = {
        "variant": "yellowfin",
        "flavor": "gnome",
        "source_image_digest": _digest("a"),
        "installer_app_id": "org.bootcinstaller.Installer",
        "screens": MODULE.REQUIRED_SCREENS,
        "luks": True,
        "installed_boot": True,
        "desktop_contract": True,
    }
    with pytest.raises(ValueError, match="not a QualificationEvidence v1"):
        MODULE.validate(old, "test")


def test_rejects_wrong_schema():
    with pytest.raises(ValueError, match="not a QualificationEvidence v1"):
        MODULE.validate(manifest(schema="bogus"), "test")


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_rejects_missing_observed_mode(mode):
    data = manifest()
    del data["observed"][mode]
    with pytest.raises(ValueError, match=f"observed.{mode} is missing"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("value", [False, None])
def test_rejects_network_not_disabled(value):
    data = manifest(offline_network_disabled=value)
    with pytest.raises(ValueError, match="offline_network_disabled must be true"):
        MODULE.validate(data, "test")


def test_rejects_missing_offline_network_flag():
    data = manifest()
    del data["offline_network_disabled"]
    with pytest.raises(ValueError, match="offline_network_disabled must be true"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_rejects_unbooted_observed_mode(mode):
    data = manifest()
    data["observed"][mode]["installed_boot"] = False
    with pytest.raises(ValueError, match=f"observed.{mode}.installed_boot must be true"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_rejects_failed_desktop_contract(mode):
    data = manifest()
    data["observed"][mode]["desktop_contract"] = False
    with pytest.raises(ValueError, match=f"observed.{mode}.desktop_contract must be true"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_rejects_booted_digest_mismatch(mode):
    data = manifest()
    data["observed"][mode]["booted_digest"] = _digest("e")
    with pytest.raises(ValueError, match="does not match"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize(
    "field", ["install_duration_s", "cold_boot_s", "warm_boot_s"]
)
def test_compare_ignores_install_and_boot_timing_fields(field):
    left = manifest()
    right = copy.deepcopy(left)
    left["observed"]["plain"][field] = 1.0
    right["observed"]["plain"][field] = 2.0
    left["measurements"]["cold"][field] = 3.0
    right["measurements"]["cold"][field] = 4.0
    assert MODULE.compare(left, right) == []

def test_compare_ignores_transient_free_disk_measurement():
    left = manifest()
    right = copy.deepcopy(left)
    left["browser"]["free_disk_gib"] = 20
    right["browser"]["free_disk_gib"] = 11
    assert MODULE.compare(left, right) == []

def test_compare_ignores_builder_specific_media_output():
    left = manifest()
    right = copy.deepcopy(left)
    left["resolved_inputs"]["media"] = _digest("a")
    right["resolved_inputs"]["media"] = _digest("f")
    assert MODULE.compare(left, right) == []


def test_rejects_receipt_digest_for_changed_content():
    data = manifest()
    data["browser"]["memory_gib"] = 9
    with pytest.raises(ValueError, match="receiptDigest"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("mode", ["plain", "encrypted"])
def test_rejects_observed_source_digest_mismatch(mode):
    data = manifest()
    data["observed"][mode]["source_digest"] = _digest("e")
    with pytest.raises(ValueError, match="source_digest.*does not match"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("field", ["platform", "cpu_baseline", "hardware_scope"])
@pytest.mark.parametrize("bad", ["", "   ", 123, None])
def test_rejects_missing_identity_fields(field, bad):
    with pytest.raises(ValueError, match=field):
        MODULE.validate(manifest(**{field: bad}), "test")


@pytest.mark.parametrize("field", ["resolved_inputs", "browser", "observed", "measurements"])
def test_rejects_missing_top_level_blocks(field):
    data = manifest()
    del data[field]
    with pytest.raises(ValueError, match=field):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("digest_name", ["source", "overlay", "installer", "engine", "media"])
def test_rejects_missing_resolved_input_digest(digest_name):
    data = manifest()
    del data["resolved_inputs"][digest_name]
    with pytest.raises(ValueError, match=f"resolved_inputs.{digest_name} is missing"):
        MODULE.validate(data, "test")


def test_rejects_malformed_resolved_input_digest():
    data = manifest()
    data["resolved_inputs"]["source"] = "not-a-digest"
    with pytest.raises(ValueError, match="resolved_inputs.source must be a sha256 digest"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("field", ["name", "version"])
def test_rejects_missing_browser_identity(field):
    data = manifest()
    data["browser"][field] = "  "
    with pytest.raises(ValueError, match=field):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("field", ["memory_gib", "free_disk_gib"])
def test_rejects_missing_browser_resources(field):
    data = manifest()
    del data["browser"][field]
    with pytest.raises(ValueError, match=f"browser.{field} is missing"):
        MODULE.validate(data, "test")


@pytest.mark.parametrize("native_name", ["native", "native-fallback", " Native-Fallback ", "NATIVE"])
def test_rejects_native_fallback_masquerading_as_browser(native_name):
    data = manifest()
    data["browser"]["name"] = native_name
    with pytest.raises(ValueError, match="declares a native"):
        MODULE.validate(data, "test")


def test_compare_accepts_identical_evidence():
    assert MODULE.compare(manifest(), manifest()) == []


def test_compare_flags_browser_drift():
    other = manifest()
    other["browser"]["version"] = "131.0"
    assert MODULE.compare(manifest(), other) == ["browser"]


def test_compare_flags_resolved_input_drift():
    other = manifest()
    other["resolved_inputs"]["source"] = _digest("f")
    assert MODULE.compare(manifest(), other) == ["resolved_inputs"]


def test_compare_ignores_timing_only_drift():
    left = manifest()
    right = copy.deepcopy(left)
    right["observed"]["plain"]["duration_s"] += 42.0
    right["measurements"]["cold"]["duration_s"] += 10.0
    assert MODULE.compare(left, right) == []


def test_compare_flags_missing_observed_mode():
    other = manifest()
    del other["observed"]["encrypted"]
    assert "observed" in MODULE.compare(manifest(), other)


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


def test_main_single_valid_manifest(tmp_path, monkeypatch, capsys):
    path = tmp_path / "evidence.json"
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
