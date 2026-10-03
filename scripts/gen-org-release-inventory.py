#!/usr/bin/env python3
"""Generate the TunaOS organization GitHub release inventory.

The inventory is deliberately derived from the GitHub API. Release status was
previously copied into planning issues by hand, so the same repository could be
called versioned in one issue and unversioned in another after its state moved.
This script gives that discussion one reproducible GitHub-plane measurement.

Scope is every non-archived, public repository in the ``tuna-os`` organization.
The report measures Git tags, published GitHub Releases, and assets attached to
the latest release. OCI and Flatpak publication are separate distribution
planes and are explicitly not inferred from repository names or workflow text.

For offline tests or a reproducible snapshot, ``--repos-json`` accepts a list of
repository objects. Each object can include ``tags`` and ``releases`` arrays;
when present, no API probe is made for that repository.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ORG = "tuna-os"
ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "ORG-RELEASE-INVENTORY.md"
SEMVER = re.compile(r"^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")
CALVER = re.compile(r"^(?:v|[0-9A-Za-z][0-9A-Za-z._-]*-)?20\d{2}(?:[-.]?\d{2}){1,2}(?:[-._].*)?$")


class ProbeError(RuntimeError):
    """GitHub state could not be measured without guessing."""


def _gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, check=False
    )


def fetch_repos() -> list[dict[str, Any]]:
    proc = _gh([
        "repo", "list", ORG, "--limit", "200",
        "--json", "name,isArchived,isPrivate,url,defaultBranchRef",
    ])
    if proc.returncode:
        raise ProbeError(f"gh repo list {ORG} failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def active(repos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        (r for r in repos if not r.get("isArchived") and not r.get("isPrivate")),
        key=lambda r: r["name"].lower(),
    )


def _api_json(path: str, *, absence_is_empty: bool = False) -> Any:
    proc = _gh(["api", path])
    if proc.returncode == 0:
        return json.loads(proc.stdout)
    if absence_is_empty and ("404" in proc.stderr or "Not Found" in proc.stderr):
        return []
    raise ProbeError(f"gh api {path} failed: {proc.stderr.strip()}")


def tags(repo: dict[str, Any]) -> list[dict[str, Any]]:
    if "tags" in repo:
        return repo["tags"]
    return _api_json(f"repos/{ORG}/{repo['name']}/tags?per_page=100")


def releases(repo: dict[str, Any]) -> list[dict[str, Any]]:
    values = (
        repo["releases"]
        if "releases" in repo
        else _api_json(f"repos/{ORG}/{repo['name']}/releases?per_page=100")
    )
    return [r for r in values if not r.get("draft")]


def version_pattern(ref: str | None) -> str:
    if not ref:
        return "none"
    # Check CalVer first: v2026.09.26 resembles three numeric SemVer fields,
    # but the year in the major position is the project's release date.
    if CALVER.fullmatch(ref):
        return "date-based"
    if SEMVER.fullmatch(ref):
        return "SemVer"
    return "other"


def asset_signals(assets: list[dict[str, Any]]) -> str:
    """Summarize integrity/distribution evidence without claiming validation."""
    if not assets:
        return "0"
    names = [a.get("name", "").lower() for a in assets]
    signals: list[str] = []
    if any("sha256" in n or "checksum" in n for n in names):
        signals.append("checksum")
    if any("sbom" in n or "spdx" in n or "cyclonedx" in n for n in names):
        signals.append("SBOM")
    if any(
        n.endswith((".sig", ".asc", ".pem", ".bundle", ".intoto.jsonl"))
        or "provenance" in n
        for n in names
    ):
        signals.append("signature/provenance")
    suffixes = (".dmg", ".pkg", ".msi", ".exe", ".deb", ".rpm", ".flatpak", ".appimage")
    if any(n.endswith(suffixes) for n in names):
        signals.append("installer/package")
    detail = ", ".join(signals) if signals else "no integrity marker in name"
    return f"{len(assets)} ({detail})"


def inspect(repo: dict[str, Any]) -> dict[str, Any]:
    repo_tags = tags(repo)
    repo_releases = releases(repo)
    latest = repo_releases[0] if repo_releases else None
    latest_tag = repo_tags[0].get("name") if repo_tags else None
    release_tag = latest.get("tag_name") if latest else None
    version_ref = release_tag or latest_tag
    return {
        "name": repo["name"],
        "url": repo.get("url") or f"https://github.com/{ORG}/{repo['name']}",
        "latest_tag": latest_tag,
        "release": latest,
        "pattern": version_pattern(version_ref),
        "assets": asset_signals(latest.get("assets", []) if latest else []),
    }


def _cell(value: str) -> str:
    return value.replace("|", "\\|")


def render(repos: list[dict[str, Any]], measured: str | None = None) -> str:
    rows = [inspect(repo) for repo in active(repos)]
    stamp = measured or dt.date.today().isoformat()
    releases_count = sum(row["release"] is not None for row in rows)
    unversioned = sum(row["latest_tag"] is None and row["release"] is None for row in rows)
    semver = sum(row["pattern"] == "SemVer" for row in rows)
    calver = sum(row["pattern"] == "date-based" for row in rows)

    out = [
        "# Organization Release Inventory",
        "",
        f"**Measured {stamp}** from the GitHub API by",
        "[`scripts/gen-org-release-inventory.py`](../scripts/gen-org-release-inventory.py).",
        "",
        "This reproducible audit covers GitHub distribution for active public",
        "repositories in the `tuna-os` organization. It reports tags, published",
        "GitHub Releases, and the assets attached to each latest release. It does",
        "**not** infer OCI, Flatpak, package-repository, app-store, or notarization",
        "status: those planes need their own authenticated inventories. An asset",
        "signal below is based on its filename and is not a cryptographic validation.",
        "",
        "## Current snapshot",
        "",
        f"- Active public repositories: **{len(rows)}**",
        f"- Repositories with a published GitHub Release: **{releases_count}**",
        f"- Repositories with no Git tag or GitHub Release: **{unversioned}**",
        f"- Latest visible version pattern: **{semver} SemVer**, **{calver} date-based**",
        "",
        "| Repository | Latest Git tag | Latest GitHub Release | Version pattern | Latest release assets |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        tag = f"`{_cell(row['latest_tag'])}`" if row["latest_tag"] else "—"
        release = row["release"]
        if release:
            release_tag = _cell(release.get("tag_name") or "unnamed")
            release_url = release.get("html_url") or f"{row['url']}/releases"
            release_cell = f"[`{release_tag}`]({release_url})"
            if release.get("prerelease"):
                release_cell += " (pre-release)"
        else:
            release_cell = "—"
        out.append(
            f"| [{row['name']}]({row['url']}) | {tag} | {release_cell} | "
            f"{row['pattern']} | {row['assets']} |"
        )

    out += [
        "",
        "## How to use this inventory",
        "",
        "- Treat `none` and `other` as triage inputs, not automatic defects. Some",
        "  repositories do not publish a consumer artifact.",
        "- Follow a repository's release tracker before adding another issue. The",
        "  inventory measures state; it does not replace release ownership or gates.",
        "- Do not edit status by hand. Regenerate it with",
        "  `GH_TOKEN=… ./scripts/gen-org-release-inventory.py`.",
        "- Use `--check` only against a fixed `--repos-json` fixture. Live org state",
        "  can change independently of a pull request.",
        "",
        "## Tracked adoption gaps",
        "",
        "- [finupdate#141](https://github.com/tuna-os/finupdate/issues/141) — first versioned release",
        "- [iso-builder#214](https://github.com/tuna-os/iso-builder/issues/214) — release pipeline for the native writer",
        "- [bootc-installer-asahi#77](https://github.com/tuna-os/bootc-installer-asahi/issues/77) — versioned, hardware-verified first release",
        "- [`.github`#170](https://github.com/tuna-os/.github/issues/170) — shared workflow that fails closed and verifies releases",
        "",
        "## Standard",
        "",
        "[tunaOS#2731](https://github.com/tuna-os/tunaOS/issues/2731) defines the",
        "organization-wide version identifiers, release gates, immutable references,",
        "support, and EOL contract. Operating-system images retain the separate",
        "[date-based image policy](../VERSIONING.md).",
        "",
    ]
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--repos-json", type=Path)
    parser.add_argument("--measured", help="override YYYY-MM-DD stamp (fixtures)")
    args = parser.parse_args()

    try:
        repos = json.loads(args.repos_json.read_text()) if args.repos_json else fetch_repos()
        generated = render(repos, args.measured)
    except (OSError, json.JSONDecodeError, ProbeError) as exc:
        print(f"refusing to write a partial release inventory: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if DOC.exists() and DOC.read_text() == generated:
            print("organization release inventory is current")
            return 0
        print("organization release inventory is out of date", file=sys.stderr)
        return 1

    DOC.write_text(generated)
    print(f"{DOC.relative_to(ROOT)} regenerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
