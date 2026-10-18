import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "verify-experience-manifest.py"
SPEC = importlib.util.spec_from_file_location("experience_manifest", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MANIFEST_SHA256 = "sha256:" + "e" * 64


def manifest(**overrides):
    digest = "sha256:" + "a" * 64
    value = {
        "kind": MODULE.MANIFEST_KIND,
        "variant": "yellowfin",
        "flavor": "gnome",
        "architecture": "x86_64",
        "platform": "linux/amd64",
        "hardware_scope": "qemu-kvm",
        "source_image_ref": f"ghcr.io/tuna-os/yellowfin@{digest}",
        "source_image_digest": digest,
        "base_image_digest": "sha256:" + "b" * 64,
        "overlay_digest": "sha256:" + "c" * 64,
        "iso_sha256": "sha256:" + "d" * 64,
        "installer_app_id": "org.bootcinstaller.Installer",
        "installer_revision": "1" * 40,
        "builder_revision": "2" * 40,
        "engine_revision": "3" * 40,
        "build_path": "browser",
        "browser": {"name": "chromium", "version": "141.0.0"},
        "resource_profile": {"cpus": 4, "memory_mib": 8192, "disk_gib": 32},
    }
    value.update(overrides)
    return value


def result(profile, **overrides):
    value = {
        "kind": MODULE.RESULT_KIND,
        "profile": profile,
        "network_disabled": True,
        "installer_source": "bundled",
        "install_method": "graphical",
        "generic_cli": False,
        "wizard_screens": MODULE.REQUIRED_SCREENS,
        "installed_boot": True,
        "desktop_contract": True,
        "source_image_digest": "sha256:" + "a" * 64,
        "iso_sha256": "sha256:" + "d" * 64,
        "manifest_sha256": MANIFEST_SHA256,
        "iso_detached": True,
        "owned_disk": True,
        "encrypted": profile == "encrypted",
        "duration_seconds": 123,
    }
    value.update(overrides)
    return value


def test_accepts_complete_manifest(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest()))
    MODULE.validate(MODULE.load(path), str(path))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("network_disabled", False, "network_disabled"),
        ("installer_source", "injected", "installer_source"),
        ("install_method", "fisherman-cli", "install_method"),
        ("generic_cli", True, "generic_cli"),
        ("wizard_screens", ["welcome", "done"], "wizard_screens"),
        ("installed_boot", False, "installed_boot"),
        ("desktop_contract", False, "desktop_contract"),
        ("iso_detached", False, "iso_detached"),
        ("owned_disk", False, "owned_disk"),
    ],
)
def test_rejects_non_strict_qualification_evidence(field, value, message):
    with pytest.raises(ValueError, match=message):
        MODULE.validate_result(result("plain", **{field: value}), "test")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("network_disabled", 1),
        ("generic_cli", 0),
        ("installed_boot", 1.0),
        ("desktop_contract", 1),
        ("iso_detached", 1),
        ("owned_disk", 1),
        ("encrypted", 0.0),
    ],
)
def test_rejects_numeric_values_for_strict_boolean_evidence(field, value):
    with pytest.raises(ValueError, match=field):
        MODULE.validate_result(result("plain", **{field: value}), "test")


def test_rejects_plain_result_claiming_encryption():
    with pytest.raises(ValueError, match="encrypted"):
        MODULE.validate_result(result("plain", encrypted=True), "test")


def test_rejects_encrypted_result_without_encryption():
    with pytest.raises(ValueError, match="encrypted"):
        MODULE.validate_result(result("encrypted", encrypted=False), "test")


def test_manifest_requires_immutable_source_reference():
    with pytest.raises(ValueError, match="source_image_ref"):
        MODULE.validate_manifest(
            manifest(source_image_ref="ghcr.io/tuna-os/yellowfin:gnome"), "test"
        )


@pytest.mark.parametrize(
    "field",
    ["source_image_digest", "base_image_digest", "overlay_digest", "iso_sha256"],
)
def test_manifest_requires_all_immutable_digests(field):
    with pytest.raises(ValueError, match=field):
        MODULE.validate_manifest(manifest(**{field: "latest"}), "test")

def test_manifest_rejects_unsupported_hardware_scope():
    with pytest.raises(ValueError, match="hardware_scope"):
        MODULE.validate_manifest(manifest(hardware_scope="whatever-ran"), "test")

def test_manifest_requires_matching_platform_and_architecture():
    with pytest.raises(ValueError, match="platform does not match architecture"):
        MODULE.validate_manifest(manifest(platform="linux/arm64"), "test")



@pytest.mark.parametrize(
    "field", ["installer_revision", "builder_revision", "engine_revision"]
)
def test_manifest_requires_full_revisions(field):
    with pytest.raises(ValueError, match=field):
        MODULE.validate_manifest(manifest(**{field: "main"}), "test")

def test_manifest_accepts_exact_ostree_installer_commit():
    MODULE.validate_manifest(manifest(installer_revision="4" * 64), "test")


def test_browser_build_requires_browser_identity():
    with pytest.raises(ValueError, match="browser builds require"):
        MODULE.validate_manifest(manifest(browser=None), "test")


def test_ci_build_forbids_fake_browser_identity():
    with pytest.raises(ValueError, match="CI builds must set browser to null"):
        MODULE.validate_manifest(manifest(build_path="ci"), "test")


def test_ci_build_accepts_null_browser():
    MODULE.validate_manifest(manifest(build_path="ci", browser=None), "test")


