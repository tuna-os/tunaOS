# Branch Protection & Required CI (main)

**Status**: Current-state audit + proposal
**Tracks**: #1167 (Q4 goal — branch protection + required CI, untracked enforcement)

## Why this doc exists

#1167 flagged that branch-protection enforcement on `main` was **unverifiable**
via `GET /repos/tuna-os/tunaos/branches/main/protection` (classic API — 403 for
non-admin callers, and in fact 404 "Branch not protected" even for an admin
token, because this repo uses the newer **rulesets** API instead of classic
branch protection). This doc records what `GET
/repos/tuna-os/tunaos/rulesets` actually shows (verified 2026-08-13) and what
is missing.

## Current state (verified 2026-08-13)

Three rulesets exist on the repo, targeting branches:

| Ruleset | Enforcement | Rules |
|---|---|---|
| `main` (id 10437561) | **active** | `deletion`, `non_fast_forward`, `merge_queue` (grouping `ALLGREEN`), `copilot_code_review` |
| `prod branches` (id 7096492) | disabled | — |
| `Code Quality Copilot review for default branch` (id 19461730) | disabled | — |

The active `main` ruleset protects against branch deletion and force-push,
routes merges through a merge queue, and requires Copilot code review. **It
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
actually exercised, not just theoretically available.

## Candidate required-check list

Required-status-checks must name individual **job** names (not workflow
names). Workflows that trigger unconditionally (or near-unconditionally) on
every PR into `main` today:

| Workflow | Job(s) | Trigger |
|---|---|---|
| `lint.yml` (Lint and Check) | `lint`, `lint-summary` | every PR |
| `test.yml` (Test) | `unit-tests` | every PR (path-filtered) |

Other `pull_request`-triggered workflows (`iso-e2e.yml`, `just-fix.yml`,
`matrix-status.yml`, `live-iso-bootc.yml`, `conductor-smoke.yml`,
`validate-renovate.yaml`) are either path-filtered to a narrow subset of PRs,
advisory/autofix in nature (`just-fix.yml`), or gate speculative code
(`conductor-smoke.yml`, see #1158) — none of them are safe to name as a
blanket required check without excluding PRs that never trigger them (a
required check that never runs blocks the PR forever).

**Proposal**: the minimum required-status-checks list for a `main`-targeting
ruleset should be `lint`, `lint-summary`, and `unit-tests`. Broader coverage
(ISO E2E, Matrix Status) should be phased in only if their triggers are
widened to run unconditionally, or added as a separate, narrower ruleset
scoped to the paths they already filter on.

## What this doc is not

This is a documentation-only audit and proposal. Applying it (adding a
`required_status_checks` rule to the `main` ruleset, or narrowing the bypass
list) is a live GitHub repo-settings change outside the scope of a code PR,
and should be made deliberately by a maintainer, not encoded here as if
already in effect.
