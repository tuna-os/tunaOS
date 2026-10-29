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
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))
SPEC = importlib.util.spec_from_file_location("identity_config_under_test", ROOT / "scripts/lib/tunaos_config.py")
config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(config)

from test_anime_finalization import Image  # noqa: E402

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
    "TUNAOS_WEBSITE": "https://tunaos.org", "TUNAOS_DOCS_URL": "https://tunaos.org/docs",
    "TUNAOS_COUNTME_ENDPOINT": "https://countme.tunaos.org/v1/report",
    "TUNAOS_COUNTME_METRICS_URL": "https://tunaos.org/metrics",
    "TUNAOS_FLATPAK_REMOTE_URL": "https://tunaos.org/flatpak/tuna-os.flatpakrepo",
}


# A fork that renamed itself and changed every [project] value a rename touches.
# countme_endpoint is left out on purpose: absent means the image never reports.
ACME_PROJECT = {"name": "Acme OS", "id": "acmeos", "cpe_vendor": "acme",
                "website": "https://acme.example", "docs_url": "https://acme.example/docs"}


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
    fork["project"] = dict(ACME_PROJECT)
    fork["defaults"]["branding"] = {**{key: f"https://acme.example/{key}" for key in config.BRANDING_URLS},
                                    "plymouth": "acme"}
    fork["variants"]["yellowfin"]["codename"] = "Wile E"
    values, codenames = sourced(config.render_identity(fork), tmp_path)
    assert values["TUNAOS_PROJECT_NAME"] == "Acme OS"
    assert values["TUNAOS_CPE_VENDOR"] == "acme"
    assert values["TUNAOS_BUG_REPORT_URL"] == "https://acme.example/bug_report"
    assert codenames["yellowfin"] == "Wile E"


@pytest.mark.parametrize("remove", [("project",), ("defaults",), ("variants", "grouper", "codename"),
                                    ("project", "website"), ("project", "docs_url")])
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


def test_generate_identity_reports_an_unwritable_target_without_a_traceback(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/config.py"), "generate-identity",
         "--output", str(tmp_path / "missing-dir/identity.env")],
        text=True, capture_output=True)
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert str(tmp_path / "missing-dir/identity.env") in result.stderr


