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
import urllib.error
from pathlib import Path
import pytest
import sys

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
    assert "no fisherman git or submodule source" in problems[0]


def test_every_shipped_desktop_is_covered() -> None:
    """A desktop missing from the list is a desktop with no guard at all."""
    assert set(mod.INSTALLERS) == {"kde", "cosmic", "niri", "xfce", "gnome"}


def test_every_desktop_is_read_from_its_flatpak_manifest() -> None:
    """The manifest decides where fisherman comes from, so read it for all five.

    gnome, and since bootc-installer#351 the other four, build fisherman from a
    Flatpak `type: dir` source backed by a git submodule. The manifest carries
    no URL and the built binary carries no VCS stamp, so the check follows the
    dir source to .gitmodules and the committed gitlink.
    """
    for desktop, where in mod.INSTALLERS.items():
        assert set(where) == {"repo", "manifest"}, desktop
        assert where["manifest"].endswith(".json"), desktop


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


# bootc-installer@prod after #351: four frontends include one shared module
# file, gnome declares the module inline. Both use the `fisherman` submodule.
SHARED_MODULE = json.dumps(
    {"name": "fisherman", "sources": [{"type": "dir", "path": "../../fisherman"}]}
)
PROD_FILES = {
    **{
        where["manifest"]: json.dumps(
            {"modules": ["../../../shared/flatpak/go.json",
                         "../../../shared/flatpak/fisherman.json",
                         {"name": f"tuna-installer-{desktop}"}]}
        )
        for desktop, where in mod.INSTALLERS.items()
        if desktop != "gnome"
    },
    mod.INSTALLERS["gnome"]["manifest"]: json.dumps(
        {"modules": ["../shared/flatpak/go.json",
                     {"name": "fisherman",
                      "sources": [{"type": "dir", "path": "../fisherman"}]}]}
    ),
    "shared/flatpak/go.json": json.dumps({"name": "go"}),
    "shared/flatpak/fisherman.json": SHARED_MODULE,
    ".gitmodules": f'[submodule "fisherman"]\n\tpath = fisherman\n\turl = {LIVE}\n\tbranch = main\n',
}


def test_collect_follows_dir_sources_to_the_production_gitlink(monkeypatch):
    committed = "f" * 40
    fetched = []

    def fake_fetch(_repo, path, ref):
        fetched.append((path, ref))
        return PROD_FILES[path]

    monkeypatch.setattr(mod, "fetch", fake_fetch)
    gitlinks = []

    def fake_api(url):
        if "/contents/" in url:
            gitlinks.append(url)
            assert url.endswith("/contents/fisherman?ref=prod")
            return {"sha": committed}
        if "/compare/" in url:
            return {"status": "ahead"}
        raise AssertionError(url)

    monkeypatch.setattr(mod, "api_json", fake_api)
    sources = mod.collect()
    assert set(sources) == set(mod.INSTALLERS)
    for desktop, source in sources.items():
        # A tracking branch is not what the build checks out.
        assert source["url"] == LIVE, desktop
        assert source["commit"] == committed, desktop
        assert source["resolved"] == committed, desktop
        assert "branch" not in source, desktop
    assert mod.audit(sources) == []
    # Each production file and the gitlink are read once, at the production ref.
    assert sorted(fetched) == sorted((path, mod.INSTALLER_REF) for path in PROD_FILES)
    assert len(gitlinks) == 1


def test_a_dir_source_without_a_submodule_fails_closed(monkeypatch) -> None:
    files = {**PROD_FILES, ".gitmodules": '[submodule "docs"]\n\tpath = docs\n\turl = x\n'}
    monkeypatch.setattr(mod, "fetch", lambda _repo, path, _ref: files[path])
    sources = mod.collect()
    problems = mod.audit(sources)
    assert len(problems) == 5
    assert all("not a submodule" in problem for problem in problems)


def test_a_dir_source_outside_the_repository_fails_closed() -> None:
    files = {"m.json": json.dumps(
        {"modules": [{"name": "fisherman", "sources": [{"type": "dir", "path": "../x"}]}]}
    )}
    with pytest.raises(KeyError, match="outside the repository"):
        mod.fisherman_source("m.json", files.__getitem__)


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
    got = mod.fisherman_source("frontend.json", {"frontend.json": manifest}.__getitem__)
    assert got["url"] == LIVE
    assert got["commit"] == "027fa25c"


