#!/usr/bin/env python3
"""Adapt one reviewed Chunkah Containerfile for older cache-mount parsers."""

import hashlib
import sys
from pathlib import Path

# This verifies the build-file layout, not the provenance of the whole source.
REVIEWED_SHA256 = "02d30f78556863150e50a696d2e61b571cd7f64d77297a9ddc541a34a0da851d"
ORIGINAL = b"--mount=type=cache,rw,"
REPLACEMENT = b"--mount=type=cache,"
BIND = b"--mount=type=bind,target=/run/src,rw"


def transform(source):
    if hashlib.sha256(source).hexdigest() != REVIEWED_SHA256:
        raise ValueError("unrecognized Chunkah Containerfile bytes")
    if source.count(ORIGINAL) != 4 or source.count(BIND) != 1:
        raise ValueError("reviewed cache or bind mount shape changed")
    return source.replace(ORIGINAL, REPLACEMENT)


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: chunkah-cache-compat.py INPUT OUTPUT")
    source, output = map(Path, sys.argv[1:])
    if source.resolve() == output.resolve():
        raise ValueError("input and output must differ")
    result = transform(source.read_bytes())
    with output.open("xb") as stream:
        stream.write(result)


if __name__ == "__main__":
    main()
