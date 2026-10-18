#!/usr/bin/env python3
"""Reject OCI manifests containing zstd layers too small to hold a tar entry.

Read one platform manifest from stdin or a named file. OCI indexes must be
resolved by the caller so diagnostics identify the failing platform artifact.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The layer that broke bootc in tunaOS#3378 is a 25-byte zstd frame expanding
# to the two 512-byte zero blocks of an empty tar. A tar with any member needs
# a non-zero 512-byte header; even a zero-length, one-character file compressed
# at zstd's maximum level is larger than this conservative floor.
MIN_ZSTD_TAR_LAYER_BYTES = 50


def undersized_zstd_layers(manifest: dict) -> list[tuple[int, str, int]]:
    """Return (index, digest, size) for layers that cannot hold a tar member."""
    layers = manifest.get("layers")
    if not isinstance(layers, list):
        raise ValueError("input is not a platform image manifest with a layers array")

    bad = []
    for index, layer in enumerate(layers):
        media_type = layer.get("mediaType", "")
        size = layer.get("size")
        if "tar+zstd" in media_type and isinstance(size, int) and size < MIN_ZSTD_TAR_LAYER_BYTES:
            bad.append((index, layer.get("digest", "<missing digest>"), size))
    return bad


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="?", help="manifest JSON file (default: stdin)")
    args = parser.parse_args()

    try:
        if args.manifest:
            manifest = json.loads(Path(args.manifest).read_text())
        else:
            manifest = json.load(sys.stdin)
        bad = undersized_zstd_layers(manifest)
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
