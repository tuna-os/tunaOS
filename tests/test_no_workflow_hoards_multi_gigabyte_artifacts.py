"""Actions storage is 0.5 GB. One ISO is bigger than that.

On 2026-08-24 the account hit 90% of its included Actions storage. Three
upload steps were parking ISOs with NO `retention-days`, which means the
GitHub default of NINETY DAYS:

    live-iso-bootc.yml      path: "*.iso"                      every run, PRs included
    publish-iso-groups.yml  path: <basename>-*.iso             every grouped cell
    installer-smoke.yml     path: iso-out/dev.iso              retention-days: 1 (the only one set)

The publish one was the worst of the three on two counts: it uploaded the
very ISO it had just pushed to R2 — a second copy of the deliverable — and it
did so once per grouped cell.

This test is the rule rather than the three fixes. Any workflow that uploads
something ISO-shaped must say how long to keep it, and the answer must be
short. A default that costs money is not a default anyone chose.
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
MAX_RETENTION_DAYS = 7


def upload_steps():
    """(workflow, job, step) for every upload-artifact step in the repo."""
    found = []
    for wf in WORKFLOWS:
        try:
            doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        for job_name, job in (doc or {}).get("jobs", {}).items():
            if not isinstance(job, dict):
                continue
            for step in job.get("steps", []) or []:
                if "upload-artifact" in str(step.get("uses", "")):
                    found.append((wf.name, job_name, step))
    return found


def test_there_are_upload_steps_to_check():
    """Guard: a sweep that matches nothing passes for the wrong reason.

    This repository has produced that failure repeatedly — a regex that
    found no workflows, a scan that read comments. Assert the corpus first.
    """
    steps = upload_steps()
    assert len(steps) >= 5, f"only found {len(steps)} upload steps; parser broken?"
    assert any(wf == "live-iso-bootc.yml" for wf, _, _ in steps)


def iso_uploads():
    for wf, job, step in upload_steps():
        path = str(step.get("with", {}).get("path", ""))
        # `.iso.sha256` and `.iso.sigstore.json` are kilobytes — the point is
        # the image itself, so match a path component ENDING in .iso.
        lines = [l.strip() for l in path.splitlines() if l.strip()]
        if any(l.endswith(".iso") for l in lines):
            yield wf, job, step


def test_the_iso_uploads_are_still_findable():
    assert list(iso_uploads()), (
        "no ISO upload found — either they are all gone (good, delete this "
        "test) or the matcher stopped matching (bad, and silent)"
    )


def test_every_iso_upload_sets_a_short_retention():
    for wf, job, step in iso_uploads():
        with_ = step.get("with", {})
        assert "retention-days" in with_, (
            f"{wf}:{job} uploads an ISO with no retention-days — that is the "
            "GitHub default of 90 days, on a multi-gigabyte file, against "
            "0.5 GB of included storage"
        )
        days = int(with_["retention-days"])
        assert 1 <= days <= MAX_RETENTION_DAYS, f"{wf}:{job} keeps an ISO {days} days"


def test_iso_uploads_do_not_waste_minutes_compressing():
    """An ISO is already compressed; level 6 burns runner minutes for ~0%."""
    for wf, job, step in iso_uploads():
        level = step.get("with", {}).get("compression-level")
        assert str(level) == "0", (
            f"{wf}:{job} compresses an ISO (level={level}); it is already "
            "compressed, so this costs minutes and saves nothing"
        )


def test_the_publish_job_does_not_also_hoard_what_it_published():
    """R2 is where the grouped ISO goes. An artifact of the same bytes is a
    second copy of the deliverable, per cell, and the reason to keep a run's
    output around is the checksum and signature — not the image."""
    doc = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "publish-iso-groups.yml").read_text(
            encoding="utf-8"))
    paths = [
        str(s.get("with", {}).get("path", ""))
        for job in doc["jobs"].values() if isinstance(job, dict)
        for s in job.get("steps", []) or []
        if "upload-artifact" in str(s.get("uses", ""))
    ]
    assert paths, "no upload steps in the publish workflow"
    blob = "\n".join(paths)
    assert ".iso.sha256" in blob, "the checksum should still be kept"
    for line in [l.strip() for l in blob.splitlines() if l.strip()]:
        assert not line.endswith(".iso"), (
            f"the publish job uploads {line!r} as an artifact as well as to "
            "R2 — one deliverable, two bills"
        )
