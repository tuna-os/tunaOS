"""Campaign evidence must not equate automation or concurrent work with retention (#3148)."""
import importlib.util
import json
from pathlib import Path
import subprocess

import pytest

spec = importlib.util.spec_from_file_location(
    "conversion", Path(__file__).resolve().parents[1] / "scripts/hacktoberfest-conversion.py",
)
conversion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conversion)
START = conversion.timestamp("2026-10-01T00:00:00Z")
END = conversion.timestamp("2026-11-01T00:00:00Z")


def pr(number, created="2026-10-02T00:00:00Z", merged=None, login="new-person", **extra):
    return {
        "number": number, "repository": "tuna-os/example",
        "html_url": f"https://github.com/tuna-os/example/pull/{number}",
        "title": "A contribution", "created_at": created,
        "updated_at": merged or created, "merged_at": merged,
        "state": "closed" if merged else "open",
        "user": {"login": login, "type": "User"},
        "author_association": "CONTRIBUTOR", **extra,
    }


def test_unreviewed_user_accounts_do_not_meet_human_target():
    report = conversion.summarize(
        [pr(n, merged="2026-10-03T00:00:00Z") for n in range(20)], START, END, None,
    )
    assert report["raw_activity"]["merged_prs"] == 20
    assert report["new_human_conversion"] is None
    assert not any(row["reviewed_new_human"] for row in report["pull_requests"])


def test_retention_needs_new_pr_after_first_merge_and_window_boundaries():
    cohort = {"new-person": {"login": "new-person", "evidence": "reviewed history URL"}}
    report = conversion.summarize([
        pr(1, created="2026-09-30T23:59:59Z", merged="2026-10-01T00:00:00Z"),
        pr(2, created="2026-10-01T00:00:00Z", merged="2026-10-04T00:00:00Z"),
        pr(3, created="2026-10-05T00:00:00Z", login="New-Person"),
        pr(4, merged="2026-11-01T00:00:00Z"),
        pr(5, merged="2026-10-04T00:00:00Z", user={"login": "new-person", "type": "Bot"}),
        pr(6, merged="2026-10-04T00:00:00Z", user=None),
    ], START, END, cohort)
    metrics = report["new_human_conversion"]
    assert metrics["merged_prs"] == 2
    assert metrics["unique_authors_with_merges"] == 1
    assert metrics["merge_target_met"] is False
    assert metrics["authors_with_followup_prs"] == [{
        "login": "new-person", "prs": ["https://github.com/tuna-os/example/pull/3",
                                        "https://github.com/tuna-os/example/pull/4"],
    }]
    assert not report["pull_requests"][0]["opened_in_window"]


def test_concurrent_prs_are_not_return_visits():
    cohort = {"new-person": {"login": "new-person", "evidence": "history URL"}}
    report = conversion.summarize([
        pr(1, merged="2026-10-03T00:00:00Z"),
        pr(2, merged="2026-10-04T00:00:00Z"),
    ], START, END, cohort)
    assert report["new_human_conversion"]["authors_with_followup_prs"] == []


def test_pagination_keeps_older_opened_pr_merged_during_event(monkeypatch):
    pages = [
        [pr(1, merged="2026-11-02T00:00:00Z"),
         pr(2, created="2026-09-01T00:00:00Z", merged="2026-10-10T00:00:00Z")],
        [pr(3, created="2026-09-01T00:00:00Z")],
    ]
    calls = []

    def api(endpoint):
        calls.append(endpoint)
        return pages.pop(0)

    monkeypatch.setattr(conversion, "api", api)
    rows = conversion.campaign_prs("tuna-os/example", START, END)
    assert {row["number"] for row in rows} == {1, 2}
    assert len(calls) == 2
    assert calls[-1].endswith("page=2")


def test_cohort_requires_review_evidence_and_unique_logins(tmp_path):
    path = tmp_path / "cohort.json"
    for entries in ({}, [None], [{"login": "a", "evidence": None}],
                    [{"login": "a", "evidence": " "}],
                    [{"login": "a", "evidence": "url"}, {"login": "A", "evidence": "url"}]):
        path.write_text(json.dumps(entries))
        with pytest.raises(ValueError):
            conversion.load_cohort(path)


def test_api_uses_get_and_propagates_failure(monkeypatch):
    def fail(command, **kwargs):
        assert command[:4] == ["gh", "api", "--method", "GET"]
        assert kwargs["check"] is True
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(conversion.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        conversion.campaign_prs("tuna-os/example", START, END)


def test_cli_failure_emits_no_partial_receipt(monkeypatch, capsys):
    monkeypatch.setattr(conversion.sys, "argv", ["report", "--repo", "tuna-os/example"])

    def fail(*args):
        raise subprocess.CalledProcessError(1, ["gh", "api"])

    monkeypatch.setattr(conversion, "campaign_prs", fail)
    assert conversion.main() == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "incomplete campaign report" in output.err


def test_cli_reports_reviewed_diff_totals_and_normalizes_scope(monkeypatch, tmp_path, capsys):
    path = tmp_path / "cohort.json"
    path.write_text(json.dumps([{"login": "new-person", "evidence": "public review URL"}]))
    monkeypatch.setattr(conversion.sys, "argv", [
        "report", "--repo", "TUNA-OS/example", "--repo", "tuna-os/example",
        "--cohort", str(path),
    ])
    calls = []

    def campaign(repo, start, end):
        calls.append(repo)
        return [pr(1, merged="2026-10-03T00:00:00Z")]

    monkeypatch.setattr(conversion, "campaign_prs", campaign)
    monkeypatch.setattr(conversion, "api", lambda endpoint: {"additions": 12, "deletions": 3})
    assert conversion.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert calls == ["tuna-os/example"]
    assert report["new_human_conversion"]["additions"] == 12
    assert report["new_human_conversion"]["deletions"] == 3
    assert report["new_human_conversion"]["merged_prs"] == 1
