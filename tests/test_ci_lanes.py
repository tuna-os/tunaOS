"""The documented two-speed CI split is generated and executable.

TunaOS#2264: predictable PR feedback and independent scheduled revalidation
must not drift into an aspirational hand-maintained workflow list.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github/workflows"

spec = importlib.util.spec_from_file_location("gen_ci_lanes", ROOT / "scripts/gen-ci-lanes.py")
assert spec and spec.loader
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)

WORKFLOWS = generator.load_workflows()
ASSERTED = generator.criterion_index()


def test_generated_inventory_names_every_workflow_once() -> None:
    rendered = generator.render(WORKFLOWS, ASSERTED)
    rows = [line for line in rendered.splitlines() if line.startswith("| `")]
    names = [line.split("`")[1] for line in rows]
    expected = sorted(path.name for path in WORKFLOW_DIR.glob("*.y*ml"))
    assert names == expected


def test_committed_inventory_is_generated_not_transcribed() -> None:
    text = (ROOT / "docs/CI_SPEC.md").read_text()
    committed = text.split(generator.BEGIN, 1)[1].split(generator.END, 1)[0]
    generated = generator.render(WORKFLOWS, ASSERTED)
    expected = generated.split(generator.BEGIN, 1)[1].split(generator.END, 1)[0]
    assert committed == expected
    assert generator.update(check=True) == 0


def test_every_green_gate_has_independent_trusted_revalidation() -> None:
    """A PR-only check tests contributor code, not the published factory.
    Every declared criterion must also run after merge or on a schedule."""
    violations = []
    for workflow, criteria in ASSERTED.items():
        lanes = generator.workflow_lanes(workflow, WORKFLOWS)
        if not lanes & {"post-merge", "scheduled"}:
            ids = ", ".join(item["id"] for item in criteria)
            violations.append(f"{workflow} ({ids}) is only {sorted(lanes)}")
    assert not violations, "\n".join(violations)


def test_pr_kvm_checks_have_a_hosted_fallback() -> None:
    """A PR job may use KVM, but lack of KVM cannot strand fork feedback."""
    violations = []
    for name, document in WORKFLOWS.items():
        if "PR-deterministic" not in generator.workflow_lanes(name, WORKFLOWS):
            continue
        run_code = "\n".join(
            str(step.get("run", ""))
            for job in (document.get("jobs") or {}).values()
            for step in (job or {}).get("steps", [])
        )
        if "/dev/kvm" in run_code and "--no-kvm" not in run_code:
            violations.append(f"{name} touches /dev/kvm without a TCG fallback")
    assert not violations, "\n".join(violations)


def test_pr_lane_is_covered_by_the_contributor_ci_contract() -> None:
    """`just ci` composes the same lint, contract, and unit suites used on PRs."""
    utilities = (ROOT / "just/utilities.just").read_text()
    assert "ci: check test-contract test" in utilities
    assert "scripts/gen-ci-lanes.py --check" in utilities

    test_workflow = yaml.safe_load((WORKFLOW_DIR / "test.yml").read_text())
    paths = generator.triggers(test_workflow)["pull_request"]["paths"]
    assert "docs/CI_SPEC.md" in paths
    assert "just/**" in paths

    pr_names = {
        Path(name).name
        for name in WORKFLOWS
        if "PR-deterministic" in generator.workflow_lanes(name, WORKFLOWS)
    }
    assert {"lint.yml", "test.yml"} <= pr_names


def test_pr_lane_remains_fork_safe() -> None:
    """The two-speed classification must retain the existing fork contract."""
    spec = importlib.util.spec_from_file_location(
        "fork_safety", ROOT / "tests/test_fork_safe_workflows.py"
    )
    assert spec and spec.loader
    fork_safety = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fork_safety)

    problems = []
    for name in fork_safety.PR_WORKFLOWS:
        problems.extend(fork_safety._unguarded_write_steps(name))
        document = yaml.safe_load((WORKFLOW_DIR / name).read_text()) or {}
        assert "permissions" in document or all(
            "permissions" in (job or {}) or "uses" in (job or {})
            for job in (document.get("jobs") or {}).values()
        )
    assert not problems, "\n".join(problems)
