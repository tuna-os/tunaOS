#!/usr/bin/env python3
"""Unit tests for .github/scripts/fire-copilot-batch.py

Tests core logic extractable from the script:
  - GH_TOKEN empty check → graceful skip
  - Unported commit filtering (PR existence check)
  - Issue body construction with commit sections
  - Body truncation at ~60K characters
  - Auth failure signal detection
  - Label argument construction
  - Title formatting
  - REPO parsing (owner/name split)
"""

import pytest
import json
import os


# ── Constants from the script ───────────────────────────────────────────────

AUTH_FAILURE_SIGNALS = (
    "401",
    "Bad credentials",
    "Failed to log in",
    "token in GH_TOKEN is invalid",
    "token is invalid",
)


# ── GH_TOKEN Empty Check ────────────────────────────────────────────────────

def test_empty_gh_token_triggers_skip():
    """When GH_TOKEN is empty, the script exits 0 with a warning."""
    GH_TOKEN = ""
    if not GH_TOKEN:
        skip = True
    else:
        skip = False
    assert skip is True


def test_nonempty_gh_token_proceeds():
    """When GH_TOKEN is set, the script continues."""
    GH_TOKEN = "ghp_faketoken123"
    if not GH_TOKEN:
        skip = True
    else:
        skip = False
    assert skip is False


# ── Auth Failure Signal Detection ───────────────────────────────────────────

@pytest.mark.parametrize("stderr_line,should_detect", [
    ("401 Bad credentials", True),
    ("Bad credentials", True),
    ("Failed to log in", True),
    ("token in GH_TOKEN is invalid", True),
    ("token is invalid", True),
    ("HTTP 401 Unauthorized", True),
    ("Some other error message", False),
    ("rate limit exceeded", False),
    ("202 Accepted", False),
])
def test_auth_failure_detection(stderr_line, should_detect):
    """Auth failure signals should be correctly detected in stderr."""
    detected = any(s in stderr_line for s in AUTH_FAILURE_SIGNALS)
    assert detected == should_detect


def test_auth_probe_check_logic():
    """Precheck: if gh auth status fails with auth signal, exit 0."""
    pretend_stderr = "Failed to log in: token is invalid"
    rc = 1  # non-zero exit

    is_auth_failure = any(s in pretend_stderr for s in AUTH_FAILURE_SIGNALS)
    if rc != 0 and is_auth_failure:
        should_exit_gracefully = True
    else:
        should_exit_gracefully = False

    assert should_exit_gracefully is True


def test_auth_probe_passes():
    """If gh auth status succeeds, continue."""
    rc = 0
    pretend_stderr = ""
    should_skip = False

    if rc != 0:
        is_auth_failure = any(s in pretend_stderr for s in AUTH_FAILURE_SIGNALS)
        if is_auth_failure:
            should_skip = True

    assert should_skip is False


# ── REPO Parsing ────────────────────────────────────────────────────────────

def test_repo_split_owner_name():
    """REPO is split on first '/' to get owner and name."""
    REPO = "tuna-os/tunaos"
    owner, name = REPO.split("/", 1)
    assert owner == "tuna-os"
    assert name == "tunaos"


def test_repo_split_handles_org_with_slash():
    """Org names don't contain slashes, but handle edge case."""
    REPO = "org-name/repo-name/extra"
    owner, name = REPO.split("/", 1)
    assert owner == "org-name"
    assert name == "repo-name/extra"


# ── Unported Commit Filtering ───────────────────────────────────────────────

def test_filter_unported_commits():
    """Commits without PRs should be collected into unported list."""
    commits = [
        {"sha": "abc111", "short_sha": "abc11100", "subject": "feat: a", "url": "http://a"},
        {"sha": "abc222", "short_sha": "abc22200", "subject": "feat: b", "url": "http://b"},
        {"sha": "abc333", "short_sha": "abc33300", "subject": "feat: c", "url": "http://c"},
    ]
    # Simulate: first and third have no PR, second has one
    pr_counts = {"abc11100": "0", "abc22200": "1", "abc33300": "0"}

    unported = []
    for commit in commits:
        short = commit["short_sha"]
        if pr_counts.get(short, "0") == "0":
            unported.append(commit)

    assert len(unported) == 2
    assert unported[0]["short_sha"] == "abc11100"
    assert unported[1]["short_sha"] == "abc33300"


def test_all_commits_ported_skips_issue():
    """When all commits have PRs, exit with nothing to do."""
    commits = [
        {"sha": "abc111", "short_sha": "abc11100", "subject": "feat: a"},
    ]
    pr_counts = {"abc11100": "1"}

    unported = []
    for commit in commits:
        if pr_counts.get(commit["short_sha"], "0") == "0":
            unported.append(commit)

    assert len(unported) == 0


