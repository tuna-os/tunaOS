"""tunaOS#3378: reject published images with an empty zstd tar layer.

The published marlin:tuna amd64 manifest
sha256:32b048f76d1b951577ce95bd2ecfaa5896a013e9ec0a34e76379dcd762bd363e
contained a 25-byte top layer whose payload was exactly 1024 zero bytes. bootc
1.16.10 rejected that otherwise-valid empty tar as truncated, so the image
could not install itself.

Falsification: behavioural — the published descriptor shape is passed through
the same manifest gate used after each push; deleting or weakening the gate
makes the broken-manifest test stop failing closed.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts" / "check-oci-layers.py"
EMPTY_LAYER = {
    "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
    "digest": "sha256:9cb6e55d671da388441c798406eb605d59bbb743708e52c051de21ce13dbb3c4",
    "size": 25,
}


def _check(*layers: dict) -> subprocess.CompletedProcess[str]:
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "layers": list(layers),
    }
    return subprocess.run(
        [str(CHECK)],
        input=json.dumps(manifest),
        text=True,
        capture_output=True,
        check=False,
    )


def test_the_published_empty_layer_fails_closed():
    healthy = {
        "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
        "digest": "sha256:healthy",
        "size": 80,
    }
    result = _check(healthy, EMPTY_LAYER)

    assert result.returncode == 1
    assert "layer 1" in result.stderr
    assert EMPTY_LAYER["digest"] in result.stderr
    assert "25-byte zstd tar layer" in result.stderr


def test_a_zstd_layer_large_enough_to_contain_a_tar_entry_passes():
    result = _check(
        {
            "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
            "digest": "sha256:nonempty",
            "size": 80,
        }
    )

    assert result.returncode == 0
    assert "none empty" in result.stdout


def test_the_push_gate_inspects_the_digest_forwarded_to_promotion(tmp_path: Path):
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-build-image.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["build_push"]["steps"]
    gate = next(step for step in steps if step.get("name") == "Verify pushed layer metadata")

    tools = tmp_path / "tools"
    tools.mkdir()
    record = tmp_path / "inspected-ref"
    sudo = tools / "sudo"
    sudo.write_text("#!/usr/bin/env bash\nexec \"$@\"\n", encoding="utf-8")
    sudo.chmod(0o755)
    skopeo = tools / "skopeo"
    skopeo.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s' \"$3\" > \"$INSPECTED_REF\"\n"
        "cat <<'EOF'\n"
        '{"schemaVersion":2,"layers":[{"mediaType":"application/vnd.oci.image.layer.v1.tar+zstd","digest":"sha256:healthy","size":80}]}\n'
        "EOF\n",
        encoding="utf-8",
    )
    skopeo.chmod(0o755)

    digest = "sha256:" + "a" * 64
    env = os.environ | {
        "PATH": f"{tools}:{os.environ['PATH']}",
        "IMAGE_REGISTRY": "ghcr.io",
        "IMAGE_NAME": "tuna-os/marlin",
        "DEFAULT_TAG": "tuna",
        "SAFE_PLATFORM": "linux-amd64",
        "DIGEST": digest,
        "INSPECTED_REF": str(record),
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", gate["run"]],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8") == (
        f"docker://ghcr.io/tuna-os/marlin@{digest}"
    )