@pytest.mark.parametrize("path,value", [
    (("defaults", "branding", "homepage"), "http://insecure.example"),
    (("defaults", "branding", "support"), 'https://x.example/"quoted"'),
    (("defaults", "branding", "documentation"), "https://x.example/a|b"),
    (("defaults", "branding", "homepage"), "https://user:secret@example.com/path"),
    (("defaults", "branding", "homepage"), "https://example.com:not-a-port/path"),
    (("project", "name"), 'Acme "OS"'),
    (("project", "name"), "Acme\nOS"),
    (("project", "id"), "Acme"),
    (("project", "cpe_vendor"), "Acme Corp"),
    (("project", "website"), "http://acme.example"),
    (("project", "website"), "https://acme.example/"),
    (("project", "docs_url"), "https://acme.example/docs?x=1"),
    (("project", "docs_url"), "https://acme.example/docs#top"),
    (("project", "countme_endpoint"), "http://countme.acme.example/v1/report"),
    (("project", "countme_metrics_url"), "https://acme.example/m|x"),
    (("flatpak_preinstall", "remote_url"), "https://acme.example/flatpak/remote.txt"),
    (("flatpak_preinstall", "remote_url"), "http://acme.example/flatpak/acme.flatpakrepo"),
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


def test_identity_stays_out_of_the_build_matrix():
    assert all("codename" not in variant and "branding" not in variant
               for variant in config.matrix(config.load())["variants"])


def test_kde_about_page_shows_the_configured_project(tmp_path):
    fork = copy.deepcopy(config.load())
    fork["project"] = dict(ACME_PROJECT)
    fork["defaults"]["branding"]["homepage"] = "https://acme.example/os"
    adapter = tmp_path / "identity.env"
    adapter.write_text(config.render_identity(fork), encoding="utf-8")
    about = tmp_path / "kcm-about-distrorc"
    subprocess.run(["bash", str(ROOT / "build_scripts/desktop/kde-set-look-and-feel.sh"), str(tmp_path / "unused")],
                   env={**os.environ, "TUNAOS_KCM_ABOUT": str(about), "TUNAOS_IDENTITY_ENV": str(adapter),
                        "TUNAOS_IDENTITY_TEST_OVERRIDE": "1"},
                   text=True, capture_output=True, check=True)
    lines = about.read_text(encoding="utf-8").splitlines()
    assert "Website=https://acme.example/os" in lines
    assert "Variant=part of Acme OS" in lines

def test_kde_about_rejects_a_non_file_identity_adapter(tmp_path):
    about = tmp_path / "kcm-about-distrorc"
    result = subprocess.run(
        ["bash", str(ROOT / "build_scripts/desktop/kde-set-look-and-feel.sh"),
         str(tmp_path / "unused")],
        env={**os.environ, "TUNAOS_KCM_ABOUT": str(about),
             "TUNAOS_IDENTITY_ENV": str(tmp_path),
             "TUNAOS_IDENTITY_TEST_OVERRIDE": "1"},
        text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "identity adapter is missing or unreadable" in result.stderr
    assert not about.exists()

def test_kde_about_rejects_identity_override_outside_tests(tmp_path):
    adapter = tmp_path / "identity.env"
    adapter.write_text("TUNAOS_PROJECT_NAME=Untrusted\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(ROOT / "build_scripts/desktop/kde-set-look-and-feel.sh"),
         str(tmp_path / "unused")],
        env={**os.environ, "TUNAOS_KCM_ABOUT": str(tmp_path / "about"),
             "TUNAOS_IDENTITY_ENV": str(adapter)},
        text=True, capture_output=True,
    )
    assert result.returncode != 0
    assert "TUNAOS_IDENTITY_ENV is test-only" in result.stderr


def test_branding_contract_rejects_identity_override_outside_tests(tmp_path):
    adapter = tmp_path / "identity.env"
    adapter.write_text(config.render_identity(config.load()), encoding="utf-8")
    result = subprocess.run(
        ["bash", str(ROOT / "build_scripts/checks/verify-branding.sh"), "yellowfin"],
        env={**os.environ, "TUNAOS_IDENTITY_ENV": str(adapter)},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "TUNAOS_IDENTITY_ENV is test-only" in result.stderr


def test_rendered_identity_always_quotes_hyphenated_subscripts():
    rendered = config.render_identity(config.load())
    assert '["bonito-rawhide"]=' in rendered


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
                            env={**os.environ, "TUNAOS_OS_RELEASE": str(os_release),
                                 "TUNAOS_IDENTITY_ENV": str(adapter), "TUNAOS_IDENTITY_TEST_OVERRIDE": "1"},
                            text=True, capture_output=True)
    output = result.stdout + result.stderr
    assert ("ok: VERSION_CODENAME=Wile E" in output) is passes
    assert ("FAIL: VERSION_CODENAME" in output) is not passes

def test_installed_branding_verifier_ignores_identity_override(tmp_path):
    installed = tmp_path / "usr/libexec/tunaos/verify-branding"
    installed.parent.mkdir(parents=True)
    installed.write_bytes((ROOT / "build_scripts/checks/verify-branding.sh").read_bytes())
    adapter = tmp_path / "attacker.env"
    adapter.write_text('declare -A TUNAOS_CODENAMES=([yellowfin]="spoofed")\n')
    os_release = tmp_path / "os-release"
    os_release.write_text('VERSION_CODENAME="spoofed"\nPRETTY_NAME="Yellowfin"\n')
    result = subprocess.run(
        ["bash", str(installed), "yellowfin"],
        env={**os.environ, "TUNAOS_OS_RELEASE": str(os_release),
             "TUNAOS_IDENTITY_ENV": str(adapter)},
        text=True, capture_output=True,
    )
    output = result.stdout + result.stderr
    assert "ok: VERSION_CODENAME=spoofed" not in output
    assert "no identity adapter readable" in output


# The hand-written variant-identity.tsv rows before the migration (main @ 8b11ad7c).
STOCK_VARIANT_ROWS = """\
yellowfin	#FFC702	yellow	AlmaLinux Kitten	the yellow petal of the AlmaLinux flower
albacore	#0069DA	blue	AlmaLinux	the blue petal of the AlmaLinux flower
skipjack	#932279	purple	CentOS Stream	CentOS purple
wahoo	#294172	blue	Fedora ELN	Fedora's deep blue
bonito	#51A2DA	blue	Fedora	Fedora's light blue
hummingbird	#1E9E8A	teal	Fedora Hummingbird	a hummingbird's teal
sailfin	#73BA25	green	openSUSE Tumbleweed	openSUSE green
guppy	#54487A	purple	Gentoo	Gentoo purple
bonito-rawhide	#3C6EB4	blue	Fedora Rawhide	Fedora blue
gurnard	#3689E6	blue	Ubuntu + Pantheon	elementary's blueberry
grouper	#E95420	orange	Ubuntu	Ubuntu orange
marlin	#1793D1	blue	Arch Linux	Arch blue
flounder	#D70751	red	Debian	the Debian swirl
flounder-sid	#A80030	red	Debian Sid	Debian's darker red
""".splitlines()


# The variant -> theme case in plymouth-set-theme.sh before #3668 F3d.
STOCK_PLYMOUTH = {
    "yellowfin": "tropical-fish", "albacore": "tunaos", "skipjack": "sushi", "wahoo": "carp-streamer",
    "bonito": "fishing-pole", "hummingbird": "bird", "sailfin": "sailboat", "guppy": "rainbow",
    "bonito-rawhide": "dragon", "gurnard": "robot", "grouper": "coral", "marlin": "rocket",
    "flounder": "pufferfish", "flounder-sid": "radioactive",
}
# canonical_variant() in 90-image-info.sh before #3668 F3d.
STOCK_ALIASES = {
    "almalinux-kitten": "yellowfin", "almalinux": "albacore", "centos": "skipjack", "fedora": "bonito",
    "opensuse": "sailfin", "tumbleweed": "sailfin", "gentoo": "guppy", "elementary": "gurnard",
    "ubuntu": "grouper", "arch": "marlin", "archlinux": "marlin", "debian": "flounder",
}


def data_rows(tsv):
    return [line for line in tsv.splitlines() if line and not line.startswith("#")]


def test_stock_variant_branding_is_unchanged_by_the_migration():
    rows = [row.split("\t") for row in data_rows(config.render_variant_identity(config.load()))]
    assert ["\t".join(row[:5]) for row in rows] == STOCK_VARIANT_ROWS
    assert {row[0]: row[5] for row in rows} == STOCK_PLYMOUTH


def test_stock_aliases_are_unchanged_by_the_migration():
    rows = data_rows(config.render_variant_aliases(config.load()))
    assert dict(row.split("\t") for row in rows) == STOCK_ALIASES


@pytest.mark.parametrize("adapter", ["variant-identity", "variant-aliases"])
def test_committed_variant_adapters_match_the_toml(adapter):
    render = getattr(config, "render_" + adapter.replace("-", "_"))
    committed = (ROOT / f"build_scripts/lib/{adapter}.tsv").read_text(encoding="utf-8")
    assert committed == render(config.load())


def test_a_fork_changes_variant_branding_only_in_toml():
    fork = copy.deepcopy(config.load())
    fork["variants"]["marlin"]["branding"] = {"accent": "#123ABC", "gnome_accent": "green",
                                              "base": "Acme Linux", "homage": "Acme's own green",
                                              "plymouth": "acme"}
    rows = data_rows(config.render_variant_identity(fork))
    assert "marlin\t#123ABC\tgreen\tAcme Linux\tAcme's own green\tacme" in rows


def test_a_forks_aliases_fold_onto_its_variant():
    fork = copy.deepcopy(config.load())
    fork["variants"]["marlin"]["aliases"] = ["acme"]
    aliases = dict(row.split("\t") for row in data_rows(config.render_variant_aliases(fork)))
    assert aliases["acme"] == "marlin" and "arch" not in aliases


def test_a_forks_plymouth_choice_reaches_the_build(tmp_path):
    """plymouth-set-theme.sh reads the theme, aliases and default from TOML."""
    fork = copy.deepcopy(config.load())
    fork["defaults"]["branding"]["plymouth"] = "acme-default"
    fork["variants"]["marlin"]["branding"]["plymouth"] = "acme-rocket"
    lib = tmp_path / "build_scripts/lib"
    lib.mkdir(parents=True)
    shutil.copy2(ROOT / "build_scripts/plymouth-set-theme.sh", tmp_path / "build_scripts")
    (lib / "identity.env").write_text(config.render_identity(fork))
    (lib / "variant-identity.tsv").write_text(config.render_variant_identity(fork))
    (lib / "variant-aliases.tsv").write_text(config.render_variant_aliases(fork))

    def theme(name):
        return subprocess.run(["bash", str(tmp_path / "build_scripts/plymouth-set-theme.sh"), "--print", name],
                              check=True, capture_output=True, text=True).stdout.strip()

    assert theme("marlin") == theme("archlinux") == "acme-rocket"
    assert theme("grouper") == "coral"
    assert theme("not-a-variant") == "acme-default"


def test_variant_identity_cannot_be_generated_with_a_gap():
    source = copy.deepcopy(config.load())
    del source["variants"]["grouper"]["branding"]
    with pytest.raises(config.ConfigError):
        config.render_variant_identity(source)


@pytest.mark.parametrize("key,value", [
    ("accent", "#ffc702"),            # readers expect canonical uppercase hex
    ("accent", "FFC702"),
    ("gnome_accent", "magenta"),      # GNOME has a fixed list of accents
    ("base", 'Alma "Kitten"'),        # lands in a JSON heredoc (fastfetch)
    ("homage", "a `whale`"),
    ("plymouth", "../rocket"),        # a directory name, joined onto a path
    ("plymouth", "Rocket"),
])
def test_unusable_variant_branding_is_rejected(key, value):
    source = copy.deepcopy(config.load())
    source["variants"]["yellowfin"]["branding"][key] = value
    with pytest.raises(config.ConfigError):
        config.validate(source)


FORK_URLS = {
    "HOME_URL": "https://acme.example/?a=1&b=2&c=3",
    "DOCUMENTATION_URL": "https://acme.example/docs?x=1&y=2",
    "SUPPORT_URL": "https://acme.example/help?topic=a&lang=en",
    "BUG_REPORT_URL": "https://acme.example/bugs?label=b&state=open",
}


def fork_identity():
    fork = copy.deepcopy(config.load())
    fork["project"] = dict(ACME_PROJECT)
    # Change only the URLs: the table carries other required keys (plymouth).
    fork["defaults"]["branding"].update(homepage=FORK_URLS["HOME_URL"], documentation=FORK_URLS["DOCUMENTATION_URL"],
                                        support=FORK_URLS["SUPPORT_URL"], bug_report=FORK_URLS["BUG_REPORT_URL"])
    return config.render_identity(fork)


def url_findings(tmp_path, written):
    """Run the branding contract on an os-release carrying `written` URLs and return its URL lines."""
    adapter = tmp_path / "identity.env"
    adapter.write_text(fork_identity(), encoding="utf-8")
    os_release = tmp_path / "os-release"
    os_release.write_text("".join(f'{key}="{value}"\n' for key, value in written.items()), encoding="utf-8")
    result = subprocess.run(["bash", str(ROOT / "build_scripts/checks/verify-branding.sh"), "yellowfin"],
                            env={**os.environ, "TUNAOS_OS_RELEASE": str(os_release),
                                 "TUNAOS_IDENTITY_ENV": str(adapter), "TUNAOS_IDENTITY_TEST_OVERRIDE": "1"},
                            text=True, capture_output=True)
    return [line.strip() for line in (result.stdout + result.stderr).splitlines()
            if line.strip().startswith(tuple(f"{p}: {key}" for p in ("ok", "FAIL") for key in FORK_URLS))]


def test_branding_contract_accepts_the_configured_urls_of_a_fork(tmp_path):
    # A fork that names its own project must not need tuna-os in its URLs.
    assert url_findings(tmp_path, FORK_URLS) == [f"ok: {key}={value}" for key, value in FORK_URLS.items()]


@pytest.mark.parametrize("wrong", [
    STOCK["TUNAOS_HOME_URL"],               # TunaOS's value left on a fork
    "https://help.ubuntu.com/",             # the upstream value
    "https://evil.example/tunaos",          # contains the old substring but is not the configured URL
])
def test_branding_contract_rejects_a_url_other_than_the_configured_one(tmp_path, wrong):
    written = {**FORK_URLS, "SUPPORT_URL": wrong}
    # Failures go to stderr and passes to stdout, so compare as sets.
    expected = {f"ok: {key}={value}" for key, value in FORK_URLS.items() if key != "SUPPORT_URL"}
    expected.add(f"FAIL: SUPPORT_URL is '{wrong}', want '{FORK_URLS['SUPPORT_URL']}'")
    assert set(url_findings(tmp_path, written)) == expected


def test_branding_contract_still_matches_stock_urls(tmp_path):
    adapter = tmp_path / "identity.env"
    adapter.write_text(config.render_identity(config.load()), encoding="utf-8")
    os_release = tmp_path / "os-release"
    os_release.write_text("".join(f'{key}="{STOCK["TUNAOS_" + key]}"\n' for key in FORK_URLS), encoding="utf-8")
    result = subprocess.run(["bash", str(ROOT / "build_scripts/checks/verify-branding.sh"), "yellowfin"],
                            env={**os.environ, "TUNAOS_OS_RELEASE": str(os_release),
                                 "TUNAOS_IDENTITY_ENV": str(adapter), "TUNAOS_IDENTITY_TEST_OVERRIDE": "1"},
                            text=True, capture_output=True)
    for key in FORK_URLS:
        assert f"ok: {key}={STOCK['TUNAOS_' + key]}" in result.stdout
    assert "FAIL: HOME_URL" not in result.stderr


@pytest.mark.parametrize("preexisting", [True, False], ids=["replaced", "appended"])
def test_urls_with_ampersands_reach_os_release_verbatim(tmp_path, preexisting):
    # osr_set writes through a sed replacement, where `&` means "the matched
    # text". A valid URL query string must survive both the replace and the
    # append path, in both os-release files.
    image = Image(tmp_path)
    (image.context / "build_scripts/lib/identity.env").write_text(fork_identity(), encoding="utf-8")
    if preexisting:
        seed = "".join(f'{key}="https://upstream.example/old"\n' for key in FORK_URLS)
        for path in ("usr/lib/os-release", "etc/os-release"):
            (image.root / path).write_text('NAME="Fixture"\n' + seed)
    image.info()
    for path in ("usr/lib/os-release", "etc/os-release"):
        lines = (image.root / path).read_text().splitlines()
        for key, value in FORK_URLS.items():
            assert [line for line in lines if line.startswith(key + "=")] == [f'{key}="{value}"']


@pytest.mark.parametrize("variant,image_name,fork,expected", [
    ("yellowfin", "yellowfin", False, "cpe:/o:jamesreilly:yellowfin-tunaos"),
    # The product is the publish name, as before the migration; the variant key
    # selects only the codename.
    ("bonito-rawhide", "bonito", False, "cpe:/o:jamesreilly:bonito-tunaos"),
    ("yellowfin", "yellowfin", True, "cpe:/o:acme:yellowfin-acmeos"),
])
def test_cpe_name_comes_from_the_adapter_and_the_image_name(tmp_path, variant, image_name, fork, expected):
    image = Image(tmp_path, variant=variant)
    image.env["IMAGE_NAME"] = image_name
    if fork:
        (image.context / "build_scripts/lib/identity.env").write_text(fork_identity(), encoding="utf-8")
    image.info()
    for path in ("usr/lib/os-release", "etc/os-release"):
        lines = (image.root / path).read_text().splitlines()
        assert [line for line in lines if line.startswith("CPE_NAME=")] == [f'CPE_NAME="{expected}"']


def project_of(**changes):
    source = copy.deepcopy(config.load())
    source["project"].update(changes)
    for key, value in list(source["project"].items()):
        if value is None:
            del source["project"][key]
    return source


def test_a_missing_site_key_is_named():
    source = copy.deepcopy(config.load())
    del source["project"]["website"]
    with pytest.raises(config.ConfigError, match=r"project: missing keys \['website'\]"):
        config.validate(source)


def test_a_fork_cannot_keep_the_stock_usage_report_endpoint():
    """The service counts TunaOS's variant and flavor ids. A renamed fork that kept the
    endpoint would report its images as those cells, so validation names the key."""
    source = project_of(name="Acme OS", id="acmeos", cpe_vendor="acme")
    with pytest.raises(config.ConfigError, match=r"project\.countme_endpoint: .*countme\.tunaos\.org.*'Acme OS'/'acmeos'.*\"\""):
        config.validate(source)
    renamed_only = project_of(name="Acme OS")
    with pytest.raises(config.ConfigError, match="project.countme_endpoint"):
        config.validate(renamed_only)


@pytest.mark.parametrize("endpoint", ["", "https://stats.acme.example/v1/report"])
def test_a_fork_may_empty_or_replace_the_usage_report_endpoint(endpoint, tmp_path):
    source = project_of(name="Acme OS", id="acmeos", cpe_vendor="acme", countme_endpoint=endpoint,
                        countme_metrics_url=None)
    config.validate(source)
    values, _ = sourced(config.render_identity(source), tmp_path)
    assert values["TUNAOS_COUNTME_ENDPOINT"] == endpoint
    assert values["TUNAOS_COUNTME_METRICS_URL"] == ""


def test_an_absent_endpoint_is_disabled_not_the_stock_one(tmp_path):
    source = project_of(countme_endpoint=None, countme_metrics_url=None)
    values, _ = sourced(config.render_identity(source), tmp_path)
    assert values["TUNAOS_COUNTME_ENDPOINT"] == "" and values["TUNAOS_COUNTME_METRICS_URL"] == ""


def test_a_metrics_page_without_an_endpoint_is_rejected():
    with pytest.raises(config.ConfigError, match="project.countme_metrics_url: set without project.countme_endpoint"):
        config.validate(project_of(countme_endpoint=""))


def test_a_fork_flatpak_remote_reaches_the_adapter_and_empty_registers_none(tmp_path):
    source = copy.deepcopy(config.load())
    source["flatpak_preinstall"]["remote_url"] = "https://acme.example/flatpak/acme.flatpakrepo"
    values, _ = sourced(config.render_identity(source), tmp_path)
    assert values["TUNAOS_FLATPAK_REMOTE_URL"] == "https://acme.example/flatpak/acme.flatpakrepo"
    del source["flatpak_preinstall"]["remote_url"]
    values, _ = sourced(config.render_identity(source), tmp_path)
    assert values["TUNAOS_FLATPAK_REMOTE_URL"] == ""


# ── Live ISO, ISO media and Flatpak remote: the name comes from the adapter ─────

LIVE_SRC = ROOT / "live-iso/common/src"


def heredocs(path, tags):
    """(tag, quoted, body) for each heredoc of `path` whose tag is in `tags`, from the script text."""
    import re
    lines = path.read_text(encoding="utf-8").split("\n")
    found, i = [], 0
    while i < len(lines):
        match = re.search(r"<<-?(['\"]?)([A-Z_]+)\1\s*$", lines[i])
        if match and match.group(2) in tags:
            j = i + 1
            while lines[j] != match.group(2):
                j += 1
            found.append((match.group(2), bool(match.group(1)), "\n".join(lines[i + 1:j]) + "\n"))
            i = j
        i += 1
    return found


def rendered_heredocs(path, tags, project_name):
    """What the script writes, as bash expands it with TUNAOS_PROJECT_NAME set."""
    out = []
    for tag, quoted, body in heredocs(path, tags):
        if quoted:
            out.append(body)
            continue
        out.append(subprocess.run(["bash", "-c", f"TUNAOS_PROJECT_NAME={project_name!r}\ncat <<{tag}\n{body}{tag}\n"],
                                  text=True, capture_output=True, check=True).stdout)
    return out


@pytest.mark.parametrize("desktop", ["kde", "cosmic", "xfce", "pantheon", "gnome"])
def test_live_iso_launcher_names_the_configured_project(desktop):
    script = LIVE_SRC / f"desktop-{desktop}.sh"
    stock = rendered_heredocs(script, {"DESKEOF"}, "TunaOS")
    assert len(stock) == 1 and "Name=Install TunaOS\n" in stock[0]       # byte for byte what shipped
    fork = rendered_heredocs(script, {"DESKEOF"}, "Acme OS")[0]
    assert "Name=Install Acme OS\n" in fork and "TunaOS" not in fork


def test_live_iso_gnome_extension_and_polkit_action_name_the_configured_project():
    stock = rendered_heredocs(LIVE_SRC / "desktop-gnome.sh", {"METADATAEOF"}, "TunaOS")[0]
    assert json.loads(stock)["name"] == "TunaOS Live Installer"
    assert json.loads(rendered_heredocs(LIVE_SRC / "desktop-gnome.sh", {"METADATAEOF"}, "Acme OS")[0])["name"] == "Acme OS Live Installer"
    policy = rendered_heredocs(LIVE_SRC / "customize-live.sh", {"POLICYEOF"}, "TunaOS")[0]
    assert "<description>Install TunaOS to a disk</description>" in policy
    assert "<description>Install Acme OS to a disk</description>" in rendered_heredocs(
        LIVE_SRC / "customize-live.sh", {"POLICYEOF"}, "Acme OS")[0]


def test_customize_live_reads_the_adapter_before_any_adapter_runs_and_has_no_remote_literal():
    text = (LIVE_SRC / "customize-live.sh").read_text(encoding="utf-8")
    detect_only = text.index("TUNA_DETECT_ONLY")
    assert detect_only < text.index("identity-config.env") < text.index('source "${SCRIPT_DIR}/desktop-${DESKTOP}.sh"')
    assert "tunaos.org/flatpak" not in text and "TUNAOS_FLATPAK_REMOTE_URL" in text
    for script in sorted(LIVE_SRC.glob("desktop-*.sh")):
        assert "Install TunaOS" not in script.read_text(encoding="utf-8"), script.name


def test_customize_live_refuses_an_image_without_the_identity_adapter(tmp_path):
    root = tmp_path / "root"
    (root / "usr/share/wayland-sessions").mkdir(parents=True)
    result = subprocess.run(["bash", str(LIVE_SRC / "customize-live.sh")], capture_output=True, text=True,
                            env={**os.environ, "TUNA_SESSION_ROOT": str(root)})
    assert result.returncode != 0 and "identity-config.env is missing" in result.stderr


def media_names(identity_text, tmp_path, variant="yellowfin", suffix="kde", flavor="kde-nvidia"):
    """Evaluate the real MEDIA_NAME lines of both ISO builders under a given adapter."""
    adapter = tmp_path / "identity.env"
    adapter.write_text(identity_text, encoding="utf-8")
    group = (ROOT / "scripts/build-iso-group.sh").read_text(encoding="utf-8")
    names = group[group.index("# ── Names"):group.index('echo "==> Building grouped ISO')]
    tacklebox = [line for line in (ROOT / "scripts/build-iso-tacklebox.sh").read_text(encoding="utf-8").splitlines()
                 if line.startswith("MEDIA_NAME=")]
    assert len(tacklebox) == 1
    script = (f'. "{ROOT}/scripts/lib/common.sh" >/dev/null 2>&1; . "{adapter}"\n'
              f'VARIANT={variant}; FLAVOR={flavor}\n'
              f'GROUP_SUFFIX={suffix}\n{names}\nprintf "%s\\n" "$MEDIA_NAME"\n'
              f'GROUP_SUFFIX=\n{names}\nprintf "%s\\n" "$MEDIA_NAME"\n{tacklebox[0]}\nprintf "%s\\n" "$MEDIA_NAME"\n')
    return subprocess.run(["bash", "-c", script], text=True, capture_output=True, check=True).stdout.splitlines()


def test_iso_media_names_keep_their_stock_text_and_follow_a_fork(tmp_path):
    assert media_names((ROOT / "build_scripts/lib/identity.env").read_text(encoding="utf-8"), tmp_path) == [
        "TunaOS Yellowfin Kde", "TunaOS Yellowfin", "tunaos-yellowfin-kde-nvidia"]
    fork = copy.deepcopy(config.load())
    fork["project"] = dict(ACME_PROJECT)
    assert media_names(config.render_identity(fork), tmp_path) == [
        "Acme OS Yellowfin Kde", "Acme OS Yellowfin", "acmeos-yellowfin-kde-nvidia"]


def flatpak_remote(tmp_path, identity_text):
    """Run the real tuna-flatpak-remote.sh with /etc redirected and curl recorded, not fetched."""
    tree = tmp_path / "tree"
    (tree / "build_scripts/desktop").mkdir(parents=True)
    (tree / "build_scripts/lib").mkdir(parents=True)
    (tree / "build_scripts/lib/identity.env").write_text(identity_text, encoding="utf-8")
    source = (ROOT / "build_scripts/desktop/tuna-flatpak-remote.sh").read_text(encoding="utf-8")
    (tree / "build_scripts/desktop/tuna-flatpak-remote.sh").write_text(source.replace("/etc/flatpak", f"{tree}/etc/flatpak"))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;; http*) url="$1";; esac; shift; done\n'
                    f'echo "$url" >> "{tmp_path}/curl.log"; echo "[Flatpak Repo]" > "$out"\n')
    curl.chmod(0o755)
    result = subprocess.run(["bash", "-c", 'source "$1"', "_", str(tree / "build_scripts/desktop/tuna-flatpak-remote.sh")],
                            text=True, capture_output=True, env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})
    log = (tmp_path / "curl.log").read_text().split() if (tmp_path / "curl.log").exists() else []
    return result, log, tree / "etc/flatpak/remotes.d"


