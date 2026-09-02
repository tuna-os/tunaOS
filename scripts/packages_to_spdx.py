#!/usr/bin/env python3
"""Build an SPDX document from a package manifest the build already produced.

`Generate SBOM` scans the finished image with syft. On most editions that is
fine. On guppy it is not: Gentoo's file inventory is large enough that syft
outgrows the runner, and the cgroup cap added in #1784/#1795 kills it rather
than letting it take the runner agent down. The variant still builds, signs
and promotes -- but it publishes no SBOM, and `Attest SBOM` reports the gap
every single night.

The information was never actually missing. Two steps earlier, `Publish
package manifest` already enumerated every installed package straight from
the image's own package database, at a cost of seconds and a few hundred
kilobytes. Re-deriving that same list by walking every file in the image is
what costs the memory.

So when the scan dies, fall back to the manifest instead of shipping nothing.
The result is a smaller SBOM than syft's -- packages only, no file-level
inventory and no license detection -- but it is accurate, it is complete at
the package level, and it is the difference between an attestable SBOM and
none at all. This is the second suggestion in #1567.

Handles every manifest format `Publish package manifest` can emit:

    rpm      name<TAB>version-release
    dpkg     name<TAB>version
    pacman   name<TAB>version
    portage  category/name-version          (qlist -ICv, single column)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# A Gentoo atom: category/name-version, where the version starts at the last
# hyphen followed by a digit. `app-editors/vim-9.1.0` -> vim / 9.1.0, while
# `x11-libs/gtk+-3.24.43` -> gtk+ / 3.24.43 and `dev-libs/libx86-1.1` does not
# split at `x86`.
_ATOM = re.compile(r"^(?P<category>[\w+.-]+)/(?P<name>.+?)-(?P<version>\d[^-]*(?:-r\d+)?)$")

# SPDX 2.3 restricts the SPDXID tail to letters, digits, `.` and `-` -- note
# that `+` is NOT among them, so `x11-libs/gtk+` cannot be used verbatim. The
# leading index keeps the result unique even when two packages sanitize to the
# same string.
_UNSAFE_ID = re.compile(r"[^-.a-zA-Z0-9]")

NOASSERTION = "NOASSERTION"


def parse_manifest(text: str) -> list[tuple[str, str]]:
    """Return (name, version) pairs, preserving manifest order.

    Comment lines are skipped, which also handles the `# NO PACKAGE DATABASE
    IN IMAGE` marker the manifest step writes when an image cannot enumerate
    itself (tunaos-packages#135) -- that yields no packages, and the caller
    treats an empty result as "cannot synthesize" rather than emitting an
    empty SBOM.
    """
    packages: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "\t" in line:
            name, _, version = line.partition("\t")
            name, version = name.strip(), version.strip()
            if name:
                packages.append((name, version or NOASSERTION))
            continue
        atom = _ATOM.match(line)
        if atom:
            packages.append((atom["name"], atom["version"]))
            continue
        # A bare name with no version is still a package worth recording;
        # claiming a version we did not read would be worse than NOASSERTION.
        packages.append((line, NOASSERTION))
    return packages


def _spdx_id(index: int, name: str) -> str:
    return f"SPDXRef-Package-{index}-{_UNSAFE_ID.sub('-', name)}"


def build_document(
    packages: list[tuple[str, str]],
    *,
    image: str,
    namespace_seed: str,
    created: str,
) -> dict:
    doc_packages = []
    relationships = []
    for i, (name, version) in enumerate(packages):
        pid = _spdx_id(i, name)
        doc_packages.append(
            {
                "SPDXID": pid,
                "name": name,
                "versionInfo": version,
                # Not "unknown": we genuinely did not look, and SPDX has a
                # word for that.
                "downloadLocation": NOASSERTION,
                # False, and it must stay false -- this document is derived
                # from the package database, so no file-level analysis was
                # performed and claiming otherwise would misrepresent it.
                "filesAnalyzed": False,
                "licenseConcluded": NOASSERTION,
                "licenseDeclared": NOASSERTION,
                "copyrightText": NOASSERTION,
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relatedSpdxElement": pid,
                "relationshipType": "DESCRIBES",
            }
        )

    digest = hashlib.sha256(namespace_seed.encode("utf-8")).hexdigest()
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": image,
        "documentNamespace": f"https://tunaos.org/spdxdocs/{image}-{digest}",
        "creationInfo": {
            "created": created,
            "creators": [
                "Tool: tunaos-packages-to-spdx",
                "Organization: TunaOS",
            ],
            # Say plainly what this document is and is not, so a consumer
            # never mistakes a package-level fallback for a full syft scan.
            "comment": (
                "Derived from the image's package database rather than a "
                "filesystem scan. Package-level inventory is complete; file "
                "inventory and license detection are absent by construction."
            ),
        },
        "packages": doc_packages,
        "relationships": relationships,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    ap.add_argument("--image", required=True, help="image ref this describes")
    ap.add_argument(
        "--created",
        default=None,
        help="RFC3339 creation timestamp; defaults to now (UTC)",
    )
    args = ap.parse_args(argv)

    if not args.manifest.is_file():
        print(f"no package manifest at {args.manifest}", file=sys.stderr)
        return 1

    packages = parse_manifest(args.manifest.read_text(encoding="utf-8", errors="replace"))
    if not packages:
        # Emitting a zero-package SPDX document would pass a `.packages |
        # length > 0` check nowhere and would assert, falsely, that the image
        # contains nothing.
        print(f"{args.manifest} lists no packages; refusing to write an empty SBOM", file=sys.stderr)
        return 1

    created = args.created or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    doc = build_document(
        packages,
        image=args.image,
        namespace_seed=f"{args.image}\n{len(packages)}\n{created}",
        created=created,
    )
    args.output.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.output} with {len(packages)} packages from {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
