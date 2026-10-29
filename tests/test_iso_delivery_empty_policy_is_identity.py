"""The committed (empty) ISO delivery policy must change nothing.

R2 cutover policy (#3382) is opt-in. With `[iso_delivery]` empty in tunaos.toml,
every target must upload exactly as it did before the policy existed and the R2
pruner must delete exactly what it deleted before. These tests run the real
`scripts/iso-delivery-policy.py` over the real resolved matrix and compare the
effective workflow conditions against the literal pre-policy expressions.

A crafted non-empty policy (accepted only through the explicit
`receipts_validated` seam, because the command line refuses non-empty policy
until #3381) must suppress the cut-over target's upload, protect its retained
objects from prune, and still upload group members that the policy leaves
uncovered. Malformed policy must fail loudly.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "scripts" / "iso-delivery-policy.py"
WORKFLOWS = ROOT / ".github" / "workflows"
SPEC = importlib.util.spec_from_file_location("iso_delivery_policy_identity", POLICY)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)

CONFIG = yaml.safe_load((ROOT / ".github" / "build-config.yml").read_text(encoding="utf-8"))

# Verbatim from origin/main before the policy: the conditions that decide
# whether an ISO is uploaded to R2.
MAIN_UPLOAD_CONDITIONS = {
    "build-variant.yml": ["github.event_name == 'schedule' || inputs.publish-isos"] * 3,
    "publish-isos.yml": ["inputs.skip_upload != true"],
}
MAIN_GROUP_UPLOAD_IF = "inputs.skip_upload != true && env.R2_CONFIGURED == 'true'"
# prune-r2.yml on main: one ordered filter list, equivalent to these rules.
MAIN_PRUNE_FILTERS = ["- *-latest*", "+ *.iso", "+ *.iso.sha256", "+ *.iso.sigstore.json", "- *"]


def _cli(config: dict, command: str, stdin: str = "", tmp_path: Path | None = None):
    path = (tmp_path or ROOT) / "policy-config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    try:
        return subprocess.run(
            [sys.executable, str(POLICY), "--config-json", str(path), command],
            input=stdin, text=True, capture_output=True, check=False,
        )
    finally:
        path.unlink()


def _cells() -> list[dict]:
    cells = []
    for variant in CONFIG["variants"]:
        for flavor in variant["flavors"]:
            if flavor.get("build_image") is not True:
                continue
            for platform in flavor.get("platforms", variant.get("platforms", [])):
                # build-variant.yml emits ISO/QCOW2 rows only for these two.
                if platform not in ("linux/amd64", "linux/arm64"):
                    continue
                cells.append({"variant": variant["id"], "flavor": flavor["id"], "platform": platform})
    return cells


def test_the_committed_policy_is_empty():
    policy = CONFIG.get("iso_delivery", {})
    assert policy.get("cutover_targets", []) == []
    assert policy.get("retained_r2_isos", []) == []


def test_every_real_cell_keeps_uploading(tmp_path):
    cells = _cells()
    assert len(cells) > 20, "matrix is unexpectedly small; assertions would be vacuous"
    result = _cli(CONFIG, "annotate-target-matrix", json.dumps({"include": cells}), tmp_path)
    assert result.returncode == 0, result.stderr
    annotated = json.loads(result.stdout)["include"]
    assert [{k: v for k, v in row.items() if k != "r2_cutover"} for row in annotated] == cells
    assert all(row["r2_cutover"] is False for row in annotated)


def test_every_real_group_keeps_uploading(tmp_path):
    rows = []
    for variant in CONFIG["variants"]:
        built = [f["id"] for f in variant["flavors"] if f.get("build_image") is True]
        for group in CONFIG["iso_groups"]:
            required = [f for f in group.get("offline_flavors", group["flavors"]) if f in built]
            if any(f in built for f in group["flavors"]):
                rows.append({"variant": variant["id"], "platform": "linux/amd64",
                             "required_flavors": required})
    assert rows
    result = _cli(CONFIG, "annotate-group-matrix", json.dumps({"include": rows}), tmp_path)
    assert result.returncode == 0, result.stderr
    assert all(row["r2_cutover"] is False for row in json.loads(result.stdout)["include"])


def test_empty_policy_retains_nothing_and_prunes_as_before(tmp_path):
    assert _cli(CONFIG, "validate", tmp_path=tmp_path).returncode == 0
    assert _cli(CONFIG, "retained-objects", tmp_path=tmp_path).stdout == ""
    filters = _cli(CONFIG, "retention-filters", tmp_path=tmp_path).stdout.splitlines()
    assert filters == MAIN_PRUNE_FILTERS


def _upload_expressions(name: str) -> list[str]:
    text = (WORKFLOWS / name).read_text(encoding="utf-8")
    return re.findall(r"^\s*upload-r2: \$\{\{ (.*) \}\}\s*$", text, re.M)


def _without_cutover_guard(expr: str) -> str:
    """Evaluate the expression with matrix.r2_cutover false/absent."""
    assert expr.endswith(" && !matrix.r2_cutover"), expr
    expr = expr.removesuffix(" && !matrix.r2_cutover")
    if expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1]
    return expr


@pytest.mark.parametrize("name", sorted(MAIN_UPLOAD_CONDITIONS))
def test_upload_conditions_equal_main_when_not_cut_over(name):
    got = [_without_cutover_guard(e) for e in _upload_expressions(name)]
    assert got == MAIN_UPLOAD_CONDITIONS[name]


def test_grouped_upload_condition_equals_main_when_not_cut_over():
    text = (WORKFLOWS / "publish-iso-groups.yml").read_text(encoding="utf-8")
    match = re.search(
        r"- name: Upload ISO to Cloudflare R2\n\s+if: \$\{\{ (.*) \}\}", text)
    assert match
    assert _without_cutover_guard(match.group(1)) == MAIN_GROUP_UPLOAD_IF


# ---- crafted non-empty policy -------------------------------------------

def _target(flavor: str) -> dict:
    return {"variant": "fish", "flavor": flavor, "platform": "linux/amd64",
            "qualification": "browser-qualified", "qualified_at": "2026-10-18",
            "evidence": f"qualification/fish-{flavor}.json"}


def _config(targets: list[dict], retained: list[str]) -> dict:
    return {
        "iso_delivery": {"cutover_targets": targets, "retained_r2_isos": retained},
        "iso_groups": [{"suffix": "kde", "flavors": ["kde"], "offline_flavors": ["kde", "kde-hwe"]}],
        "variants": [{
            "id": "fish", "platforms": ["linux/amd64"],
            "flavors": [{"id": "kde", "build_image": True, "build_iso": True},
                        {"id": "kde-hwe", "build_image": True, "build_iso": False}],
        }],
    }


KDE_RETAINED = ["fish-kde-latest.iso", "fish-kde-10.2-x86_64.iso"]


def _run(fn, config, matrix, active):
    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(json.dumps(matrix)), io.StringIO()
    try:
        fn(config, active)
        return json.loads(sys.stdout.getvalue())["include"]
    finally:
        sys.stdin, sys.stdout = stdin, stdout


def test_cut_over_target_is_suppressed_and_protected():
    config = _config([_target("kde")], KDE_RETAINED)
    active = MOD.active_targets(config, receipts_validated=True)
    assert active == {("fish", "kde", "linux/amd64")}
    rows = _run(MOD.annotate_targets, config, {"include": [
        {"variant": "fish", "flavor": "kde", "platform": "linux/amd64"},
        {"variant": "fish", "flavor": "kde-hwe", "platform": "linux/amd64"},
    ]}, active)
    assert [r["r2_cutover"] for r in rows] == [True, False]
    out = io.StringIO()
    stdout, sys.stdout = sys.stdout, out
    try:
        MOD.print_retention_filters(config)
    finally:
        sys.stdout = stdout
    lines = out.getvalue().splitlines()
    for name in KDE_RETAINED:
        for suffix in ("", ".sha256", ".sigstore.json"):
            assert f"- /{name}{suffix}" in lines
    # Protection precedes the include rules, so first-match-wins keeps them.
    assert max(i for i, l in enumerate(lines) if l.startswith("- /")) < lines.index("+ *.iso")


def test_group_closure_uploads_uncovered_members():
    config = _config([_target("kde")], KDE_RETAINED)
    active = MOD.active_targets(config, receipts_validated=True)
    group = {"variant": "fish", "platform": "linux/amd64", "required_flavors": ["kde", "kde-hwe"]}
    assert _run(MOD.annotate_groups, config, {"include": [group]}, active)[0]["r2_cutover"] is False

    config = _config([_target("kde"), _target("kde-hwe")], KDE_RETAINED)
    active = MOD.active_targets(config, receipts_validated=True)
    assert _run(MOD.annotate_groups, config, {"include": [group]}, active)[0]["r2_cutover"] is True


def test_cli_refuses_nonempty_policy(tmp_path):
    result = _cli(_config([_target("kde")], KDE_RETAINED), "annotate-target-matrix",
                  json.dumps({"include": []}), tmp_path)
    assert result.returncode == 1
    assert "#3381" in result.stderr


@pytest.mark.parametrize("mutate", [
    lambda c: c["iso_delivery"].update(cutover_targets={"variant": "fish"}),
    lambda c: c["iso_delivery"].update(cutover_targets=["fish:kde"]),
    lambda c: c["iso_delivery"]["cutover_targets"][0].update(platform="linux/riscv64"),
    lambda c: c["iso_delivery"]["cutover_targets"][0].update(qualification="maybe"),
    lambda c: c["iso_delivery"]["cutover_targets"][0].update(variant="nonesuch"),
    lambda c: c["iso_delivery"]["cutover_targets"][0].pop("evidence"),
    lambda c: c["iso_delivery"]["cutover_targets"].append(_target("kde")),
    lambda c: c["iso_delivery"].update(retained_r2_isos=["../escape.iso"]),
    lambda c: c["iso_delivery"].update(retained_r2_isos=[]),
])
def test_malformed_policy_fails_loudly(mutate):
    config = copy.deepcopy(_config([_target("kde")], KDE_RETAINED))
    mutate(config)
    with pytest.raises(MOD.PolicyError):
        MOD.active_targets(config, receipts_validated=True)


def test_non_object_policy_fails_loudly():
    with pytest.raises(MOD.PolicyError):
        MOD.active_targets({"iso_delivery": ["kde"]})
