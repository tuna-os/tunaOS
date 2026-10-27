"""The empty ISO delivery policy must preserve normal publication behavior.

Exercise the real policy CLI and retention output. Non-empty cutovers remain
disabled until #3381 supplies current validated receipts and input checks.
"""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "scripts" / "iso-delivery-policy.py"
SPEC = importlib.util.spec_from_file_location("iso_delivery_policy_identity", POLICY)
MOD = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MOD)

CONFIG = yaml.safe_load((ROOT / ".github" / "build-config.yml").read_text(encoding="utf-8"))

# The default retention output protects stable pointers and leaves dated
# artifacts eligible for the existing age-based prune.
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
                # The publisher supports generic AMD64, AMD64/v2, and ARM64 rows.
                if platform not in ("linux/amd64", "linux/amd64/v2", "linux/arm64"):
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


@pytest.mark.parametrize(("platform", "latest", "dated", "legacy"), [
    ("linux/amd64", "fish-kde-latest.iso", "fish-kde-10.2-linux-amd64.iso",
     "fish-kde-10.2-x86_64.iso"),
    ("linux/amd64/v2", "fish-kde-latest-v2.iso", "fish-kde-10.2-linux-amd64-v2.iso", None),
    ("linux/arm64", "fish-kde-latest-arm64.iso", "fish-kde-10.2-linux-arm64.iso",
     "fish-kde-10.2-aarch64.iso"),
])
def test_platform_retention_names_match_iso_safeplatform(platform, latest, dated, legacy):
    assert MOD.latest_name("fish", "kde", platform) == latest
    assert MOD.has_dated_iso((dated,), "fish", "kde", platform)
    if legacy is not None:
        assert MOD.has_dated_iso((legacy,), "fish", "kde", platform)
    wrong = "fish-kde-10.2-wrong-platform.iso"
    assert not MOD.has_dated_iso((wrong,), "fish", "kde", platform)

    config = _config([], [])
    matrix = {"include": [
        {"variant": "fish", "flavor": "kde", "platform": platform},
    ]}
    input_stream, output_stream = sys.stdin, sys.stdout
    output = io.StringIO()
    try:
        sys.stdin, sys.stdout = io.StringIO(json.dumps(matrix)), output
        MOD.annotate_targets(config, frozenset())
    finally:
        sys.stdin, sys.stdout = input_stream, output_stream
    assert json.loads(output.getvalue())["include"] == [{
        "variant": "fish", "flavor": "kde", "platform": platform,
        "r2_cutover": False,
    }]

    config = _config([_target("kde")], [latest, dated])
    config["iso_delivery"]["cutover_targets"][0]["platform"] = platform
    config["variants"][0]["platforms"] = [platform]
    config["variants"][0]["flavors"][0]["platforms"] = [platform]
    with pytest.raises(MOD.PolicyError, match="current validated qualification snapshot"):
        MOD.active_targets(config)


def test_nonempty_policy_requires_authoritative_receipt_and_current_inputs():
    config = _config([_target("kde")], KDE_RETAINED)
    with pytest.raises(MOD.PolicyError, match="current validated qualification snapshot"):
        MOD.active_targets(config)


def test_complete_group_still_fails_closed_without_a_snapshot():
    config = _config([_target("kde"), _target("kde-hwe")], KDE_RETAINED)
    with pytest.raises(MOD.PolicyError, match="current validated qualification snapshot"):
        MOD.active_targets(config)


def test_retention_filters_protect_listed_objects_without_claiming_cutover():
    config = _config([_target("kde")], KDE_RETAINED)
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
    assert max(i for i, line in enumerate(lines) if line.startswith("- /")) < lines.index("+ *.iso")




def test_cli_refuses_nonempty_policy_without_current_snapshot(tmp_path):
    result = _cli(_config([_target("kde")], KDE_RETAINED), "annotate-target-matrix",
                  json.dumps({"include": []}), tmp_path)
    assert result.returncode == 1
    assert "current validated qualification snapshot" in result.stderr


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
        MOD.active_targets(config)


def test_non_object_policy_fails_loudly():
    with pytest.raises(MOD.PolicyError):
        MOD.active_targets({"iso_delivery": ["kde"]})
