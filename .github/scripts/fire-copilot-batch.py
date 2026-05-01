#!/usr/bin/env python3
"""Fire ONE Copilot coding agent issue for all unported upstream commits.

Runs after Gemini has processed each commit individually. For any commits
that Gemini couldn't port (no PR/branch exists), bundles them all into one
Copilot issue so the agent handles them in a single session.

Environment variables:
  GH_TOKEN       - Fine-grained PAT with Issues:write (COPILOT_PAT secret)
  REPO           - owner/repo (from github.repository)
  MATRIX         - JSON from scan: {"include": [{sha, short_sha, subject, author, date, url}]}
  BRANCH_PREFIX  - Branch prefix to check for existing PRs (e.g. zirconium-port)
  PROMPT_FILE    - Path to porting guide markdown
  UPSTREAM_REPO  - Upstream repo slug (e.g. zirconium-dev/zirconium)
  FLAVOR         - Build flavor (niri / gnome / kde)
  BUILD_SCRIPT   - Path to flavor build script
  OVERRIDES_DIR  - Path to flavor overrides directory
  LABEL          - Issue label to attach
"""
import json
import os
import pathlib
import subprocess
import sys

GH_TOKEN = os.environ["GH_TOKEN"]
REPO = os.environ["REPO"]
MATRIX = json.loads(os.environ["MATRIX"])
BRANCH_PREFIX = os.environ["BRANCH_PREFIX"]
PROMPT_FILE = os.environ.get("PROMPT_FILE", "")
UPSTREAM_REPO = os.environ.get("UPSTREAM_REPO", "")
FLAVOR = os.environ.get("FLAVOR", "niri")
BUILD_SCRIPT = os.environ.get("BUILD_SCRIPT", "")
OVERRIDES_DIR = os.environ.get("OVERRIDES_DIR", "")
LABEL = os.environ.get("LABEL", "")

owner, repo = REPO.split("/", 1)
commits = MATRIX.get("include", [])
env = {**os.environ, "GH_TOKEN": GH_TOKEN}


