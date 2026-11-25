"""The published installer image tiles the medium with no gap (tunaOS#4907).

Falsification: a chunk above the 256 MiB contract cap, a gap or overlap in
the table, a wrong whole-image sha256, or an unreadable layer fails here,
before CI signs the manifest. These checks mirror `medium.Config.Validate`
in tacklebox (tuna-os/tacklebox#511), the reference consumer.
"""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("medium_chunk_publish", ROOT / "installer-medium/publish/chunk-publish.py")
publish = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publish)

SCRIPT = ROOT / "installer-medium/publish/chunk-publish.py"


def test_plan_tiles_without_gap_or_overlap():
    assert publish.plan(3 * (1 << 20) + 7, 1 << 20) == [
        (0, 1 << 20), (1 << 20, 1 << 20), (2 << 20, 1 << 20), (3 << 20, 7)]
    with pytest.raises(ValueError):
        publish.plan(10, (256 << 20) + 1)


def test_chunk_media_types_match_the_contract():
    assert publish.CHUNK_MEDIA_TYPE == "application/vnd.tunaos.installer.chunk.v1+zstd"
    assert publish.CONFIG_MEDIA_TYPE == "application/vnd.tunaos.installer.config.v1+json"
    assert publish.SCHEMA_VERSION == 1
    assert publish.MAX_CHUNK_BYTES == 256 << 20


def run(*args):
    return subprocess.run(["python3", "-I", str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_dry_run_names_chunks_and_annotations(tmp_path):
    iso = tmp_path / "medium.iso"
    iso.write_bytes(b"\0" * 3000000)
    result = run("albacore:gnome", str(iso), str(tmp_path / "layout"), "--dry-run")
    assert result.returncode == 0, result.stderr
    assert "chunks: 1 x up to 134217728 bytes" in result.stdout
    assert "cell=albacore:gnome" in result.stdout


def test_layout_round_trips_offline(tmp_path):
    iso = tmp_path / "medium.iso"
    raw = bytes(range(256)) * 8000
    iso.write_bytes(raw)
    layout = tmp_path / "layout"
    result = run("albacore:gnome", str(iso), str(layout))
    assert result.returncode == 0, result.stderr
    manifest_digest = result.stdout.strip()
    assert manifest_digest.startswith("sha256:")
    blobs = layout / "blobs" / "sha256"
    manifest = json.loads((blobs / manifest_digest.removeprefix("sha256:")).read_text())
    assert manifest["config"]["mediaType"] == publish.CONFIG_MEDIA_TYPE
    config = json.loads((blobs / manifest["config"]["digest"].removeprefix("sha256:")).read_text())
    assert config["schemaVersion"] == 1
    assert config["totalSize"] == len(raw)
    assert config["sha256"] == "sha256:" + hashlib.sha256(raw).hexdigest()
    assert config["bootModes"] == ["uefi", "usb", "cdrom"]
    assert len(manifest["layers"]) == len(config["chunks"])
    offset = 0
    for i, chunk in enumerate(config["chunks"]):
        layer = manifest["layers"][i]
        assert layer["mediaType"] == publish.CHUNK_MEDIA_TYPE
        assert layer["digest"] != ""
        assert chunk["offset"] == offset
        assert chunk["length"] <= publish.MAX_CHUNK_BYTES
        blob = blobs / layer["digest"].removeprefix("sha256:")
        check = subprocess.run(["zstd", "-d", "-c", str(blob)], capture_output=True, check=True).stdout
        assert check == raw[offset:offset + chunk["length"]]
        assert chunk["sha256"] == "sha256:" + hashlib.sha256(check).hexdigest()
        offset += chunk["length"]
    assert offset == len(raw)
    annotations = manifest["annotations"]
    assert annotations["org.tunaos.installer.cell"] == "albacore:gnome"
    assert annotations["org.tunaos.installer.base-image"].startswith("ghcr.io/")
    assert len(annotations["org.tunaos.installer.systemd-ref"]) == 40


def test_the_manifest_names_the_qualification_receipt(tmp_path):
    """The tacklebox verifier compares this annotation with the attested digest (tacklebox#513)."""
    iso, layout, receipt = tmp_path / "m.iso", tmp_path / "layout", tmp_path / "receipt.json"
    iso.write_bytes(b"x" * 4096)
    receipt.write_text('{"cell": "albacore:gnome"}\n')
    done = run("albacore:gnome", str(iso), str(layout), "--receipt", str(receipt))
    assert done.returncode == 0, done.stderr
    manifest = json.loads(
        (layout / "blobs/sha256" / done.stdout.strip().removeprefix("sha256:")).read_text()
    )
    want = "sha256:" + hashlib.sha256(receipt.read_bytes()).hexdigest()
    assert manifest["annotations"]["org.tunaos.installer.receipt-sha256"] == want


def test_the_workflow_attests_the_receipt_that_the_manifest_names():
    text = (ROOT / ".github/workflows/image-installer.yml").read_text()
    assert '"$WORK/layout" --receipt "$WORK/qualification.json"' in text
    assert "--type https://tunaos.dev/installer/receipt/v1" in text
    assert '"receiptDigest": "sha256:"' in text
    # A lane with a stage that did not pass exits non-zero and is not published.
    assert 'assert lane["code"] == 0' in text