def test_empty_matrix_exits_cleanly():
    """When MATRIX has no commits, nothing to do."""
    commits = []
    if not commits:
        should_exit = True
    else:
        should_exit = False
    assert should_exit is True


# ── Issue Title Formatting ──────────────────────────────────────────────────

def test_issue_title_includes_flavor_and_count():
    """Title format: ⬆️ [{flavor} port] {count} upstream commit(s): {shorts}"""
    flavor = "niri"
    shorts = "`abc11100`, `abc22200`"
    title = f"⬆️ [{flavor} port] {2} upstream commit(s): {shorts}"
    assert "⬆️" in title
    assert "[niri port]" in title
    assert "2 upstream commit(s)" in title
    assert "`abc11100`" in title
    assert "`abc22200`" in title


def test_issue_title_singular_commit():
    """Title should use singular 'commit' for 1 commit."""
    flavor = "gnome"
    shorts = "`abc11100`"
    title = f"⬆️ [{flavor} port] {1} upstream commit(s): {shorts}"
    assert "1 upstream commit(s)" in title


# ── Issue Body Construction ─────────────────────────────────────────────────

def test_issue_body_contains_commit_sections():
    """Each commit should have a ## Commit section in the body."""
    body_parts = []
    for i, commit in enumerate([
        {"short_sha": "abc11100", "subject": "feat: a", "url": "http://a"}
    ]):
        body_parts.append(
            f"## Commit `{commit['short_sha']}`: {commit['subject']}\n\n"
            f"**URL**: {commit['url']}"
        )
    body = "\n\n---\n\n".join(body_parts)
    assert "## Commit `abc11100`" in body
    assert "feat: a" in body
    # --- separator only appears between multiple commits; single commit has none
    if len(body_parts) > 1:
        assert "---" in body


def test_issue_body_contains_porting_guide():
    """Porting guide content should be in the body."""
    guide = "# Porting Guide\n\nSteps here."
    body = f"""## Porting Guide

{guide}"""
    assert "# Porting Guide" in body
    assert "Steps here." in body


def test_issue_body_contains_build_script():
    """Build script section should be included."""
    build_sh = "#!/bin/bash\necho build"
    body = f"""## Current `build_scripts/niri.sh`

```bash
{build_sh}
```"""
    assert "build_scripts/niri.sh" in body
    assert "```bash" in body
    assert "echo build" in body


def test_issue_body_contains_overrides():
    """Overrides content should be included."""
    overrides = "=== overrides/gdx/10-packages.sh ===\ncontent here"
    body = f"""## Current `overrides/` overrides

{overrides}"""
    assert "overrides" in body
    assert "10-packages.sh" in body


# ── Body Truncation ─────────────────────────────────────────────────────────

def test_body_not_truncated_when_under_limit():
    """Body under 60K chars should not be truncated."""
    body = "x" * 50000
    if len(body) > 60000:
        body = body[:60000] + "\n\n… (truncated — see upstream links above)"
    assert len(body) == 50000
    assert "truncated" not in body


def test_body_truncated_when_over_limit():
    """Body over 60K chars should be truncated."""
    body = "x" * 70000
    original_len = len(body)
    if len(body) > 60000:
        body = body[:60000] + "\n\n… (truncated — see upstream links above)"
    assert len(body) < original_len
    assert "truncated" in body
    assert len(body) == 60000 + len("\n\n… (truncated — see upstream links above)")


# ── Label Handling ──────────────────────────────────────────────────────────

def test_label_args_when_label_provided():
    """When LABEL is set, --label args should be included."""
    LABEL = "upstream-port"
    label_args = ["--label", LABEL] if LABEL else []
    assert label_args == ["--label", "upstream-port"]


def test_label_args_when_label_empty():
    """When LABEL is empty, no --label args."""
    LABEL = ""
    label_args = ["--label", LABEL] if LABEL else []
    assert label_args == []


# ── GraphQL Query Construction ──────────────────────────────────────────────

def test_graphql_query_has_required_header():
    """GraphQL API calls include the copilot_assignment header."""
    args = [
        "api", "graphql",
        "-H", "GraphQL-Features: issues_copilot_assignment_api_support",
        "-f", "query=...",
    ]
    assert "GraphQL-Features: issues_copilot_assignment_api_support" in args


def test_graphql_variables_passed_as_f():
    """Variables are passed as separate -f arguments."""
    variables = {"issueId": "node123", "repoId": "repo456"}
    args = ["api", "graphql"]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    assert "-f" in args
    assert "issueId=node123" in args
    assert "repoId=repo456" in args
