"""The #3065 census must distinguish empty, claimed, and paired starter pools."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "hacktoberfest_audit",
    Path(__file__).resolve().parents[1] / "scripts/hacktoberfest-audit.py",
)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_zero_pool_keeps_label_coverage():
    row = audit.summarize(
        {"full_name": "tuna-os/example", "archived": False, "has_issues": True},
        [{"name": "good first issue"}], [],
    )
    assert row["has_gfi_label"] is True
    assert row["open_gfi"] == 0
    assert row["starter_urls"] == []


def test_claims_and_pull_requests_do_not_inflate_available_pool():
    def issue(number, labels, **extra):
        return {"html_url": f"https://github.com/tuna-os/example/issues/{number}",
                "labels": [{"name": name} for name in labels], **extra}

    row = audit.summarize(
        {"full_name": "tuna-os/example", "archived": False, "has_issues": True}, [],
        [issue(1, ["good first issue", "help wanted"]),
         issue(2, ["good first issue"], assignees=[{"login": "contributor"}]),
         issue(3, ["good first issue", "help wanted"], pull_request={}),
         issue(4, ["good first issue"])],
    )
    assert row["open_gfi"] == 3
    assert row["unassigned_gfi"] == 2
    assert row["paired_unassigned_gfi"] == 1
    assert len(row["starter_urls"]) == 2


def test_api_pagination_is_flattened(monkeypatch):
    import subprocess

    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, '[[{"name":"a"}],[{"name":"b"}]]')

    monkeypatch.setattr(audit.subprocess, "run", run)
    assert audit.pages("orgs/tuna-os/repos?per_page=100") == [{"name": "a"}, {"name": "b"}]
    assert calls[0][0][2:4] == ["--paginate", "--slurp"]
    assert calls[0][1]["check"] is True


def test_api_failure_is_not_an_empty_pool(monkeypatch):
    import subprocess
    import pytest

    def run(command, **kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="API rate limit exceeded")

    monkeypatch.setattr(audit.subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        audit.pages("orgs/tuna-os/repos?per_page=100")
