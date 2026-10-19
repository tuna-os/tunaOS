"""The small native lane must run real cases and retain verifiable evidence.

These are orchestration regressions. They are not native package-manager proof.
"""
from pathlib import Path
import json
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/fork-removal-native.yml"
RUNNER = ROOT / "scripts/test-native-fork-removals.sh"


def test_native_lane_is_read_only_bounded_and_runs_for_candidate_changes():
    config = yaml.safe_load(WORKFLOW.read_text())
    triggers = config.get("on", config.get(True))
    assert "workflow_dispatch" in triggers
    paths = triggers["pull_request"]["paths"]
    for path in ("build_scripts/lib/fork-removals.sh", "build_scripts/lib/fork-removal-inventory.py",
                 "tests/test_fork_removal_inventory.py", "tests/test_fork_removals_native_families.py",
                 "scripts/test-native-fork-removals.sh", ".github/workflows/fork-removal-native.yml"):
        assert path in paths
    assert config["permissions"] == {"contents": "read"}
    job = config["jobs"]["native-removal"]
    assert job["timeout-minutes"] <= 15
    assert job["strategy"]["matrix"]["family"] == ["rpm", "pacman"]
    assert job["strategy"]["fail-fast"] is False
    assert not job.get("continue-on-error")
    steps = job["steps"]
    assert steps[0]["with"]["persist-credentials"] is False
    assert "scripts/test-native-fork-removals.sh" in steps[1]["run"]
    assert steps[-1]["if"] == "always()"
    assert steps[-1]["with"]["if-no-files-found"] == "error"


def test_runner_keeps_native_policy_and_immutable_container_provenance():
    script = RUNNER.read_text()
    assert "set -Eeuo pipefail" in script
    assert "docker.io/library/almalinux:10" in script
    assert "docker.io/library/archlinux:base" in script
    assert "docker image inspect" in script and '"$image_id" bash' in script
    assert "dst=/src,readonly" in script
    assert "TUNAOS_NATIVE_REMOVAL_REQUIRED=$family" in script
    assert "--junitxml=/evidence/results.xml" in script
    assert "timeout --kill-after=15s 600s docker run" in script
    assert "--privileged" not in script
    assert not any(flag in script for flag in ("--nodeps", "--nosignature", "--nogpgcheck", "SigLevel = Never"))
    assert "|| true" not in script


def validate_evidence(tmp_path, *, skipped=False, passed=True, count=4, steps=12, evidence=True):
    cases = [f'<testcase name="rpm-{i}">' + ('<skipped />' if skipped else '') + '</testcase>'
             for i in range(count)]
    (tmp_path / "results.xml").write_text("<testsuites><testsuite>" + "".join(cases)
                                           + "</testsuite></testsuites>")
    if evidence:
        for name in ("rpm-dnf", "rpm-zypper", "rpm-dnf-protected", "rpm-zypper-protected"):
            (tmp_path / f"{name}.json").write_text(json.dumps({"passed": passed, "steps": [{}] * (3 if name.endswith("-protected") else steps)}))
    validator = RUNNER.read_text().split("<<'PY'\n", 1)[1].rsplit("\nPY", 1)[0]
    return subprocess.run([sys.executable, "-c", validator, str(tmp_path), "rpm"],
                          text=True, capture_output=True, timeout=10)


def test_evidence_validator_accepts_executed_cases(tmp_path):
    result = validate_evidence(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "4 executed, zero skipped" in result.stdout


@pytest.mark.parametrize("change", [
    {"skipped": True}, {"passed": False}, {"count": 0}, {"count": 1}, {"count": 3},
    {"steps": 8}, {"evidence": False},
])
def test_evidence_validator_rejects_incomplete_or_skipped_cases(tmp_path, change):
    result = validate_evidence(tmp_path, **change)
    assert result.returncode != 0


def test_runner_rejects_unknown_family_before_any_container_action(tmp_path):
    result = subprocess.run(["bash", str(RUNNER), "unknown", str(tmp_path)],
                            text=True, capture_output=True, timeout=10)
    assert result.returncode == 2 and "unsupported native family" in result.stderr
    assert not list(tmp_path.iterdir())


def test_runner_refuses_reused_evidence_before_any_container_action(tmp_path):
    marker = tmp_path / "old.json"
    marker.write_text("old pass")
    result = subprocess.run(["bash", str(RUNNER), "rpm", str(tmp_path)],
                            text=True, capture_output=True, timeout=10)
    assert result.returncode != 0
    assert marker.read_text() == "old pass"
    assert list(tmp_path.iterdir()) == [marker]
