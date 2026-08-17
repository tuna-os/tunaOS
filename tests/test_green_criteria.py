"""The green criteria must stay honest about what is actually enforced.

Before 2026-08-17, "green" meant the image built and promoted. That is the
weakest claim this pipeline can make -- `marlin:kde` published with no
`/usr/share/wayland-sessions/` at all and counted as green (tunaOS#858).

The criteria were raised to cover: desktop present, boots to a session, ISO
installs, installation completes, update/rollback work, upstream parity, no
silent omissions, still rebuildable, and no unsatisfiable architectures.

The risk in a list like that is not that it is wrong -- it is that it becomes
decorative. Every criterion in it already existed in some form and almost none
of them blocked anything: the boot Gate was skippable, the parity manifest was
written into every image and read by nothing, and Bootc Lifecycle had never
run once for any of 52 cells. These tests exist so the file cannot quietly
turn into a wish list: every criterion must declare how it is asserted and
whether it actually blocks, and the prose must not drift from the data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CRITERIA = ROOT / ".github/green-criteria.yml"
DOC = ROOT / "docs/GREEN-CRITERIA.md"

VALID_ENFORCEMENT = {"blocking", "advisory", "unimplemented"}


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(CRITERIA.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def criteria(spec):
    return spec["criteria"]


def test_the_user_facing_criteria_are_all_present(criteria):
    """The four the maintainer asked for, plus the ones added alongside them.

    Pinned by id so a rename has to be deliberate rather than accidental.
    """
    ids = {c["id"] for c in criteria}
    required = {
        # asked for explicitly
        "desktop", "parity", "iso", "install",
        # added with them
        "lifecycle", "rebuildable", "no_silent_omissions", "arch_honesty",
        # the baseline that used to be the whole definition
        "builds", "boots",
    }
    assert required <= ids, f"missing criteria: {sorted(required - ids)}"


def test_every_criterion_says_how_it_is_asserted(criteria):
    """A criterion with no named assertion is an aspiration, not a criterion.

    `asserted_by: null` is allowed, but only together with
    `enforcement: unimplemented` -- so the gap is visible rather than implied.
    """
    for c in criteria:
        assert "asserted_by" in c, f"{c['id']}: no asserted_by field"
        if not c["asserted_by"]:
            assert c["enforcement"] == "unimplemented", (
                f"{c['id']}: claims enforcement={c['enforcement']} but names "
                "nothing that asserts it"
            )


def test_enforcement_is_explicit_and_valid(criteria):
    """The whole point is that nobody has to guess what actually blocks."""
    for c in criteria:
        assert c.get("enforcement") in VALID_ENFORCEMENT, (
            f"{c['id']}: enforcement={c.get('enforcement')!r} "
            f"not one of {sorted(VALID_ENFORCEMENT)}"
        )


def test_every_criterion_records_where_it_stood_when_the_bar_was_raised(spec, criteria):
    """Progress has to be measurable, not remembered."""
    field = f"status_{spec['raised_on'].replace('-', '_')}"
    for c in criteria:
        assert c.get(field), f"{c['id']}: no {field} baseline recorded"


def test_never_tested_does_not_count_as_green(spec):
    """The distinction the whole exercise turns on.

    "Nobody has ever looked" must not render the same as "we checked and it
    works". Bootc Lifecycle is 0 tested of 52; if never-tested counted as
    green, that axis would silently contribute nothing but look complete.
    """
    rule = spec["rule"]
    assert rule["never_tested_is_not_green"] is True
    assert rule["skipped_is_not_green"] is True
    assert rule["stale_is_not_green"] is True


def test_the_document_covers_every_criterion(criteria):
    """The prose is what people read; it must not omit a criterion silently."""
    doc = DOC.read_text(encoding="utf-8")
    missing = [c["id"] for c in criteria if c["name"].split()[0].lower() not in doc.lower()]
    assert not missing, f"criteria absent from {DOC.name}: {missing}"


def test_the_document_points_at_the_machine_readable_source(criteria):
    """Two sources of truth is one too many; the doc must defer to the file."""
    doc = DOC.read_text(encoding="utf-8")
    assert "green-criteria.yml" in doc


def test_provenance_is_not_green_blocking(criteria):
    """Deliberate exclusion, and an easy one to undo by accident.

    A Rekor 502 took 136 cells down on 2026-08-15 after signing had already
    succeeded (#1560). Signature availability is unrelated to whether an image
    works, so it is reported on its own axis rather than gating green.
    """
    ids = {c["id"] for c in criteria}
    assert not ({"provenance", "attestation", "signature"} & ids), (
        "provenance became a green criterion — see #1560 for why that couples "
        "the matrix to Sigstore availability"
    )
