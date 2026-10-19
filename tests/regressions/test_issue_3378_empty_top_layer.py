"""tunaOS#3378: marlin:tuna shipped with a 25-byte empty zstd top layer.

The published amd64 image at manifest prefix ``32b048f7`` was pullable and
runnable, but bootc installation failed with ``Truncated tar archive``. These
tests serve real OCI manifests and blobs to the production validator, covering
the empty incident shape and valid small layers. They also execute the final
stage's provenance write and require the original published flavor identity.

Falsification: behavioural — an empty zstd tar must be rejected, valid small
tars (including a highly compressible many-entry archive) must be accepted,
and the real final-stage command must create parseable, correctly identified
provenance content.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import gzip
import hashlib
import http.server
import io
import json
import os
import socketserver
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path

import pytest
import yaml





ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts" / "check-bootc-installable-layers"
FINAL_CONTAINERFILE = ROOT / "Containerfile.final"


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

ZSTD_DECOMPRESSOR = r"""#!/usr/bin/env python3
import ctypes
import ctypes.util
import sys

library = ctypes.CDLL(ctypes.util.find_library("zstd"))
library.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
library.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
library.ZSTD_decompress.argtypes = [
    ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t
]
library.ZSTD_decompress.restype = ctypes.c_size_t
library.ZSTD_isError.argtypes = [ctypes.c_size_t]
library.ZSTD_isError.restype = ctypes.c_uint
source = open(sys.argv[-1], "rb").read()
size = library.ZSTD_getFrameContentSize(source, len(source))
if size >= (1 << 64) - 2:
    raise SystemExit("zstd frame has no bounded content size")
destination = ctypes.create_string_buffer(size)
written = library.ZSTD_decompress(destination, size, source, len(source))
if library.ZSTD_isError(written):
    raise SystemExit("zstd decompression failed")
