"""The hummingbird desktop repo must resolve on every arch it is built for.

install-desktop.sh writes the manifest's `baseurl` VERBATIM into
/etc/yum.repos.d/<name>.repo:

    echo "baseurl=${_TD_RB}"

dnf expands $basearch when it reads that file, so an arch-neutral URL is not
merely tidier -- it is the only form that works on more than one arch.

gnome.yaml and cosmic.yaml both hardcoded `.../hummingbird/20251124-x86_64/`.
On aarch64 that points at the x86_64 prefix, which serves no aarch64 RPMs. The
desktop lanes install with --skip-unavailable, so the result is not a loud
failure: it is an image that builds green and silently contains no desktop --
the exact shape verify-desktop-experience.sh records for hummingbird:gnome
("410 packages -- gnome-backgrounds and gnome-user-docs, no gnome-shell, no
gdm, no mutter, no gtk4 -- and this check called it passed").

build_scripts/10-base-packages.sh already writes the same repo correctly:

    baseurl=https://repo.tunaos.org/hummingbird/20251124-$basearch/

so the manifests were the odd ones out, not the pattern. Both prefixes were
confirmed served (HTTP 200 on repodata/repomd.xml for x86_64 and aarch64)
before this was changed -- $basearch is only right if both actually exist.

## Why this is scoped to hummingbird

A broader "no manifest may hardcode an arch" rule sounds better and is wrong.
Two other pins are deliberate and say so in their own comments:

  * cosmic.yaml el10 `tuna-os-fprintd` -> .../fprintd/10-stream-aarch64/
    "only aarch64 RPMs are published here, so this is harmless to enable
    unconditionally on x86_64 -- dnf just finds no matching-arch packages and
    falls back to CentOS Stream's own x86_64 fprintd-pam". $basearch there
    would point x86_64 at a prefix that does not exist, and the repo writer
    sets skip_if_unavailable=False, so it would hard-fail the build.
  * xfce.yaml el10 `tunaos-xfce` -> .../xfce/10-stream-x86_64/, an
    x86_64-only lane.

Pinning a rule those two must violate would either red-line them or invite
someone to "fix" them into a broken state.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFESTS = sorted((ROOT / "manifests" / "desktops").glob("*.yaml"))
ARCHES = ("x86_64", "aarch64", "arm64", "amd64", "ppc64le", "s390x")


def hummingbird_repos(path: pathlib.Path):
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    section = (doc.get("packages") or {}).get("hummingbird")
    if not isinstance(section, dict):
        return
    for repo in section.get("repos") or []:
        if isinstance(repo, dict) and repo.get("baseurl"):
            yield repo.get("name"), repo["baseurl"]


def test_some_manifest_actually_declares_a_hummingbird_repo():
    """Guard against a check that passes because it examined nothing."""
    found = [row for path in MANIFESTS for row in hummingbird_repos(path)]
    assert found, (
        "no packages.hummingbird.repos[].baseurl found in any "
        "manifests/desktops/*.yaml -- the check below is vacuous"
    )


@pytest.mark.parametrize("manifest", MANIFESTS, ids=lambda p: p.name)
def test_the_hummingbird_repo_is_arch_neutral(manifest):
    for name, url in hummingbird_repos(manifest):
        hardcoded = [a for a in ARCHES if re.search(rf"[-/]{a}(/|$)", url)]
        assert not hardcoded, (
            f"{manifest.name}: packages.hummingbird.repos[{name}].baseurl "
            f"hardcodes {hardcoded[0]!r}:\n    {url}\n"
            "install-desktop.sh writes this verbatim into a .repo file, so on "
            "any other arch it serves no matching RPMs and the desktop "
            "silently installs nothing. Use $basearch, as "
            "build_scripts/10-base-packages.sh already does for this repo."
        )
