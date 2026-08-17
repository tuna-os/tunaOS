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
- [gtk-office-suite](https://github.com/tuna-os/gtk-office-suite) — replaces
  `letters` below, which is **archived** (confirmed 2026-08-12) and
  read-only; any GFI issue there is unclaimable. gtk-office-suite is the
  active successor (tunaos#1362).
- [wootc](https://github.com/tuna-os/wootc)
- [Tavern](https://github.com/tuna-os/Tavern)

~~[letters](https://github.com/tuna-os/letters)~~ — archived, removed from
scope (tunaos#1362).

Apply the `hacktoberfest` repository or issue label only after the 2026
registration guidance is published. Until then, keep curation and eligibility
review separate from the promotional label.

## Current TunaOS candidates

Re-verified live on 2026-08-14 (23:45Z) against the 09-15 seeding target.
The label census finds **11 issues carrying `good first issue` org-wide** —
9 in docs, 1 in tunaos, 1 in letters — but only **9 are contributable**:

| repo | labelled | contributable | why |
|---|---|---|---|
| `tuna-os/docs` | 9 | **9** | |
| `tuna-os/tunaOS` | 1 | **0** | only the meta-tracker (#1308), which is not a starter task |
| `tuna-os/letters` | 1 | **0** | repository is archived read-only; a PR cannot be merged |

That is a net-of-consumption count, not a gross total of every issue ever
seeded, and it is **9 against the 15–20 needed by 09-15** (#1537).

The concentration matters as much as the total. **Every contributable task is
in one repository**, and the flagship repo offers none — a contributor who
wants to write code, or who has already taken the docs task, sees nothing. So
"the pool is ≥8" can be true while the pool is thin, which is why the sweep
reports the per-repository split and warns when one repository holds more than
60% of it. It currently holds 100%.

Re-run this census at the 09-08 audit; the table below is a dated snapshot,
not a static promise.

| Target repo | Open `good first issue` | Usable for Hacktoberfest? | Next action |
|---|---|---|---|
| [tunaos](https://github.com/tuna-os/tunaOS) | 1 (only [#1308](https://github.com/tuna-os/tunaOS/issues/1308)) | **0** — planning issue only | Seed one bounded implementation task. |
| [docs](https://github.com/tuna-os/docs) | 9 ([#217](https://github.com/tuna-os/docs/issues/217), [#231](https://github.com/tuna-os/docs/issues/231), [#232](https://github.com/tuna-os/docs/issues/232), [#255](https://github.com/tuna-os/docs/issues/255), [#256](https://github.com/tuna-os/docs/issues/256), [#257](https://github.com/tuna-os/docs/issues/257), [#259](https://github.com/tuna-os/docs/issues/259), [#262](https://github.com/tuna-os/docs/issues/262), [#264](https://github.com/tuna-os/docs/issues/264)) | **9** pending maintainer confirmation | Maintain against claims and merges. |
| [protota](https://github.com/tuna-os/protota) | 0 | **0** | Curate one small test or documentation task. |
| [wootc](https://github.com/tuna-os/wootc) | 0 | **0** | Re-check the two earlier security seeds; relabel or replace if closed. |
| [gtk-office-suite](https://github.com/tuna-os/gtk-office-suite) | 0 | **0** | Named seeder needed before the 08-22 checkpoint. |
| [tunaos-packages](https://github.com/tuna-os/tunaos-packages) | 0 | **0** | Named seeder needed; choose a bounded packaging/docs task. |
| [corral](https://github.com/tuna-os/corral) | 0 | **0** | Do not label the Renovate dashboard or large VDI epic; find a smaller task. |
| [bootc-installer](https://github.com/tuna-os/bootc-installer) | N/A | **0** — issues disabled | Resolve the structural blocker before counting it. |

~~[#1350](https://github.com/tuna-os/tunaos/issues/1350)~~,
~~[#1366](https://github.com/tuna-os/tunaos/issues/1366)~~, and
~~[#1385](https://github.com/tuna-os/tunaos/issues/1385)~~ — merged, no
longer available to claim.

The earlier 08-14 report listed wootc and protota seeds that are no longer
present in the live label search. `gtk-office-suite`, `tunaos-packages`, and
`corral` still have **zero** open curated tasks; bootc-installer cannot be
counted while its issue tracker is disabled. **Assign named seeders for
gtk-office-suite and tunaos-packages before the 08-22 Q3 checkpoint** (#1537),
then re-check wootc, protota, iso-builder, and Tavern before the 09-08 audit.
Keep two alternates available for tasks that are claimed or found to be too
broad.

## Conversion-loop evidence (2026-08-14)

The “no external capacity” assumption is no longer valid for the docs channel.
Two first-time, human-authored docs contributions converted from seeded issues
to merged PRs on 2026-08-14:

| Seed / surface | Result | Evidence |
|---|---|---|
| QEMU/KVM evaluation guide | Merged | [docs#234](https://github.com/tuna-os/docs/pull/234), Dipak Chaudhari, 07:16Z |
| Gurnard Pantheon edition fix | Merged | [docs#239](https://github.com/tuna-os/docs/pull/239), Shawn, 09:19Z |

This is a proven GFI → review → merge loop: **2 converted in one day from
roughly 6–9 usable seeds** (about a 25% observed conversion rate). It is
evidence for docs-channel external contribution capacity, not evidence of
TunaOS adoption or production use. Keep core-code capacity and adopter
evidence as separate checkpoint inputs.

Re-baseline the seeding plan against **net usable tasks**, not gross issues:
replace consumed tasks promptly, preserve 15–20 usable candidates by the
2026-09-15 deadline, and carry two alternates through the 09-08 audit. At the
first post-launch snapshot, record claims, merged PRs, distinct contributors,
and whether any contributor returns; do not count a contribution as an adopter
entry without the consent workflow in `ADOPTERS.md`.

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
| By 2026-09-08 | Audit the six repositories and select 10–15 tasks plus two alternates — **re-check net pool vs consumption** and preserve the proven docs conversion loop (#1537, #1714) | guide + repository maintainers |
| By 2026-09-15 | Apply final labels, add missing acceptance criteria, and publish the backlog | guide |
| 2026-09-15–30 | Announce participation on the blog and Matrix; link directly to the filtered issue view | outreach |
| 2026-10-01–31 | Triage claims, answer questions, and review starter PRs promptly | repository maintainers |
| By 2026-11-01 | Record results in the adoption funnel | strategist + guide |

Use the organization-wide filtered view when announcing the event:

<https://github.com/issues?q=is%3Aissue+is%3Aopen+org%3Atuna-os+label%3A%22good+first+issue%22+archived%3Afalse>

`archived:false` is load-bearing, not tidiness. GitHub's issue search includes
archived repositories unless told otherwise, and this document already excludes
`letters` from the repo list because it is archived — but the URL above did
not, so the announced view still offered its `good first issue`. A first-timer
who clicks through, picks it, and finds they cannot open a pull request has had
exactly the experience this plan exists to prevent. Measured 2026-08-14: 13
results without the filter, 12 with it.

Re-run [`scripts/gfi-pool-report.sh`](../scripts/gfi-pool-report.sh) for the
Monday sweep rather than counting by hand — it applies the same filter, splits
the pool by repository, and flags issues that are already claimed.

## Measurement

At launch, record the selected issue URLs and a count by repository. During
the event, record claims, first-time contributor PRs, merged PRs, and median
time to first maintainer response. After the event, record which contributors
returned for another issue or PR. These values feed the community rows in
[`ADOPTION-METRICS.md`](../ADOPTION-METRICS.md); do not treat GitHub stars or
raw PR volume as retention by themselves.
