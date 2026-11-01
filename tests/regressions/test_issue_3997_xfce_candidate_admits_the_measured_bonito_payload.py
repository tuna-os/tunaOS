"""tunaOS#3997: the XFCE candidate rejected the real bonito:xfce source payload.

Run 40546860986 (bonito xfce linux/amd64, candidate_xfce=true) stopped in recipe
``iso`` before export with ``{"kind": "source-payload-estimate", "bytes":
6478177651, "limit_bytes": 4294967296}``. ``skopeo copy --preserve-digests``
from containers-storage keeps uncompressed layers, and the published amd64
manifest ``728db807`` is 6480981504 bytes uncompressed across 65 layers (2.55
GiB zstd). The 4 GiB ceiling was an unmeasured guess. These tests drive the
real ``--source-budget`` command and payload check at the real ceiling, and
require the producer disk floor to hold three payload copies.

Falsification: behavioural -- on the 4 GiB tree the measured 6478177651-byte
manifest and the exact-ceiling manifest exit non-zero, so both acceptance
cases fail; a ceiling raised without BUILD_DISK lets the under-floor
preflight pass and fails the disk test.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ADAPTER = ROOT / "live-iso/common/src/xfce-media-input.py"
GIB = 1024**3
MEASURED_RUN_40546860986 = 6478177651
sys.path.insert(0, str(ROOT / "scripts"))
from lib.xfce_launch import preflight  # noqa: E402


def adapter():
    spec = importlib.util.spec_from_file_location("issue_3997_adapter", ADAPTER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest(tmp_path, total, layers=65):
    """Write a manifest whose descriptor sizes plus its own bytes equal total."""
    config = 32367
    sizes = [(total - config) // layers] * layers
    while True:
        raw = json.dumps(dict(schemaVersion=2, config=dict(size=config),
                              layers=[dict(size=size) for size in sizes])).encode()
        missing = total - config - sum(sizes) - len(raw)
        if missing == 0:
            break
        sizes[-1] += missing
    path = tmp_path / "xfce-source-manifest.json"
    path.write_bytes(raw)
    return path, "sha256:" + hashlib.sha256(raw).hexdigest()


def source_budget(path, digest):
    return subprocess.run([sys.executable, str(ADAPTER), "--source-budget", str(path), digest],
                          capture_output=True, text=True, check=False)


@pytest.mark.parametrize("total,admitted", [
    (MEASURED_RUN_40546860986, True),
    (8 * GIB, True),
    (8 * GIB + 1, False),
    (2 * MEASURED_RUN_40546860986, False),
])
def test_source_budget_boundary(tmp_path, total, admitted):
    path, digest = manifest(tmp_path, total)
    result = source_budget(path, digest)
    report = json.loads(result.stdout)
    assert report == dict(kind="source-payload-estimate", bytes=total,
                          limit_bytes=8 * GIB, within_budget=admitted)
    if admitted:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0
        assert "source payload exceeds candidate budget" in result.stderr


def test_measured_manifest_with_wrong_digest_is_still_refused(tmp_path):
    path, digest = manifest(tmp_path, MEASURED_RUN_40546860986)
    result = source_budget(path, "sha256:" + "0" * 64)
    assert result.returncode != 0 and "source manifest digest mismatch" in result.stderr
    assert source_budget(path, digest).returncode == 0


@pytest.mark.parametrize("extra,admitted", [(0, True), (1, False)])
def test_embedded_payload_boundary(tmp_path, extra, admitted):
    module = adapter()
    layout = tmp_path / "xfce-candidate-oci"
    (layout / "blobs/sha256").mkdir(parents=True)
    with (layout / "blobs/sha256/layer").open("wb") as blob:
        blob.truncate(8 * GIB + extra)
    if admitted:
        assert module.check_budget(layout, "payload")["bytes"] == 8 * GIB
    else:
        with pytest.raises(ValueError, match="size budget exceeded"):
            module.check_budget(layout, "payload")


def test_build_disk_floor_holds_three_payload_copies(tmp_path):
    module = adapter()
    floor = 3 * module.PAYLOAD_LIMIT + 2 * module.ISO_LIMIT + 8 * GIB
    values = dict(which=lambda _: "/pinned/yq", memory=12 * GIB, cpus=4)
    preflight(tmp_path, "build", free=floor, **values)
    with pytest.raises(ValueError, match="resources insufficient"):
        preflight(tmp_path, "build", free=floor - 1, **values)
