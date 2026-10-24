"""tunaOS#3813: the matrix board and its provenance must be one snapshot.

Merge 4912d39d combined the 2026-10-23 board with an older provenance summary.
On main 7f590be8, docs/matrix-provenance.json reported factory_health 124/147
while docs/MATRIX-STATUS.md reported 120/147.
tests/test_matrix_status_config.py::test_committed_snapshot_counts_match_provenance_and_board
failed in every PR's Unit Tests (run 40042245544, job 120727240280).

Now the generator seals the generated block, the historical disclosure and the
provenance payload into one identity. scripts/check-matrix-snapshot.py rejects
a mixed pair even when the aggregate counts agree. The committed pair is
validated without comparing against the checkout's current configuration, so
an unrelated tunaos.toml edit or the daily live refresh cannot recreate a
repo-wide red. Replay of retained inputs still requires the configuration they
were recorded under.

Falsification: behavioural -- splice a board block from one snapshot with a
provenance payload from another (test_mixed_snapshot_is_rejected) and
validate_snapshot raises. Restore the configuration digest comparison in
validate_context() and
test_committed_pair_does_not_depend_on_current_configuration fails.
Structural -- restore the shared `group: matrix-status` in
.github/workflows/matrix-status.yml and
test_pull_request_checks_do_not_cancel_each_other_or_publication fails.

The PR check that runs check-matrix-snapshot.py must also run to completion.
Its workflow shared one concurrency group across all events: 41 of the last 98
pull_request runs ended cancelled on 2026-10-24, including this fix's own run
40065011718.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "matrix_snapshot_under_test", ROOT / "scripts/matrix_snapshot.py"
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load scripts/matrix_snapshot.py")
matrix_snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(matrix_snapshot)
BEGIN = matrix_snapshot.BEGIN
CONFIGURATION_FILES = matrix_snapshot.CONFIGURATION_FILES
END = matrix_snapshot.END
configuration_digest = matrix_snapshot.configuration_digest
historical_notice = matrix_snapshot.historical_notice
load_retained_inputs = matrix_snapshot.load_retained_inputs
snapshot_identity = matrix_snapshot.snapshot_identity
validate_context = matrix_snapshot.validate_context
validate_snapshot = matrix_snapshot.validate_snapshot

RETAINED = ROOT / "docs/matrix-snapshots/2026-10-23-reconciled.json"


def pair():
    document = BEGIN + """