def test_the_manifest_parser_follows_included_module_files() -> None:
    files = {
        "frontends/kde/flatpak/kde.json": json.dumps(
            {"modules": ["../../../shared/flatpak/fisherman.json"]}
        ),
        "shared/flatpak/fisherman.json": SHARED_MODULE,
    }
    got = mod.fisherman_source("frontends/kde/flatpak/kde.json", files.__getitem__)
    assert got == {"dir": "fisherman"}


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
    for source in ({"url": LIVE}, {"url": LIVE, "at_or_after_floor": None}):
        problems = mod.audit({"kde": source})
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


def test_invalid_production_gitlink_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(mod, "fetch", lambda _repo, path, _ref: PROD_FILES[path])
    monkeypatch.setattr(
        mod,
        "submodule_sha",
        lambda *_args: (_ for _ in ()).throw(KeyError("invalid gitlink")),
    )

    sources = mod.collect()

    assert "source_error" in sources["gnome"]
    assert "invalid gitlink" in mod.audit(sources)[0]


def test_missing_production_gitlink_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(mod, "fetch", lambda _repo, path, _ref: PROD_FILES[path])
    missing = urllib.error.HTTPError("", 404, "Not Found", {}, None)
    monkeypatch.setattr(mod, "submodule_sha", lambda *_args: (_ for _ in ()).throw(missing))

    problems = mod.audit(mod.collect())

    assert len(problems) == 5
    assert all("production gitlink fisherman is missing" in p for p in problems)


def test_non_object_gitlink_response_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(mod, "api_json", lambda _url: [])
    with pytest.raises(KeyError, match="non-object"):
        mod.submodule_sha("tuna-os/bootc-installer", "fisherman")


def test_missing_fisherman_revision_fails_closed(monkeypatch) -> None:
    monkeypatch.setattr(
        mod,
        "INSTALLERS",
        {
            "kde": {
                "repo": "tuna-os/bootc-installer",
                "manifest": "frontend.json",
            }
        },
    )
    manifest = json.dumps(
        {
            "modules": [
                {
                    "name": "fisherman",
                    "sources": [{"type": "git", "url": LIVE, "branch": "missing"}],
                }
            ]
        }
    )
    monkeypatch.setattr(mod, "fetch", lambda *_args: manifest)
    missing = urllib.error.HTTPError("", 404, "Not Found", {}, None)
    monkeypatch.setattr(
        mod,
        "resolve_sha",
        lambda *_args: (_ for _ in ()).throw(missing),
    )

    sources = mod.collect()

    assert "does not exist" in mod.audit(sources)[0]


def test_missing_production_manifest_fails_through_main(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "INSTALLERS",
        {
            "kde": {
                "repo": "tuna-os/bootc-installer",
                "manifest": "frontends/kde/flatpak/org.tunaos.InstallerKde.json",
            }
        },
    )
    missing = urllib.error.HTTPError("", 404, "Not Found", {}, None)
    monkeypatch.setattr(mod, "fetch", lambda *_args: (_ for _ in ()).throw(missing))
    monkeypatch.setattr(sys, "argv", ["check-installer-fisherman-pins.py"])

    assert mod.main() == 1
    assert (
        "production file frontends/kde/flatpak/org.tunaos.InstallerKde.json is missing"
        in capsys.readouterr().out
    )


def test_invalid_json_response_fails_closed(monkeypatch) -> None:
    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"not-json"

    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *_args, **_kwargs: Response())
    with pytest.raises(KeyError, match="invalid JSON"):
        mod.api_json("https://api.example.test/resource")


def test_floor_ancestry_follows_the_compare_status(monkeypatch) -> None:
    seen = []

    def status_for(status):
        def fake_api(url):
            seen.append(url)
            return {"status": status}

        return fake_api

    expected = {"identical": True, "ahead": True, "behind": False, "diverged": False}
    for status, want in expected.items():
        monkeypatch.setattr(mod, "api_json", status_for(status))
        assert mod.floor_is_ancestor("tuna-os/fisherman", "f" * 40) is want, status
    assert all(f"/compare/{mod.FLOOR_COMMIT}...{'f' * 40}" in u for u in seen)
