"""The committed (empty) ISO delivery policy must change nothing.

R2 cutover policy (#3382) is opt-in. With `[iso_delivery]` empty in tunaos.toml,
every target must upload exactly as it did before the policy existed and the R2
pruner must delete exactly what it deleted before. These tests run the real
`scripts/iso-delivery-policy.py` over the real resolved matrix and compare the
effective workflow conditions against the literal pre-policy expressions.

A non-empty policy is accepted only when each target names, by digest, a
committed BrowserIsoQualificationReceipt/v1 that proves it (#3381). Such a
policy must suppress the cut-over target's upload, protect its retained
objects from prune, and still upload group members that the policy leaves
uncovered. Malformed policy and unproven receipts must fail loudly.
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

RECEIPT_FIXTURE = ROOT / "tests" / "fixtures" / "browser-iso-qualification-v1" / "receipt.json"
KDE_RETAINED = ["fish-kde-latest.iso", "fish-kde-10.2-x86_64.iso"]
ARM64_RETAINED = KDE_RETAINED + ["fish-kde-latest-arm64.iso", "fish-kde-10.2-aarch64.iso"]


def _receipt(flavor: str = "kde") -> dict:
    receipt = json.loads(RECEIPT_FIXTURE.read_text(encoding="utf-8"))
    image = f"ghcr.io/tuna-os/fish:{flavor}"
    receipt["target"].update(flavor=flavor, image=image)
    for mode in receipt["modes"].values():
        mode["target_imgref"] = image
    return receipt


def _commit(receipts: Path, receipt: dict) -> str:
    data = MOD.qualification_receipt.canonical(receipt)
    evidence = MOD.qualification_receipt.digest(data)
    receipts.mkdir(parents=True, exist_ok=True)
    (receipts / f"{evidence.removeprefix('sha256:')}.json").write_bytes(data)
    return evidence


def _target(receipts: Path, flavor: str, platform: str = "linux/amd64",
            receipt: dict | None = None) -> dict:
    return {"variant": "fish", "flavor": flavor, "platform": platform,
            "qualification": "browser-qualified", "qualified_at": "2026-11-04",
            "evidence": _commit(receipts, receipt or _receipt(flavor))}


def _config(targets: list[dict], retained: list[str],
            platforms: tuple[str, ...] = ("linux/amd64",)) -> dict:
    return {
        "iso_delivery": {"cutover_targets": targets, "retained_r2_isos": retained},
        "iso_groups": [{"suffix": "kde", "flavors": ["kde"], "offline_flavors": ["kde", "kde-hwe"]}],
        "variants": [{
            "id": "fish", "platforms": list(platforms),
            "flavors": [{"id": "kde", "build_image": True, "build_iso": True},
                        {"id": "kde-hwe", "build_image": True, "build_iso": False}],
        }],
    }


def _run(fn, config, matrix, active):
    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(json.dumps(matrix)), io.StringIO()
    try:
        fn(config, active)
        return json.loads(sys.stdout.getvalue())["include"]
    finally:
        sys.stdin, sys.stdout = stdin, stdout


def test_receipt_fixture_satisfies_the_contract():
    MOD.qualification_receipt.validate(_receipt())


def test_cut_over_target_is_suppressed_and_protected(tmp_path):
    config = _config([_target(tmp_path, "kde")], KDE_RETAINED)
    active = MOD.active_targets(config, receipts_dir=tmp_path)
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


def test_arm64_target_cuts_over_on_the_amd64_receipt(tmp_path):
    amd64 = _target(tmp_path, "kde")
    arm64 = dict(amd64, platform="linux/arm64")
    config = _config([amd64, arm64], ARM64_RETAINED, ("linux/amd64", "linux/arm64"))
    assert MOD.active_targets(config, receipts_dir=tmp_path) == {
        ("fish", "kde", "linux/amd64"), ("fish", "kde", "linux/arm64"),
    }


def test_group_closure_uploads_uncovered_members(tmp_path):
    config = _config([_target(tmp_path, "kde")], KDE_RETAINED)
    active = MOD.active_targets(config, receipts_dir=tmp_path)
    group = {"variant": "fish", "platform": "linux/amd64", "required_flavors": ["kde", "kde-hwe"]}
    assert _run(MOD.annotate_groups, config, {"include": [group]}, active)[0]["r2_cutover"] is False

    config = _config([_target(tmp_path, "kde"), _target(tmp_path, "kde-hwe")], KDE_RETAINED)
    active = MOD.active_targets(config, receipts_dir=tmp_path)
    assert _run(MOD.annotate_groups, config, {"include": [group]}, active)[0]["r2_cutover"] is True


def test_cli_refuses_a_target_without_a_committed_receipt(tmp_path):
    result = _cli(_config([_target(tmp_path, "kde")], KDE_RETAINED), "annotate-target-matrix",
                  json.dumps({"include": []}), tmp_path)
    assert result.returncode == 1
    assert result.stdout == ""


def _other_receipt_bytes(receipts: Path, target: dict) -> None:
    path = receipts / f"{target['evidence'].removeprefix('sha256:')}.json"
    path.write_bytes(MOD.qualification_receipt.canonical(_receipt("kde-hwe")))


def _noncanonical_bytes(receipts: Path, target: dict) -> None:
    receipt = _receipt()
    data = json.dumps(receipt, indent=2).encode()
    target["evidence"] = MOD.qualification_receipt.digest(data)
    (receipts / f"{target['evidence'].removeprefix('sha256:')}.json").write_bytes(data)


def _set_receipt(mutate):
    def apply(receipts: Path, target: dict) -> None:
        receipt = _receipt()
        mutate(receipt)
        target["evidence"] = _commit(receipts, receipt)
    return apply


def _both_modes(field, value):
    def mutate(receipt):
        for mode in receipt["modes"].values():
            mode[field] = value
    return mutate


@pytest.mark.parametrize("refuse", [
    pytest.param(lambda r, t: t.update(evidence="sha256:" + "9" * 64), id="missing-file"),
    pytest.param(lambda r, t: t.update(evidence="qualification/fish-kde.json"), id="evidence-not-digest"),
    pytest.param(_other_receipt_bytes, id="hash-mismatch"),
    pytest.param(_noncanonical_bytes, id="non-canonical-bytes"),
    pytest.param(_set_receipt(lambda r: r["modes"].pop("luks")), id="luks-mode-missing"),
    pytest.param(_set_receipt(lambda r: r["modes"].pop("plain")), id="plain-mode-missing"),
    *[pytest.param(_set_receipt(lambda r, f=field: r["modes"]["luks"].update({f: False})),
                   id=f"{field}-false")
      for field in MOD.qualification_receipt.REQUIRED_TRUE],
    pytest.param(_set_receipt(lambda r: r["modes"]["plain"].update(passphrase_prompt=True)),
                 id="plain-prompted"),
    pytest.param(_set_receipt(lambda r: r["modes"]["luks"].update(passphrase_prompt=False)),
                 id="luks-unprompted"),
    pytest.param(_set_receipt(lambda r: r["modes"]["plain"].update(
        warm_boot_id=r["modes"]["plain"]["cold_boot_id"])), id="boot-ids-equal"),
    pytest.param(_set_receipt(lambda r: r["modes"]["luks"].update(cold_boot_id="not-a-uuid")),
                 id="boot-id-not-uuid"),
    pytest.param(_set_receipt(lambda r: r["modes"]["luks"].update(booted_digest="sha256:" + "7" * 64)),
                 id="booted-not-source"),
    pytest.param(_set_receipt(_both_modes("source_digest", "sha256:" + "7" * 64)),
                 id="source-not-image"),
    pytest.param(_set_receipt(lambda r: r["inputs"].update(source="sha256:" + "7" * 64)),
                 id="input-source-not-image"),
    pytest.param(_set_receipt(_both_modes("target_imgref", "ghcr.io/tuna-os/fish:kde-hwe")),
                 id="imgref-not-image"),
    pytest.param(_set_receipt(lambda r: r["target"].update(variant="bonito", image="ghcr.io/tuna-os/bonito:kde")
                              or _both_modes("target_imgref", "ghcr.io/tuna-os/bonito:kde")(r)),
                 id="variant-mismatch"),
    pytest.param(_set_receipt(lambda r: r["target"].update(platform="linux/arm64")),
                 id="amd64-target-arm64-receipt"),
    pytest.param(_set_receipt(lambda r: r.update(qualification="diagnostic")), id="diagnostic"),
    pytest.param(_set_receipt(lambda r: r.update(qualification="browser-unqualified")), id="other-qualification"),
    pytest.param(_set_receipt(lambda r: r.update(schema="BrowserIsoQualificationReceipt/v0")), id="schema"),
    pytest.param(_set_receipt(lambda r: r["producer"].update(ref="refs/heads/feature")), id="producer-ref"),
    pytest.param(lambda r, t: t.update(qualified_at="2026-11-03"), id="qualified-at-differs"),
])
def test_unproven_receipt_is_refused(tmp_path, refuse):
    target = _target(tmp_path, "kde")
    refuse(tmp_path, target)
    with pytest.raises(MOD.PolicyError):
        MOD.active_targets(_config([target], KDE_RETAINED), receipts_dir=tmp_path)


def test_arm64_target_is_refused_on_an_arm64_receipt(tmp_path):
    receipt = _receipt()
    receipt["target"]["platform"] = "linux/arm64"
    amd64 = _target(tmp_path, "kde")
    arm64 = dict(amd64, platform="linux/arm64", evidence=_commit(tmp_path, receipt))
    config = _config([amd64, arm64], ARM64_RETAINED, ("linux/amd64", "linux/arm64"))
    with pytest.raises(MOD.PolicyError):
        MOD.active_targets(config, receipts_dir=tmp_path)


@pytest.mark.parametrize("mutate", [
    lambda c: c["iso_delivery"].update(cutover_targets={"variant": "fish"}),
    lambda c: c["iso_delivery"].update(cutover_targets=["fish:kde"]),
    lambda c: c["iso_delivery"]["cutover_targets"][0].update(platform="linux/riscv64"),
    lambda c: c["iso_delivery"]["cutover_targets"][0].update(qualification="maybe"),
    lambda c: c["iso_delivery"]["cutover_targets"][0].update(variant="nonesuch"),
    lambda c: c["iso_delivery"]["cutover_targets"][0].pop("evidence"),
    lambda c: c["iso_delivery"]["cutover_targets"].append(c["iso_delivery"]["cutover_targets"][0]),
    lambda c: c["iso_delivery"].update(retained_r2_isos=["../escape.iso"]),
    lambda c: c["iso_delivery"].update(retained_r2_isos=[]),
])
def test_malformed_policy_fails_loudly(tmp_path, mutate):
    config = copy.deepcopy(_config([_target(tmp_path, "kde")], KDE_RETAINED))
    mutate(config)
    with pytest.raises(MOD.PolicyError):
        MOD.active_targets(config, receipts_dir=tmp_path)


def test_non_object_policy_fails_loudly():
    with pytest.raises(MOD.PolicyError):
        MOD.active_targets({"iso_delivery": ["kde"]})
