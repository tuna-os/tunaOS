#!/usr/bin/env python3
"""Inventory large blobs reachable from one or more Git revisions."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_THRESHOLD = 5 * 1024 * 1024


@dataclass(frozen=True)
class Blob:
    oid: str
    size_bytes: int
    path: str


def git(*args: str, stdin: str | None = None) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        ).stdout
    except FileNotFoundError:
        raise SystemExit("error: git is not installed") from None
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "git command failed"
        raise SystemExit(f"error: {detail}") from None


def inventory(revisions: list[str], threshold: int) -> list[Blob]:
    object_paths: dict[str, str] = {}
    for line in git("rev-list", "--objects", *revisions).splitlines():
        oid, separator, path = line.partition(" ")
        object_paths.setdefault(oid, path if separator else "")

    if not object_paths:
        return []

    request = "".join(f"{oid}\n" for oid in object_paths)
    blobs: list[Blob] = []
    for line in git(
        "cat-file",
        "--batch-check=%(objectname) %(objecttype) %(objectsize)",
        stdin=request,
    ).splitlines():
        fields = line.split()
        if len(fields) != 3 or fields[1] != "blob":
            continue
        oid, _, raw_size = fields
        size = int(raw_size)
        if size > threshold:
            blobs.append(Blob(oid=oid, size_bytes=size, path=object_paths[oid]))

    return sorted(blobs, key=lambda blob: (-blob.size_bytes, blob.path, blob.oid))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List unique Git blobs larger than a threshold."
    )
    parser.add_argument(
        "revisions",
        nargs="*",
        help="revisions to scan (default: HEAD); use --all for every local ref",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="scan every ref visible in this clone",
    )
    parser.add_argument(
        "--threshold-bytes",
        type=int,
        default=DEFAULT_THRESHOLD,
        metavar="BYTES",
        help=f"report blobs larger than BYTES (default: {DEFAULT_THRESHOLD})",
    )
    parser.add_argument(
        "--format",
        choices=("table", "json"),
        default="table",
        help="output format (default: table)",
    )
    parser.add_argument(
        "--fail-if-found",
        action="store_true",
        help="exit 1 when at least one blob exceeds the threshold",
    )
    args = parser.parse_args()
    if args.all and args.revisions:
        parser.error("--all cannot be combined with revisions")
    if args.threshold_bytes < 0:
        parser.error("--threshold-bytes must be non-negative")
    return args


def main() -> int:
    args = parse_args()
    revisions = ["--all"] if args.all else (args.revisions or ["HEAD"])
    blobs = inventory(revisions, args.threshold_bytes)
    total = sum(blob.size_bytes for blob in blobs)

    if args.format == "json":
        print(
            json.dumps(
                {
                    "repository": str(Path.cwd()),
                    "revisions": revisions,
                    "threshold_bytes": args.threshold_bytes,
                    "count": len(blobs),
                    "total_bytes": total,
                    "blobs": [asdict(blob) for blob in blobs],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print("size_bytes\tsize_mib\toid\tpath")
        for blob in blobs:
            print(
                f"{blob.size_bytes}\t{blob.size_bytes / 1024 / 1024:.2f}"
                f"\t{blob.oid}\t{blob.path}"
            )
        print(
            f"# {len(blobs)} unique blobs; {total} bytes "
            f"({total / 1024 / 1024:.2f} MiB)",
            file=sys.stderr,
        )

    return 1 if args.fail_if_found and blobs else 0


if __name__ == "__main__":
    raise SystemExit(main())
