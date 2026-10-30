# Branch Protection & Required CI (main)

**Status**: Applied 2026-10-29: `Lint` and `Unit Tests` are required on `main`
**Tracks**: #1167 (Q4 goal — branch protection + required CI, untracked enforcement)

## Why this doc exists

#1167 flagged that branch-protection enforcement on `main` was **unverifiable**
via `GET /repos/tuna-os/tunaos/branches/main/protection` (classic API — 403 for
non-admin callers, and in fact 404 "Branch not protected" even for an admin
token, because this repo uses the newer **rulesets** API instead of classic
branch protection). This doc records what `GET
/repos/tuna-os/tunaos/rulesets` shows (verified 2026-08-13) and what
is missing.

## Current state (verified 2026-08-13)

Three rulesets exist on the repo, targeting branches:

| Ruleset | Enforcement | Rules |
|---|---|---|
| `main` (id 10437561) | **active** | `deletion`, `non_fast_forward`, `merge_queue` (grouping `ALLGREEN`), `copilot_code_review` |
| `prod branches` (id 7096492) | disabled | — |
| `Code Quality Copilot review for default branch` (id 19461730) | disabled | — |

The active `main` ruleset protects against branch deletion and force-push,
routes merges through a merge queue, and needs Copilot code review. **It
does not contain a `required_status_checks` rule or a `pull_request` (required
review count) rule.** The merge queue's `ALLGREEN` grouping strategy waits for
whatever checks a given PR happens to have — it does not itself pin down a
required-check list, so there is no enforced minimum CI signal before merge.

`bypass_actors` on the `main` ruleset include `OrganizationAdmin` (always) and
two `RepositoryRole` entries (always) — i.e., admins and elevated repo roles
can bypass every rule on this ruleset, including the merge queue. Rule-suite
history (`GET /repos/tuna-os/tunaos/rulesets/rule-suites?ref=main`) shows
several recent pushes straight to `main` with `"result": "fail"` from
`hanthor-hive-agent[bot]` (e.g. 2026-08-12T23:41 UTC) — evidence the bypass is
exercised, not just theoretically available.

## Candidate required-check list

Each required check in a ruleset is a check **context**. For GitHub Actions,
the context is the job's `name:` (`Lint`, `Unit Tests`), not the job id
(`lint`, `unit-tests`) and not the workflow name. Workflows that report on
every PR into `main` and every merge-queue entry:

| Workflow | Job id | Check context | Trigger |
|---|---|---|---|
| `lint.yml` (Lint and Check) | `lint` | `Lint` | every PR + merge queue; skipped when the PR changes only `**/*.md`, `docs/**`, `LICENSE` |
| `test.yml` (Test) | `unit-tests` | `Unit Tests` | every PR + merge queue; skipped when the PR changes none of the suite's inputs |

Both workflows used to filter at the workflow level (`paths` in `test.yml`,
`paths-ignore` in `lint.yml`), and neither ran on `merge_group`. A PR outside
the filter never got the check. A merge-queue entry never got it either. In
both cases, the PR or the queue waited forever.

Since #1167 each workflow triggers unconditionally on `pull_request` and
`merge_group` and decides in a `changes` job (`dorny/paths-filter`, same path
lists as before). A job skipped by its `if:` reports **Skipped**, which
satisfies a required check; merge-queue entries always run in full.
`tests/test_ci_contract.py` pins that shape. The Tuna PR image builds moved
from `test.yml` to `tuna-pr-images.yml`, because they reach the publish
credential resolver, which may not run on `merge_group`.

Other `pull_request`-triggered workflows (`iso-e2e.yml`, `just-fix.yml`,
`matrix-status.yml`, `live-iso-bootc.yml`, `validate-renovate.yaml`) are
either path-filtered to a narrow subset of PRs or advisory/autofix in nature
(`just-fix.yml`) — none of them are safe to name as a blanket required check
without excluding PRs that never trigger them (a required check that never
runs blocks the PR forever). `conductor-smoke.yml`, previously listed here as
an example of gating speculative code, was removed per #1158 — the ports it
smoke-checked had no packaging and were never wired into a real build.
`conductor/` itself has since been deleted under the same issue.

**Proposal**: the minimum required-status-checks list for a `main`-targeting
ruleset is `Lint` and `Unit Tests`. Broader coverage
(ISO E2E, Matrix Status) should be phased in only if their triggers are
widened to run unconditionally, or added as a separate, narrower ruleset
scoped to the paths they already filter on.

## Applied state (2026-10-29)

Ruleset 10437561 (`main`, active) now has a `required_status_checks` rule.
It names exactly `Lint` and `Unit Tests` (GitHub Actions, integration 15368).
The deletion, non-fast-forward, merge-queue and Copilot review rules stay.
Before this change, #4073 made both checks report on every pull request and
every `merge_group` entry. When a job's `if:` condition skips it, the job
reports Skipped, and Skipped satisfies the rule.

The bypass actors stay: OrganizationAdmin, the repository roles 2 and 5, and
deploy keys. With one maintainer, an emergency fix must not wait on a red
check that has no relation to it. The rule-suite history of the ruleset
records each bypass, so an admin merge is visible.

The PR that adds this section is the enforcement test (step 4). It changes
only documentation, so both checks report Skipped on the PR. The merge queue
runs them in full before it merges.

## Maintainer action and verification checklist

This is the remaining live-repository work for #1167. A maintainer with
ruleset-admin access should apply the proposal to the active `main` ruleset,
then record the result in the issue. The API shape is intentionally shown as a
checklist instead of embedded in CI: rulesets are repository configuration and
must not be silently changed by a code workflow.

1. Read back `GET /repos/tuna-os/tunaos/rulesets/10437561` and confirm that the
   target is `main` and enforcement is `active`.
2. Add one `required_status_checks` rule containing exactly these contexts:
   `Lint` and `Unit Tests` (integration: GitHub Actions, id 15368). Keep the
   merge-queue rule enabled.
3. Decide whether the `OrganizationAdmin` and repository-role bypass actors
   are still necessary. If they remain, document the operational exception;
   if they are removed, verify that the merge queue can still be operated by
   the normal maintainer workflow.
4. Open a small PR that triggers both jobs and confirm that the ruleset's
   rule-suite evaluation reports success before the PR can merge. A direct
   push or an admin merge is not evidence of enforcement because both can
   bypass the ruleset.
5. Re-read the ruleset and rule-suite history, capture the verification date,
   and update this document and #1167 with the observed rule and test PR.

The Q4 exit criterion is satisfied only after steps 1–5 are evidenced. The
current audit is not that evidence: it explicitly found that the
`required_status_checks` rule is absent.

## What this doc is not

This is a documentation-only audit and proposal. Applying it (adding a
`required_status_checks` rule to the `main` ruleset, or narrowing the bypass
list) is a live GitHub repo-settings change outside the scope of a code PR,
and should be made deliberately by a maintainer, not encoded here as if
already in effect.