@pytest.mark.parametrize("field", ["cpus", "memory_mib", "disk_gib"])
def test_resource_profile_values_are_positive_integers(field):
    resources = manifest()["resource_profile"] | {field: 0}
    with pytest.raises(ValueError, match=field):
        MODULE.validate_manifest(manifest(resource_profile=resources), "test")


def test_build_receipt_requires_both_install_profiles():
    with pytest.raises(ValueError, match="missing: encrypted"):
        MODULE.build_receipt(manifest(), [result("plain")], MANIFEST_SHA256)


def test_build_receipt_rejects_installed_digest_mismatch():
    with pytest.raises(ValueError, match="installed source digest"):
        MODULE.build_receipt(
            manifest(),
            [
                result("plain"),
                result("encrypted", source_image_digest="sha256:" + "f" * 64),
            ],
            MANIFEST_SHA256,
        )


def test_build_receipt_rejects_iso_or_manifest_identity_mismatch():
    with pytest.raises(ValueError, match="ISO digest"):
        MODULE.build_receipt(
            manifest(),
            [result("plain", iso_sha256="sha256:" + "f" * 64), result("encrypted")],
            MANIFEST_SHA256,
        )
    with pytest.raises(ValueError, match="different manifest"):
        MODULE.build_receipt(
            manifest(),
            [result("plain", manifest_sha256="sha256:" + "f" * 64), result("encrypted")],
            MANIFEST_SHA256,
        )


def test_receipt_records_identity_inputs_context_resources_and_timings():
    receipt = MODULE.build_receipt(
        manifest(),
        [result("plain"), result("encrypted", duration_seconds=321)],
        MANIFEST_SHA256,
    )
    MODULE.validate_receipt(receipt, "receipt")
    assert receipt["qualified_manifest_sha256"] == MANIFEST_SHA256
    assert receipt["source_image_digest"] == "sha256:" + "a" * 64
    assert receipt["installer_revision"] == "1" * 40
    assert receipt["builder_revision"] == "2" * 40
    assert receipt["engine_revision"] == "3" * 40
    assert receipt["browser"] == {"name": "chromium", "version": "141.0.0"}
    assert receipt["resource_profile"]["memory_mib"] == 8192
    assert receipt["qualification"]["plain"]["network_disabled"] is True
    assert receipt["qualification"]["encrypted"]["encrypted"] is True
    assert receipt["timings"] == {
        "plain_seconds": 123,
        "encrypted_seconds": 321,
        "total_seconds": 444,
    }


def test_receipt_schema_cannot_carry_disk_or_iso_artifact_paths():
    receipt = MODULE.build_receipt(
        manifest(), [result("plain"), result("encrypted")], MANIFEST_SHA256
    )
    receipt["disk_path"] = "install-disk.qcow2"
    with pytest.raises(ValueError, match="unsupported fields: disk_path"):
        MODULE.validate_receipt(receipt, "receipt")


@pytest.mark.parametrize("field,value", [
    ("profile", "encrypted"),
    ("kind", "forged-kind"),
    ("duration_seconds", 1),
])
def test_receipt_nested_evidence_cannot_override_derived_fields(field, value):
    receipt = MODULE.build_receipt(
        manifest(), [result("plain"), result("encrypted")], MANIFEST_SHA256
    )
    receipt["qualification"]["plain"][field] = value
    with pytest.raises(ValueError, match=f"unsupported fields: {field}"):
        MODULE.validate_receipt(receipt, "receipt")


def test_compare_reports_parity_critical_mismatch_only():
    left = manifest()
    right = manifest(
        source_image_digest="sha256:" + "e" * 64,
        source_image_ref="ghcr.io/tuna-os/yellowfin@sha256:" + "e" * 64,
        build_path="ci",
        browser=None,
        builder_revision="4" * 40,
    )
    assert MODULE.compare(left, right) == [
        "source_image_ref",
        "source_image_digest",
    ]


def test_load_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid JSON"):
        MODULE.load(path)


def test_load_non_dict_json(tmp_path):
    path = tmp_path / "array.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="document must be a JSON object"):
        MODULE.load(path)


def test_main_writes_and_validates_receipt(tmp_path, monkeypatch, capsys):
    manifest_path = tmp_path / "manifest.json"
    plain_path = tmp_path / "plain.json"
    encrypted_path = tmp_path / "encrypted.json"
    receipt_path = tmp_path / "receipt.json"
    manifest_path.write_text(json.dumps(manifest()), encoding="utf-8")
    identity = MODULE.file_sha256(manifest_path)
    plain_path.write_text(
        json.dumps(result("plain", manifest_sha256=identity)), encoding="utf-8"
    )
    encrypted_path.write_text(
        json.dumps(result("encrypted", manifest_sha256=identity)), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            str(SCRIPT),
            str(manifest_path),
            "--result",
            str(plain_path),
            "--result",
            str(encrypted_path),
            "--write-receipt",
            str(receipt_path),
        ],
    )
    assert MODULE.main() == 0
    MODULE.validate_receipt(MODULE.load(receipt_path), str(receipt_path))
    assert "wrote strict qualification receipt" in capsys.readouterr().out


def test_main_compare_mismatch(tmp_path, monkeypatch, capsys):
    path1 = tmp_path / "m1.json"
    path2 = tmp_path / "m2.json"
    path1.write_text(json.dumps(manifest()), encoding="utf-8")
    path2.write_text(json.dumps(manifest(flavor="kde")), encoding="utf-8")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), str(path1), "--compare", str(path2)])
    assert MODULE.main() == 1
    assert "error: parity mismatch in: flavor" in capsys.readouterr().err

