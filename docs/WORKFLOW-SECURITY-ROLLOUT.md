# Coordinate workflow security fixes

[#3152](https://github.com/tuna-os/tunaos/issues/3152) coordinates permission
baselines and action pins across the organization.
[#2916](https://github.com/tuna-os/tunaos/issues/2916) tracks the permission
audit and its enforcement. Keep the work linked through these trackers.

The [generated index](WORKFLOW-SECURITY-ROLLOUT-INDEX.md) groups open issues
by repository. Its JSON source is
[`data/workflow-security-issues.json`](data/workflow-security-issues.json).
It counts issue reports. Several reports can describe the same workflow, and
a report can remain open after its fix merges. Validate each one before you plan a batch.

## Shared baseline

Use the [shared workflow template and security checklist](https://github.com/tuna-os/.github/tree/main/workflow-templates).
New repositories can use [project-starter](https://github.com/tuna-os/.github/tree/main/project-starter).
Consumers copy the template. Later changes to the template do not update
existing consumers. Reusable workflows also cannot supply a missing caller
permission baseline. Declare permissions in each caller.

Use `contents: read` as the normal top-level baseline. Grant write access only
on the job that needs it, with required read scopes repeated in that job's
map. Pin remote actions and reusable workflows to reviewed commit SHAs. Use
local contribution guidance for the PR base and checks.

[PR #3726](https://github.com/tuna-os/tunaos/pull/3726) tracks the audit and checker implementation. It supersedes
[PR #3624](https://github.com/tuna-os/tunaos/pull/3624). Use its workflow
measurements for permission gaps. Do not treat an open PR as a deployed gate,
or create a second permission scanner for this coordination task.

## Batch execution and ownership

1. The coordinator refreshes the issue index before each batch and reviews
   the permission audit. Select one repository and check its required PR base.
   Search its open PRs before you write a fix. If a PR covers the same paths, link this tracker and the local issues in it.
2. A scanner or architect contributor groups the workflow paths in those
   findings into one consumer PR. Reproduce each gap on the required base.
   If it no longer exists, record the merged PR or base commit that removed
   it. Do not infer a gap from the age or title of an issue.
3. The contributor adapts the shared baseline to each job. Review release,
   package, attestation and OIDC grants separately. Check which events reach
   those jobs. Do not apply a global write scope to preserve a publisher.
4. The contributor runs both shared checks and the repository's local lint
   and tests. Include changed paths, base commit, action pin revisions and
   command output in the PR. Keep release and package uploads on trusted events.
5. A maintainer reviews the permission changes. After merge, the coordinator
   verifies the affected workflow on the required branch and links that run
   in the local findings. Keep the issue open if the workflow still fails
   because the change removed a needed permission.

App-level permission to push workflow files and runtime token scopes are
separate. [#1557](https://github.com/tuna-os/tunaos/issues/1557) records the
publication problem and an approved alternate route. Follow the
[publication runbook](CI-WORKFLOW-PUBLISHING.md) if GitHub rejects a push. Record
the actual rejection and route the prepared patch through an authorized
contributor; do not change token scopes or bypass a write gate.

## Closure evidence

Close a local issue after a fix merges and the affected workflow passes.
A checked commit on the base can also prove that the report no longer applies. Link that evidence in the issue.
Do not close issues merely because a template merged or a batch started.
Keep issues with different permission or pin problems separate in the same
PR's coverage notes.

Keep #3152 open until consumers deploy the shared checks and each confirmed gap has closure evidence. Track remaining permission gaps
in #2916 as well. A failed API read is missing evidence, not a clean audit.

## Refresh the index

The index uses paginated GitHub searches for open issue titles with
permission and action pin terms. It does not inspect workflow contents or
prove that an issue is a vulnerability. Search has a 1,000-result cap; the
script rejects a truncated or incomplete response. New issue titles outside
these queries need a query update or separate audit coverage.

```bash
# Read GitHub, then replace the snapshot and index.
GH_TOKEN="$GH_TOKEN" python3 scripts/gen-workflow-security-rollout.py --refresh
# Reproduce the index from the saved snapshot, without network access.
python3 scripts/gen-workflow-security-rollout.py
python3 scripts/gen-workflow-security-rollout.py --check
python3 -m pytest -q tests/test_workflow_security_rollout.py
```

The [weekly workflow](../.github/workflows/workflow-security-rollout.yml)
runs the queries with read-only access and uploads the JSON and Markdown.
It also supports manual runs. It does not change issues or repository settings.

Refresh at the start of each batch and during the weekly security review.
Review the JSON and Markdown diff together. Never transcribe counts from
issue titles into a table of workflow status.
