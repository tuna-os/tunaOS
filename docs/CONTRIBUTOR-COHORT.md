# Core contributor cohort: October 2026

Tracker: [#2999](https://github.com/tuna-os/tunaos/issues/2999).
The target is **three distinct external human contributors with merged PRs
in `tuna-os/tunaos` by 2026-10-31 (UTC)**. This is a target, not a claim
that the project has achieved it. Contributions to `docs` demonstrate that
repository's onboarding loop; they do not satisfy this core-repository target.

## Prepare a claimable runway

Use the [Hacktoberfest curation checklist](HACKTOBERFEST-2026.md#curation-checklist)
before offering any task. Inventory `tunaos`, `bootc-installer`, `corral`,
`tacklebox`, and `iso-builder`; record zero-task or archived repositories
rather than silently dropping them. Run
[`gfi-pool-report.sh`](../scripts/gfi-pool-report.sh) for the org-wide pool,
then inspect each candidate's body, comments, linked PRs, and local reproduction.
A label alone does not prove that dependencies are resolved or a task is free.
Keep the core-repository starter tasks visible separately: work in another
repository is welcome, but cannot convert into this cohort's core merge count.

For each candidate, record its URL, reproduction/check command, observable
acceptance criteria, dependencies, claim status, and reviewer. Offer only
bounded work that a newcomer can validate without secrets or specialist
hardware. Replace consumed tasks and answer questions before promoting the
pool. Use the existing contributor fork-to-PR instructions rather than asking
new contributors for upstream write access.

After a maintainer verifies event eligibility and the available pool, they can
apply promotional labels and announce it in Matrix and Discord. Link directly
to reviewed tasks and the contributor guide. Do not announce a cohort result
or promise event acceptance before verifying it.

## Daily review through October 31

The repository maintainer, or a reviewer they delegate, checks new claims and
external PRs each day during this campaign. This is the campaign cadence;
the normal [weekly triage](../CONTRIBUTING.md#weekly-contributor-triage)
continues afterward.

1. Acknowledge claims, resolve duplicate claims, and offer an alternate when
   a task has already been taken.
2. Reproduce reported blockers and distinguish environment failures from
   requested code changes. Give the contributor a concrete next action.
3. Review ready PRs promptly; keep required checks, DCO, and review gates.
   Only maintainers merge. A cohort deadline never justifies bypassing a gate.
4. Replenish the available starter pool as work merges. Invite contributors
   to a second bounded task without treating that invitation as retention.

## Weekly evidence receipt

Produce a receipt now, then weekly through October 31 and at the November 1
wrap-up. Save timestamped command output with the checkpoint; never copy a
live count into this runbook. Fetch merged PRs directly, with pagination,
rather than counting search results that may be truncated:

```bash
gh api --paginate --slurp \
  'repos/tuna-os/tunaos/pulls?state=closed&sort=updated&direction=desc&per_page=100' \
  > core-closed-prs.json
jq '[.[][] | select(.merged_at != null) |
     select(.merged_at >= "2026-10-01T00:00:00Z" and
            .merged_at < "2026-11-01T00:00:00Z") |
     {url: .html_url, login: .user.login, type: .user.type,
      association: .author_association, created_at, merged_at}]' \
  core-closed-prs.json > core-october-merges.json
```

API failures or incomplete pagination invalidate the receipt; they are not
zero contributions. Record the UTC collection time, repository, and window.
The window is merge time: a PR opened earlier can still qualify if merged in
October. Future weekly receipts should use the same fixed campaign window,
so cumulative progress remains comparable.

Review each author's identity before counting them. Exclude bots, known
agent-operated accounts, and maintainers; `type: User` and
`author_association: CONTRIBUTOR` alone do not prove an external human.
Use public evidence and maintainer confirmation where identity is ambiguous;
keep unknown accounts explicitly unverified rather than guessing. Do not
collect private identity documents. Deduplicate qualifying people across
multiple PRs or accounts, and retain the PR URLs and exclusion reasons.

Each receipt records:

- qualifying merged PR URLs and distinct verified external humans;
- other merges and why they were excluded or remain unverified;
- claimed tasks, open external PRs, and unanswered blockers, with URLs;
- merges during the last seven days as well as cumulative campaign merges;
- merge conversion: qualifying merged PRs / qualifying submitted PRs in the
  same opening-time cohort, with still-open PRs shown separately;
- repeat contributors, supported by a second contribution's URL, separately
  from the three-person acquisition target.

Do not divide October merges by October submissions: those sets can contain
different PRs. Report counts with every rate, and report an empty denominator
as unavailable. Link the receipt from the tracker and the community checkpoint
in [ADOPTION-METRICS.md](../ADOPTION-METRICS.md).

## Outreach handoff

Once the receipt verifies at least three qualifying people, a maintainer can
link their merged core PRs in outreach material. Until then, describe measured
progress and the open invitation to contribute. Merged work demonstrates an
onboarding loop; it does not by itself establish sustained maintenance,
production adoption, or a support commitment. At wrap-up record unmet targets
and outstanding blockers as well as successes; keep #2999 open until its
cohort and operational follow-through are actually verified.
