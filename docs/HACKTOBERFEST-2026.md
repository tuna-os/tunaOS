# Hacktoberfest 2026 contributor plan

This runbook prepares the tuna-os organization for Hacktoberfest 2026
(October 1–31). It is maintained ahead of the event so contributors arrive at
a useful, reviewed backlog rather than an empty label search.

Tracking issue: [tunaos#1331](https://github.com/tuna-os/tunaos/issues/1331)

## Launch target

Before October 1, maintainers should publish 10–15 open issues that are both
`good first issue` and `help wanted` in the participating repositories. The
backlog should include at least three repositories and no repository should
account for more than half of the tasks.

The initial participation scope is:

- [tunaos](https://github.com/tuna-os/tunaos)
- [docs](https://github.com/tuna-os/docs)
- [corral](https://github.com/tuna-os/corral)
- [iso-builder](https://github.com/tuna-os/iso-builder)
- [letters](https://github.com/tuna-os/letters)
- [Tavern](https://github.com/tuna-os/Tavern)

Apply the `hacktoberfest` repository or issue label only after the 2026
registration guidance is published. Until then, keep curation and eligibility
review separate from the promotional label.

## Current TunaOS candidates

These open issues were present in the queue on 2026-08-13. Recheck their
scope, ownership, and dependencies before announcing them; an issue that is
claimed, stale, or blocked must be replaced.

| Issue | Task | Contribution shape |
|---|---|---|
| [#1308](https://github.com/tuna-os/tunaos/issues/1308) | Reconcile the published-edition documentation/download checklist | research + documentation |
| [#1350](https://github.com/tuna-os/tunaos/issues/1350) | Document the `pantheon` desktop suffix in the README | one-file documentation |
| [#1351](https://github.com/tuna-os/tunaos/issues/1351) | Add a Gurnard/Pantheon desktop guide in `tuna-os/docs` | documentation |
| [#1366](https://github.com/tuna-os/tunaos/issues/1366) | Add README guidance for checksum and SBOM verification | documentation |
| [#1385](https://github.com/tuna-os/tunaos/issues/1385) | Document supported ARM laptop hardware in the README | documentation |

The five items above are a starting pool, not a promise that all five will be
selected. Add at least five more tasks from the other participating
repositories, and keep two alternates available for tasks that are claimed or
found to be too broad.

## Curation checklist

For every selected issue, the maintainer should confirm:

- [ ] The problem statement names the files, page, or test surface to change.
- [ ] The acceptance criteria are observable without privileged hardware or
      secrets.
- [ ] The expected contribution is normally one focused pull request and can
      be reviewed in a few days.
- [ ] Dependencies, generated files, and out-of-scope changes are called out.
- [ ] The issue has both `good first issue` and `help wanted` labels.
- [ ] A maintainer has confirmed that the task is still available.
- [ ] The issue links to `CONTRIBUTING.md` and names where a contributor can
      ask for help.

Do not label speculative feature requests, security-sensitive changes,
release-critical fixes, or work that requires access to organization secrets
as Hacktoberfest starter tasks.

## Timeline and ownership

| Date | Deliverable | Owner |
|---|---|---|
| By 2026-09-01 | Confirm registration and label guidance | strategist |
| By 2026-09-08 | Audit the six repositories and select 10–15 tasks plus two alternates | guide + repository maintainers |
| By 2026-09-15 | Apply final labels, add missing acceptance criteria, and publish the backlog | guide |
| 2026-09-15–30 | Announce participation on the blog and Matrix; link directly to the filtered issue view | outreach |
| 2026-10-01–31 | Triage claims, answer questions, and review starter PRs promptly | repository maintainers |
| By 2026-11-01 | Record results in the adoption funnel | strategist + guide |

Use the organization-wide filtered view when announcing the event:

<https://github.com/issues?q=is%3Aissue+is%3Aopen+org%3Atuna-os+label%3A%22good+first+issue%22>

## Measurement

At launch, record the selected issue URLs and a count by repository. During
the event, record claims, first-time contributor PRs, merged PRs, and median
time to first maintainer response. After the event, record which contributors
returned for another issue or PR. These values feed the community rows in
[`ADOPTION-METRICS.md`](../ADOPTION-METRICS.md); do not treat GitHub stars or
raw PR volume as retention by themselves.
