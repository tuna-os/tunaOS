"""The check that keeps an installer from silently building the wrong fisherman.

fisherman moved from projectbluefin/fisherman to tuna-os/fisherman and only
org.tunaos.InstallerKde followed. For two months the other four desktops built
their installer from a repository that had stopped moving -- while their
Flatpaks kept rebuilding daily, so nothing looked stale. marlin:cosmic could
not install at all and no gate said so.

These tests exercise the pure audit and the two parsers with no network, so
the check itself cannot rot into a no-op the way the gate it replaces did.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-installer-fisherman-pins.py"

spec = importlib.util.spec_from_file_location("fisherman_pins", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

DEAD = "https://github.com/projectbluefin/fisherman.git"
LIVE = "https://github.com/tuna-os/fisherman.git"


def test_the_abandoned_repo_is_rejected() -> None:
    """The exact configuration that shipped a broken cosmic installer."""
    problems = mod.audit({"cosmic": {"url": DEAD, "branch": "dev"}})
    assert len(problems) == 1
    assert "projectbluefin/fisherman" in problems[0]


def test_a_pinned_commit_on_the_dead_repo_is_still_rejected() -> None:
    """niri and xfce pinned a COMMIT and were just as stale.

    Pinning does not make a dead source safe -- it makes it permanent.
    """
    problems = mod.audit({"niri": {"url": DEAD, "commit": "35c8f6f1"}})
    assert len(problems) == 1


def test_the_live_repo_passes() -> None:
    assert mod.audit({"kde": {"url": LIVE, "commit": "027fa25c"}}) == []


def test_an_old_revision_of_the_live_repo_is_allowed() -> None:
    """Deliberately about the REPO, not the revision.

    Pinning an older revision of a live repo is a visible, reviewable choice;
    sourcing a repo that stopped moving is the silent one. Failing on revision
    age here would make the check noisy and it would get switched off.
    """
    assert mod.audit({"kde": {"url": LIVE, "commit": "6092be78"}}) == []


def test_a_missing_source_fails_loudly() -> None:
    """A check that silently finds nothing is worse than no check.

    The gate this replaces reported '127 failure(s)' on healthy and broken
    images alike because its helper never loaded; it could neither pass nor
    fail. If the manifest shape changes, say so.
    """
    problems = mod.audit({"xfce": {}})
    assert len(problems) == 1
    assert "no fisherman git source" in problems[0]


def test_every_shipped_desktop_is_covered() -> None:
    """A desktop missing from the list is a desktop with no guard at all."""
    assert set(mod.INSTALLERS) == {"kde", "cosmic", "niri", "xfce", "gnome"}


def test_gnome_is_read_from_its_submodule_not_a_manifest() -> None:
    """gnome is the one that cannot be checked the same way.

    bootc-installer builds fisherman from a Flatpak `type: dir` source backed
    by a git submodule, so the manifest carries no URL and the built binary
    carries no VCS stamp -- binary inspection could not date it. .gitmodules
    is the only place its source is written down.
    """
    assert "submodule" in mod.INSTALLERS["gnome"]
    assert "manifest" not in mod.INSTALLERS["gnome"]


def test_the_gitmodules_parser_reads_the_right_submodule() -> None:
    gitmodules = """
[submodule "docs-theme"]
\tpath = docs-theme
\turl = https://github.com/example/theme.git
[submodule "fisherman"]
\tpath = fisherman
\turl = https://github.com/projectbluefin/fisherman.git
\tbranch = dev
"""
    got = mod.source_from_gitmodules(gitmodules, "fisherman")
    assert got == {"url": DEAD, "branch": "dev"}
    assert mod.audit({"gnome": got})


def test_the_manifest_parser_finds_the_fisherman_module() -> None:
    manifest = json.dumps(
        {
            "modules": [
                {"name": "golang", "sources": [{"type": "archive", "url": "x"}]},
                {
                    "name": "fisherman",
                    "sources": [
                        {"type": "file", "path": "patch.diff"},
                        {"type": "git", "url": LIVE, "commit": "027fa25c"},
                    ],
                },
            ]
        }
    )
    got = mod.source_from_manifest(manifest)
    assert got["url"] == LIVE
    assert got["commit"] == "027fa25c"


def test_url_forms_normalize_to_the_same_repo() -> None:
    for url in (
        "https://github.com/tuna-os/fisherman.git",
        "https://github.com/tuna-os/fisherman",
        "git@github.com:tuna-os/fisherman.git",
    ):
        assert mod.normalize_repo(url) == "tuna-os/fisherman"
