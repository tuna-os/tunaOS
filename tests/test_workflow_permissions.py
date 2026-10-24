"""Explicit token baselines must not regress (#2916); also runs in test.yml."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "workflow_permissions", ROOT / "scripts/check-workflow-permissions.py"
)
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


@pytest.mark.parametrize("text", [
    "permissions: {}\njobs: {build: {runs-on: ubuntu-latest}}",
    "permissions: {contents: read}\njobs: {publish: {permissions: {packages: write}}}",
    "permissions: read-all\njobs: {}",
])
def test_explicit_baselines_and_job_inheritance(text):
    assert CHECK.findings(text) == []


@pytest.mark.parametrize("text", [
    "jobs: {build: {permissions: {contents: read}}}",
    "permissions: write-all\njobs: {}",
    "permissions: null",
    "permissions: {}\njobs: {publish: {permissions: write-all}}",
    "permissions: {}\njobs: {publish: {permissions: null}}",
    "permissions: [",
    "[]",
])
def test_unsafe_or_invalid_baselines_fail(text):
    assert CHECK.findings(text)


def test_repository_workflows_declare_permissions():
    paths = sorted((ROOT / ".github/workflows").glob("*"))
    workflows = [path for path in paths if path.suffix in (".yml", ".yaml")]
    assert workflows
    failures = {str(path.relative_to(ROOT)): errors for path in workflows
                if (errors := CHECK.findings(path.read_text()))}
    assert not failures, failures


def test_audit_paginates(monkeypatch):
    calls = []
    def fake_api(endpoint):
        calls.append(endpoint)
        return [{"full_name": f"org/repo-{i}"} for i in range(100)] if endpoint.endswith("&page=1") else []
    monkeypatch.setattr(CHECK, "api", fake_api)
    monkeypatch.setattr(CHECK, "audit_repository", lambda repo: repo)
    assert len(CHECK.audit_org("org")) == 100
    assert len(calls) == 2


def test_truncated_tree_is_an_error(monkeypatch):
    responses = iter([{"sha": "commit", "commit": {"tree": {"sha": "tree"}}}, {"truncated": True}])
    monkeypatch.setattr(CHECK, "api", lambda endpoint: next(responses))
    record = CHECK.audit_repository({"full_name": "org/repo", "default_branch": "main",
                                     "archived": False, "size": 1})
    assert "truncated" in record["error"]


def test_audit_uses_immutable_tree_and_checks_blob(monkeypatch):
    import base64
    calls = []
    responses = iter([
        {"sha": "commit", "commit": {"tree": {"sha": "tree"}}},
        {"tree": [{"path": ".github/workflows/build.yml", "mode": "100644", "sha": "blob"},
                  {"path": "README.md", "mode": "100644", "sha": "ignored"}]},
        {"content": base64.b64encode(b"jobs: {}").decode()},
    ])
    def fake_api(endpoint):
        calls.append(endpoint)
        return next(responses)
    monkeypatch.setattr(CHECK, "api", fake_api)
    record = CHECK.audit_repository({"full_name": "org/repo", "default_branch": "main",
                                     "archived": False, "size": 1})
    assert record["commit"] == "commit"
    assert record["workflows"][0]["findings"] == ["missing top-level permissions"]
    assert calls[1].endswith("/trees/tree?recursive=1")
    assert calls[2].endswith("/blobs/blob")


def test_missing_or_empty_workflow_directory_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(CHECK.sys, "argv", ["check", str(tmp_path)])
    assert CHECK.main() != 0
    err = capsys.readouterr().err
    assert "workflow directory not found" in err

    wf_dir = tmp_path / ".github/workflows"
    wf_dir.mkdir(parents=True)
    assert CHECK.main() != 0
    err = capsys.readouterr().err
    assert "no workflow files found" in err
