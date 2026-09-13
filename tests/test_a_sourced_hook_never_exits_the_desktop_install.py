"""A post_install hook must not `exit` — install-desktop.sh sources them.

`install-desktop.sh` runs each manifest `post_install` entry with `source`, so
an `exit` inside one does not end the hook: it ends the whole desktop install,
with status 0. Every later hook is skipped and the build reports success.

Measured 2026-09-12 on grouper:gnome-zfs (run 34714039087).
gnome-extensions.sh's apt branch ended in `exit 0`, so gnome.yaml's three
hooks ran as two:

    Running post-install: tuna-flatpak-remote.sh
    Running post-install: gnome-extensions.sh
    (flatpak-preinstall.sh never ran)

and the image failed its own contract on

    missing required path: /usr/share/flatpak/preinstall.d/*.preinstall

Only one cell went red, which is the dangerous part: every apt-based gnome
image had the same truncated install, hidden wherever the Containerfile stage
also runs configure-desktop-runtime.sh, which lays the flatpak baseline down a
second time. grouper:gnome-zfs is simply the one stage without that
compensator.

tests/bats/test_niri_dms_payload.bats already pins this property for one hook,
after the same bug shipped a niri image with no shell (tunaOS#1009, #637).
This generalises it: the rule is not about that hook, it is about how hooks are
invoked, so it applies to every one a manifest names.

The accepted idiom for "stop this hook early" is the one gnome-extensions.sh's
non-dnf branch already uses:

    return 0 2>/dev/null || exit 0

which returns when sourced and still works if the file is ever run directly.
It does not trip this test, because the line begins with `return`.
"""
from __future__ import annotations

import pathlib
import re

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "manifests" / "desktops"
HOOK_DIR = ROOT / "build_scripts" / "desktop"


def _hooks() -> dict[str, set[str]]:
    """Every script named in a post_install block, and which manifests name it.

    Read from the manifests rather than from a list here, so a hook added to a
    manifest is covered without touching this file.
    """
    found: dict[str, set[str]] = {}
    for m in sorted(MANIFESTS.glob("*.yaml")):
        try:
            doc = yaml.safe_load(m.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        for hook in doc.get("post_install") or []:
            found.setdefault(str(hook), set()).add(m.name)
    return found


def _top_level_exits(path: pathlib.Path) -> list[tuple[int, str]]:
    """Lines that would exit the sourcing script.

    Comments are stripped because this repo's prose quotes the very construct
    these tests search for. A line inside a function body would still match,
    which is deliberate: a hook is sourced, so an `exit` in a function it calls
    ends the install just as thoroughly as one at the top level.
    """
    hits = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if re.match(r"^exit\b", stripped):
            hits.append((n, stripped))
    return hits


def test_the_manifests_actually_declare_hooks():
    """Guard the selector: no hooks found would make the assertion below
    vacuously true (tunaOS#1730)."""
    hooks = _hooks()
    assert hooks, "no post_install hooks parsed out of manifests/desktops/*.yaml"
    for known in ("flatpak-preinstall.sh", "gnome-extensions.sh"):
        assert known in hooks, f"expected {known} among {sorted(hooks)}"


@pytest.mark.parametrize("hook", sorted(_hooks()))
def test_a_post_install_hook_does_not_exit(hook: str):
    path = HOOK_DIR / hook
    assert path.exists(), (
        f"manifest post_install names {hook}, but "
        f"{path.relative_to(ROOT)} does not exist -- install-desktop.sh "
        f"resolves hooks by bare name from that directory")
    hits = _top_level_exits(path)
    assert not hits, (
        f"{path.relative_to(ROOT)} calls exit at {hits}, and it is SOURCED by "
        f"install-desktop.sh (named in: {', '.join(sorted(_hooks()[hook]))}).\n"
        f"That does not end the hook, it ends the desktop install -- with "
        f"status 0 -- and every later post_install hook is skipped while the "
        f"build reports success.\n"
        f"Use the idiom the other branches use:  return 0 2>/dev/null || exit 0"
    )
