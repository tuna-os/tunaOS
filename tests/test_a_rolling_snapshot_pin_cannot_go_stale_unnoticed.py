"""A datestamped snapshot keeps returning 200 long after it stops working.

check-package-repo-pins.py asks whether a pin RESOLVES. For an immutable
snapshot of a stable release that is the whole question. For a snapshot of a
ROLLING distribution it is the wrong one.

Fedora Hummingbird is a rolling release tracking Fedora Rawhide -- not Fedora
43, whatever its .fc43 dist tags suggest (docs/HUMMINGBIRD.md). tunaOS pins two
halves of it independently: the base image by digest, and the package snapshot
by datestamp. They drift apart with every upstream roll, and the drift does not
look like a pin problem.

Measured on 2026-08-25: the 20251124 snapshot served gtk4 but not the harfbuzz
gtk4 requires. dnf reported gtk4 and 17 other packages as having BROKEN
dependencies rather than being unavailable, --skip-unavailable dropped them
without failing, and hummingbird:gnome was published with 410 packages and no
GNOME in it. Every pin in that build resolved; nothing was red anywhere.
"""

import datetime
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "cprp", ROOT / "scripts" / "check-package-repo-pins.py")
cprp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cprp)

TODAY = datetime.date(2026, 8, 25)
HB = "https://repo.tunaos.org/hummingbird/20251124-x86_64/repodata/repomd.xml"


def test_a_datestamped_pin_reports_its_age():
    age = cprp.snapshot_age_days(HB, today=TODAY)
    assert age is not None, "the hummingbird snapshot datestamp was not parsed"
    assert age == (TODAY - datetime.date(2025, 11, 24)).days == 274


def test_the_live_hummingbird_pin_is_past_the_failing_threshold():
    """Not hypothetical: this is the pin in build_scripts/10-base-packages.sh."""
    assert cprp.snapshot_age_days(HB, today=TODAY) >= cprp.SNAPSHOT_FAIL_DAYS


def test_an_undated_pin_is_left_alone():
    """Most pins carry no datestamp and must not be aged or flagged."""
    for url in (
        "https://copr.fedorainfracloud.org/api_3/project?ownername=a&projectname=b",
        "https://repo.tunaos.org/repo/10/x86_64/repodata/repomd.xml",
        "https://download.opensuse.org/repositories/X/xUbuntu_24.04/Release.key",
    ):
        assert cprp.snapshot_age_days(url, today=TODAY) is None, url


def test_a_number_that_is_not_a_date_is_not_treated_as_one():
    assert cprp.snapshot_age_days(
        "https://example.invalid/x/20259999-x86_64/repodata/repomd.xml",
        today=TODAY) is None


def test_a_fresh_snapshot_passes_both_thresholds():
    fresh = "https://repo.tunaos.org/hummingbird/20260820-x86_64/repodata/repomd.xml"
    age = cprp.snapshot_age_days(fresh, today=TODAY)
    assert age == 5
    assert age < cprp.SNAPSHOT_WARN_DAYS < cprp.SNAPSHOT_FAIL_DAYS


def test_the_thresholds_are_ordered_and_sane():
    """A warn above the fail line would mean the warning never fires."""
    assert 0 < cprp.SNAPSHOT_WARN_DAYS < cprp.SNAPSHOT_FAIL_DAYS


def test_the_detector_still_matches_a_real_declared_pin():
    """Guard the guard.

    If the manifests stop carrying a datestamped pin, or the regex stops
    matching the shape they use, every test above keeps passing while the
    check examines nothing. Assert against the real manifests.
    """
    import glob
    import yaml
    dated = []
    for path in sorted(glob.glob(str(ROOT / "manifests" / "desktops" / "*.yaml"))):
        with open(path, encoding="utf-8") as f:
            for _kind, url in cprp.collect(yaml.safe_load(f)):
                if cprp.snapshot_age_days(url, today=TODAY) is not None:
                    dated.append(url)
    assert dated, (
        "no declared package-repo pin carries a datestamp any more — either "
        "the snapshot pin was replaced (good, remove this) or the detector "
        "has gone blind (bad)"
    )


# --- content age beats name age ---------------------------------------------
# The 20251124 prefix is a LIVING repo the package factory publishes into
# nightly (r2_path: hummingbird/20251124-$arch), not an immutable snapshot.
# Judged by its NAME it is forever stale; judged by its repomd <revision>
# (createrepo_c stamps the indexing epoch) it is as old as its content.
# Measured live while writing this: 274d by name, 8d by content -- the
# name-based verdict this suite originally pinned was a false positive of
# exactly the cry-wolf kind that gets checks deleted.

def test_an_epoch_revision_yields_content_age():
    body = b"<repomd><revision>1786000000</revision></repomd>"
    age = cprp.repomd_content_age_days(body, today=TODAY)
    assert age is not None and 0 <= age <= 30, age


def test_a_serial_revision_falls_back_to_none():
    """Some tools write serials (small ints); those are not timestamps."""
    assert cprp.repomd_content_age_days(
        b"<repomd><revision>17</revision></repomd>", today=TODAY) is None


def test_a_body_without_a_revision_is_none_not_zero():
    assert cprp.repomd_content_age_days(b"<repomd/>", today=TODAY) is None
    assert cprp.repomd_content_age_days(b"", today=TODAY) is None


def test_probe_returns_the_body_content_age_needs():
    """The verdict reads the revision out of the SAME fetch reachability
    used; if probe stops returning the body, content age silently never
    applies and every datestamped repo is judged by its name again."""
    import inspect
    sig = inspect.signature(cprp.probe)
    ret = inspect.getsource(cprp.probe)
    assert "resp.read()" in ret, "probe no longer returns the body"
