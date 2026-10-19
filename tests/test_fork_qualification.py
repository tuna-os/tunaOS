"""Qualification authority must not become a production-build bypass."""
import importlib.util
import json
from pathlib import Path

import pytest

from tests.test_fork_identity import IDENTITY, ROOT, materialize, staged  # noqa: F401

SPEC = importlib.util.spec_from_file_location("qualify", ROOT / "scripts/qualify-fork-image.py")
QUALIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUALIFY)


def canary(staged, tmp_path):
    import yaml
    config = yaml.safe_load(staged.read_text())
    config["image"] = {"registry": "localhost", "namespace": "fork-qualification"}
    staged.write_text(yaml.safe_dump(config))
    manifest, root, *_ = materialize(staged, tmp_path)
    return manifest, root


def test_default_has_no_qualification(staged, tmp_path):
    manifest, _, *_ = materialize(staged, tmp_path)
    assert IDENTITY.qualification(manifest) is False


def test_exact_receipts_only(staged, tmp_path):
    manifest, _ = canary(staged, tmp_path)
    QUALIFY.authorize(tmp_path)
    assert IDENTITY.qualification(manifest)
    base = manifest.parent / "fork-config.json"
    content = json.loads(base.read_text())
    content["intent"]["branding"]["homepage"] = "https://example.net/changed"
    base.write_text(json.dumps(content))
    with pytest.raises(ValueError, match="receipt"):
        IDENTITY.qualification(manifest)


def test_remote_namespace_rejected(staged, tmp_path):
    manifest, _, *_ = materialize(staged, tmp_path)
    with pytest.raises(ValueError, match="namespace"):
        QUALIFY.authorize(tmp_path)


def test_container_required(staged, tmp_path, monkeypatch):
    manifest, _ = canary(staged, tmp_path)
    QUALIFY.authorize(tmp_path)
    original = Path.is_file
    monkeypatch.setattr(Path, "is_file", lambda p: False if str(p) == "/run/.containerenv" else original(p))
    with pytest.raises(ValueError, match="Podman"):
        IDENTITY.qualification(manifest, container=True)
    with pytest.raises(ValueError, match="Podman"):
        IDENTITY.apply_boot(manifest, Path("/"))
    with pytest.raises(ValueError, match="Podman"):
        IDENTITY.apply(manifest, Path("/"), check=True)


def test_changed_cell_rejected(staged, tmp_path):
    manifest, _ = canary(staged, tmp_path)
    for path in (manifest, manifest.parent / "fork-config.json"):
        data = json.loads(path.read_text())
        data["platform"] = "linux/arm64"
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="amd64"):
        QUALIFY.authorize(tmp_path)


def test_build_entry_rejects_empty_or_remote_environment(staged, tmp_path):
    manifest, _ = canary(staged, tmp_path)
    QUALIFY.authorize(tmp_path)
    with pytest.raises(ValueError, match="environment"):
        QUALIFY.validate_entry(tmp_path, {})


def test_duplicate_authority_keys_rejected(staged, tmp_path):
    manifest, _ = canary(staged, tmp_path)
    QUALIFY.authorize(tmp_path)
    path = manifest.parent / "fork-qualification.json"
    path.write_text('{"schema_version":1,"schema_version":1}')
    with pytest.raises(ValueError, match="duplicate"):
        IDENTITY.qualification(manifest)


def test_workflow_nonpublishing_and_bounded():
    text = "\n".join(line for line in (ROOT / ".github/workflows/fork-image-qualification.yml").read_text().splitlines() if not line.lstrip().startswith("#"))
    for forbidden in ("secrets.", "write", "podman push", "rclone", "pull_request_target"):
        assert forbidden not in text.replace("registry writes", "registry mutations")
    assert "timeout-minutes: 180" in text
    assert "for variant in yellowfin grouper" in text


def test_real_canary_prepares_before_native_build(tmp_path, monkeypatch):
    import subprocess
    import sys
    original = subprocess.run
    output = tmp_path / "qualification"

    class BuildReached(Exception):
        pass

    def intercept(command, **kwargs):
        if command == ["bash", "scripts/build-image-inner.sh"]:
            QUALIFY.validate_entry(kwargs["cwd"], kwargs["env"])
            raise BuildReached()
        return original(command, **kwargs)

    monkeypatch.setattr(subprocess, "run", intercept)
    monkeypatch.setattr(sys, "argv", ["qualify", "--variant", "yellowfin", "--output", str(output)])
    with pytest.raises(BuildReached):
        QUALIFY.main()
    report = json.loads((output / "qualification.json").read_text())
    assert report["build"] == "failed"
    assert report["boot"] == "not-run"
    assert report["login"] == "not-run"
