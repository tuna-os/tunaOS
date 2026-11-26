"""Every desktop image ships a screen reader.

COSMIC's Super+Alt+S, Plasma's Meta+Alt+S, the COSMIC installer's first page
(tunaOS#5012) and GNOME's top bar turn on the at-spi screen-reader status,
and the session starts orca on it. Fedora installs no weak dependencies
(01-workarounds.sh), so orca came only where a list named it: the KDE, XFCE,
niri, COSMIC, Pantheon and several GNOME lists did not. This test makes the
list name it, so a change cannot drop it again without failing here.

dnf lists carry it as optional (install_available: a repository without it
does not stop the build); apt, pacman and zypper lists have no optional
tier, and every one of their repositories has orca. Gentoo (emerge) is left
out: orca needs brltty[python] there, which the Tuna desktop sets and the
others do not.

A list can name orca and the image still lack it: a dnf repository without
orca skips an optional package. So the desktop contract
(verify-desktop-experience.sh, build and runtime) also fails an image with no
orca command, for every desktop; Gentoo (by its Portage database) and
Hummingbird are waived.
"""

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = tomllib.loads((ROOT / "tunaos.toml").read_text())
GROUPS = CONFIG["package_groups"]
DNF = {"fedora", "rawhide", "eln", "el10", "hummingbird"}
CONTRACT = (ROOT / "build_scripts/checks/verify-desktop-experience.sh").read_text()


def lists():
    for desktop, spec in CONFIG["desktops"].items():
        for base, section in spec.get("packages", {}).items():
            if not isinstance(section, dict) or base == "emerge":
                continue
            if any(k in section for k in ("required", "optional", "include", "groups")):
                yield desktop, base, section


def named(section):
    names = set(section.get("required", [])) | set(section.get("optional", []))
    for group in section.get("include", []):
        names |= set(GROUPS[group].get("required", [])) | set(GROUPS[group].get("optional", []))
    return {n.split("/")[-1] for n in names}


@pytest.mark.parametrize("desktop, base, section", list(lists()), ids=lambda v: v if isinstance(v, str) else "")
def test_the_desktop_list_names_a_screen_reader(desktop, base, section):
    assert "orca" in named(section), f"{desktop} on {base} has no screen reader"


def test_dnf_lists_take_it_as_optional():
    for desktop, base, section in lists():
        if base in DNF and "orca" not in set(section.get("required", [])):
            assert "orca" in named(section), (desktop, base)


def test_every_desktop_is_covered():
    desktops = {d for d, _b, _s in lists()}
    for expected in ("cosmic", "gnome", "kde", "niri", "xfce", "pantheon", "tuna"):
        assert expected in desktops


def _run_contract_helper(tmp_path, has_orca, **env):
    helper = re.search(
        r"^require_screen_reader\(\) \{\n.*?^\}\n", CONTRACT, re.DOTALL | re.MULTILINE
    )
    assert helper, "require_screen_reader is not defined in verify-desktop-experience.sh"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    if has_orca:
        orca = bindir / "orca"
        orca.write_text("#!/bin/sh\n")
        orca.chmod(0o755)
    script = (
        "TUNAOS_CONTRACT_WAIVED=0\n"
        "waive() { TUNAOS_CONTRACT_WAIVED=$((TUNAOS_CONTRACT_WAIVED + 1)); }\n"
        + helper.group(0)
        + 'require_screen_reader\necho "waived=$TUNAOS_CONTRACT_WAIVED"\n'
    )
    return subprocess.run(
        ["/bin/bash", "-c", script],
        check=False,
        env={"PATH": str(bindir), "TUNAOS_PORTAGE_DB": str(tmp_path / "no-portage"), **env},
        capture_output=True,
        text=True,
    )


def test_the_contract_fails_an_image_with_no_screen_reader(tmp_path):
    result = _run_contract_helper(tmp_path, has_orca=False)
    assert result.returncode == 1
    assert "orca" in result.stderr


def test_the_contract_passes_an_image_with_orca(tmp_path):
    result = _run_contract_helper(tmp_path, has_orca=True)
    assert result.returncode == 0
    assert "waived=0" in result.stdout


def test_hummingbird_is_waived_not_passed(tmp_path):
    result = _run_contract_helper(tmp_path, has_orca=False, IS_HUMMINGBIRD="true")
    assert result.returncode == 0
    assert "waived=1" in result.stdout


def test_gentoo_is_waived_by_its_portage_database(tmp_path):
    """The contract step passes no Gentoo flag; the image's Portage database says it."""
    (tmp_path / "pkg").mkdir()
    result = _run_contract_helper(tmp_path, has_orca=False, TUNAOS_PORTAGE_DB=str(tmp_path / "pkg"))
    assert result.returncode == 0
    assert "waived=1" in result.stdout


def test_every_desktop_runs_the_screen_reader_check():
    """The call sits after the desktop case, so no desktop branch can skip it."""
    esac = CONTRACT.index("\nesac\n", CONTRACT.index('case "$desktop" in'))
    call = CONTRACT.index("\nrequire_screen_reader\n")
    assert call > esac