def gh(*args):
    result = subprocess.run(
        ["gh", *args], env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"gh {' '.join(args)} failed (exit {result.returncode}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        result.check_returncode()
    return result


def graphql(query, **variables):
    args = [
        "api", "graphql",
        "-H", "GraphQL-Features: issues_copilot_assignment_api_support",
        "-f", f"query={query}",
    ]
    for k, v in variables.items():
        args += ["-f", f"{k}={v}"]
    result = subprocess.run(["gh", *args], env=env, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


# ── Find commits that Gemini didn't port (no PR exists for the branch) ──────
unported = []
for commit in commits:
    short_sha = commit["short_sha"]
    count = gh(
        "pr", "list",
        "--repo", REPO,
        "--search", f"head:{BRANCH_PREFIX}/{short_sha}",
        "--state", "all",
        "--json", "number",
        "--jq", "length",
    ).stdout.strip()
    if count == "0":
        print(f"  {short_sha}: no PR — needs Copilot")
        unported.append(commit)
    else:
        print(f"  {short_sha}: PR exists — Gemini succeeded")

if not unported:
    print("All commits were ported by Gemini — nothing to do")
    sys.exit(0)

print(f"Batching {len(unported)} commit(s) into one Copilot agent issue")

# ── Load repo context ────────────────────────────────────────────────────────
guide = (
    pathlib.Path(PROMPT_FILE).read_text()
    if PROMPT_FILE and pathlib.Path(PROMPT_FILE).exists()
    else ""
)
build_sh = (
    pathlib.Path(BUILD_SCRIPT).read_text()
    if BUILD_SCRIPT and pathlib.Path(BUILD_SCRIPT).exists()
    else "(not found)"
)
overrides_parts = []
if OVERRIDES_DIR:
    op = pathlib.Path(OVERRIDES_DIR)
    if op.exists():
        for f in sorted(op.rglob("*")):
            if f.is_file():
                try:
                    overrides_parts.append(f"=== {f} ===\n{f.read_text()}")
                except Exception:
                    overrides_parts.append(f"=== {f} === (binary)")
overrides_content = "\n\n".join(overrides_parts) if overrides_parts else "(empty)"

# ── Fetch diffs for each unported commit ────────────────────────────────────
commit_sections = []
for commit in unported:
    sha = commit["sha"]
    short_sha = commit["short_sha"]
    subject = commit["subject"]
    url = commit["url"]

    data = json.loads(
        subprocess.run(
            ["gh", "api", f"/repos/{UPSTREAM_REPO}/commits/{sha}"],
            env=env, capture_output=True, text=True, check=True,
        ).stdout
    )
    full_msg = data["commit"]["message"]
    diff = "\n\n".join(
        f"### {f['filename']}\n```diff\n{f.get('patch', '(binary or no diff)')}\n```"
        for f in data.get("files", [])
    )
    commit_sections.append(
        f"## Commit `{short_sha}`: {subject}\n\n"
        f"**URL**: {url}\n\n"
        f"### Full commit message\n```\n{full_msg}\n```\n\n"
        f"### Diff\n\n{diff}"
    )

# ── Build combined issue body ────────────────────────────────────────────────
all_commits = "\n\n---\n\n".join(commit_sections)
shorts = ", ".join(f"`{c['short_sha']}`" for c in unported)

issue_body = f"""## Upstream Porting Task — {len(unported)} commit(s)

Gemini CLI was unable to port {len(unported)} commit(s) from \
[{UPSTREAM_REPO}](https://github.com/{UPSTREAM_REPO}).

Please port all of them into TunaOS's `{BUILD_SCRIPT}` and `{OVERRIDES_DIR}/`.

**Commits**: {shorts}

---

## Porting Guide

{guide}

---

## Commits to Port

{all_commits}

---

## Current `{BUILD_SCRIPT}`

```bash
{build_sh}
```

## Current `{OVERRIDES_DIR}/` overrides

{overrides_content}
"""

# Truncate if needed — GitHub issue body limit is 65 536 chars
if len(issue_body) > 60_000:
    issue_body = issue_body[:60_000] + "\n\n… (truncated — see upstream links above)"

label_args = ["--label", LABEL] if LABEL else []
title = f"⬆️ [{FLAVOR} port] {len(unported)} upstream commit(s): {shorts}"

# ── Create the issue ─────────────────────────────────────────────────────────
# gh issue create prints the issue URL to stdout; parse the number from it
url_output = gh(
    "issue", "create",
    "--repo", REPO,
    "--title", title,
    "--body", issue_body,
    *label_args,
).stdout.strip()
issue_number = int(url_output.rstrip("/").rsplit("/", 1)[-1])
print(f"Created issue #{issue_number} — {url_output}")

# Fetch the nodeId via REST so we can use it in the GraphQL mutation
issue_data = json.loads(
    gh("api", f"/repos/{REPO}/issues/{issue_number}").stdout
)
issue_node_id = issue_data["node_id"]

# ── Assign the issue to the Copilot coding agent via agentAssignment ─────────
# Get the repo nodeId required by agentAssignment
repo_data = graphql(
    "query($owner: String!, $repo: String!) { repository(owner: $owner, name: $repo) { id } }",
    owner=owner, repo=repo,
)
repo_node_id = repo_data["data"]["repository"]["id"]

graphql(
    """
    mutation($issueId: ID!, $repoId: ID!) {
      replaceActorsForAssignable(input: {
        assignableId: $issueId,
        actorLogins: ["copilot-swe-agent"],
        agentAssignment: { targetRepositoryId: $repoId }
      }) {
        assignable { ... on Issue { number } }
      }
    }
    """,
    issueId=issue_node_id, repoId=repo_node_id,
)
print(f"Copilot coding agent assigned to issue #{issue_number}")
print(f"Track: https://github.com/{REPO}/issues/{issue_number}")
