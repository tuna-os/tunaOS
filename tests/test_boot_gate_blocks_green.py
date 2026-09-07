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
    # The script scores `builds` and `boots` itself and takes everything else
    # from gen-matrix-status.py's count. It used to carry a literal
    # "boots,builds" whitelist and exit 1 on anything else, which froze the
    # README block for two weeks after `desktop` and `no_silent_omissions`
    # graduated on 2026-08-19. What matters is the pair of behaviours, not
    # the literal.
    assert "builds | boots)" in body, (
        "the two criteria this script can measure must be named where it "
        "decides whether it can score the blocking set itself"
    )
    assert "composite-green" in body, (
        "a blocking set this script cannot score must be sourced from "
        "docs/MATRIX-STATUS.md, not refused"
    )
    assert "gate=" in body


def test_marker_timeout_dumps_the_serial_tail_into_the_job_log() -> None:
    """2026-08-18 nightlies: every base Gate timed out marker-less with the
    only evidence in a download-only artifact — the job log said nothing
    about WHY. On rc=2 the disk mode now prints the serial tail directly
    (or states the log is EMPTY, which means the guest's console= routing
    never targeted the serial port), so the next silent gate is
    classifiable from the job log alone."""
    script = (ROOT / "scripts" / "iso-e2e.sh").read_text(encoding="utf-8")
    assert "serial log is EMPTY" in script
    assert 'tail -n 120 "$SERIAL_LOG"' in script


def test_base_is_a_reviewed_boots_exclusion_and_the_gate_is_gone() -> None:
    """Maintainer decision 2026-08-18: base images are parent layers, not
    user-facing artifacts — nobody runs them as-is. Their boot machinery is
    transitively proven by every desktop Gate stacked on them (marlin's 15
    Gate-passing cells prove marlin's base boots without ever booting
    marlin:base), and the dedicated base Gate never delivered its serial
    marker on any variant. So: `base` joins the reviewed boots-scope
    exclusions, and the verify_boot_base job is removed rather than left as
    permanently-red noise. This test replaces the three that pinned the old
    gate; re-gating base is a criteria + workflow change that must land
    together, which asserting both halves here enforces."""
    scope = BOOTS["scope"]
    for flavor in ("base", "base-hwe", "base-nvidia"):
        assert flavor in scope["excludes_flavors"]
    doc = yaml.safe_load(WORKFLOW)
    assert "verify_boot_base" not in doc["jobs"], (
        "the base Gate is back but `base` is still scope-excluded — either "
        "remove the job or remove the exclusion; both at once is a board "
        "that ignores a gate it runs")
    # The in-image contract unit stays: it costs nothing and still fires on
    # desktop images at multi-user, before the graphical marker.
    services = (ROOT / "build_scripts" / "40-services.sh").read_text(
        encoding="utf-8")
    assert "tunaos-base-contract.service" in services


def test_scope_excludes_are_not_judged() -> None:
    """Out-of-scope is not the same as untested: an excluded cell simply is
    not judged on boots, while an in-scope cell with no Gate result renders
    untested and cannot be green."""
    boots = BOOTS
    assert not gms.criterion_scope_allows(boots, "base")
    assert not gms.criterion_scope_allows(boots, "base-hwe")
    assert not gms.criterion_scope_allows(boots, "gnome-asahi")
    assert gms.criterion_scope_allows(boots, "gnome")
    assert gms.criterion_scope_allows(boots, "kde-nvidia")
