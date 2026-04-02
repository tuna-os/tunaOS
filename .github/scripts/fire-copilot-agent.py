#!/usr/bin/env python3
"""Create a GitHub issue with the porting task and assign it to the Copilot coding agent.

Gemini CLI failed — this fires the Copilot coding agent as an async fallback.
The agent will read the issue, check out the repo, and open its own PR.

Environment variables:
  GH_TOKEN  - Fine-grained PAT with Issues:write permission (COPILOT_PAT secret)
  REPO      - owner/repo (from github.repository)
  SHORT_SHA - 8-char commit SHA
  SUBJECT   - commit subject line
  URL       - upstream commit URL
  FLAVOR    - build flavor (niri / gnome / kde)
  UPSTREAM  - upstream repo slug (e.g. zirconium-dev/zirconium)
  LABEL     - issue label to attach
"""
import json
import os
import pathlib
import subprocess
import sys

GH_TOKEN = os.environ["GH_TOKEN"]
REPO = os.environ["REPO"]
SHORT_SHA = os.environ["SHORT_SHA"]
SUBJECT = os.environ["SUBJECT"]
URL = os.environ["URL"]
FLAVOR = os.environ.get("FLAVOR", "niri")
UPSTREAM = os.environ.get("UPSTREAM", "upstream")
LABEL = os.environ.get("LABEL", "")

owner, repo = REPO.split("/", 1)

task = pathlib.Path("GEMINI_TASK.md").read_text()
# Truncate if needed — GitHub issue body limit is 65 536 chars
if len(task) > 60_000:
    task = task[:60_000] + "\n\n… (truncated — see full diff in upstream commit)"

issue_body = f"""## Upstream Porting Task

Gemini CLI was unable to port this upstream commit automatically. \
Please port the change into TunaOS.

**Upstream commit**: [`{SHORT_SHA}`]({URL})
**Flavor**: `{FLAVOR}`
**From**: [{UPSTREAM}](https://github.com/{UPSTREAM})

---

{task}
"""

label_args = ["--label", LABEL] if LABEL else []

# Create the issue
result = subprocess.run(
    ["gh", "issue", "create",
     "--repo", REPO,
     "--title", f"⬆️ [{FLAVOR} port] {SUBJECT} ({SHORT_SHA})",
     "--body", issue_body,
     "--json", "number,nodeId",
     *label_args],
    capture_output=True, text=True, check=True,
    env={**os.environ, "GH_TOKEN": GH_TOKEN},
)
issue = json.loads(result.stdout)
issue_number = issue["number"]
issue_node_id = issue["nodeId"]
print(f"Created issue #{issue_number}")

# Find the Copilot coding agent actor ID
find_query = """
query($owner: String!, $repo: String!) {
  repository(owner: $owner, name: $repo) {
    suggestedActors(capabilities: [CAN_BE_ASSIGNED_TO_COPILOT_ISSUES], first: 1) {
      nodes { id login }
    }
  }
}
"""
result = subprocess.run(
    ["gh", "api", "graphql",
     "-H", "GraphQL-Features: issues_copilot_assignment_api_support",
     "-f", f"query={find_query}",
     "-f", f"owner={owner}",
     "-f", f"repo={repo}"],
    capture_output=True, text=True, check=True,
    env={**os.environ, "GH_TOKEN": GH_TOKEN},
)
data = json.loads(result.stdout)
actors = data["data"]["repository"]["suggestedActors"]["nodes"]
if not actors:
    print("ERROR: No Copilot coding agent actor found.")
    print("Make sure the Copilot coding agent is enabled for this repository.")
    sys.exit(1)

copilot_id = actors[0]["id"]
copilot_login = actors[0]["login"]
print(f"Copilot actor: {copilot_login}")

# Assign the issue to the Copilot coding agent
assign_mutation = """
mutation($issueId: ID!, $actorId: ID!) {
  replaceActorsForAssignable(input: {assignableId: $issueId, actorIds: [$actorId]}) {
    assignable {
      ... on Issue { number }
    }
  }
}
"""
subprocess.run(
    ["gh", "api", "graphql",
     "-H", "GraphQL-Features: issues_copilot_assignment_api_support",
     "-f", f"query={assign_mutation}",
     "-f", f"issueId={issue_node_id}",
     "-f", f"actorId={copilot_id}"],
    check=True,
    env={**os.environ, "GH_TOKEN": GH_TOKEN},
)
print(f"Copilot coding agent assigned to issue #{issue_number}")
print(f"Track: https://github.com/{REPO}/issues/{issue_number}")