def test_tuna_flatpak_remote_follows_the_configured_url(tmp_path):
    stock = (ROOT / "build_scripts/lib/identity.env").read_text(encoding="utf-8")
    result, log, remotes = flatpak_remote(tmp_path / "stock", stock)
    assert result.returncode == 0, result.stderr
    assert log == ["https://tunaos.org/flatpak/tuna-os.flatpakrepo", "https://dl.flathub.org/repo/flathub.flatpakrepo"]
    assert (remotes / "tuna-os.flatpakrepo").exists()

    fork = copy.deepcopy(config.load())
    fork["flatpak_preinstall"]["remote_url"] = "https://acme.example/flatpak/acme.flatpakrepo"
    result, log, _ = flatpak_remote(tmp_path / "fork", config.render_identity(fork))
    assert result.returncode == 0, result.stderr
    assert log[0] == "https://acme.example/flatpak/acme.flatpakrepo"

    del fork["flatpak_preinstall"]["remote_url"]
    result, log, remotes = flatpak_remote(tmp_path / "none", config.render_identity(fork))
    assert result.returncode == 0, result.stderr
    assert log == ["https://dl.flathub.org/repo/flathub.flatpakrepo"] and not (remotes / "tuna-os.flatpakrepo").exists()


def test_tuna_flatpak_remote_without_the_adapter_fails_loudly(tmp_path):
    result, log, _ = flatpak_remote(tmp_path, "")
    (tmp_path / "tree/build_scripts/lib/identity.env").unlink()
    again = subprocess.run(["bash", "-c", 'source "$1"', "_", str(tmp_path / "tree/build_scripts/desktop/tuna-flatpak-remote.sh")],
                           text=True, capture_output=True)
    assert again.returncode != 0 and "identity.env is missing" in again.stderr


