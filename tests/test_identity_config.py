"""Image identity is declared in tunaos.toml and reaches images through one adapter.

[project], [defaults.branding] and each variant's codename compile to
build_scripts/lib/identity.env, which 90-image-info.sh and the KDE About hook
source. TunaOS's own values pass through the same path as a fork's, so the
stock values below are frozen: they are the literals 90-image-info.sh hard-coded
before the migration (main @ 8b11ad7c). Changing one must be a deliberate edit
here, because every installed system shows them.
"""
from __future__ import annotations

import copy
import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("identity_config_under_test", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)

STOCK_CODENAMES = {
    "yellowfin": "Thunnus albacares", "albacore": "Thunnus alalunga", "skipjack": "Katsuwonus pelamis",
    "wahoo": "Acanthocybium solandri", "bonito": "Sarda sarda", "bonito-rawhide": "Sarda sarda",
    "hummingbird": "Trochilidae", "sailfin": "Istiophorus platypterus", "guppy": "Poecilia reticulata",
    "gurnard": "Chelidonichthys lucerna", "grouper": "Epinephelus marginatus", "marlin": "Makaira nigricans",
    "flounder": "Platichthys flesus", "flounder-sid": "Platichthys flesus",
}
STOCK = {
    "TUNAOS_PROJECT_NAME": "TunaOS", "TUNAOS_PROJECT_ID": "tunaos", "TUNAOS_CPE_VENDOR": "jamesreilly",
    "TUNAOS_HOME_URL": "https://github.com/tuna-os/tunaos",
    "TUNAOS_DOCUMENTATION_URL": "https://github.com/tuna-os/tunaos/tree/main/docs",
    "TUNAOS_SUPPORT_URL": "https://github.com/tuna-os/tunaos/issues/",
    "TUNAOS_BUG_REPORT_URL": "https://github.com/tuna-os/tunaos/issues/",
}


def sourced(adapter_text, tmp_path):
    """What a build script sees after sourcing the adapter."""
    path = tmp_path / "identity.env"
    path.write_text(adapter_text, encoding="utf-8")
    script = ('source "$1"; for k in ' + " ".join(STOCK) + '; do printf "%s=%s\\n" "$k" "${!k}"; done; '
              'for k in "${!TUNAOS_CODENAMES[@]}"; do printf "codename:%s=%s\\n" "$k" "${TUNAOS_CODENAMES[$k]}"; done')
    out = subprocess.run(["bash", "-c", script, "_", str(path)], text=True, capture_output=True, check=True).stdout
    values, codenames = {}, {}
    for line in out.splitlines():
        key, _, value = line.partition("=")
        (codenames if key.startswith("codename:") else values)[key.removeprefix("codename:")] = value
    return values, codenames


def test_stock_identity_is_unchanged_by_the_migration(tmp_path):
    values, codenames = sourced(config.render_identity(config.load()), tmp_path)
    assert values == STOCK
    assert codenames == STOCK_CODENAMES


def test_committed_adapter_matches_the_toml():
    assert (ROOT / "build_scripts/lib/identity.env").read_text(encoding="utf-8") == config.render_identity(config.load())


def test_a_fork_changes_identity_only_in_toml(tmp_path):
    fork = copy.deepcopy(config.load())
    fork["project"] = {"name": "Acme OS", "id": "acmeos", "cpe_vendor": "acme"}
    fork["defaults"]["branding"] = {key: f"https://acme.example/{key}" for key in config.BRANDING_URLS}
    fork["variants"]["yellowfin"]["codename"] = "Wile E"
    values, codenames = sourced(config.render_identity(fork), tmp_path)
    assert values["TUNAOS_PROJECT_NAME"] == "Acme OS"
    assert values["TUNAOS_CPE_VENDOR"] == "acme"
    assert values["TUNAOS_BUG_REPORT_URL"] == "https://acme.example/bug_report"
    assert codenames["yellowfin"] == "Wile E"


@pytest.mark.parametrize("remove", [("project",), ("defaults",), ("variants", "grouper", "codename")])
def test_identity_cannot_be_generated_with_a_gap(remove):
    # A missing value would otherwise surface as an image with no codename or
    # URL, or one that silently kept TunaOS's.
    source = copy.deepcopy(config.load())
    node = source
    for key in remove[:-1]:
        node = node[key]
    del node[remove[-1]]
    with pytest.raises(config.ConfigError):
        config.render_identity(source)


@pytest.mark.parametrize("path,value", [
    (("defaults", "branding", "homepage"), "http://insecure.example"),
    (("defaults", "branding", "support"), 'https://x.example/"quoted"'),
    (("defaults", "branding", "documentation"), "https://x.example/a|b"),
    (("project", "name"), 'Acme "OS"'),
    (("project", "name"), "Acme\nOS"),
    (("project", "id"), "Acme"),
    (("project", "cpe_vendor"), "Acme Corp"),
    (("variants", "yellowfin", "codename"), "Thunnus $(id)"),
])
def test_values_that_would_corrupt_os_release_are_rejected(path, value):
    source = copy.deepcopy(config.load())
    node = source
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    with pytest.raises(config.ConfigError):
        config.validate(source)


def test_codename_stays_out_of_the_build_matrix():
    assert all("codename" not in variant for variant in config.matrix(config.load())["variants"])


def test_kde_about_page_shows_the_configured_project(tmp_path):
    fork = copy.deepcopy(config.load())
    fork["project"]["name"] = "Acme OS"
    fork["defaults"]["branding"]["homepage"] = "https://acme.example/os"
    adapter = tmp_path / "identity.env"
    adapter.write_text(config.render_identity(fork), encoding="utf-8")
    about = tmp_path / "kcm-about-distrorc"
    subprocess.run(["bash", str(ROOT / "build_scripts/desktop/kde-set-look-and-feel.sh"), str(tmp_path / "unused")],
                   env={**os.environ, "TUNAOS_KCM_ABOUT": str(about), "TUNAOS_IDENTITY_ENV": str(adapter)},
                   text=True, capture_output=True, check=True)
    lines = about.read_text(encoding="utf-8").splitlines()
    assert "Website=https://acme.example/os" in lines
    assert "Variant=part of Acme OS" in lines


@pytest.mark.parametrize("written,passes", [("Wile E", True), ("Achillobator", False)])
def test_branding_contract_checks_the_configured_codename(tmp_path, written, passes):
    # The contract once kept its own codename table, so a fork's codename would
    # fail it. It must accept the configured value and still reject a leftover
    # upstream codename.
    fork = copy.deepcopy(config.load())
    fork["variants"]["yellowfin"]["codename"] = "Wile E"
    adapter = tmp_path / "identity.env"
    adapter.write_text(config.render_identity(fork), encoding="utf-8")
    os_release = tmp_path / "os-release"
    os_release.write_text(f'VERSION_CODENAME="{written}"\nPRETTY_NAME="Yellowfin"\n', encoding="utf-8")
    result = subprocess.run(["bash", str(ROOT / "build_scripts/checks/verify-branding.sh"), "yellowfin"],
                            env={**os.environ, "TUNAOS_OS_RELEASE": str(os_release), "TUNAOS_IDENTITY_ENV": str(adapter)},
                            text=True, capture_output=True)
    output = result.stdout + result.stderr
    assert ("ok: VERSION_CODENAME=Wile E" in output) is passes
    assert ("FAIL: VERSION_CODENAME" in output) is not passes