sys.stdout.buffer.write(destination.raw[:written])
"""


def tar_archive(entries: list[str], *, padding: int = 0) -> bytes:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        for name in entries:
            info = tarfile.TarInfo(name)
            info.size = 0
            stream.addfile(info)
    return archive.getvalue() + b"\0" * padding


def zstd_tar(entries: list[str], *, padding: int = 0) -> bytes:
    source = tar_archive(entries, padding=padding)
    destination = ctypes.create_string_buffer(ZSTD.ZSTD_compressBound(len(source)))
    size = ZSTD.ZSTD_compress(
        destination, len(destination), source, len(source), 3
    )
    assert not ZSTD.ZSTD_isError(size)
    return destination.raw[:size]


def gzip_tar(entries: list[str], *, padding: int = 0) -> bytes:
    return gzip.compress(tar_archive(entries, padding=padding))


def run_validator(
    blob: bytes,
    *,
    immutable_reference: bool = False,
    media_type: str = "application/vnd.oci.image.layer.v1.tar+zstd",
) -> subprocess.CompletedProcess[str]:
    digest = "sha256:" + hashlib.sha256(blob).hexdigest()
    manifest = json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "layers": [{
            "digest": digest,
            "size": len(blob),
            "mediaType": media_type,
        }],
    }).encode()
    reference = (
        "sha256:" + hashlib.sha256(manifest).hexdigest()
        if immutable_reference
        else "image"
    )

    class Registry(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path == f"/v2/test/manifests/{reference}":
                payload, content_type = manifest, "application/json"
            elif self.path == f"/v2/test/blobs/{digest}":
                payload, content_type = blob, "application/octet-stream"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            pass

    with socketserver.TCPServer(("127.0.0.1", 0), Registry) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                zstd = Path(directory) / "zstd"
                zstd.write_text(ZSTD_DECOMPRESSOR, encoding="utf-8")
                zstd.chmod(0o755)
                env = os.environ.copy()
                env["PATH"] = f"{directory}:{env['PATH']}"
                return subprocess.run(
                    [str(VALIDATOR), f"127.0.0.1:{server.server_address[1]}/test@{reference}"],
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
        finally:
            server.shutdown()
            thread.join()


def test_empty_zstd_layer_is_rejected():
    result = run_validator(zstd_tar([]))
    assert result.returncode != 0
    assert "holds no tar entries" in result.stderr


def test_nonempty_small_zstd_layer_is_accepted():
    result = run_validator(zstd_tar(["usr/share/tunaos/build-info.json"]))
    assert result.returncode == 0, result.stderr
    assert "all small layers importable" in result.stdout


def test_nonempty_layer_is_checked_through_an_immutable_manifest_reference():
    result = run_validator(
        zstd_tar(["usr/share/tunaos/build-info.json"]),
        immutable_reference=True,
    )
    assert result.returncode == 0, result.stderr


def test_many_entry_small_zstd_layer_is_fully_drained():
    blob = zstd_tar([f"usr/share/test/{number:03d}" for number in range(300)])
    assert len(blob) < 4096, "fixture must exercise the small-layer validation path"
    result = run_validator(blob)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("compress", "media_type"),
    [
        (zstd_tar, "application/vnd.oci.image.layer.v1.tar+zstd"),
        (gzip_tar, "application/vnd.oci.image.layer.v1.tar+gzip"),
    ],
)
def test_padded_small_compressed_layer_is_fully_drained(compress, media_type):
    blob = compress(["usr/share/test/entry"], padding=1024 * 1024)
    assert len(blob) < 4096, "fixture must exercise the small-layer validation path"
    result = run_validator(blob, media_type=media_type)
    assert result.returncode == 0, result.stderr



@pytest.mark.parametrize(
    ("reference", "repository", "tag"),
    [
        ("ubuntu:latest", "library/ubuntu", "latest"),
        ("tuna-os/marlin:tuna", "tuna-os/marlin", "tuna"),
        ("docker.io/ubuntu:latest", "library/ubuntu", "latest"),
    ],
)
def test_docker_hub_reference_resolves_registry_and_namespace(
    tmp_path, reference, repository, tag
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    urls = tmp_path / "urls"
    curl = fake_bin / "curl"
    curl.write_text(
        "#!/bin/sh\n"
        "url=\n"
        "for arg in \"$@\"; do case \"$arg\" in http://*|https://*) url=$arg;; esac; done\n"
        "printf '%s\\n' \"$url\" >> \"$URL_LOG\"\n"
        "case \"$url\" in\n"
        "  *auth.docker.io*) printf '{\"token\":\"test-token\"}\\n' ;;\n"
        "  */manifests/*) printf '%s\\n' "
        "'{\"schemaVersion\":2,\"mediaType\":\"application/vnd.oci.image.manifest.v1+json\","
        "\"layers\":[{\"digest\":\"sha256:test\",\"size\":4096,"
        "\"mediaType\":\"application/vnd.oci.image.layer.v1.tar+gzip\"}]}' ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    curl.chmod(0o755)
    proc = subprocess.run(
        [str(VALIDATOR), reference],
        cwd=ROOT,
        env=os.environ | {
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "URL_LOG": str(urls),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    requests = urls.read_text()
    assert f"scope=repository:{repository}:pull" in requests
    assert (
        f"https://registry-1.docker.io/v2/{repository}/manifests/{tag}"
        in requests
    )

def test_final_stage_writes_original_published_flavor(tmp_path):
    source = FINAL_CONTAINERFILE.read_text(encoding="utf-8")
    run_command = source[source.index("RUN mkdir -p ") :].removeprefix("RUN ")
    output_root = tmp_path / "usr/share/tunaos"
    run_command = run_command.replace("/usr/share/tunaos", str(output_root))
    env = os.environ.copy()
    env.update({
        "IMAGE_NAME": "yellowfin",
        "DESKTOP_FLAVOR": "base-no-de",
        "TUNAOS_IMAGE_FLAVOR": "gnome-nvidia-hwe",
        "IMAGE_VENDOR": "tuna-os",
        "SHA_HEAD_SHORT": "deadbeef",
    })

    subprocess.run(["bash", "-eu", "-c", run_command], env=env, check=True)
    provenance = json.loads((output_root / "build-info.json").read_text())
    assert provenance == {
        "image": "yellowfin",
        "flavor": "gnome-nvidia-hwe",
        "vendor": "tuna-os",
        "revision": "deadbeef",
    }

def test_workflow_layer_gate_propagates_an_empty_layer_failure(tmp_path):
    """The publish job must fail on the immutable pushed manifest digest."""
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/reusable-build-image.yml").read_text()
    )
    step = next(
        step
        for job in workflow["jobs"].values()
        for step in job.get("steps", [])
        if step.get("name") == "Verify bootc-installable layers"
    )
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    gate = scripts / "check-bootc-installable-layers"
    gate.write_text(
        "#!/bin/sh\n"
        'printf "%s\\n" "$*" > "$GATE_ARGS"\n'
        'printf "%s\\n" "holds no tar entries" >&2\n'
        "exit 1\n",
        encoding="utf-8",
    )
    gate.chmod(0o755)
    zstd = tmp_path / "zstd"
    zstd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    zstd.chmod(0o755)
    digest = "sha256:" + "b" * 64
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", step["run"]],
        cwd=tmp_path,
        env=os.environ
        | {
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "REMOTE_IMAGE_DIGEST": digest,
            "IMAGE_REGISTRY": "ghcr.io/tuna-os",
            "IMAGE_NAME": "marlin",
            "GATE_ARGS": str(tmp_path / "gate-args"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert (tmp_path / "gate-args").read_text().strip() == (
        f"ghcr.io/tuna-os/marlin@{digest}"
    )
