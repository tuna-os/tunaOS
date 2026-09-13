"""The COSMIC-on-EL10 COPR retires at the EL10 -> EL11 transition, not via Tideforge.

tunaOS#2049 asked one question that outlives the flavor it was filed about:
does Fedora ELN carry COSMIC from the distribution, so that
`yselkowitz/cosmic-epel` ages out when EL10 becomes EL11 instead of needing a
Tideforge packaging project?

Measured, and the answer is yes. COSMIC 1.6.0 is in `eln-extras`: 23 of the 24
names `cosmic.yaml` asks for resolve there, `cosmic-wallpapers` being the only
miss. `fprintd-1.94.5-6.eln158` is in `eln-appstream` on both arches, so the
aarch64 fprintd shortfall that pinned cosmic off arm64 on EL10 (tunaOS#732)
does not reproduce either. `wahoo:cosmic` builds from that section on amd64 and
arm64 with no third-party source of any kind (run 34690922548).

That finding is only worth having if it stays true, and it is the kind that
decays quietly: someone hits a resolution error on ELN, reaches for the
`copr:` block sitting right there in the `el10:` section one screen below, and
the claim in PACKAGE-SOURCING.md becomes false without anyone editing
PACKAGE-SOURCING.md.

So this pins the claim in both directions -- the ELN section carries no
third-party source, the EL10 section still carries the ones the finding is
*about* -- and pins that the inventory names them. A test that only checked
"eln has no copr" would also pass if the whole section were deleted.

Not pinned here: that `scripts/check-package-sources.py` rejects a new `copr:`
block. That check already exists and has its own tests
(tests/test_package_source_policy.py); this is about one specific measured
claim, not the general mechanism.
"""
from __future__ import annotations

import pathlib

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COSMIC = ROOT / "manifests" / "desktops" / "cosmic.yaml"
POLICY = ROOT / "PACKAGE-SOURCING.md"

# The two sources the finding is about, named as PACKAGE-SOURCING.md names them.
COPR_REPO = "yselkowitz/cosmic-epel"
FPRINTD_REPO = "repo.tunaos.org/fprintd/"

# Third-party source keys, matching what check-package-sources.py treats as
# needing admission.
SOURCE_KEYS = ("copr", "ppa", "repos")


@pytest.fixture(scope="module")
def packages():
    doc = yaml.safe_load(COSMIC.read_text(encoding="utf-8")) or {}
    section = doc.get("packages")
    assert isinstance(section, dict), "cosmic.yaml has no packages: mapping"
    return section


def test_the_eln_section_exists(packages):
    """Guard against a vacuous pass: no section, nothing to check."""
    assert "eln" in packages, (
        "manifests/desktops/cosmic.yaml has no packages.eln section. "
        "wahoo:cosmic is built from it (.github/build-config.yml), and every "
        "assertion below examines it."
    )


def test_eln_sources_cosmic_from_the_distribution_only(packages):
    """No copr:, no ppa:, no extra repos: -- that IS the finding."""
    eln = packages["eln"]
    declared = [key for key in SOURCE_KEYS if eln.get(key)]
    assert not declared, (
        f"packages.eln declares {declared!r}. ELN carries COSMIC in eln-extras "
        "and fprintd in eln-appstream, so a third-party source here would mean "
        "either the measurement has gone stale or the el10 block was copied "
        "across. Re-measure against the pinned eln-bootc digest before adding "
        "one, and update PACKAGE-SOURCING.md's rows for "
        f"{COPR_REPO} and {FPRINTD_REPO} if the answer has changed."
    )


def test_the_el10_section_still_carries_what_the_finding_is_about(packages):
    """The claim is 'ELN does not need these', not 'these are gone'.

    EL10 is still sourced from the COPR and the fprintd repo. If that stops
    being true the finding needs rewording, not silently re-scoping.
    """
    el10 = packages["el10"]
    coprs = [entry.get("repo") for entry in el10.get("copr") or []]
    assert COPR_REPO in coprs, (
        f"packages.el10 no longer declares {COPR_REPO}. The ELN finding is "
        "stated as a comparison against EL10; if EL10 has moved, "
        "PACKAGE-SOURCING.md's row needs updating rather than this test "
        "relaxing."
    )
    baseurls = " ".join(str(repo.get("baseurl", "")) for repo in el10.get("repos") or [])
    assert FPRINTD_REPO in baseurls, (
        f"packages.el10 no longer declares the {FPRINTD_REPO} repo -- same "
        "reasoning as the COPR above."
    )


def test_cosmic_wallpapers_is_the_single_measured_miss(packages):
    """The one name ELN lacks is best-effort, and only that one.

    A second entry appearing under optional: means something else stopped
    resolving, and a required name quietly demoted to optional is how a
    desktop ships without a piece of itself.
    """
    eln = packages["eln"]
    assert eln.get("optional") == ["cosmic-wallpapers"], (
        f"packages.eln.optional is {eln.get('optional')!r}; the measurement "
        "recorded exactly one miss (cosmic-wallpapers). Anything else here "
        "needs its own measurement and a note saying what went missing."
    )
    assert "cosmic-wallpapers" not in (eln.get("packages") or []), (
        "cosmic-wallpapers is both required and optional -- the strict list "
        "wins and the build fails on a name ELN does not publish."
    )
    # The session itself is required, not best-effort: an image tagged for a
    # desktop that contains no desktop is tunaOS#858.
    assert "cosmic-session" in (eln.get("packages") or [])


def test_the_sourcing_inventory_records_the_retirement():
    """PACKAGE-SOURCING.md is where a source's fate is recorded.

    Both entries were missing from that inventory entirely until this finding
    landed, despite one of them being the sole source of a whole desktop.
    """
    text = POLICY.read_text(encoding="utf-8")
    assert COPR_REPO in text, (
        f"PACKAGE-SOURCING.md does not name {COPR_REPO}. It is declared twice "
        "in cosmic.yaml's el10 section and supplies the entire COSMIC desktop "
        "there; an inventory that omits it understates the migration surface."
    )
    assert FPRINTD_REPO in text, (
        f"PACKAGE-SOURCING.md does not name the {FPRINTD_REPO} repo."
    )
    assert "2049" in text, (
        "the rows must cite the issue the measurement came from, so the next "
        "reader can check the evidence rather than trusting the summary"
    )
