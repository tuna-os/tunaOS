"""Advisory criteria graduate on measured run history, not on memory.

`lifecycle` was declared "advisory until a second consecutive weekly sweep
holds the shape, then graduate" on 2026-08-17. Nothing re-evaluated that.
scripts/graduation-check.py does, against the `graduation` bar in
green-criteria.yml; these tests drive it with synthetic run histories in
the exact shape `gh run list --json` emits, so the verdict logic is pinned
without a network. Epic #2250, item 8.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "graduation_check", ROOT / "scripts" / "graduation-check.py"
)
grad = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grad)

SPEC = grad.load()


def _runs(*conclusions: str) -> list[dict]:
    return [{"conclusion": c, "createdAt": f"2026-09-{i + 1:02d}T05:00:00Z",
             "databaseId": 1000 + i, "url": f"https://example/{1000 + i}"}
            for i, c in enumerate(conclusions)]


def _fixture(**by_workflow: list[dict]):
    def runs_for(name: str, limit: int):
        runs = by_workflow.get(name)
        return None if runs is None else runs[:limit]
    return runs_for


ADVISORY = [c["id"] for c in SPEC["criteria"] if c["enforcement"] == "advisory"]


def test_the_policy_block_exists_with_the_three_knobs():
    pol = SPEC["graduation"]
    assert set(pol) >= {"required_consecutive_passes", "maximum_failure_rate", "lookback_runs"}
    assert pol["required_consecutive_passes"] >= 2
    assert 0 < pol["maximum_failure_rate"] < 1


def test_only_advisory_criteria_are_evaluated():
    rows = grad.evaluate(SPEC, _fixture())
    assert sorted(r["id"] for r in rows) == sorted(ADVISORY)
    assert "builds" not in {r["id"] for r in rows}, "blocking criteria have nothing to graduate to"


def test_a_streak_at_the_bar_is_ready():
    # Three fresh passes, one old failure in a window of twenty (5%).
    rows = grad.evaluate(SPEC, _fixture(**{
        "package-parity.yml": _runs("success", "success", "success", "failure", *["success"] * 16),
    }))
    parity = next(r for r in rows if r["id"] == "parity")
    assert parity["ready"], parity["reason"]
    assert "3 consecutive passes" in parity["reason"]
    assert "1/20 failed" in parity["reason"]


def test_a_streak_below_the_bar_is_not_ready():
    rows = grad.evaluate(SPEC, _fixture(**{
        "package-parity.yml": _runs("success", "success", "failure", "success"),
    }))
    parity = next(r for r in rows if r["id"] == "parity")
    assert not parity["ready"]
    assert "streak 2 < 3" in parity["reason"]


def test_a_cancelled_run_breaks_the_streak():
    """A run that produced no verdict has proven nothing — the same rule as
    skipped_is_not_green, applied to the gate itself."""
    rows = grad.evaluate(SPEC, _fixture(**{
        "package-parity.yml": _runs("success", "cancelled", "success", "success", "success"),
    }))
    parity = next(r for r in rows if r["id"] == "parity")
    assert not parity["ready"], parity["reason"]
    assert parity["measured"][".github/workflows/package-parity.yml"]["streak"] == 1


def test_a_flaky_window_is_not_ready_even_with_a_fresh_streak():
    runs = _runs("success", "success", "success", *(["failure", "success"] * 8))
    rows = grad.evaluate(SPEC, _fixture(**{"package-parity.yml": runs}))
    parity = next(r for r in rows if r["id"] == "parity")
    assert not parity["ready"]
    assert "failure rate" in parity["reason"]


def test_unavailable_history_is_never_ready():
    rows = grad.evaluate(SPEC, _fixture())
    assert not any(r["ready"] for r in rows)
    assert all("unavailable" in r["reason"] or "no gates" in r["reason"] for r in rows)


def test_a_monthly_gate_can_lower_its_bar_per_criterion():
    """install is asserted monthly (luks-e2e.yml); the criterion overrides
    required_consecutive_passes so a quarter of green is not the price."""
    install = next(c for c in SPEC["criteria"] if c["id"] == "install")
    assert grad.policy_for(SPEC, install)["required_consecutive_passes"] == 2
    rows = grad.evaluate(SPEC, _fixture(**{"luks-e2e.yml": _runs("success", "success")}))
    assert next(r for r in rows if r["id"] == "install")["ready"]


def test_the_report_names_the_ready_ones_and_asks_a_human_to_flip(tmp_path):
    fixture = tmp_path / "runs.json"
    fixture.write_text(json.dumps({"package-parity.yml": _runs("success", "success", "success")}))
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert grad.main(["--runs", str(fixture)]) == 0
    out = buf.getvalue()
    assert "`parity`" in out and "✅ yes" in out
    assert "A human flips `enforcement`" in out
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        grad.main(["--runs", str(fixture), "--json"])
    assert json.loads(buf.getvalue())["ready"] == ["parity"]


def test_the_weekly_workflow_runs_the_script_and_only_opens_an_issue_when_ready():
    doc = yaml.safe_load((ROOT / ".github/workflows/graduation-check.yml").read_text())
    body = (ROOT / ".github/workflows/graduation-check.yml").read_text()
    on = doc.get("on", doc.get(True))
    assert "schedule" in on
    assert "scripts/graduation-check.py" in body
    assert "gh issue" in body
    assert doc["permissions"].get("issues") == "write"
    assert doc["permissions"].get("contents") == "read"
