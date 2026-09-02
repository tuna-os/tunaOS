"""Every green criterion must be asserted by a gate that actually runs.

`.github/green-criteria.yml` is the definition of green, and its own header
names the failure mode it exists to prevent: a criterion everyone believes is
checked and which nothing actually blocks on. The `gates` block on each
criterion is the machine-readable claim of what checks it; this file is what
makes the claim cost something.

Each case here corresponds to a way the claim has already been wrong in this
repo's history:

  * `boots` "silently broke matrix-wide on 2026-08-17 (#1811)" — the gate was
    skippable per cell, so a run with no gate looked identical to a pass.
  * `parity` read "not scheduled" for its whole first life — the script
    existed, nothing ran it.
  * `no_silent_omissions` was "written into every image; read by nothing on a
    schedule" — an assertion with no consumer.
  * `bootc-lifecycle.yml` ran once in 9 seconds and the matrix believed it
    was covered (docs/GREEN-MASTER-PLAN.md W2).

The logic lives in scripts/check-ci-contract.py so `just test-contract` and
this PR gate cannot disagree; the tests below drive it per criterion for
precise failures, and pin the helpers it relies on.

Adopted from Hive practice #1 in #2250: "a test existing in the repository is
not the same as a test being run."
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CRITERIA_PATH = ROOT / ".github" / "green-criteria.yml"

spec = importlib.util.spec_from_file_location(
    "check_ci_contract", ROOT / "scripts" / "check-ci-contract.py"
)
contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(contract)

CRITERIA = contract.load_criteria(CRITERIA_PATH)
WORKFLOWS = contract.load_workflows()


@pytest.mark.parametrize("criterion", CRITERIA, ids=[c["id"] for c in CRITERIA])
def test_every_gate_exists_is_reachable_and_cannot_be_waved_through(criterion):
    problems = contract.violations_for(criterion, WORKFLOWS)
    assert not problems, "\n".join(problems)


def test_every_criterion_with_an_assertion_declares_gates():
    """`asserted_by` is prose; `gates` is what the checker can prove. A
    criterion that names an assertion in prose only is exactly the shape
    this file exists to reject."""
    for c in CRITERIA:
        if c.get("asserted_by"):
            assert c.get("gates"), f"{c['id']}: asserted_by without gates"


def test_the_cli_and_the_test_agree():
    """`just test-contract` runs the script; a contributor must not be able
    to get a different verdict from it than CI gets from pytest."""
    assert contract.check() == []
    assert contract.main([]) == 0


# ── the checker would notice ──────────────────────────────────────────────
#
# Guard the guard: each of these mutates a real criterion into a shape that
# has happened before and asserts the checker names it. Without them a
# checker that silently matched nothing would pass the suite above by
# finding zero problems in a clean tree.

def _clone(cid: str) -> dict:
    import copy
    return copy.deepcopy(next(c for c in CRITERIA if c["id"] == cid))


def test_a_missing_workflow_is_a_violation():
    c = _clone("builds")
    c["gates"][0]["workflow"] = ".github/workflows/does-not-exist.yml"
    c["asserted_by"] = "does-not-exist.yml"
    assert any("does not exist" in p for p in contract.violations_for(c, WORKFLOWS))


def test_a_missing_job_is_a_violation():
    c = _clone("builds")
    c["gates"][0]["jobs"] = {"no_such_job": None}
    assert any("no job 'no_such_job'" in p for p in contract.violations_for(c, WORKFLOWS))


def test_a_missing_verdict_step_is_a_violation():
    c = _clone("boots")
    c["gates"][0]["jobs"] = {"verify_boot": "Boot and hope"}
    assert any("no step named 'Boot and hope'" in p
               for p in contract.violations_for(c, WORKFLOWS))


def test_a_blocking_gate_with_continue_on_error_is_a_violation():
    import copy
    wfs = copy.deepcopy(WORKFLOWS)
    wfs[".github/workflows/reusable-build-image.yml"]["jobs"]["verify_boot"][
        "continue-on-error"] = True
    problems = contract.violations_for(_clone("boots"), wfs)
    assert any("continue-on-error" in p for p in problems), problems


def test_an_advisory_gate_may_carry_continue_on_error():
    """The rule is about blocking criteria. bootc-lifecycle's BETA lane is
    continue-on-error by design and lifecycle is advisory."""
    import copy
    wfs = copy.deepcopy(WORKFLOWS)
    wfs[".github/workflows/bootc-lifecycle.yml"]["jobs"]["lifecycle"][
        "continue-on-error"] = True
    assert contract.violations_for(_clone("lifecycle"), wfs) == []


def test_a_flavor_skip_without_scope_is_a_violation():
    c = _clone("boots")
    del c["scope"]
    problems = contract.violations_for(c, WORKFLOWS)
    assert any("no `scope` exemption" in p for p in problems), problems


def test_an_unreachable_reusable_workflow_is_a_violation():
    """Delete every caller of reusable-build-image.yml: it still exists, its
    jobs still exist, and nothing would ever run it."""
    wfs = {k: v for k, v in WORKFLOWS.items()
           if k in {".github/workflows/reusable-build-image.yml"}}
    problems = contract.violations_for(_clone("builds"), wfs)
    assert any("not reachable" in p for p in problems), problems


def test_a_schedule_slower_than_the_sla_is_a_violation():
    c = _clone("parity")
    c["freshness_sla_days"] = 0.5
    problems = contract.violations_for(c, WORKFLOWS)
    assert any("freshness SLA" in p for p in problems), problems


def test_a_criterion_without_an_sla_is_a_violation():
    c = _clone("parity")
    del c["freshness_sla_days"]
    assert any("freshness_sla_days" in p for p in contract.violations_for(c, WORKFLOWS))


# ── helpers ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("expr,gap", [
    ("0 1 * * *", 1),        # nightly
    ("20 22 * * *", 1),
    ("0 5 * * 4", 7),        # weekly, Thursday
    ("0 0 * * MON", 7),
    ("0 6 * * 1,4", 4),      # Mon + Thu: longest wait is Thu → Mon
    ("0 7 1 * *", 31),       # monthly
    ("0 0 1,15 * *", 17),    # 15th → 1st of next month
    ("0 7 1 */3 *", 93),     # quarterly
])
def test_cron_gap_is_bounded_correctly(expr, gap):
    assert contract.cron_max_gap_days(expr) == gap


def test_reachability_follows_uses_chains():
    """reusable-build-image.yml has only workflow_call; it is reachable via
    build-variant.yml (workflow_call) via build-<variant>.yml (schedule)."""
    assert contract.is_reachable(".github/workflows/reusable-build-image.yml", WORKFLOWS)
    assert contract.cadence_days(".github/workflows/reusable-build-image.yml", WORKFLOWS) == 1


def test_a_dispatch_only_workflow_is_not_active():
    doc = {"on": {"workflow_dispatch": None}, "jobs": {}}
    assert not contract.is_reachable("x.yml", {"x.yml": doc})
    assert contract.cadence_days("x.yml", {"x.yml": doc}) is None


def test_the_contract_test_runs_on_workflow_changes():
    """A contract that only runs when tests/ change cannot catch a workflow
    edit that breaks a gate. test.yml's pull_request paths must include the
    workflows and the criteria file."""
    doc = yaml.safe_load((ROOT / ".github/workflows/test.yml").read_text())
    paths = contract.triggers(doc)["pull_request"]["paths"]
    assert ".github/workflows/**" in paths, paths
    assert ".github/green-criteria.yml" in paths, paths
