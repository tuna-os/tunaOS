#!/usr/bin/env python3
"""Publish screenshot PNGs to the rolling `screenshots` GitHub Release.

The R2 upload stays; this is the second copy (epic #3470). It needs no
credential beyond the job's own GITHUB_TOKEN and gives the docs site a URL that
does not depend on download.tunaos.org:

    https://github.com/<owner>/<repo>/releases/download/screenshots/<asset>

`<asset>` is the R2 key with the leading `screenshots/` removed and every
remaining `/` written as `__`. docs/SCREENSHOT-RELEASE.md holds the mapping
table; `table` prints it and tests/test_screenshot_release_dual_publish.py
keeps the two equal.

    screenshot-release.py publish --kind KIND --repo OWNER/REPO NAME=PATH...
    screenshot-release.py table [--repo OWNER/REPO]

KIND is where the workflow writes the object in R2:

    desktop    screenshots/<NAME>-latest.png            weekly-desktop-screenshots.yml
    installer  screenshots/installer/<NAME>-latest.png  installer-screenshots.yml, installer-smoke.yml
    boot       screenshots/boot/<NAME>-latest.png       weekly-qcow2-screenshots.yml

Only the `-latest` pointers go to the release. The dated R2 copies exist for
evidence and are pruned by prune-r2.yml; on a release they would grow without
bound and nothing reads them.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

RELEASE_TAG = "screenshots"
R2_ROOT = "screenshots/"
ASSET_SEP = "__"
DEFAULT_REPO = "tuna-os/tunaos"

KINDS = {
    "desktop": "",
    "installer": "installer/",
    "boot": "boot/",
}

# GitHub rewrites other characters in an asset name, which would break the URL.
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

RELEASE_NOTES = (
    "Rolling store for the latest workflow screenshots. Assets are replaced in "
    "place by the screenshot workflows; do not delete this release. "
    "Mapping from the R2 keys: docs/SCREENSHOT-RELEASE.md."
)


def r2_key(kind: str, name: str) -> str:
    """The object key the workflows write to R2 for a screenshot."""
    if kind not in KINDS:
        raise ValueError(f"unknown kind {kind!r}; expected one of {sorted(KINDS)}")
    if not _SAFE.match(name) or ASSET_SEP in name:
        raise ValueError(
            f"screenshot name {name!r} must match {_SAFE.pattern} and not contain {ASSET_SEP!r}"
        )
    return f"{R2_ROOT}{KINDS[kind]}{name}-latest.png"


def asset_name(key: str) -> str:
    """Release asset name for an R2 key: drop `screenshots/`, flatten `/`."""
    if not key.startswith(R2_ROOT) or not key.endswith(".png"):
        raise ValueError(f"{key!r} is not a {R2_ROOT}*.png key")
    flat = key[len(R2_ROOT):].replace("/", ASSET_SEP)
    if not _SAFE.match(flat):
        raise ValueError(f"{key!r} flattens to {flat!r}, which GitHub would rename")
    return flat


def asset_url(repo: str, key: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError(f"{repo!r} is not OWNER/REPO")
    return f"https://github.com/{repo}/releases/download/{RELEASE_TAG}/{asset_name(key)}"


def plan(kind: str, repo: str, sources: list[str]) -> list[dict]:
    """Validate NAME=PATH arguments and resolve each to its key, asset and URL."""
    rows, seen = [], {}
    for source in sources:
        name, sep, path = source.partition("=")
        if not sep or not name or not path:
            raise ValueError(f"{source!r} is not NAME=PATH")
        if not Path(path).is_file():
            raise ValueError(f"{path!r} for {name!r} is not a file")
        key = r2_key(kind, name)
        asset = asset_name(key)
        if asset in seen:
            raise ValueError(f"{name!r} and {seen[asset]!r} both map to asset {asset}")
        seen[asset] = name
        rows.append({"name": name, "path": path, "key": key, "asset": asset, "url": asset_url(repo, key)})
    return rows


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=check, text=True, capture_output=True)


def _ensure_release(repo: str) -> None:
    if _gh("release", "view", RELEASE_TAG, "--repo", repo, check=False).returncode == 0:
        return
    created = _gh(
        "release", "create", RELEASE_TAG, "--repo", repo,
        "--title", "Rolling workflow screenshots",
        "--notes", RELEASE_NOTES,
        "--prerelease", "--latest=false",
        check=False,
    )
    # Two screenshot workflows can both find the release missing; the loser's
    # create fails, and that is fine as long as the release now exists.
    if created.returncode != 0 and _gh("release", "view", RELEASE_TAG, "--repo", repo, check=False).returncode != 0:
        raise RuntimeError(f"cannot create release {RELEASE_TAG}: {created.stderr.strip()}")


def publish(kind: str, repo: str, sources: list[str], dry_run: bool = False) -> list[dict]:
    rows = plan(kind, repo, sources)
    if dry_run or not rows:
        return rows
    _ensure_release(repo)
    with tempfile.TemporaryDirectory() as tmp:
        staged = []
        for row in rows:
            dest = Path(tmp) / row["asset"]
            shutil.copyfile(row["path"], dest)
            staged.append(str(dest))
        try:
            _gh("release", "upload", RELEASE_TAG, "--repo", repo, "--clobber", *staged)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"gh release upload failed: {exc.stderr.strip()}") from exc
    return rows


# One real example per R2 prefix the workflows write.
TABLE_EXAMPLES = (
    ("desktop", "yellowfin-gnome"),
    ("installer", "cosmic_01_welcome"),
    ("installer", "smoke-kde_03"),
    ("boot", "yellowfin-gnome"),
)


def render_table(repo: str = DEFAULT_REPO) -> str:
    lines = [
        "| R2 key under `download.tunaos.org` | Release asset URL |",
        "|---|---|",
    ]
    for kind, name in TABLE_EXAMPLES:
        key = r2_key(kind, name)
        lines.append(f"| `{key}` | `{asset_url(repo, key)}` |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    pub = sub.add_parser("publish", help="upload PNGs to the rolling release")
    pub.add_argument("--kind", required=True, choices=sorted(KINDS))
    pub.add_argument("--repo", required=True)
    pub.add_argument("--dry-run", action="store_true", help="print the mapping, change nothing")
    pub.add_argument("sources", nargs="*", metavar="NAME=PATH")
    tab = sub.add_parser("table", help="print the docs mapping table")
    tab.add_argument("--repo", default=DEFAULT_REPO)
    args = ap.parse_args(argv)

    if args.cmd == "table":
        print(render_table(args.repo), end="")
        return 0
    try:
        rows = publish(args.kind, args.repo, args.sources, args.dry_run)
    except (ValueError, RuntimeError) as exc:
        print(f"::error::screenshot release: {exc}", file=sys.stderr)
        return 1
    if not rows:
        print("::notice::no screenshots to publish to the release")
        return 0
    verb = "Would publish" if args.dry_run else "Published"
    for row in rows:
        print(f"{verb} {row['key']} -> {row['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
