# Publishing workflow-file fixes

**Owner:** repository maintainers and the GitHub App owner

This runbook covers the GitHub error:

```text
refusing to allow a GitHub App to create or update workflow
`.github/workflows/...` without `workflows` permission
```

## What the error means

GitHub treats files under `.github/workflows/` as a protected write surface.
The token's ordinary repository `contents: write` access is not enough: the
specific GitHub App installation must also have the App-level **Workflows: Read
and write** permission. A workflow YAML `permissions:` block cannot grant that
permission, and changing the repository branch protection settings does not
work around it.

The failure happens during `git push`, before a pull request exists. A normal
non-workflow commit may push successfully with the same token, which can make
the installation look healthy when it is not.

## Restore the hive App path

Two parties may need to act, in this order:

1. The App owner opens the App settings, edits **Repository permissions →
   Workflows**, selects **Read and write**, and submits the permission change.
2. An organization administrator opens the organization's installed-app
   configuration, selects the hive App, and approves the pending permission
   request. If the App was reinstalled or its permissions were reset, GitHub
   shows the approval banner there instead of applying the App change
   automatically.
3. Retry a small, already-reviewed workflow-fix branch. Verify that the push
   reaches the fork and that the resulting PR contains the workflow diff; do
   not use a test commit on `main`.

If the organization denies the request, record that decision in the tracking
issue and route workflow changes through an approved human or App installation
with `workflows` write access. Keep the patch in the PR or issue discussion
until the replacement route is confirmed.

## Keep App access separate from workflow token access

App-level **Workflows: Read and write** permission controls whether the App can
push workflow files. The workflow's top-level `permissions:` map controls what
its runtime `GITHUB_TOKEN` can do. These are separate security boundaries: an
App can publish a workflow whose runtime token is read-only.

Every workflow must declare a top-level permission baseline before `jobs:`.
Use the smallest baseline that applies to every job:

```yaml
permissions:
  contents: read
```

Add `packages: read` only for a job that pulls from a private registry. A
CodeQL upload job needs `security-events: write`. A job that publishes packages
needs `packages: write`. A job that creates attestations needs
`attestations: write`. A job that uses keyless signatures needs
`id-token: write`. Put each grant only on the applicable job. A job-level map
replaces the top-level map for that job, so repeat required read grants there.

Do not omit the top-level map when repository defaults are read-only. Settings
at the repository or organization level can change. A workflow with no map
inherits the new default. Do not use `write-all`; enumerate each required
permission.

## Triage checklist for a rejected push

- Preserve the complete error, repository, branch, and affected workflow path
  in the issue.
- Confirm the branch contains only the intended workflow change with
  `git diff upstream/main...HEAD -- .github/workflows/`.
- Test whether a non-workflow branch push succeeds; this distinguishes the App
  permission problem from ordinary fork authentication or branch protection.
- Check App-level permission and organization-installation approval separately;
  changing only one side may leave the installation in a pending state.
- Link the replacement PR and close the incident only after the workflow file
  is visible in the PR and its checks start.

## Current incident references

- [#2769](https://github.com/tuna-os/tunaos/issues/2769) — read-only token
  baselines across smaller repositories.
- [#1557](https://github.com/tuna-os/tunaos/issues/1557) — hive App missing
  `workflows` permission.
- [#1390](https://github.com/tuna-os/tunaos/issues/1390) — Catalog Facts
  checkout fix, later routed through [PR #1484](https://github.com/tuna-os/tunaos/pull/1484).
- [#1430](https://github.com/tuna-os/tunaos/issues/1430) — Bootc Lifecycle
  matrix fix, later routed through [PR #1519](https://github.com/tuna-os/tunaos/pull/1519).

This runbook documents the access-recovery path; it does not claim that a
repository commit can grant an App permission.
