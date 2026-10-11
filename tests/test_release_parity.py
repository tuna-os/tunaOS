#!/usr/bin/env python3
"""Tier-1 desktop streams must ship the same daily release (#2550).

On 2026-10-02 the scheduled Generate Release run 37034962525 concluded
`success` while publishing gnome, kde and niri only. The cosmic and xfce
cells read a failed build-runs query as "no build ran", and the per-stream
cadence gate accepted that as a legitimate no-op. These tests hold the two
fixes: the cross-stream check in scripts/check-release-parity.py, and the
release workflow no longer turning a failed runs query into zero candidates.

Falsification: behavioural — make evaluate() ignore streams that lack the bar
date and test_the_2026_10_02_gap_fails passes no more; restore the
`2>/dev/null || echo ""` on the runs query and the workflow tests fail.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-release-parity.py"
WORKFLOW = ROOT / ".github" / "workflows" / "generate-changelog-release.yml"

_spec = importlib.util.spec_from_file_location("check_release_parity", SCRIPT)
crp = importlib.util.module_from_spec(_spec)
sys.modules["check_release_parity"] = crp
_spec.loader.exec_module(crp)


def release(stream, date, assets=None, draft=False):
    if assets is None:
        assets = [
            "release-card-dark.png",
            "release-card.png",
            f"sbom-yellowfin-{stream}-linux-amd64.spdx.json",
        ]
    return {
        "tag_name": f"{stream}-{date}",
        "draft": draft,
        "assets": [{"name": a} for a in assets],
    }


def day(date, streams=crp.TIER1_STREAMS):
    return [release(s, date) for s in streams]


def failing(verdicts):
    return sorted(v.stream for v in verdicts if not v.ok)


def test_the_2026_10_02_gap_fails():
    releases = day("20261002", ("gnome", "kde", "niri")) + day("20261001")
    bar, verdicts = crp.evaluate(releases)
    assert bar == "20261002"
    assert failing(verdicts) == ["cosmic", "xfce"]
    cosmic = next(v for v in verdicts if v.stream == "cosmic")
    assert "missing cosmic-20261002 (newest is cosmic-20261001)" in cosmic.problems


def test_every_stream_at_the_same_date_passes():
    bar, verdicts = crp.evaluate(day("20261002") + day("20261001"))
    assert bar == "20261002"
    assert failing(verdicts) == []


def test_a_day_on_which_no_stream_shipped_passes():
    # Nothing ran today; every stream still sits at yesterday together.
    bar, verdicts = crp.evaluate(day("20261001"))
    assert bar == "20261001"
    assert failing(verdicts) == []


def test_a_stream_that_never_released_fails():
    bar, verdicts = crp.evaluate(day("20261002", ("gnome", "kde", "xfce", "niri")))
    assert failing(verdicts) == ["cosmic"]
    assert "no release at all" in next(v for v in verdicts if v.stream == "cosmic").problems[0]


def test_a_suffixed_tag_does_not_count_for_the_bare_stream():
    # kde-nvidia-20261002 is a different stream, not a kde release.
    releases = day("20261001") + [release("kde-nvidia", "20261002")]
    bar, verdicts = crp.evaluate(releases)
    assert bar == "20261001"
    assert failing(verdicts) == []


def test_a_draft_release_does_not_count():
    releases = day("20261001") + [release("gnome", "20261002", draft=True)]
    bar, verdicts = crp.evaluate(releases)
    assert bar == "20261001"
    assert failing(verdicts) == []


def test_a_release_without_its_sbom_fails():
    releases = day("20261002", ("gnome", "kde", "xfce", "niri")) + [
        release("cosmic", "20261002", ["release-card.png", "release-card-dark.png",
                                       "sbom-yellowfin-gnome-linux-amd64.spdx.json"])
    ]
    _, verdicts = crp.evaluate(releases)
    assert failing(verdicts) == ["cosmic"]


def test_a_release_without_its_cards_fails():
    releases = day("20261002", ("gnome", "kde", "cosmic", "niri")) + [
        release("xfce", "20261002", ["sbom-albacore-xfce-linux-amd64.spdx.json"])
    ]
    _, verdicts = crp.evaluate(releases)
    xfce = next(v for v in verdicts if v.stream == "xfce")
    assert not xfce.ok
    assert len(xfce.problems) == 2


def test_no_release_at_all_fails_every_stream():
    bar, verdicts = crp.evaluate([])
    assert bar is None
    assert failing(verdicts) == sorted(crp.TIER1_STREAMS)


def test_main_exit_codes(tmp_path):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(day("20261002")))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(day("20261002", ("gnome",)) + day("20261001")))
    summary = tmp_path / "summary.md"

    assert crp.main(["--releases", str(good), "--summary", str(summary)]) == 0
    assert "Release parity" in summary.read_text()
    assert crp.main(["--releases", str(bad)]) == 1
    assert crp.main(["--releases", str(tmp_path / "absent.json")]) == 2
    (tmp_path / "obj.json").write_text("{}")
    assert crp.main(["--releases", str(tmp_path / "obj.json")]) == 2


def _workflow():
    return yaml.safe_load(WORKFLOW.read_text())


def test_scheduled_matrix_matches_the_tier1_list():
    expr = _workflow()["jobs"]["generate-release"]["strategy"]["matrix"]["stream"]
    literal = re.findall(r"fromJson\('(\[[^']*\])'\)", expr)
    assert literal, f"no scheduled stream list in {expr!r}"
    assert tuple(json.loads(literal[-1])) == crp.TIER1_STREAMS


def test_parity_job_runs_after_every_scheduled_matrix():
    job = _workflow()["jobs"]["release-parity"]
    assert job["needs"] == "generate-release"
    assert "!cancelled()" in job["if"]
    assert "schedule" in job["if"]
    run = "\n".join(step.get("run", "") for step in job["steps"])
    assert "scripts/check-release-parity.py" in run


def test_a_failed_runs_query_is_not_a_no_build_day():
    steps = _workflow()["jobs"]["generate-release"]["steps"]
    locate = next(s for s in steps if s.get("id") == "sbom")["run"]
    runs_query = locate[locate.index("RUNS=") : locate.index("CANDIDATES=0")]
    assert '|| echo ""' not in runs_query
    assert "lookup=${LOOKUP}" in locate

    check = next(s for s in steps if s.get("id") == "check")
    assert check["env"]["LOOKUP"] == "${{ steps.sbom.outputs.lookup }}"
    assert "reason=lookup-failed" in check["run"]
    # The lookup-failed branch must be decided before the no-build branch.
    assert check["run"].index("lookup-failed") < check["run"].index("no-build")

    gate = next(s for s in steps if s.get("name") == "Release cadence health gate")["run"]
    branch = gate[gate.index("lookup-failed)") : gate.index("no-sbom)")]
    assert 'STATUS="fail"' in branch
