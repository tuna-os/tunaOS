#!/usr/bin/env python3
"""Reject OCI manifests containing zstd layers whose tar stream is empty.

Small descriptors are only a prefilter. Their blobs are decompressed and
parsed because compressed size alone cannot distinguish an empty tar from a
valid highly-compressible tar entry.

Read one platform manifest from stdin or a named file. OCI indexes must be
resolved by the caller so diagnostics identify the failing platform artifact.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import json
import sys
import tarfile
from pathlib import Path

# Only unusually small layers need the extra registry read. The tunaOS#3378
# incident was 25 bytes; this bound keeps the gate cheap without making size
# itself the verdict.
INSPECT_ZSTD_LAYER_BYTES = 50


def suspicious_zstd_layers(manifest: dict) -> list[tuple[int, str, int]]:
    """Return (index, digest, size) for layers requiring content inspection."""
    layers = manifest.get("layers")
    if not isinstance(layers, list):
        raise ValueError("input is not a platform image manifest with a layers array")

    suspicious = []
    for index, layer in enumerate(layers):
        media_type = layer.get("mediaType", "")
        size = layer.get("size")
        if (
            "tar+zstd" in media_type
            and isinstance(size, int)
            and size < INSPECT_ZSTD_LAYER_BYTES
        ):
            suspicious.append((index, layer.get("digest", "<missing digest>"), size))
    return suspicious


class _ZstdInput(ctypes.Structure):
    _fields_ = [
        ("src", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


class _ZstdOutput(ctypes.Structure):
    _fields_ = [
        ("dst", ctypes.c_void_p),
        ("size", ctypes.c_size_t),
        ("pos", ctypes.c_size_t),
    ]


def _zstd_prefix(blob: bytes, length: int) -> bytes:
    library_name = ctypes.util.find_library("zstd")
    if not library_name:
        raise ValueError("libzstd is unavailable")
    library = ctypes.CDLL(library_name)
    library.ZSTD_createDStream.restype = ctypes.c_void_p
    library.ZSTD_initDStream.argtypes = [ctypes.c_void_p]
    library.ZSTD_initDStream.restype = ctypes.c_size_t
    library.ZSTD_decompressStream.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ZstdOutput),
        ctypes.POINTER(_ZstdInput),
    ]
    library.ZSTD_decompressStream.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    library.ZSTD_getErrorName.argtypes = [ctypes.c_size_t]
    library.ZSTD_getErrorName.restype = ctypes.c_char_p
    library.ZSTD_freeDStream.argtypes = [ctypes.c_void_p]

    stream = library.ZSTD_createDStream()
    if not stream:
        raise ValueError("cannot create zstd decompressor")
    source = ctypes.create_string_buffer(blob)
    input_buffer = _ZstdInput(ctypes.addressof(source), len(blob), 0)
    output = bytearray()
    try:
        status = library.ZSTD_initDStream(stream)
        if library.ZSTD_isError(status):
            raise ValueError(library.ZSTD_getErrorName(status).decode())
        while len(output) < length:
            destination = ctypes.create_string_buffer(length - len(output))
            output_buffer = _ZstdOutput(
                ctypes.addressof(destination), len(destination), 0
            )
            previous = input_buffer.pos
            status = library.ZSTD_decompressStream(
                stream, ctypes.byref(output_buffer), ctypes.byref(input_buffer)
            )
            if library.ZSTD_isError(status):
                raise ValueError(library.ZSTD_getErrorName(status).decode())
            output.extend(destination.raw[: output_buffer.pos])
            if status == 0:
                # A skippable or completed frame can end before the input
                # buffer. Continue so concatenated frames still contribute to
                # the bounded tar prefix.
                if input_buffer.pos < input_buffer.size:
                    continue
                break
            if input_buffer.pos == previous and output_buffer.pos == 0:
                raise ValueError("truncated zstd stream")
    finally:
        library.ZSTD_freeDStream(stream)
    return bytes(output)


def zstd_tar_has_entries(blob: Path) -> bool:
    """Inspect the tar header from a bounded libzstd decompression prefix."""
    prefix = _zstd_prefix(blob.read_bytes(), 1024)
    if len(prefix) < 1024:
        raise ValueError(f"{blob.name} expands to a truncated tar")
    if prefix == bytes(1024):
        return False
    try:
        tarfile.TarInfo.frombuf(prefix[:512], "utf-8", "surrogateescape")
    except tarfile.TarError as exc:
        raise ValueError(f"cannot parse {blob.name} as tar: {exc}") from exc
    return True


def empty_zstd_layers(
    manifest: dict, blob_dir: Path | None
) -> list[tuple[int, str, int]]:
    bad = []
    for index, digest, size in suspicious_zstd_layers(manifest):
        if blob_dir is None:
            raise ValueError("small zstd layers require --blob-dir")
        blob = blob_dir / digest.replace(":", "_")
        if not blob.is_file():
            raise ValueError(f"missing fetched layer blob {digest}")
        if not zstd_tar_has_entries(blob):
            bad.append((index, digest, size))
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", help="manifest JSON file (default: stdin)")
    parser.add_argument(
        "--blob-dir",
        type=Path,
        help="directory containing fetched blobs named sha256_<hex>",
    )
    args = parser.parse_args()

    try:
        if args.manifest:
            manifest = json.loads(Path(args.manifest).read_text())
        else:
            manifest = json.load(sys.stdin)
        bad = empty_zstd_layers(manifest, args.blob_dir)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: cannot validate OCI manifest: {exc}", file=sys.stderr)
        return 2

    if bad:
        for index, digest, size in bad:
            print(
                f"ERROR: layer {index} {digest} is a {size}-byte zstd tar layer; "
                "bootc cannot import an empty tar layer (tunaOS#3378)",
                file=sys.stderr,
            )
        return 1

    print(f"OCI layer check passed: {len(manifest['layers'])} layer(s), none empty")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