@pytest.mark.parametrize("adapter_name", ["identity.env", "image-packages.tsv"])
def test_regenerating_an_adapter_changes_the_layer_cache_key(tmp_path, adapter_name):
    """Generated adapters are bind-mounted context that changes no *.sh file.

    Run the real build engine against a copy of the tracked sources, with a stub
    `podman` that only records its arguments, and compare the BUILD_SCRIPTS_HASH
    build argument before and after the adapter's bytes change.
    """
    context = tmp_path / "context"
    tracked = subprocess.check_output(["git", "-C", str(ROOT), "ls-files", "-z"], text=True).split("\0")
    for relative in filter(None, tracked):
        if relative.split("/", 1)[0] in {"docs", "tests", "_upstream-snapshots", "system_files", "live-iso", ".spektacular"}:
            continue
        source = ROOT / relative
        if source.is_dir():
            continue
        (context / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, context / relative, follow_symlinks=False)
    subprocess.run(["git", "init", "-q", str(context)], check=True)
    subprocess.run(["git", "-C", str(context), "add", "--all"], check=True)
    binaries = tmp_path / "bin"
    binaries.mkdir()
    log = tmp_path / "builder.log"
    (binaries / "podman").write_text('#!/bin/bash\nprintf "%s\\n" "$@" >>"$BUILDER_LOG"\n')
    (binaries / "podman").chmod(0o755)
    env = {**os.environ, "BUILDER_LOG": str(log), "PATH": f"{binaries}{os.pathsep}{os.environ['PATH']}",
           "IMAGE_TAG": "localhost/acme/yellowfin:gnome", "VARIANT": "yellowfin", "PUBLIC_IMAGE_NAME": "yellowfin",
           "CONTAINERFILE": "Containerfile.el10", "BASE_IMAGE": "localhost/base:1", "PLATFORM": "linux/amd64",
           "DESKTOP_FLAVOR": "gnome", "TUNAOS_IMAGE_FLAVOR": "gnome", "ENABLE_HWE": "0", "ENABLE_NVIDIA": "0",
           "ENABLE_ASAHI": "0", "ENABLE_SSHD": "0", "IMAGE_REGISTRY": "localhost", "REPO_ORGANIZATION": "acme",
           "USE_CACHE": "0", "IS_CI": "0", "SKIP_RECHUNK": "1", "SKIP_SUBMODULES": "1"}
    env.pop("TUNAOS_BUILD_CONFIG", None)

    def cache_key():
        log.write_text("")
        result = subprocess.run(["bash", "scripts/build-image-inner.sh"], cwd=context, env=env,
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr
        return next(arg for arg in log.read_text().splitlines() if arg.startswith("BUILD_SCRIPTS_HASH="))

    first = cache_key()
    assert len(first.split("=", 1)[1]) == 16
    assert cache_key() == first
    adapter = context / "build_scripts/lib" / adapter_name
    adapter.write_text(adapter.read_text(encoding="utf-8") + "# regenerated\n", encoding="utf-8")
    assert cache_key() != first
