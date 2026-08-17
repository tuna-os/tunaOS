"""W3 of docs/GREEN-MASTER-PLAN.md: boots is blocking where CI can boot.

Three parts land together and these tests hold them together:
  * the base Gate (verify_boot_base) — boots plain `base` to multi-user and
    requires TUNAOS_BASE_CONTRACT_OK, WITHOUT blocking Promote ("required for
    green, not for promote")
  * the in-image marker (tunaos-base-contract.service, every image)
  * `boots: blocking` in green-criteria.yml with a reviewed scope, honored
    identically by the composite scoreboard and the README refresh
"""
from __future__ import annotations

import importlib.util
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / ".github" / "workflows" /
            "reusable-build-image.yml").read_text(encoding="utf-8")
CRITERIA = yaml.safe_load(
    (ROOT / ".github" / "green-criteria.yml").read_text()
)["criteria"]
BOOTS = next(c for c in CRITERIA if c["id"] == "boots")
spec = importlib.util.spec_from_file_location(
    "gms", ROOT / "scripts" / "gen-matrix-status.py"
)
gms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gms)


def test_boots_is_blocking_with_a_reviewed_scope() -> None:
    assert BOOTS["enforcement"] == "blocking"
    scope = BOOTS.get("scope") or {}
    assert "base-hwe" in scope.get("excludes_flavors", [])
    assert "base-nvidia" in scope.get("excludes_flavors", [])
    assert "-asahi" in scope.get("excludes_flavor_suffixes", [])


def test_base_gate_exists_and_does_not_block_promote() -> None:
    doc = yaml.safe_load(WORKFLOW)
    jobs = doc["jobs"]
    assert "verify_boot_base" in jobs, "the base Gate job is missing"
    base = jobs["verify_boot_base"]
    assert base["name"] == "Gate", (
        "the job must render as '<flavor> / Gate' — every scoreboard keys on "
        "that name"
    )
    assert "--contract base" in str(base), "base Gate must assert the base marker"
    assert "continue-on-error" not in base, (
        "continue-on-error would launder a failed boot into a success "
        "conclusion — the scoreboard reads this job's conclusion"
    )
    promote_needs = str(jobs["tag-image"]["needs"])
    assert "verify_boot_base" not in promote_needs, (
        "W3 is 'required for green, NOT for promote' — the base Gate must "
        "never gate promotion"
    )


def test_every_image_ships_the_base_contract() -> None:
    services = (ROOT / "build_scripts" / "40-services.sh").read_text()
    assert "tunaos-base-contract.service" in services
    assert "verify-base-contract" in services
    script = (ROOT / "build_scripts" / "checks" /
              "verify-base-contract.sh").read_text()
    assert "TUNAOS_BASE_CONTRACT_OK" in script
    assert "TUNAOS_BASE_CONTRACT_FAIL" in script
    assert "bootc status" in script, (
        "an unoperable bootc deployment must fail the base contract — for a "
        "bootc OS the update machinery is the product"
    )


def test_harness_selects_the_marker_by_contract_flag() -> None:
    harness = (ROOT / "scripts" / "iso-e2e.sh").read_text()
    assert "--contract" in harness
    assert 'CONTRACT_PREFIX="TUNAOS_BASE_CONTRACT"' in harness
    assert 'CONTRACT_PREFIX="TUNAOS_DESKTOP_CONTRACT"' in harness


def test_scope_excludes_are_not_judged_and_gate_absence_is_not_green() -> None:
    criteria = [
        {"id": "builds", "enforcement": "blocking"},
        {"id": "boots", "enforcement": "blocking", "scope": BOOTS["scope"]},
    ]
    stage = {"albacore": {"jobs": {
        ("base", "Promote"): "success",          # promoted, gate absent → ⬜
        ("base-hwe", "Promote"): "success",      # out of boots scope → green
        ("gnome", "Promote"): "success",
        ("gnome", "Gate"): "success",            # the full bar → green
    }, "date": "x"}}
    _, green, _ = gms.composite_section(criteria, stage, {}, {}, {}, {}, {}, {})
    # gnome (promote+gate) and base-hwe (boots out of scope) are green;
    # base promoted but its gate never ran — skipped_is_not_green.
    assert green == 2


def test_duplicate_gate_names_prefer_the_real_verdict() -> None:
    """'base / Gate' exists twice per run (desktop Gate skipped on base, base
    Gate skipped on desktops). Neither job order nor a skipped twin may
    overwrite a real conclusion."""
    verdicts = {}
    for conclusion in ("skipped", "failure", "skipped"):
        key = ("base", "Gate")
        if key in verdicts and conclusion not in ("success", "failure"):
            continue
        verdicts[key] = conclusion
    assert verdicts[("base", "Gate")] == "failure"


def test_readme_updater_scores_boots_with_the_same_scope() -> None:
    body = (ROOT / ".github" / "scripts" / "update-build-status.sh").read_text()
    assert 'select(.id == "boots")' in body, (
        "the README must read the boots scope from green-criteria.yml, not "
        "hardcode it — the two scoreboards may never disagree"
    )
    assert '"boots,builds"' in body, "guard must accept the graduated set"
    assert "gate=" in body


def test_base_gate_evidence_survives_sudo_and_timeouts() -> None:
    """Sailfin run 32068513822, the base Gate's first real boot: the 600s
    timeout crashed on an unbound SCREENSHOT_STDDEV before printing any
    diagnostics, and the root-owned screendump made the artifact upload die
    on EACCES — losing the one serial log that says why the marker never
    arrived. Evidence collection must survive both failure modes."""
    doc = yaml.safe_load(WORKFLOW)
    steps = doc["jobs"]["verify_boot_base"]["steps"]
    names = [s.get("name", "") for s in steps]
    assert "Make evidence uploadable" in names, (
        "verify-out is root-owned (iso-e2e runs under sudo); without a chown "
        "the upload EACCESes and the evidence is lost"
    )
    chown = next(s for s in steps if s.get("name") == "Make evidence uploadable")
    assert chown.get("if") == "always()", "evidence matters MOST on failure"
    assert names.index("Make evidence uploadable") < names.index("Upload boot evidence")
    install = next(s for s in steps if s.get("name") == "Install dependencies")
    assert "imagemagick" in install["run"], (
        "without ImageMagick every screenshot is unjudgeable and the paint "
        "poll burns its full cap"
    )
    harness = (ROOT / "scripts" / "iso-e2e.sh").read_text(encoding="utf-8")
    assert "${SCREENSHOT_STDDEV:-" in harness, (
        "screenshot_sane's early returns never set SCREENSHOT_STDDEV; a bare "
        "expansion under set -u kills the timeout path before diagnostics"
    )
    assert "(stddev=${SCREENSHOT_STDDEV})" not in harness
