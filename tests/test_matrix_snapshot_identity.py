"""A mixed merge must fail even if both snapshots have identical totals (#3813)."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from matrix_snapshot import BEGIN, END, snapshot_identity, validate_snapshot


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


def test_duplicate_markers_are_rejected():
    document, payload = pair()
    with pytest.raises(ValueError, match="exactly one"):
        snapshot_identity(document + document, payload)


def test_committed_replay_is_offline_and_preserves_verdicts(monkeypatch):
    import importlib.util
    import json

    from matrix_snapshot import load_retained_inputs
    root = Path(__file__).resolve().parents[1]
    monkeypatch.chdir(root)
    spec = importlib.util.spec_from_file_location("replay_generator", root / "scripts/gen-matrix-status.py")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    def network_forbidden(*args, **kwargs):
        raise AssertionError("offline replay attempted network collection")
    monkeypatch.setattr(generator, "gh_json", network_forbidden)
    monkeypatch.setattr(generator.subprocess, "run", network_forbidden)
    monkeypatch.setattr(generator.urllib.request, "urlopen", network_forbidden)
    inputs = load_retained_inputs(root / "docs/matrix-snapshots/2026-10-23-reconciled.json")
    assert inputs["context"]["retained_inputs_path"] == "docs/matrix-snapshots/2026-10-23-reconciled.json"
    document, provenance = generator.build(inputs)
    committed = json.loads((root / "docs/matrix-provenance.json").read_text())
    assert provenance == committed["cells"]
    assert generator.factory_health_summary(provenance, document) == committed["summary"]
    assert committed["summary"]["last_full_sweep"] == ""
    assert committed["snapshot_context"]["evaluation_date"] == "2026-10-23"


def test_replay_rejects_changed_configuration(tmp_path, monkeypatch):
    import json

    from matrix_snapshot import load_retained_inputs
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "docs/matrix-snapshots/2026-10-23-reconciled.json").read_text())
    payload["context"]["configuration_sha256"]["tunaos.toml"] = "0" * 64
    path = tmp_path / "input.json"
    path.write_text(json.dumps(payload))
    monkeypatch.chdir(root)
    with pytest.raises(ValueError, match="configuration changed"):
        load_retained_inputs(path)


def test_historical_warning_cannot_be_removed_or_resealed():
    import json
    import re
    root = Path(__file__).resolve().parents[1]
    document = (root / "docs/MATRIX-STATUS.md").read_text()
    payload = json.loads((root / "docs/matrix-provenance.json").read_text())
    document = re.sub(r"<!-- BEGIN HISTORICAL SNAPSHOT -->.*?<!-- END HISTORICAL SNAPSHOT -->", "", document, flags=re.DOTALL)
    with pytest.raises(ValueError, match="identity mismatch"):
        validate_snapshot(document, payload)
    payload["snapshot"] = snapshot_identity(document, payload)
    with pytest.raises(ValueError, match="disclosure"):
        validate_snapshot(document, payload)


@pytest.mark.parametrize("change", ["date", "future", "source", "stage"])
def test_retained_assertions_need_manifested_dated_sources(tmp_path, monkeypatch, change):
    import json

    from matrix_snapshot import load_retained_inputs
    root = Path(__file__).resolve().parents[1]
    payload = json.loads((root / "docs/matrix-snapshots/2026-10-23-reconciled.json").read_text())
    if change == "date":
        payload["evaluation_date"] = "2026-10-24"
    elif change == "future":
        next(iter(payload["luks"].values()))[1] = "2027-01-01"
    elif change == "source":
        next(iter(payload["luks"].values()))[2] = "1"
    else:
        next(iter(payload["stage"].values()))["cell_run"] = {}
    path = tmp_path / "inputs.json"
    path.write_text(json.dumps(payload))
    monkeypatch.chdir(root)
    with pytest.raises(ValueError):
        load_retained_inputs(path)


def test_actual_input_bytes_and_configuration_are_checked(tmp_path, monkeypatch):
    import json

    from matrix_snapshot import validate_context
    root = Path(__file__).resolve().parents[1]
    context = json.loads((root / "docs/matrix-provenance.json").read_text())["snapshot_context"]
    monkeypatch.chdir(root)
    validate_context(context, root)
    context = copy.deepcopy(context)
    context["retained_inputs_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="input bytes changed"):
        validate_context(context, root)
    context["configuration_sha256"]["tunaos.toml"] = "0" * 64
    with pytest.raises(ValueError, match="configuration changed"):
        validate_context(context, root)
