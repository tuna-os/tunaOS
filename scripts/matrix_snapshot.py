"""Offline identity and count checks for the generated matrix snapshot pair."""

import hashlib
import json
import re
from pathlib import Path

BEGIN = "<!-- BEGIN GENERATED — scripts/gen-matrix-status.py -->"
END = "<!-- END GENERATED -->"


def snapshot_identity(document: str, payload: dict) -> dict:
    """Bind exact generated prose and retained evidence, not wall-clock time."""
    if document.count(BEGIN) != 1 or document.count(END) != 1:
        raise ValueError("matrix board must contain exactly one generated block")
    block = BEGIN + document.split(BEGIN, 1)[1].split(END, 1)[0] + END
    historical = re.findall(
        r"<!-- BEGIN HISTORICAL SNAPSHOT -->.*?<!-- END HISTORICAL SNAPSHOT -->",
        document, re.DOTALL,
    )
    if len(historical) > 1:
        raise ValueError("duplicate historical snapshot disclosure")
    block += "".join(historical)
    evidence = {key: value for key, value in payload.items() if key != "snapshot"}
    return {
        "schema_version": 1,
        "board_sha256": hashlib.sha256(block.encode()).hexdigest(),
        "provenance_sha256": hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def validate_snapshot(document: str, payload: dict, root: Path | None = None) -> None:
    """Reject mixed merges, including equal-count snapshots with different runs."""
    if payload.get("snapshot") != snapshot_identity(document, payload):
        raise ValueError("matrix snapshot identity mismatch; regenerate the pair together")
    context = payload.get("snapshot_context", {})
    if context.get("kind") == "historical-reconciliation":
        expected = historical_notice(context["evaluation_date"])
        if expected not in document:
            raise ValueError("historical snapshot disclosure is missing or changed")
    if root is not None:
        validate_context(context, root)
    match = re.search(r"\*\*(\d+) of (\d+)\*\* published cells are composite-green", document)
    if not match or payload.get("summary", {}).get("factory_health") != {
        "green": int(match[1]), "total": int(match[2])
    }:
        raise ValueError("matrix composite headline disagrees with provenance summary")

    def tally(axis):
        values = [axes[axis]["verdict"] for axes in payload["cells"].values() if axis in axes]
        return {"passed": values.count("pass"),
                "tested": sum(value != "untested" for value in values),
                "total": len(values)}

    sections = {
        "LUKS E2E": ("install", r"\*\*(\d+) of (\d+)\*\* cells green \((\d+) tested"),
        "Desktop Contract Sweep": ("desktop", r"\*\*(\d+) of (\d+)\*\* cells satisfy .+?\((\d+) tested"),
        "Bootc Lifecycle": ("lifecycle", r"\*\*(\d+) of (\d+)\*\* cells green \((\d+) tested"),
        "Package parity": ("parity", r"\*\*(\d+) of (\d+)\*\* cells at parity \((\d+) measured"),
    }
    for title, (axis, pattern) in sections.items():
        body = document.split(f"## {title}\n", 1)
        match = re.search(pattern, body[1].split("\n## ", 1)[0], re.DOTALL) if len(body) == 2 else None
        expected = tally(axis)
        if not match or {"passed": int(match[1]), "total": int(match[2]), "tested": int(match[3])} != expected:
            raise ValueError(f"matrix {axis} headline disagrees with retained cells")
        if axis in payload["summary"] and payload["summary"][axis] != expected:
            raise ValueError(f"matrix {axis} summary disagrees with retained cells")
    if payload["summary"].get("iso") != tally("iso"):
        raise ValueError("matrix iso summary disagrees with retained cells")


def load_retained_inputs(path):
    """Read the opt-in offline render input; never reinterpret missing evidence."""
    import datetime
    payload = json.loads(Path(path).read_text())
    if payload.get("schema_version") != 1:
        raise ValueError("unsupported retained matrix input schema")
    evaluation_date = datetime.date.fromisoformat(payload["evaluation_date"])
    context = payload["context"]
    if context.get("kind") != "historical-reconciliation" or not context.get("sources"):
        raise ValueError("retained matrix inputs require historical source identity")
    if context.get("evaluation_date") != payload["evaluation_date"]:
        raise ValueError("retained evaluation dates disagree")
    source_runs = set()
    for source in context["sources"]:
        if "run_id" in source:
            source_runs.add(str(source["run_id"]))
        match = re.fullmatch(r"jobs-(\d+)\.json", source.get("path", ""))
        if match:
            source_runs.add(match[1])

    def validate_source(date, run):
        if not isinstance(run, str) or run not in source_runs:
            raise ValueError("retained assertion has no manifested source run")
        if datetime.date.fromisoformat(date) > evaluation_date:
            raise ValueError("retained assertion is later than its evaluation date")

    for name, digest in context["configuration_sha256"].items():
        if name not in ("tunaos.toml", ".github/green-criteria.yml"):
            raise ValueError("unexpected retained configuration path")
        if configuration_digest(name) != digest:
            raise ValueError(f"retained input configuration changed: {name}")
    if set(context["configuration_sha256"]) != {"tunaos.toml", ".github/green-criteria.yml"}:
        raise ValueError("retained inputs must bind matrix and criteria")
    for axis in ("luks", "lifecycle", "smoke", "contract", "omissions", "parity"):
        for key, hit in payload[axis].items():
            allowed = {"pass", "fail", "missing", "error", "lost"} if axis == "contract" else {"success", "failure", "cancelled", "skipped", ""}
            if not isinstance(key, str) or not isinstance(hit, list) or len(hit) != 3 or hit[0] not in allowed:
                raise ValueError(f"invalid retained {axis} result")
            validate_source(hit[1], hit[2])
    for stage in payload["stage"].values():
        for date, run in stage["cell_run"].values():
            validate_source(date, run)
        if stage["run_id"] or stage["date"]:
            validate_source(stage["date"], stage["run_id"])
        jobs = {}
        for flavor, name, conclusion in stage["jobs"]:
            if name not in ("Promote", "Gate") or conclusion not in ("success", "failure", "cancelled", "skipped", ""):
                raise ValueError("invalid retained build stage")
            if (flavor, name) in jobs:
                raise ValueError("duplicate retained build stage")
            if flavor not in stage["cell_run"]:
                raise ValueError("retained build stage has no cell source")
            jobs[(flavor, name)] = conclusion
        stage["jobs"] = jobs
    if not payload["overlay_section"].startswith("## Live overlay\n"):
        raise ValueError("retained overlay section must keep its original heading")
    if "\n## " in payload["overlay_section"] or BEGIN in payload["overlay_section"] or END in payload["overlay_section"]:
        raise ValueError("retained overlay observation contains another section")
    relative = Path(path).resolve().relative_to(Path.cwd().resolve())
    if relative.parts[:2] != ("docs", "matrix-snapshots"):
        raise ValueError("retained input must be stored in docs/matrix-snapshots")
    payload["context"]["retained_inputs_path"] = relative.as_posix()
    payload["context"]["retained_inputs_sha256"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return payload


def historical_notice(date: str) -> str:
    return (
        "<!-- BEGIN HISTORICAL SNAPSHOT -->\n"
        "> Historical reconciliation, evaluated on " + date
        + ". Not a current health measurement. The overlay inventory and "
        "full-sweep freshness are unverified. "
        "See [retained input limits](matrix-snapshots/README.md).\n"
        "<!-- END HISTORICAL SNAPSHOT -->"
    )


def configuration_digest(name: str, root: Path = Path(".")) -> str:
    """Bind parsed configuration; comments are not matrix or criteria changes."""
    if name == "tunaos.toml":
        from lib import tunaos_config
        value = tunaos_config.load(root / name)
    elif name == ".github/green-criteria.yml":
        import yaml
        value = yaml.safe_load((root / name).read_text())
    else:
        raise ValueError("unexpected configuration identity path")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_context(context: dict, root: Path) -> None:
    if context.get("kind") not in ("live-collection", "historical-reconciliation"):
        raise ValueError("snapshot collection context is missing")
    identities = context.get("configuration_sha256", {})
    if set(identities) != {"tunaos.toml", ".github/green-criteria.yml"}:
        raise ValueError("snapshot must bind current matrix and criteria")
    for name, expected in identities.items():
        if configuration_digest(name, root) != expected:
            raise ValueError(f"snapshot configuration changed: {name}")
    if context["kind"] == "historical-reconciliation":
        relative = Path(context.get("retained_inputs_path", ""))
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != ("docs", "matrix-snapshots"):
            raise ValueError("invalid retained input identity path")
        if hashlib.sha256((root / relative).read_bytes()).hexdigest() != context.get("retained_inputs_sha256"):
            raise ValueError("retained input bytes changed")
