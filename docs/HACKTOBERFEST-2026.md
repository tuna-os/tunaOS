# Hacktoberfest 2026 contributor plan

This runbook prepares the tuna-os organization for Hacktoberfest 2026
(October 1–31). Maintainers keep it current ahead of the event, so
contributors arrive at a useful, reviewed backlog instead of an empty label
search.

Maintainers closed the original tracker
[tunaos#1331](https://github.com/tuna-os/tunaos/issues/1331) and its follow-ups:
[tunaos#1537](https://github.com/tuna-os/tunaos/issues/1537),
[tunaos#1780](https://github.com/tuna-os/tunaos/issues/1780), and
[tunaos#2304](https://github.com/tuna-os/tunaos/issues/2304). They remain
historical references. The live completeness review is
[tunaos#2835](https://github.com/tuna-os/tunaos/issues/2835).

## Launch target

The Q4 adoption plan sets the launch contract at 15–20 open issues that are
both `good first issue` and `help wanted`, spread across at least six
repositories. Assigned issues do not count as available, and no repository
should account for more than half of the tasks.

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
registration guidance appears. Until then, keep curation and eligibility
review separate from the promotional label.

**Two places now break this rule**, and both promise a backlog that does not
exist yet. tunaos [#1798](https://github.com/tuna-os/tunaos/issues/1798),
[#1799](https://github.com/tuna-os/tunaos/issues/1799) and
[#1800](https://github.com/tuna-os/tunaos/issues/1800) already carry the
`hacktoberfest` label. `COMMUNITY.md` opens with "**Hacktoberfest 2026**:
We are participating!" above a link to the org-wide `good first issue` search.
That search returned a total of six issues on 2026-09-02 (see the census
below); three of them share the same task type.

Either bring the pool up to the launch target or hold the public claim until
it is there. A first-timer who follows the banner and finds three shell-test
issues, all near-identical, has had the experience this runbook exists to
prevent.

## Unblocked candidate: bootc-installer

[`tuna-os/bootc-installer`](https://github.com/tuna-os/bootc-installer) is a
strong candidate repo for contributors: its GTK 4/Libadwaita frontend and
`fisherman` pipeline are approachable without the image-factory context.

The plan excluded it before, because GitHub Issues were disabled there
([tunaos#1531](https://github.com/tuna-os/tunaos/issues/1531)). **That blocker
is gone** — #1531 closed, and as of 2026-09-02 the repository has Issues
enabled with 11 open. It carries no `good first issue` tasks yet, so it is an
unseeded candidate, not yet a source of starter tasks.

Remaining steps before adding it to the participation scope:

1. Open two or three bounded tasks from `ROADMAP.md` (for example, a
   `fisherman` test-coverage gap or a Flatpak-manifest polish task).
2. Give each task acceptance criteria that are observable, and both
   `good first issue` and `help wanted` labels.
3. Confirm that the issue URLs, contributor guidance, and labels are visible
   to an unauthenticated visitor before listing the repository here.

Until those checks pass, count `bootc-installer` as an unseeded candidate.
It is not one of the repositories that take part, and not part of the
launch-task quota. It now has an open issue channel and zero other starter
tasks. So it is the cheapest place to add breadth toward the six-repository
target.

## Live completeness check

Do not copy a live count into this runbook. Generate it from GitHub. This
prevents closed, assigned, or relabeled tasks from leaving a false pool claim:

```bash
# Q4 launch contract: at least 15 ready tasks across at least 6 repositories
scripts/gfi-pool-report.sh 15 6
```

The report excludes archived repositories and assigned issues. A ready task
needs both `good first issue` and `help wanted`. The check fails if one
repository holds more than half of the ready pool. The weekly maintenance
floor remains `scripts/gfi-pool-report.sh` (8 tasks across 3 repositories).

The repositories explicitly covered by the completeness review are `tunaos`,
`tromso`, `tacklebox`, `docs`, `bootc-installer`, and `iso-builder`.
`corral`, `gtk-office-suite`, `wootc`, `Tavern`, `tunaos-packages`, and
`protota` are additional candidate repositories. Each of the six review
repositories has a `CONTRIBUTING.md`. This gives new contributors guidance,
but an empty pool is not ready.

## Historical 2026-09-02 snapshot

The 2026-09-02 run of the report found **6 unassigned `good first issue`
tasks org-wide, below the weekly floor of 8**:

| repo | contributable GFI | share | also `help wanted` |
|---|---|---|---|
| `tuna-os/tunaOS` | 3 ([#1798](https://github.com/tuna-os/tunaos/issues/1798), [#1799](https://github.com/tuna-os/tunaos/issues/1799), [#1800](https://github.com/tuna-os/tunaos/issues/1800)) | 50% | 3 |
| `tuna-os/docs` | 2 ([#231](https://github.com/tuna-os/docs/issues/231), [#275](https://github.com/tuna-os/docs/issues/275)) | 33% | 1 (#231) |
| `tuna-os/spindle` | 1 ([#174](https://github.com/tuna-os/spindle/issues/174)) | 17% | 0 |

At the time of this snapshot, the launch target counted only issues with
**both** `good first issue` and `help wanted`. The result was **4 against the
then-current target of 10–15**, across two repositories instead of three.
`tunaOS` holds 3 of those 4 — 75%, past the "no more than half" rule. All
three are the same task type: unit tests for a shell script. A contributor
who does not want to write Bats tests sees one option org-wide.

`spindle` is not in the participation scope listed above. It dates
from 2026-08-26 and carries one GFI without `help wanted`. Decide whether to
admit it to scope and pair the label, or leave it out of the announced view.

### The pool is being drained faster than it is seeded

The 08-14 census in this file recorded 9 contributable tasks in `docs`.
Between 08-30 and 09-02, the project's own agent PRs have closed six of
them:

| Agent PR | Starter issues it closed |
|---|---|
| [docs#349](https://github.com/tuna-os/docs/pull/349) | docs#217 |
| [docs#350](https://github.com/tuna-os/docs/pull/350) | docs#255, docs#256, docs#257 |
| [docs#351](https://github.com/tuna-os/docs/pull/351) | docs#259 |
| [docs#352](https://github.com/tuna-os/docs/pull/352) | docs#264, closed `NOT_PLANNED` as "already addressed" |

`hanthor-hive-agent[bot]` authored all four under the `[scanner]` prefix.
This is the mechanism behind the drop from 9 to 2 in `docs`. It will re-drain
the next seeds too, unless the project separates curation from automation.
For example, agent scanners could skip any issue that carries
`good first issue`, or honour a `reserved-for-humans` label. Tracked
in [tunaos#2304](https://github.com/tuna-os/tunaos/issues/2304).

Seed rate alone does not fix this: the 08-14 snapshot met the threshold and
the pool still fell below it in under three weeks.

This table is evidence from 2026-09-02, not a current promise. Use the live
completeness command above for decisions.

| Target repo | Open `good first issue` (2026-09-02) | Counts toward the launch target? | Next action |
|---|---|---|---|
| [tunaos](https://github.com/tuna-os/tunaOS) | 3 ([#1798](https://github.com/tuna-os/tunaos/issues/1798), [#1799](https://github.com/tuna-os/tunaos/issues/1799), [#1800](https://github.com/tuna-os/tunaos/issues/1800)) | **3** | Diversify: all three are shell-script unit tests. Add a non-test task. |
| [docs](https://github.com/tuna-os/docs) | 2 ([#231](https://github.com/tuna-os/docs/issues/231), [#275](https://github.com/tuna-os/docs/issues/275)) | **1** — #275 lacks `help wanted` | Add `help wanted` to #275; reseed the six consumed tasks. |
| [spindle](https://github.com/tuna-os/spindle) | 1 ([#174](https://github.com/tuna-os/spindle/issues/174)) | **0** — lacks `help wanted`, repo out of scope | Decide on scope admission, then pair the label. |
| [bootc-installer](https://github.com/tuna-os/bootc-installer) | 0 | **0** | Issues now enabled (#1531 closed) — seed 2–3 bounded tasks. |
| [corral](https://github.com/tuna-os/corral) | 0 | **0** | Do not label the Renovate dashboard or large VDI epic; find a smaller task. |
| [iso-builder](https://github.com/tuna-os/iso-builder) | 0 | **0** | Named seeder needed. |
| [gtk-office-suite](https://github.com/tuna-os/gtk-office-suite) | 0 | **0** | Named seeder needed. |
| [wootc](https://github.com/tuna-os/wootc) | 0 | **0** | Re-check the two earlier security seeds; relabel or replace if closed. |
| [Tavern](https://github.com/tuna-os/Tavern) | 0 | **0** | Named seeder needed. |
| [tunaos-packages](https://github.com/tuna-os/tunaos-packages) | 0 | **0** | Named seeder needed; choose a bounded packaging/docs task. |
| [protota](https://github.com/tuna-os/protota) | 0 | **0** | Curate one small test or documentation task. |
| ~~[letters](https://github.com/tuna-os/letters)~~ | — | **0** | Archived (confirmed 2026-09-02); excluded by `archived:false`. |

~~[#1350](https://github.com/tuna-os/tunaos/issues/1350)~~,
~~[#1366](https://github.com/tuna-os/tunaos/issues/1366)~~, and
~~[#1385](https://github.com/tuna-os/tunaos/issues/1385)~~ — merged, no
longer available to claim.

Nine of the eleven live repositories above hold zero curated tasks. The three
cheapest places to add repository breadth are `bootc-installer` (issue channel
now open, no tasks that compete), `docs` (reseed against the six consumed
tasks), and `corral`. **Assign named seeders before the 09-08 audit**
(#1537). Keep two alternates available for tasks that someone claims, or that
turn out to be too broad. Track net pool against consumption, not gross
issues seeded — the 08-14 snapshot cleared the threshold and the pool still
fell below it.

## Conversion-loop evidence (2026-08-14)

The “no external capacity” assumption is no longer valid for the docs channel.
Two first-time, human-authored contributions to docs converted from seeded
issues to merged PRs on 2026-08-14:

| Seed / surface | Result | Evidence |
|---|---|---|
| QEMU/KVM evaluation guide | Merged | [docs#234](https://github.com/tuna-os/docs/pull/234), Dipak Chaudhari, 07:16Z |
| Gurnard Pantheon edition fix | Merged | [docs#239](https://github.com/tuna-os/docs/pull/239), Shawn, 09:19Z |

This is a proven GFI → review → merge loop: **2 converted in one day from
roughly 6–9 usable seeds** (about a 25% observed conversion rate). It is
evidence for external contribution capacity in the docs channel, not
evidence of TunaOS adoption or production use. Keep core-code capacity and adopter
evidence as separate checkpoint inputs.

Re-baseline the seed plan against **net usable tasks**, not gross issues.
Replace consumed tasks promptly, preserve 15–20 usable candidates by the
2026-09-15 deadline, and carry two alternates through the 09-08 audit. At the
first post-launch snapshot, record claims, merged PRs, distinct contributors,
and whether any contributor returns. Do not count a contribution as an adopter
entry without the consent workflow in `ADOPTERS.md`.

## Curation checklist

For every selected issue, the maintainer should confirm:

- [ ] The problem statement names the files, page, or test surface to change.
- [ ] The acceptance criteria are observable without privileged hardware or
      secrets.
- [ ] The expected contribution is usually one pull request with a single
      focus, reviewable in a few days.
- [ ] Dependencies, generated files, and out-of-scope changes are called out.
- [ ] The issue has both `good first issue` and `help wanted` labels.
- [ ] A maintainer has confirmed that the task is still available.
- [ ] The issue links to `CONTRIBUTING.md` and names where a contributor can
      ask for help.

Do not label these as Hacktoberfest starter tasks: speculative feature
requests, security-sensitive changes, or fixes that a release depends on.
Work that needs access to organization secrets is also out.

## Timeline and ownership

| Date | Deliverable | Owner |
|---|---|---|
| By 2026-09-01 | Confirm registration and label guidance | strategist — **overdue as of 2026-09-02**, while `hacktoberfest` labels and the `COMMUNITY.md` banner are already public |
| By 2026-09-08 | Audit the six repositories and select 15–20 tasks plus two alternates — **re-check net pool vs consumption** and preserve the proven docs conversion loop (#1537, #1714) | guide + repository maintainers |
| Before any reseeding | Agree how agent scanners avoid consuming curated starter tasks (#2304) — reseeding without this refills a pool that drains again | strategist + repository maintainers |
| By 2026-09-15 | Apply final labels, add missing acceptance criteria, and publish the backlog | guide |
| 2026-09-15–30 | Announce participation on the blog and Matrix; link directly to the filtered issue view | outreach |
| 2026-10-01–31 | Triage claims, answer questions, and review starter PRs promptly | repository maintainers |
| By 2026-11-01 | Record results in the adoption funnel | strategist + guide |

Use the organization-wide filtered view in the announcement:

<https://github.com/issues?q=is%3Aissue+is%3Aopen+org%3Atuna-os+label%3A%22good+first+issue%22+archived%3Afalse>

`archived:false` is essential, not tidiness. GitHub's issue search includes
archived repositories unless you tell it otherwise. This document already
excludes `letters` from the repo list, because that repository is read-only
and archived. The URL above did not exclude it, so the announced view still
offered its `good first issue`. A first-timer who clicks through, picks it,
and finds they cannot open a pull request has had exactly the experience this
plan exists to prevent.

Measured 2026-08-14: 13 results without the filter, 12 with it. Re-measured
2026-09-02: **7 without the filter, 6 with it**. The archived repository
still inflates the unfiltered count, and the pool itself is now half what it
was.

Use [`scripts/gfi-pool-report.sh`](../scripts/gfi-pool-report.sh) for the
Monday sweep. Do not count by hand. It applies the same filter and checks the
paired launch labels, claimed issues, repository breadth, and concentration.

## Measurement

At launch, record the selected issue URLs and a count by repository. During
the event, record claims, first-time contributor PRs, merged PRs, and median
time to first maintainer response. After the event, record which contributors
returned for another issue or PR. These values feed the community rows in
[`ADOPTION-METRICS.md`](../ADOPTION-METRICS.md); do not treat GitHub stars or
raw PR volume as retention by themselves.
