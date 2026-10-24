"""Offline identity and count checks for the generated matrix snapshot pair."""

import datetime
import hashlib
import importlib.util
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
    evidence = {
        key: value for key, value in payload.items()
        if key not in ("about", "snapshot")
    }
    return {
        "schema_version": 1,
        "board_sha256": hashlib.sha256(block.encode()).hexdigest(),
        "provenance_sha256": hashlib.sha256(
            json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def validate_snapshot(document: str, payload: dict, root: Path | None = None) -> None:
    """Reject mixed merges, including equal-count snapshots with different runs."""
    if not isinstance(payload, dict):
        raise ValueError("matrix provenance must be an object")
    summary = payload.get("summary")
    cells = payload.get("cells")
    context = payload.get("snapshot_context", {})
    if (not isinstance(summary, dict) or not isinstance(cells, dict)
            or not isinstance(context, dict)
            or any(not isinstance(axes, dict) for axes in cells.values())):
        raise ValueError("matrix provenance has invalid summary, cells, or snapshot context")
    for cell, axes in cells.items():
        for axis, result in axes.items():
            if not isinstance(result, dict) or "verdict" not in result:
                raise ValueError(
                    f"matrix provenance cell {cell!r} axis {axis!r} "
                    "must be an object with a verdict"
                )
    if payload.get("snapshot") != snapshot_identity(document, payload):
        raise ValueError("matrix snapshot identity mismatch; regenerate the pair together")
    if context.get("kind") == "historical-reconciliation":
        expected = historical_notice(context.get("evaluation_date"))
        if expected not in document:
            raise ValueError("historical snapshot disclosure is missing or changed")
    if root is not None:
        validate_context(context, root)
    required_summaries = {"factory_health", "install", "desktop",
                          "lifecycle", "iso"}
    missing_summaries = sorted(required_summaries - set(summary))
    if missing_summaries:
        raise ValueError(
            "matrix provenance summary is missing required axes: "
            + ", ".join(missing_summaries)
        )
    match = re.search(r"\*\*(\d+) of (\d+)\*\* published cells are composite-green", document)
    if not match or summary["factory_health"] != {
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
        if axis in summary and summary[axis] != expected:
            raise ValueError(f"matrix {axis} summary disagrees with retained cells")
    if summary["iso"] != tally("iso"):
        raise ValueError("matrix iso summary disagrees with retained cells")


RETAINED_KEYS = ("schema_version", "evaluation_date", "context", "luks", "lifecycle", "smoke",
                 "contract", "omissions", "parity", "stage", "overlay_section")


def load_retained_inputs(path):
    """Read and annotate the opt-in offline render input.

    The returned object gains the retained input's repository-relative path
    and byte digest in ``context``. Every malformed input raises ValueError
    naming what is wrong, so callers handle one error type instead of
    KeyError/TypeError from deep inside.
    """
    candidate = Path(path).resolve()
    try:
        relative = candidate.relative_to(Path.cwd().resolve())
    except ValueError as error:
        raise ValueError("retained input path must be inside the repository checkout") from error
    if relative.parts[:2] != ("docs", "matrix-snapshots"):
        raise ValueError("retained input must be stored in docs/matrix-snapshots")
    try:
        raw = candidate.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"unreadable retained matrix input {path}: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("retained matrix input must be a JSON object")
    missing = [key for key in RETAINED_KEYS if key not in payload]
    if missing:
        raise ValueError(f"retained matrix input lacks required keys: {', '.join(missing)}")
    try:
        _validate_retained(payload)
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"malformed retained matrix input: {type(error).__name__}: {error}") from error
    # Replay reproduces the committed pair only under the configuration it was
    # recorded with. Checked after the structure, so structural errors stay
    # visible whatever the configuration.
    for name, digest in payload["context"]["configuration_sha256"].items():
        if configuration_digest(name) != digest:
            raise ValueError(f"retained input configuration changed: {name}")
    payload["context"]["retained_inputs_path"] = relative.as_posix()
    payload["context"]["retained_inputs_sha256"] = hashlib.sha256(raw).hexdigest()
    return payload



def _validate_retained(payload: dict) -> None:
    def parse_date(value, what):
        try:
            return datetime.date.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"invalid retained {what} date {value!r}: expected YYYY-MM-DD"
            ) from error

    if payload["schema_version"] != 1:
        raise ValueError("unsupported retained matrix input schema")
    evaluation_date = parse_date(payload["evaluation_date"], "evaluation")
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
        if parse_date(date, "assertion") > evaluation_date:
            raise ValueError("retained assertion is later than its evaluation date")

    validate_configuration_identity(context.get("configuration_sha256"))
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


def historical_notice(date: str) -> str:
    try:
        datetime.date.fromisoformat(date)
    except (TypeError, ValueError) as error:
        raise ValueError(
            "historical snapshot evaluation_date must be a valid YYYY-MM-DD date"
        ) from error
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
        path = root / "scripts/lib/tunaos_config.py"
        spec = importlib.util.spec_from_file_location(
            "matrix_snapshot_tunaos_config", path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load primary configuration parser: {path}")
        tunaos_config = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tunaos_config)
        value = tunaos_config.load(root / name)
    elif name == ".github/green-criteria.yml":
        import yaml
        value = yaml.safe_load((root / name).read_text())
    else:
        raise ValueError("unexpected configuration identity path")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# `.github/build-config.yml` is a generated, ignored adapter. `tunaos.toml`
# is the matrix source consumed by the generator and is the identity bound here.
CONFIGURATION_FILES = ("tunaos.toml", ".github/green-criteria.yml")


def validate_configuration_identity(identities) -> None:
    """The pair records which matrix and criteria it was generated under."""
    if not isinstance(identities, dict) or set(identities) != set(CONFIGURATION_FILES):
        raise ValueError("snapshot must record its matrix and criteria configuration")
    for name, digest in identities.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"invalid configuration identity for {name}")


def validate_context(context: dict, root: Path) -> None:
    """Check the committed pair's collection context.

    The recorded configuration identity is sealed into the snapshot, so a
    mixed merge still fails. It is deliberately not compared with the
    checkout's current configuration. tunaos.toml changes in most pull
    requests, and the committed pair stays a faithful snapshot of when it was
    generated. Board-shape drift caused by a configuration change is what
    `gen-matrix-status.py --check-structure` catches. Requiring a digest match
    here would turn every unrelated config edit red until the daily refresh
    landed (#3813).
    """
    if context.get("kind") not in ("live-collection", "historical-reconciliation"):
        raise ValueError("snapshot collection context is missing")
    validate_configuration_identity(context.get("configuration_sha256"))
    if context["kind"] == "historical-reconciliation":
        relative = Path(context.get("retained_inputs_path", ""))
        if relative.is_absolute() or ".." in relative.parts or relative.parts[:2] != ("docs", "matrix-snapshots"):
            raise ValueError("invalid retained input identity path")
        expected_digest = context.get("retained_inputs_sha256")
        if not isinstance(expected_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
            raise ValueError("retained input digest must be a lowercase SHA-256")
        candidate = root / relative
        current = root
        for part in relative.parts:
            current /= part
            if current.is_symlink():
                raise ValueError("retained input identity path must not contain symlinks")
        try:
            candidate.resolve().relative_to(root.resolve())
            retained = candidate.read_bytes()
        except ValueError as error:
            raise ValueError("retained input identity path escapes the checkout") from error
        except OSError as error:
            raise ValueError(f"retained input is missing: {relative.as_posix()}") from error
        if hashlib.sha256(retained).hexdigest() != expected_digest:
            raise ValueError("retained input bytes changed")
