"""tunaOS#2750: every EL10 GNOME cell fails the shell schema gate.

The pinned gnome50-el10-packages tier ships gnome-shell-50.0-3 with
`Provides: gnome-shell-common = 50.0-3`. DNF treats that as the dependency
satisfied and omits gnome-shell-common-50.0-3.noarch, the RPM that owns
org.gnome.shell.gschema.xml. With the schema gate from #2750 in place,
albacore run 36840489732, yellowfin run 36822471546 and skipjack run
36892338904 all failed `gnome`, `gnome-hwe` and `gnome-nvidia` at Build Image
with "missing or unreadable compiled GSettings schema: org.gnome.shell".
The EL10 package list must name the common RPM itself, because only a name
match makes DNF choose the real package over the false provider.

Falsification: structural. Remove `gnome-shell-common` from
`packages.el10.packages` in manifests/desktops/gnome.yaml and this test fails.
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "manifests/desktops/gnome.yaml"


def el10():
    return yaml.safe_load(MANIFEST.read_text())["packages"]["el10"]


def test_el10_gnome_names_the_common_rpm():
    packages = el10()["packages"]
    assert "gnome-shell" in packages
    assert "gnome-shell-common" in packages, (
        "gnome-shell's self-provide lets DNF skip the RPM that owns "
        "org.gnome.shell.gschema.xml; name it explicitly"
    )


def test_common_rpm_is_not_excluded():
    section = el10()
    excluded = set(section.get("exclude", [])) | set(section.get("group_exclude", []))
    assert "gnome-shell-common" not in excluded
