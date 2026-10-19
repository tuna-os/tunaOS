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

import ctypes
import ctypes.util
import json
import os
import struct
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECK = ROOT / "scripts" / "check-oci-layers.py"
EMPTY_LAYER = {
    "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
    "digest": "sha256:9cb6e55d671da388441c798406eb605d59bbb743708e52c051de21ce13dbb3c4",
    "size": 25,
}

ZSTD = ctypes.CDLL(ctypes.util.find_library("zstd"))
ZSTD.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
ZSTD.ZSTD_compressBound.restype = ctypes.c_size_t
ZSTD.ZSTD_compress.argtypes = [
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_void_p,
    ctypes.c_size_t,
    ctypes.c_int,
]
ZSTD.ZSTD_compress.restype = ctypes.c_size_t
ZSTD.ZSTD_isError.argtypes = [ctypes.c_size_t]
ZSTD.ZSTD_isError.restype = ctypes.c_uint


def _compress_zstd(payload: bytes) -> bytes:
    output = ctypes.create_string_buffer(ZSTD.ZSTD_compressBound(len(payload)))
    size = ZSTD.ZSTD_compress(output, len(output), payload, len(payload), 3)
    assert not ZSTD.ZSTD_isError(size)
    return output.raw[:size]


def _empty_tar_blob() -> bytes:
    return _compress_zstd(bytes(1024))


def _tiny_nonempty_tar_blob() -> bytes:
    header = bytearray(512)
    header[0] = ord("a")
    header[156] = ord("0")
    header[148:156] = b"        "
    checksum = sum(header)
    header[148:156] = f"{checksum:06o}\0 ".encode()
    return _compress_zstd(bytes(header) + bytes(1024))


def _skippable_frame(payload: bytes = b"x") -> bytes:
    return struct.pack("<II", 0x184D2A50, len(payload)) + payload


def _check(*layers: dict) -> subprocess.CompletedProcess[str]:
    manifest = {
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "layers": list(layers),
    }
    with tempfile.TemporaryDirectory() as directory:
        blob_dir = Path(directory)
        for layer in layers:
            if layer.get("size", 50) < 50:
                name = layer["digest"].replace(":", "_")
                (blob_dir / name).write_bytes(_empty_tar_blob())
        return subprocess.run(
            [str(CHECK), "--blob-dir", str(blob_dir)],
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


def _run_push_gate(
    tmp_path: Path, layers: list[dict], blobs: dict[str, bytes] | None = None
) -> tuple[subprocess.CompletedProcess[str], Path, str]:
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
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps({"schemaVersion": 2, "layers": layers}), encoding="utf-8"
    )
    blob_source = tmp_path / "blobs"
    blob_source.mkdir()
    for digest, payload in (blobs or {}).items():
        (blob_source / digest.replace(":", "_")).write_bytes(payload)
    sudo = tools / "sudo"
    sudo.write_text("#!/usr/bin/env bash\nexec \"$@\"\n", encoding="utf-8")
    sudo.chmod(0o755)
    skopeo = tools / "skopeo"
    skopeo.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s' \"$3\" > \"$INSPECTED_REF\"\n"
        "cat \"$MANIFEST\"\n",
        encoding="utf-8",
    )
    skopeo.chmod(0o755)
    curl = tools / "curl"
    curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "destination=''\n"
        "url=''\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  case \"$1\" in\n"
        "    -o) destination=$2; shift 2 ;;\n"
        "    -H|-A) shift 2 ;;\n"
        "    -*) shift ;;\n"
        "    *) url=$1; shift ;;\n"
        "  esac\n"
        "done\n"
        "if [[ -z \"$destination\" ]]; then\n"
        "  [[ \"$url\" == \"$EXPECTED_TOKEN_URL\" ]] || exit 42\n"
        "  printf '{\"token\":\"fixture-token\"}\\n'\n"
        "else\n"
        "  [[ \"$url\" == \"$EXPECTED_BLOB_PREFIX\"* ]] || exit 43\n"
        "  digest=${url##*/}\n"
        "  cp \"$BLOB_SOURCE/${digest/:/_}\" \"$destination\"\n"
        "fi\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)

    digest = "sha256:" + "a" * 64
    env = os.environ | {
        "PATH": f"{tools}:{os.environ['PATH']}",
        "IMAGE_REGISTRY": "ghcr.io/tuna-os",
        "IMAGE_NAME": "marlin",
        "DEFAULT_TAG": "tuna",
        "SAFE_PLATFORM": "linux-amd64",
        "DIGEST": digest,
        "INSPECTED_REF": str(record),
        "MANIFEST": str(manifest),
        "BLOB_SOURCE": str(blob_source),
        "EXPECTED_TOKEN_URL": (
            "https://ghcr.io/token?service=ghcr.io"
            "&scope=repository:tuna-os/marlin:pull"
        ),
        "EXPECTED_BLOB_PREFIX": "https://ghcr.io/v2/tuna-os/marlin/blobs/",
    }
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", gate["run"]],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, record, digest


def test_the_push_gate_inspects_the_digest_forwarded_to_promotion(tmp_path: Path):
    healthy = {
        "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
        "digest": "sha256:healthy",
        "size": 80,
    }
    result, record, digest = _run_push_gate(tmp_path, [healthy])

    assert result.returncode == 0, result.stderr
    assert record.read_text(encoding="utf-8") == (
        f"docker://ghcr.io/tuna-os/marlin@{digest}"
    )


def test_the_push_gate_blocks_the_incident_manifest(tmp_path: Path):
    result, _, _ = _run_push_gate(
        tmp_path,
        [EMPTY_LAYER],
        {EMPTY_LAYER["digest"]: _empty_tar_blob()},
    )

    assert result.returncode == 1
    assert EMPTY_LAYER["digest"] in result.stderr
    assert "25-byte zstd tar layer" in result.stderr


def test_a_valid_tiny_zstd_tar_is_inspected_and_accepted(tmp_path: Path):
    blob = _tiny_nonempty_tar_blob()
    assert len(blob) < 50
    digest = "sha256:tiny-valid"
    layer = {
        "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
        "digest": digest,
        "size": len(blob),
    }

    result, _, _ = _run_push_gate(tmp_path, [layer], {digest: blob})

    assert result.returncode == 0, result.stderr


def test_a_skippable_frame_before_a_tiny_zstd_tar_is_accepted(tmp_path: Path):
    blob = _skippable_frame() + _tiny_nonempty_tar_blob()
    assert len(blob) < 50
    digest = "sha256:skippable-prefix"
    layer = {
        "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
        "digest": digest,
        "size": len(blob),
    }

    result, _, _ = _run_push_gate(tmp_path, [layer], {digest: blob})

    assert result.returncode == 0, result.stderr
