"""An apt manifest that uses lightdm must list an X server explicitly.

lightdm only RECOMMENDS an X server and accountsservice. Every apt install in
this tree runs with --no-install-recommends (build_scripts/lib.sh), so neither
arrives unless a manifest names it. Without an X server lightdm cannot create a
display server for its greeter and exits 1, and display-manager.service
crash-loops.

What makes this worth a test rather than a comment is where the evidence goes.
lightdm writes the real reason -- "Seat seat0: Can't create display server for
greeter" -- to /var/log/lightdm/lightdm.log and nowhere else. systemd records a
bare `status=1/FAILURE`, so the boot gate reports a desktop contract timeout and
the cause is invisible in every artifact CI collects.

It has now been paid for twice, in the same shape:

  gurnard:pantheon   LUKS run 31215923156. Diagnosed and bisected; pantheon.yaml
                     gained xserver-xorg and accountsservice, with a note.
  flounder:xfce      run 34541165610, and flounder-sid:xfce alongside it.
                     xfce-debian.yaml is the other apt manifest that declares
                     lightdm, and the fix was never carried across.

The note on the first one did not stop the second, because a note only helps a
reader who already opened that file. This asserts it over every manifest, so a
third lightdm desktop fails here instead of in a boot gate three hours later.
"""
from __future__ import annotations

import pathlib

import pytest

yaml = pytest.importorskip("yaml")

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "manifests" / "desktops"

# Debian/Ubuntu ship the server under several names; any one of them seats a
# greeter. xserver-xorg is the metapackage, -core the server itself, and the
# Xephyr/Xvfb nested servers are deliberately NOT here -- they are not display
# servers lightdm can seat on real hardware.
X_SERVERS = {"xserver-xorg", "xserver-xorg-core", "xwayland-run"}
# lightdm's other Recommends that every greeter queries for the user list.
USER_LIST = "accountsservice"


def _apt_packages(section) -> list:
    """The package names in a `packages.apt` section, whichever shape it has.

    Two are in use. xfce-debian.yaml writes a plain list; pantheon.yaml writes
    a mapping because it also needs a `ppa:` entry, and puts the names under
    `packages:`. Reading only the list shape made this test assert that
    pantheon -- the manifest that HAS the fix -- was missing it, which is the
    failure mode worth avoiding: a checker whose parser silently disagrees with
    the file reports the wrong manifests and gets muted.
    """
    if isinstance(section, dict):
        return list(section.get("packages") or [])
    return list(section or [])


def _apt_manifests_using_lightdm() -> list[tuple[str, list]]:
    """(name, apt package list) for every manifest whose apt path is lightdm.

    Scoped to the apt path on purpose: zypper and emerge resolve recommends
    differently, so xfce.yaml's zypper section naming lightdm is not in scope.
    """
    found = []
    for path in sorted(MANIFESTS.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        apt = _apt_packages((doc.get("packages") or {}).get("apt"))
        if not apt:
            continue
        if (doc.get("display_manager") or "").strip() != "lightdm":
            continue
        found.append((path.name, apt))
    return found


def test_the_scan_finds_the_manifests_it_is_meant_to_cover():
    """Absence of evidence is not evidence of absence (#1730): a selector that
    silently matches nothing would make every assertion below vacuously true."""
    names = {name for name, _ in _apt_manifests_using_lightdm()}
    assert "xfce-debian.yaml" in names, (
        "xfce-debian.yaml no longer reads as an apt+lightdm manifest; if its "
        "display manager changed, this test's premise needs revisiting"
    )
    assert "pantheon.yaml" in names


@pytest.mark.parametrize(
    "name,apt",
    _apt_manifests_using_lightdm(),
    ids=[n for n, _ in _apt_manifests_using_lightdm()],
)
def test_an_apt_lightdm_manifest_lists_an_x_server(name: str, apt: list):
    packages = {str(p).strip() for p in apt}
    assert packages & X_SERVERS, (
        f"{name} installs lightdm through apt but lists no X server "
        f"({' / '.join(sorted(X_SERVERS))}). lightdm only Recommends one and "
        "every apt install here uses --no-install-recommends, so lightdm will "
        "exit 1 with 'Can't create display server for greeter' -- written only "
        "to /var/log/lightdm/lightdm.log, never the journal. The boot gate will "
        "report a desktop contract timeout and name nothing."
    )


@pytest.mark.parametrize(
    "name,apt",
    _apt_manifests_using_lightdm(),
    ids=[n for n, _ in _apt_manifests_using_lightdm()],
)
def test_an_apt_lightdm_manifest_lists_accountsservice(name: str, apt: list):
    packages = {str(p).strip() for p in apt}
    assert USER_LIST in packages, (
        f"{name} installs lightdm through apt but not {USER_LIST}. It is "
        "another lightdm Recommends, so --no-install-recommends drops it, and "
        "every greeter then starts by warning 'Error getting user list from "
        "org.freedesktop.Accounts'."
    )
