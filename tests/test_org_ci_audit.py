"""#3011: distinguish missing visibility, reusable jobs and real timeout drift."""
import importlib.util
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location(
    "org_ci_audit", Path(__file__).resolve().parents[1] / "scripts/audit-org-ci.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_workflow_reports_job_and_step_exemptions_and_callee_timeouts():
    result = audit.workflow_summary("ci.yml", """
on: [pull_request, merge_group]
jobs:
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: advisory
        continue-on-error: true
        run: exit 1
  build:
    runs-on: ubuntu-latest
    continue-on-error: ${{ matrix.experimental }}
  ste:
    uses: tuna-os/.github/.github/workflows/ste-lint.yml@main
""")
    assert result["triggers"] == ["merge_group", "pull_request"]
    lint, build, ste = result["jobs"]
    assert lint["timeout_minutes"] == 10
    assert lint["step_continue_on_error"] == ["advisory"]
    assert build["timeout_source"] == "platform-default"
    assert build["continue_on_error"] == "${{ matrix.experimental }}"
    assert ste["timeout_source"] == "callee"
    assert ste["timeout_minutes"] is None


@pytest.mark.parametrize("error", [RuntimeError("HTTP 403"), RuntimeError("HTTP 404"),
                                   subprocess.TimeoutExpired("gh", 90)])
def test_inaccessible_settings_are_unknown(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error
    monkeypatch.setattr(audit, "api", fail)
    assert audit.observation("protection")["state"] == "unknown"


def test_api_uses_get_and_collects_all_pages(monkeypatch):
    def run(command, **kwargs):
        assert command == ["gh", "api", "--method", "GET", "orgs/tuna-os/repos",
                           "--paginate", "--slurp"]
        return subprocess.CompletedProcess(command, 0, '[[{"name":"a"}],[{"name":"b"}]]')
    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.api("orgs/tuna-os/repos", paginate=True) == [{"name": "a"}, {"name": "b"}]


def test_truncated_tree_is_incomplete(monkeypatch):
    def api(endpoint, **kwargs):
        if "/commits/" in endpoint:
            return {"sha": "head", "commit": {"tree": {"sha": "tree"}}}
        if "/git/trees/" in endpoint:
            return {"truncated": True, "tree": []}
        return []
    monkeypatch.setattr(audit, "api", api)
    result = audit.audit_repo({"full_name": "tuna-os/example", "default_branch": "dev",
                               "fork": False, "archived": False})
    assert result["inventory_state"] == "unknown"
    assert "truncated" in result["error"]
    assert result["default_branch"] == "dev"


@pytest.mark.parametrize("text", ["- invalid", "jobs: [invalid]", "jobs: {lint: null}"])
def test_malformed_workflow_is_not_a_successful_empty_inventory(text):
    with pytest.raises(ValueError):
        audit.workflow_summary("bad.yml", text)


def test_workflow_blob_failure_keeps_other_observations(monkeypatch):
    def api(endpoint, **kwargs):
        if "/commits/" in endpoint:
            return {"sha": "head", "commit": {"tree": {"sha": "tree"}}}
        if "/git/trees/" in endpoint:
            return {"tree": [{"path": ".github/workflows/ci.yml", "type": "blob", "sha": "blob"}]}
        if "/git/blobs/" in endpoint:
            raise RuntimeError("HTTP 403")
        return []
    monkeypatch.setattr(audit, "api", api)
    result = audit.audit_repo({"full_name": "tuna-os/example", "default_branch": "main",
                               "fork": False, "archived": False})
    assert result["inventory_state"] == "incomplete"
    assert result["workflows"][0]["error"] == "HTTP 403"
    assert result["effective_rules"]["state"] == "observed"