**1 of 1** published cells are composite-green.
## LUKS E2E
**1 of 1** cells green (1 tested, 0 never tested).
## Desktop Contract Sweep
**1 of 1** cells satisfy `contract` (1 tested, 0 never tested).
## Bootc Lifecycle
**0 of 1** cells green (0 tested, 1 never tested).
## Package parity
**0 of 1** cells at parity (1 measured).
""" + END
    axes = {axis: {"verdict": verdict, "date": "2026-10-23", "run": "run/1"}
            for axis, verdict in (("install", "pass"), ("desktop", "pass"),
                                   ("lifecycle", "untested"), ("parity", "fail"), ("iso", "untested"))}
    payload = {"cells": {"test:gnome": axes}, "summary": {
        "factory_health": {"green": 1, "total": 1},
        "iso": {"passed": 0, "tested": 0, "total": 1}}}
    payload["snapshot"] = snapshot_identity(document, payload)
    return document, payload


def retained_context(root: Path, data: bytes = b"{}") -> dict:
    path = root / "docs/matrix-snapshots/input.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "kind": "historical-reconciliation",
        "configuration_sha256": {name: "a" * 64 for name in CONFIGURATION_FILES},
        "retained_inputs_path": "docs/matrix-snapshots/input.json",
        "retained_inputs_sha256": hashlib.sha256(data).hexdigest(),
    }


def test_one_snapshot_passes_without_mutating_evidence():
    document, payload = pair()
    original = copy.deepcopy(payload)
    validate_snapshot(document, payload)
    assert payload == original


@pytest.mark.parametrize("side", ["board", "evidence", "summary"])
def test_mixed_snapshot_is_rejected(side):
    document, payload = pair()
    if side == "board":
        document = document.replace("`contract`", "`changed-contract`")
    elif side == "evidence":
        payload["cells"]["test:gnome"]["desktop"]["run"] = "run/2"
    else:
        payload["summary"]["factory_health"]["green"] = 0
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_snapshot(document, payload)


def test_counts_cannot_be_made_consistent_by_only_resealing_identity():
    document, payload = pair()
    payload["cells"]["test:gnome"]["install"]["verdict"] = "fail"
    payload["snapshot"] = snapshot_identity(document, payload)
    with pytest.raises(ValueError, match="install headline"):
        validate_snapshot(document, payload)


def test_composite_summary_must_match_board_even_when_resealed():
    document, payload = pair()
    payload["summary"]["factory_health"]["green"] = 0
    payload["snapshot"] = snapshot_identity(document, payload)
    with pytest.raises(ValueError, match="composite headline"):
        validate_snapshot(document, payload)


def test_missing_identity_is_not_implicitly_adopted():
    document, payload = pair()
    del payload["snapshot"]
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_snapshot(document, payload)


def test_handwritten_prose_is_not_part_of_generated_snapshot():
    document, payload = pair()
    validate_snapshot("# Human introduction\n" + document + "\nHuman footer", payload)


def test_prose_metadata_is_not_part_of_generated_snapshot():
    document, payload = pair()
    identity = snapshot_identity(document, payload)
    payload["about"] = {"description": "human-facing provenance help"}
    assert snapshot_identity(document, payload) == identity


def test_duplicate_markers_are_rejected():
    document, payload = pair()
    with pytest.raises(ValueError, match="exactly one"):
        snapshot_identity(document + document, payload)


def test_committed_pair_is_one_snapshot():
    """Whatever produced the committed pair (live or replay), it is one snapshot."""
    validate_snapshot((ROOT / "docs/MATRIX-STATUS.md").read_text(),
                      json.loads((ROOT / "docs/matrix-provenance.json").read_text()), ROOT)


def test_historical_warning_cannot_be_removed_or_resealed():
    document, payload = pair()
    payload["snapshot_context"] = {"kind": "historical-reconciliation", "evaluation_date": "2026-10-23"}
    document = historical_notice("2026-10-23") + "\n" + document
    payload["snapshot"] = snapshot_identity(document, payload)
    validate_snapshot(document, payload)
    document = re.sub(r"<!-- BEGIN HISTORICAL SNAPSHOT -->.*?<!-- END HISTORICAL SNAPSHOT -->",
                      "", document, flags=re.DOTALL)
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_snapshot(document, payload)
    payload["snapshot"] = snapshot_identity(document, payload)
    with pytest.raises(ValueError, match="disclosure"):
        validate_snapshot(document, payload)


def test_retained_replay_is_offline_and_reproduces_committed_pair(monkeypatch):
    monkeypatch.chdir(ROOT)
    recorded = json.loads(RETAINED.read_text())["context"]["configuration_sha256"]
    if any(configuration_digest(name) != digest for name, digest in recorded.items()):
        # The configuration moved on since this input was recorded: replay
        # must refuse rather than render a board the input never described.
        with pytest.raises(ValueError, match="configuration changed"):
            load_retained_inputs(RETAINED)
        return
    monkeypatch.setitem(sys.modules, "matrix_snapshot", matrix_snapshot)
    spec = importlib.util.spec_from_file_location("replay_generator", ROOT / "scripts/gen-matrix-status.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/gen-matrix-status.py for replay")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)

    def network_forbidden(*args, **kwargs):
        raise AssertionError("offline replay attempted network collection")
    monkeypatch.setattr(generator, "gh_json", network_forbidden)
    monkeypatch.setattr(generator.subprocess, "run", network_forbidden)
    monkeypatch.setattr(generator.urllib.request, "urlopen", network_forbidden)
    inputs = load_retained_inputs(RETAINED)
    assert inputs["context"]["retained_inputs_path"] == "docs/matrix-snapshots/2026-10-23-reconciled.json"
    document, provenance = generator.build_pair(inputs)
    summary = generator.factory_health_summary(provenance, document)
    assert summary["last_full_sweep"] == ""
    committed = json.loads((ROOT / "docs/matrix-provenance.json").read_text())
    if committed["snapshot_context"].get("retained_inputs_path") == inputs["context"]["retained_inputs_path"]:
        assert provenance == committed["cells"]
        assert summary == committed["summary"]
        assert committed["snapshot_context"]["evaluation_date"] == "2026-10-23"


def test_generator_build_keeps_document_only_compatibility(monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "compatibility_generator", ROOT / "scripts/gen-matrix-status.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load scripts/gen-matrix-status.py for compatibility test")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    monkeypatch.setattr(generator, "build_pair", lambda inputs=None: ("document", {"cells": {}}))

    assert generator.build() == "document"


def test_replay_rejects_changed_configuration(tmp_path, monkeypatch):
    payload = json.loads(RETAINED.read_text())
    payload["context"]["configuration_sha256"]["tunaos.toml"] = "0" * 64
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload))
    monkeypatch.chdir(ROOT)
    with pytest.raises(ValueError, match="configuration changed"):
        load_retained_inputs(path)


@pytest.mark.parametrize("change, message", [
    ("date", "evaluation dates disagree"),
    ("future", "later than its evaluation date"),
    ("source", "no manifested source run"),
    ("stage", "no cell source"),
    ("invalid-evaluation-date", "invalid retained evaluation date"),
    ("invalid-assertion-date", "invalid retained assertion date"),
])
def test_retained_assertions_need_manifested_dated_sources(tmp_path, monkeypatch, change, message):
    payload = json.loads(RETAINED.read_text())
    if change == "date":
        payload["evaluation_date"] = "2026-10-24"
    elif change == "future":
        next(iter(payload["luks"].values()))[1] = "2027-01-01"
    elif change == "source":
        next(iter(payload["luks"].values()))[2] = "1"
    elif change == "invalid-evaluation-date":
        payload["evaluation_date"] = "not-a-date"
        payload["context"]["evaluation_date"] = "not-a-date"
    elif change == "invalid-assertion-date":
        next(iter(payload["luks"].values()))[1] = "not-a-date"
    else:
        next(stage for stage in payload["stage"].values() if stage["jobs"])["cell_run"] = {}
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(payload))
    monkeypatch.chdir(ROOT)
    with pytest.raises(ValueError, match=message):
        load_retained_inputs(path)


@pytest.mark.parametrize("change, message", [
    ("missing-key", "lacks required keys: stage"),
    ("wrong-type", "malformed retained matrix input"),
    ("missing-field", "malformed retained matrix input"),
    ("not-object", "must be a JSON object"),
    ("not-json", "unreadable retained matrix input"),
    ("bad-evaluation-date", "invalid retained evaluation date '23/10/2026'"),
    ("bad-assertion-date", "invalid retained assertion date 'yesterday'"),
])
def test_malformed_retained_input_raises_one_clear_error(tmp_path, monkeypatch, change, message):
    payload = json.loads(RETAINED.read_text())
    if change == "missing-key":
        del payload["stage"]
    elif change == "wrong-type":
        payload["luks"] = []
    elif change == "missing-field":
        del next(iter(payload["stage"].values()))["cell_run"]
    elif change == "not-object":
        payload = []
    elif change == "bad-evaluation-date":
        payload["evaluation_date"] = "23/10/2026"
    elif change == "bad-assertion-date":
        next(iter(payload["luks"].values()))[1] = "yesterday"
    path = tmp_path / "inputs.json"
    path.write_text("{" if change == "not-json" else json.dumps(payload))
    monkeypatch.chdir(ROOT)
    with pytest.raises(ValueError, match=message):
        load_retained_inputs(path)


def test_retained_input_outside_the_checkout_is_rejected(tmp_path, monkeypatch):
    payload = json.loads(RETAINED.read_text())
    recorded = payload["context"]["configuration_sha256"]
    monkeypatch.setattr(matrix_snapshot, "configuration_digest", lambda name, root=Path("."): recorded[name])
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(payload))
    monkeypatch.chdir(ROOT)
    with pytest.raises(ValueError, match="inside the repository checkout"):
        load_retained_inputs(path)


def test_actual_input_bytes_and_identity_paths_are_checked(tmp_path):
    context = retained_context(tmp_path)
    validate_context(context, tmp_path)
    changed = dict(context, retained_inputs_sha256="0" * 64)
    with pytest.raises(ValueError, match="input bytes changed"):
        validate_context(changed, tmp_path)
    for path in ("../input.json", "/etc/passwd", "docs/other/input.json"):
        with pytest.raises(ValueError, match="invalid retained input identity path"):
            validate_context(dict(context, retained_inputs_path=path), tmp_path)
    (tmp_path / "docs/matrix-snapshots/input.json").unlink()
    with pytest.raises(ValueError, match="retained input is missing"):
        validate_context(context, tmp_path)


@pytest.mark.parametrize("identities", [
    None,
    {"tunaos.toml": "a" * 64},
    {"tunaos.toml": "a" * 64, ".github/green-criteria.yml": "not-a-digest"},
])
def test_pair_must_record_its_configuration_identity(tmp_path, identities):
    context = dict(retained_context(tmp_path), configuration_sha256=identities)
    with pytest.raises(ValueError, match="configuration"):
        validate_context(context, tmp_path)


def test_committed_pair_does_not_depend_on_current_configuration(tmp_path, monkeypatch):
    """A tunaos.toml edit must not turn the committed pair red (#3813 recurrence)."""
    def current_configuration_read(*args, **kwargs):
        raise AssertionError("committed pair compared against the current configuration")
    monkeypatch.setattr(matrix_snapshot, "configuration_digest", current_configuration_read)
    validate_context(retained_context(tmp_path), tmp_path)
    validate_context({"kind": "live-collection",
                      "configuration_sha256": {name: "b" * 64 for name in CONFIGURATION_FILES}}, tmp_path)


def test_pull_request_checks_do_not_cancel_each_other_or_publication():
    import yaml
    workflow = yaml.safe_load((ROOT / ".github/workflows/matrix-status.yml").read_text())
    concurrency = workflow["concurrency"]
    match = re.fullmatch(
        r"matrix-status-\$\{\{ github\.event_name == 'pull_request' && github\.ref \|\| '(\w+)' \}\}",
        concurrency["group"],
    )
    assert match, f"unexpected concurrency group {concurrency['group']!r}"

    def group(event, ref):
        return "matrix-status-" + (ref if event == "pull_request" else match[1])

    publish = {group("schedule", "refs/heads/main"), group("workflow_dispatch", "refs/heads/main")}
    assert len(publish) == 1, "publication runs must serialize on one group"
    first, second = group("pull_request", "refs/pull/1/merge"), group("pull_request", "refs/pull/2/merge")
    assert first != second and not {first, second} & publish
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
