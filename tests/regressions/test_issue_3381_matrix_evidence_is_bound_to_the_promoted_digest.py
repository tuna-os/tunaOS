"""tunaOS#3381 / #3474 exit item 4: a wrong-digest result cannot turn a cell green.

docs/MATRIX-STATUS.md scored each axis from (conclusion, date, run_id). Nothing
said which image a run tested, so a desktop-contract pass on last week's image
counted toward green for whatever the cell publishes today, as long as it was
fresh enough.

Now every producer records the digest it tested (a `tested-digest:` step or a
`tested_digest` artifact field), Promote records the platform digests it
published (`promoted-digest:`), and the evaluator binds each axis result to
the promoted digest: match counts; digest-mismatch never counts;
digest-unknown stops counting from green-criteria.yml's
digest_binding.unknown_downgrades_from; with no promoted digest nothing is
withdrawn.

Falsification: behavioural -- on the code before this change, AxisEvidence
has no tested/promoted inputs and evaluate_composite() no cutover, so every
binding test below errors; the collector has no step_digest/stage digests, so
the marker tests error; scripts/registry-platform-digests.sh does not exist.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import matrix_evaluator as me  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "gms_digest_binding", SCRIPTS / "gen-matrix-status.py"
)
gms = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gms)

A = "sha256:" + "a" * 64
B = "sha256:" + "b" * 64
C = "sha256:" + "c" * 64
CELL = "albacore:gnome"
CUTOVER = "2026-12-04"
BEFORE = datetime.date(2026, 11, 1)
AFTER = datetime.date(2026, 12, 4)

CRITERIA = [
    {"id": "builds", "enforcement": "blocking", "freshness_sla_days": 2},
    {"id": "boots", "enforcement": "blocking", "freshness_sla_days": 2},
    {"id": "desktop", "enforcement": "blocking", "freshness_sla_days": 2},
]
MATRICES = me.CellMatrices(
    published={"albacore": {"gnome"}},
    desktops={"albacore": {"gnome"}},
    isos={},
)


def evaluate(today, tested_desktop, promoted):
    """Score albacore:gnome with fresh, passing builds/boots/desktop results."""
    date = (today - datetime.timedelta(days=1)).isoformat()
    stage = {"albacore": {
        "jobs": {("gnome", "Promote"): "success", ("gnome", "Gate"): "success"},
        "date": date, "run_id": "100", "cell_run": {"gnome": (date, "100")},
    }}
    tested = {"desktop": {CELL: tested_desktop} if tested_desktop else {}}
    if promoted:
        # The Gate tested exactly what was promoted; only `desktop` varies.
        tested["boots"] = {CELL: {"amd64": promoted["amd64"]}}
    evidence = me.AxisEvidence(
        stage=stage,
        contract={CELL: ("success", date, "200")},
        tested=tested,
        promoted={CELL: promoted} if promoted else {},
    )
    result = me.evaluate_composite(
        CRITERIA, MATRICES, evidence, "tuna-os/tunaOS", today, CUTOVER
    )
    return result.verdicts[CELL], result.provenance[CELL]["desktop"], result


def test_match_counts_toward_green():
    verdict, record, result = evaluate(BEFORE, {"amd64": A}, {"amd64": A, "arm64": B})
    assert verdict == "pass"
    assert record["digest_status"] == "match"
    assert "downgrade_reason" not in record
    assert record["tested_digest"] == {"amd64": A}
    assert record["promoted_digest"] == {"amd64": A, "arm64": B}
    assert result.green == 1


@pytest.mark.parametrize("today", [BEFORE, AFTER])
def test_mismatch_is_never_green(today):
    verdict, record, result = evaluate(today, {"amd64": C}, {"amd64": A})
    assert verdict == "untested"
    assert record["verdict"] == "pass"  # the producer's own verdict is kept
    assert record["downgrade_reason"] == "digest-mismatch"
    assert result.green == 0
    assert CELL not in result.evidence


def test_a_platform_the_cell_does_not_publish_is_a_mismatch():
    verdict, record, _ = evaluate(BEFORE, {"riscv64": A}, {"amd64": A})
    assert verdict == "untested"
    assert record["downgrade_reason"] == "digest-mismatch"


def test_unknown_before_cutover_still_counts():
    verdict, record, _ = evaluate(BEFORE, None, {"amd64": A})
    assert verdict == "pass"
    assert record["digest_status"] == "digest-unknown"
    assert "downgrade_reason" not in record


def test_unknown_after_cutover_is_withdrawn():
    verdict, record, result = evaluate(AFTER, None, {"amd64": A})
    assert verdict == "untested"
    assert record["downgrade_reason"] == "digest-unknown"
    assert result.green == 0


def test_promoted_digest_unavailable_withdraws_nothing():
    verdict, record, _ = evaluate(AFTER, {"amd64": C}, None)
    assert verdict == "pass"
    assert record["digest_status"] == "promoted-digest-unavailable"
    assert record["tested_digest"] == {"amd64": C}
    assert "downgrade_reason" not in record


def test_no_digests_at_all_leaves_the_record_as_before():
    """Retained historical inputs carry no digests and must replay unchanged."""
    _, record, _ = evaluate(AFTER, None, None)
    assert set(record) == {"verdict", "date", "run", "evidence"}


def test_a_malformed_cutover_fails_loudly():
    with pytest.raises(ValueError):
        me.digest_cutover_reached("2026-13-01", AFTER)


def test_the_committed_cutover_is_one_dated_config_value():
    assert gms.load_digest_cutover() == CUTOVER


def _job(name, *steps):
    return {"name": name, "conclusion": "success",
            "steps": [{"name": n, "conclusion": c} for n, c in steps]}


def test_build_stage_reads_gate_and_promote_markers(monkeypatch):
    monkeypatch.setattr(gms, "_matrix", lambda key, desktops_only: {"albacore": {"gnome"}})
    monkeypatch.setattr(gms, "main_runs", lambda workflow, limit=10: [
        {"databaseId": 7, "conclusion": "success", "createdAt": "2026-10-29T00:00:00Z"}])
    monkeypatch.setattr(gms, "run_jobs", lambda run_id: [
        _job("build / gnome / Gate", ("Boot and verify", "success"),
             (f"tested-digest: amd64={A}", "success")),
        _job("build / gnome / Promote",
             # A marker step that did not succeed records nothing.
             (f"promoted-digest: amd64={C}", "skipped"),
             (f"promoted-digest: amd64={A} arm64={B}", "success")),
    ])
    stage = gms.build_stage_results()["albacore"]
    assert stage["tested"] == {"gnome": {"amd64": A}}
    assert stage["promoted"] == {"gnome": {"amd64": A, "arm64": B}}


def test_a_failed_promote_records_no_current_digest(monkeypatch):
    monkeypatch.setattr(gms, "_matrix", lambda key, desktops_only: {"albacore": {"gnome"}})
    monkeypatch.setattr(gms, "main_runs", lambda workflow, limit=10: [
        {"databaseId": 7, "conclusion": "failure", "createdAt": "2026-10-29T00:00:00Z"}])
    promote = _job("build / gnome / Promote", (f"promoted-digest: amd64={A}", "success"))
    promote["conclusion"] = "failure"
    monkeypatch.setattr(gms, "run_jobs", lambda run_id: [promote])
    assert gms.build_stage_results()["albacore"]["promoted"] == {}


def test_job_results_carry_their_tested_digest(monkeypatch):
    gms.JOB_DIGESTS.clear()
    monkeypatch.setattr(gms, "gh_json", lambda *args: [
        {"databaseId": 9, "createdAt": "2026-10-29T00:00:00Z", "status": "completed"}])
    monkeypatch.setattr(gms, "run_jobs", lambda run_id: [
        _job(f"LUKS {CELL}", (f"tested-digest: amd64={A}", "success")),
        _job("LUKS albacore:kde", ("tested-digest: amd64=not-a-digest", "success")),
    ])
    luks, _ = gms._collect_latest_results("luks-e2e.yml", r"^LUKS ")
    assert gms.results_tested_digests(luks) == {f"LUKS {CELL}": {"amd64": A}}


def test_lifecycle_digest_needs_every_architecture(monkeypatch):
    gms.JOB_DIGESTS.clear()
    monkeypatch.setattr(gms, "lifecycle_validation_jobs", lambda config=None: {
        f"{CELL} (amd64)", f"{CELL} (arm64)", "albacore:kde (amd64)", "albacore:kde (arm64)"})
    raw = {
        f"{CELL} (amd64)": ("success", "2026-10-29", "1"),
        f"{CELL} (arm64)": ("success", "2026-10-29", "1"),
        "albacore:kde (amd64)": ("success", "2026-10-29", "1"),
        "albacore:kde (arm64)": ("success", "2026-10-29", "1"),
    }
    gms.JOB_DIGESTS.update({
        ("1", f"{CELL} (amd64)"): {"amd64": A},
        ("1", f"{CELL} (arm64)"): {"arm64": B},
        ("1", "albacore:kde (amd64)"): {"amd64": C},
    })
    assert gms.lifecycle_tested_digests(raw) == {CELL: {"amd64": A, "arm64": B}}


def test_baseline_artifacts_carry_their_tested_digest():
    rows = [{"cell": CELL, "tested_digest": f"amd64={A}"},
            {"cell": "albacore:kde", "tested_digest": ""},
            {"cell": "albacore:xfce"}]
    assert gms.artifact_digests(rows) == {CELL: {"amd64": A}}


def test_board_names_each_withdrawn_result(monkeypatch):
    monkeypatch.setattr(gms, "_matrix", lambda key, desktops_only: {"albacore": {"gnome"}})
    monkeypatch.setattr(gms, "iso_matrix", lambda: {})
    today = datetime.date.today()
    date = today.isoformat()
    stage = {"albacore": {
        "jobs": {("gnome", "Promote"): "success", ("gnome", "Gate"): "success"},
        "date": date, "run_id": "100", "cell_run": {"gnome": (date, "100")},
        "tested": {"gnome": {"amd64": A}}, "promoted": {"gnome": {"amd64": A}},
    }}
    lines, green, _, provenance = gms.composite_section(
        CRITERIA, stage, {CELL: ("success", date, "200")}, {}, {}, {}, {}, {},
        today=today, tested={"desktop": {CELL: {"amd64": C}}},
        digest_unknown_downgrades_from=CUTOVER,
    )
    assert green == 0
    assert provenance[CELL]["boots"]["digest_status"] == "match"
    withdrawn = [line for line in lines if line.startswith("Digest binding withdrew")]
    assert len(withdrawn) == 1
    assert f"`{CELL}` desktop (digest-mismatch)" in withdrawn[0]
    # Which cells it names is live state, masked from the PR structure gate.
    assert gms.VOLATILE_LINE.match(withdrawn[0])


def _fake_skopeo(tmp_path, manifest: bytes) -> dict:
    raw = tmp_path / "index.json"
    raw.write_bytes(manifest)
    fake = tmp_path / "skopeo"
    fake.write_text(f'#!/usr/bin/env bash\ncat "{raw}"\n')
    fake.chmod(0o755)
    return {**os.environ, "SKOPEO": str(fake)}


INDEX = json.dumps({"schemaVersion": 2, "manifests": [
    {"digest": A, "platform": {"os": "linux", "architecture": "amd64"}},
    {"digest": B, "platform": {"os": "linux", "architecture": "arm64"}},
]}).encode() + b"\n"


def run_resolver(env, *args):
    return subprocess.run(
        [str(SCRIPTS / "registry-platform-digests.sh"), "ghcr.io/x/albacore:gnome", *args],
        env=env, capture_output=True, text=True,
    )


def test_resolver_reads_the_index_this_run_pushed(tmp_path):
    env = _fake_skopeo(tmp_path, INDEX)
    index = "sha256:" + hashlib.sha256(INDEX).hexdigest()
    result = run_resolver(env, index)
    assert result.returncode == 0, result.stderr
    assert gms.parse_digest_spec(result.stdout.strip()) == {"amd64": A, "arm64": B}
    one = run_resolver(env, index, "amd64")
    assert one.stdout.strip() == f"amd64={A}"


def test_resolver_records_nothing_for_a_moved_tag(tmp_path):
    env = _fake_skopeo(tmp_path, INDEX)
    result = run_resolver(env, C)
    assert result.returncode == 1
    assert result.stdout == ""
