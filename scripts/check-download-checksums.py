#!/usr/bin/env python3
"""Verify pinned binary checksums against the pinned release's published sums.

Several downloads here are pinned twice: a version, and a per-architecture
sha256 of the asset at that version. Renovate maintains the version and cannot
maintain the checksums -- both custom managers in renovate.json capture a
single version line, so a sibling `_sha256` map is outside the match and is
left untouched by a bump.

That is not theoretical. Renovate bumped chezmoi v2.71.0 -> v2.72.0 and left
chezmoi_sha256 on v2.71.0's hashes; the Ubuntu/niri build then downloaded a
v2.72.0 .deb and checked it against a v2.71.0 hash. It fails closed, so no bad
binary ships -- but the build dies, and nothing pointed at the cause.

This script closes the loop: it fetches the checksums.txt published for the
*pinned* version and asserts each pinned hash matches. It catches
  - a version bump that left checksums behind (the Renovate case), and
  - a re-published release whose asset content changed under the same tag.

Run with --fix to rewrite the pinned checksums in place.

Exits non-zero if any pin disagrees. Prints one line per pin either way,
because "which ones are fine" is as useful as "which one broke".
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCHES = ("amd64", "arm64")


@dataclass
class Pin:
    """One pinned download: where its version and checksums live, and which
    published asset each checksum is supposed to be for."""

    name: str
    # File holding the version, and a regex with one group capturing it.
    version_file: str
    version_re: str
    # File holding the checksums, and a regex template per arch. {arch} is
    # substituted; the regex must have exactly one group: the hash itself.
    checksum_file: str
    checksum_re: str
    # {version} is the tag (v1.2.3); {num} is the tag without the leading v.
    checksums_url: str
    asset: str
    versions: dict = field(default_factory=dict)


PINS = [
    Pin(
        name="remora",
        version_file="build_scripts/install-remora.sh",
        version_re=r'^REMORA_VERSION="(v[^"]+)"',
        checksum_file="build_scripts/install-remora.sh",
        checksum_re=r'^{arch}\) REMORA_SHA256="([0-9a-f]{{64}})"',
        checksums_url="https://github.com/tuna-os/remora/releases/download/{version}/checksums.txt",
        asset="remora-linux-{arch}",
    ),
    Pin(
        name="chezmoi",
        version_file="image-versions.yaml",
        version_re=r'^\s+chezmoi:\s*"(v[^"]+)"',
        checksum_file="image-versions.yaml",
        checksum_re=r'^\s+{arch}:\s*"([0-9a-f]{{64}})"',
        checksums_url="https://github.com/twpayne/chezmoi/releases/download/{version}/chezmoi_{num}_checksums.txt",
        asset="chezmoi_{num}_linux_{arch}.deb",
    ),
]


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text()


def find_version(pin: Pin) -> str:
    m = re.search(pin.version_re, read(pin.version_file), re.MULTILINE)
    if not m:
        sys.exit(f"::error::could not find {pin.name}'s version in {pin.version_file}")
    return m.group(1)


def find_checksum(pin: Pin, arch: str) -> tuple[str, str]:
    """Return (regex-used, pinned-hash) for one architecture."""
    pattern = pin.checksum_re.format(arch=arch)
    m = re.search(pattern, read(pin.checksum_file), re.MULTILINE)
    if not m:
        sys.exit(f"::error::could not find {pin.name}'s {arch} checksum in {pin.checksum_file}")
    return pattern, m.group(1)


def fetch_published(pin: Pin, version: str) -> dict[str, str]:
    """Map asset filename -> sha256, from the release's published checksums."""
    url = pin.checksums_url.format(version=version, num=version.lstrip("v"))
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as exc:
        sys.exit(
            f"::error::{pin.name} {version}: cannot fetch {url} ({exc.code}). "
            "Either the version pin names a release that does not exist, or the "
            "release did not publish a checksums file."
        )
    except urllib.error.URLError as exc:
        sys.exit(f"::error::{pin.name} {version}: cannot reach {url} ({exc.reason})")

    sums = {}
    for line in body.splitlines():
        parts = line.split()
        if len(parts) == 2:
            sums[parts[1].lstrip("*")] = parts[0]
    return sums


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--fix",
        action="store_true",
        help="rewrite stale checksums in place instead of only reporting them",
    )
    ap.add_argument("--only", help="check a single pin by name")
    args = ap.parse_args()

    failed = 0
    fixed = 0

    for pin in PINS:
        if args.only and pin.name != args.only:
            continue
        version = find_version(pin)
        published = fetch_published(pin, version)

        for arch in ARCHES:
            pattern, pinned = find_checksum(pin, arch)
            asset = pin.asset.format(arch=arch, num=version.lstrip("v"))
            want = published.get(asset)

            if want is None:
                print(f"FAIL {pin.name} {arch}: {version} publishes no asset named {asset}")
                print(
                    f"::error::{pin.name} {arch}: the pinned release {version} has no "
                    f"asset {asset}. The asset naming may have changed upstream."
                )
                failed += 1
                continue

            if pinned == want:
                print(f"ok   {pin.name} {arch}: {version} {pinned[:12]}…")
                continue

            print(f"FAIL {pin.name} {arch}: pinned {pinned[:12]}… but {version} publishes {want[:12]}…")
            if not args.fix:
                print(
                    f"::error::{pin.name} {arch} checksum does not match the pinned "
                    f"version {version}. This is what a version bump that left the "
                    f"checksums behind looks like. Run "
                    f"`python3 scripts/check-download-checksums.py --fix` to correct it."
                )
                failed += 1
                continue

            path = REPO_ROOT / pin.checksum_file
            text = path.read_text()
            # Replace only the captured hash, leaving surrounding syntax alone,
            # so this works for both the shell case arm and the YAML mapping.
            m = re.search(pattern, text, re.MULTILINE)
            start, end = m.span(1)
            path.write_text(text[:start] + want + text[end:])
            print(f"fix  {pin.name} {arch}: -> {want[:12]}…")
            fixed += 1

    if fixed:
        print(f"\nrewrote {fixed} checksum(s); re-run without --fix to confirm")
        return 0
    if failed:
        print(f"\n{failed} checksum pin(s) disagree with their pinned release")
        return 1
    print("\nall checksum pins match their pinned release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
