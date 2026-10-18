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


def test_collect_uses_production_gitlink_not_tracking_branch(monkeypatch):
    committed = "f" * 40
    gitmodules = f"""
[submodule "fisherman"]
\tpath = fisherman
\turl = {LIVE}
\tbranch = main
"""
    manifest = json.dumps(
        {
            "modules": [
                {
                    "name": "fisherman",
                    "sources": [
                        {
                            "type": "git",
                            "url": LIVE,
                            "commit": mod.FLOOR_COMMIT,
                        }
                    ],
                }
            ],
        }
    )
    fetched_refs = []

    def fake_fetch(_repo, path, ref):
        fetched_refs.append(ref)
        return gitmodules if path == ".gitmodules" else manifest

    monkeypatch.setattr(mod, "fetch", fake_fetch)

    def fake_api(url):
        if "/contents/fisherman?ref=prod" in url:
            return {"sha": committed}
        if "/compare/" in url:
            return {"status": "ahead"}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "api_json", fake_api)
    sources = mod.collect()
    source = sources["gnome"]
    assert source["commit"] == committed
    assert source["resolved"] == committed
    assert "branch" not in source
    assert fetched_refs == [mod.INSTALLER_REF] * 5

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

def test_all_five_frontends_share_the_consolidated_monorepo() -> None:
    """Every desktop builds its installer from tuna-os/bootc-installer."""
    assert set(mod.INSTALLERS) == {"kde", "cosmic", "niri", "xfce", "gnome"}
    for desktop, where in mod.INSTALLERS.items():
        assert where["repo"] == "tuna-os/bootc-installer", desktop


def test_manifest_entries_live_under_frontends() -> None:
    for desktop in ("kde", "cosmic", "niri", "xfce"):
        manifest = mod.INSTALLERS[desktop]["manifest"]
        assert manifest.startswith(f"frontends/{desktop}/flatpak/"), desktop
        assert manifest.endswith(".json"), desktop


def test_gnome_has_a_submodule_entry_and_no_manifest() -> None:
    assert mod.INSTALLERS["gnome"]["submodule"] == "fisherman"
    assert "manifest" not in mod.INSTALLERS["gnome"]


def test_audit_fails_a_non_canonical_repo() -> None:
    problems = mod.audit({"kde": {"url": DEAD, "commit": "d349c31e"}})
    assert len(problems) == 1
    assert mod.CANONICAL in problems[0]


def test_audit_fails_a_below_floor_sha() -> None:
    problems = mod.audit(
        {"kde": {"url": LIVE, "commit": "00000001", "at_or_after_floor": False}}
    )
    assert len(problems) == 1
    assert "floor" in problems[0]

def test_audit_fails_a_canonical_source_without_a_revision() -> None:
    problems = mod.audit({"kde": {"url": LIVE}})
    assert len(problems) == 1
    assert "no revision pin" in problems[0]


def test_audit_passes_the_floor_sha_and_newer() -> None:
    floor = {"url": LIVE, "resolved": mod.FLOOR_COMMIT, "at_or_after_floor": True}
    newer = {"url": LIVE, "resolved": "f" * 40, "at_or_after_floor": True}
    assert mod.audit({"kde": floor}) == []
    assert mod.audit({"kde": newer}) == []


def test_unresolvable_pins_warn_dont_fail() -> None:
    """Matching main()'s blip policy: at_or_after_floor=None only warns."""
    assert mod.audit({"kde": {"url": LIVE, "commit": "abc123"}}) == []
    unknown = {"url": LIVE, "resolved": "a" * 40, "at_or_after_floor": None}
    assert mod.audit({"kde": unknown}) == []
