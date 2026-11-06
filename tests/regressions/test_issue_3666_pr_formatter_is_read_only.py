"""#3666: `just fix` runs repository-controlled code on every pull request.

It used to run in one job holding `contents: write` + `pull-requests: write`
with `persist-credentials: true`, so a same-repository branch, a compromised
contributor or a malicious Justfile change could use the token before the
fork guard on the final push step was ever reached. The workflow now splits
the trust domains: `format-pr` (pull_request) is read-only and reports drift;
`fix-main` (push to main) is the only job that can push or open a PR.

The same split was applied to `matrix-status.yml`, whose pull_request drift
check ran PR-controlled generator scripts with `contents: write`.
"""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _jobs(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github/workflows" / name).read_text())["jobs"]


def _checkouts(job: dict) -> list[dict]:
    return [
        s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/checkout@")
    ]


def test_just_fix_pull_request_job_is_read_only_without_credentials():
    job = _jobs("just-fix.yml")["format-pr"]
    assert job["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert all(c["with"]["persist-credentials"] is False for c in _checkouts(job))
    assert not any("git push" in str(s.get("run", "")) for s in job["steps"])


def test_only_the_main_push_job_can_write():
    jobs = _jobs("just-fix.yml")
    assert set(jobs) == {"format-pr", "fix-main"}
    writer = jobs["fix-main"]
    assert writer["if"] == "github.event_name == 'push' && github.ref == 'refs/heads/main'"
    assert writer["permissions"]["contents"] == "write"


def test_matrix_status_pull_request_drift_check_is_read_only():
    jobs = _jobs("matrix-status.yml")
    check, publish = jobs["regenerate"], jobs["publish"]
    assert check["if"] == "github.event_name == 'pull_request'"
    assert check["permissions"] == {"contents": "read", "actions": "read"}
    assert all(c["with"]["persist-credentials"] is False for c in _checkouts(check))
    assert publish["if"] == "github.event_name != 'pull_request'"
    assert publish["permissions"]["contents"] == "write"
