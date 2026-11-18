"""tunaOS#4629: grouper:kde boots to SDDM's bare built-in greeter.

Ubuntu ships SDDM's Breeze theme as its own package, sddm-theme-breeze, and
the apt install runs with --no-install-recommends (build_scripts/lib.sh), so
kde-plasma-desktop never pulled it in. The published grouper:kde had an
empty /usr/share/sddm/themes; kde-set-look-and-feel.sh found no Breeze to
select, the image's branding check logged greeter=unsupported
reason=stock-or-unverified-theme, and iso-builder diag run 43582049195
captured SDDM's fallback greeter on both strict legs, which the first-boot
driver never classifies as a Plasma greeter. The apt KDE policy, as resolved
for an Ubuntu build and as projected into manifests/desktops/kde.yaml, must
name the theme package.

Falsification: behavioural. test_the_guard_fails_without_the_theme deletes
sddm-theme-breeze from a copy of the live policy and shows the same checks
report it missing; removing the entry from [desktops.kde.packages.apt] in
tunaos.toml makes the other two tests fail.
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import tunaos_config, tunaos_packages

THEME = "sddm-theme-breeze"


def policy():
    document = tunaos_config.load()
    return {key: document[key] for key in ("package_groups", "desktops")}


def resolved_apt(document):
    selected = tunaos_packages.resolve(document, "kde", manager="apt", os_id="ubuntu")
    assert selected["family"] == "apt"
    assert selected["display_manager"] == "sddm"
    return selected["sections"][-1][1]["required"]


def projected_apt(document):
    outputs = tunaos_packages.desktop_outputs(document)
    return json.loads(outputs["manifests/desktops/kde.yaml"])["packages"]["apt"]


def missing(document):
    return [where for where, packages in (("resolved", resolved_apt(document)),
                                          ("projected", projected_apt(document)))
            if "sddm" in packages and THEME not in packages]


def test_ubuntu_kde_resolves_the_breeze_greeter_theme():
    assert THEME in resolved_apt(policy()), (
        "apt skips Recommends; without the theme package SDDM draws its "
        "built-in fallback greeter"
    )


def test_generated_kde_manifest_carries_the_theme():
    assert missing(policy()) == []


def test_the_guard_fails_without_the_theme():
    broken = copy.deepcopy(policy())
    apt = broken["desktops"]["kde"]["packages"]["apt"]
    apt["required"] = [name for name in apt["required"] if name != THEME]
    assert missing(broken) == ["resolved", "projected"]
