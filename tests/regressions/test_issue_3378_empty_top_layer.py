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


def zstd_tar(entries: list[str]) -> bytes:
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        for name in entries:
            info = tarfile.TarInfo(name)
            info.size = 0
            stream.addfile(info)
    source = archive.getvalue()
    destination = ctypes.create_string_buffer(ZSTD.ZSTD_compressBound(len(source)))
    size = ZSTD.ZSTD_compress(
        destination, len(destination), source, len(source), 3
    )
    assert not ZSTD.ZSTD_isError(size)
    return destination.raw[:size]


def run_validator(blob: bytes) -> subprocess.CompletedProcess[str]:
    digest = "sha256:" + hashlib.sha256(blob).hexdigest()
    manifest = json.dumps({
        "schemaVersion": 2,
        "mediaType": "application/vnd.oci.image.manifest.v1+json",
        "layers": [{
            "digest": digest,
            "size": len(blob),
            "mediaType": "application/vnd.oci.image.layer.v1.tar+zstd",
        }],
    }).encode()

    class Registry(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
            if self.path == "/v2/test/manifests/image":
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
                    [str(VALIDATOR), f"127.0.0.1:{server.server_address[1]}/test:image"],
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


def test_many_entry_small_zstd_layer_is_fully_drained():
    blob = zstd_tar([f"usr/share/test/{number:03d}" for number in range(300)])
    assert len(blob) < 4096, "fixture must exercise the small-layer validation path"
    result = run_validator(blob)
    assert result.returncode == 0, result.stderr


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
