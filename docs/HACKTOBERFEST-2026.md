# Hacktoberfest 2026 contributor plan

This runbook prepares the tuna-os organization for Hacktoberfest 2026
(October 1–31). It is maintained ahead of the event so contributors arrive at
a useful, reviewed backlog rather than an empty label search.

Tracking issue: [tunaos#1331](https://github.com/tuna-os/tunaos/issues/1331)
— **closed**, so it is a historical reference rather than a live tracker.
Current open trackers for this work are
[tunaos#1537](https://github.com/tuna-os/tunaos/issues/1537) (seeding rate),
[tunaos#1780](https://github.com/tuna-os/tunaos/issues/1780) (pool
composition) and
[tunaos#2304](https://github.com/tuna-os/tunaos/issues/2304) (pool
consumption).

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

**This rule is currently being broken in two places, both of which promise a
backlog that does not exist yet.** tunaos
[#1798](https://github.com/tuna-os/tunaos/issues/1798),
[#1799](https://github.com/tuna-os/tunaos/issues/1799) and
[#1800](https://github.com/tuna-os/tunaos/issues/1800) already carry the
`hacktoberfest` label, and `COMMUNITY.md` opens with "**Hacktoberfest 2026**:
We are participating!" above a link to the org-wide `good first issue` search.
That search returned six issues on 2026-09-02 (see the census below), three of
them the same task type. Either bring the pool up to the launch target or hold
the public claim until it is there; a first-timer who follows the banner and
finds three near-identical shell-test issues has had the experience this
runbook exists to prevent.

## Unblocked candidate: bootc-installer

[`tuna-os/bootc-installer`](https://github.com/tuna-os/bootc-installer) is a
strong potential contributor repo: its GTK 4/Libadwaita frontend and
`fisherman` pipeline are approachable without the image-factory context.

It was previously excluded because GitHub Issues were disabled there
([tunaos#1531](https://github.com/tuna-os/tunaos/issues/1531)). **That blocker
is gone** — #1531 is closed, and as of 2026-09-02 the repository has Issues
enabled with 11 open. It carries no `good first issue` tasks yet, so it is an
unseeded candidate rather than a contributing repository.

Remaining steps before adding it to the participation scope:

1. Open two or three bounded tasks from `ROADMAP.md` (for example, a
   `fisherman` test-coverage gap or a Flatpak-manifest polish task).
2. Give each task observable acceptance criteria and both `good first issue`
   and `help wanted` labels.
3. Confirm that the issue URLs, contributor guidance, and labels are visible
   to an unauthenticated visitor before listing the repository here.

Until those checks pass, count `bootc-installer` as an unseeded candidate
rather than as one of the participating repositories or as part of the
launch-task quota. Because it now has a working issue channel and zero
competing starter tasks, it is the cheapest place to add repository breadth
toward the "at least three repositories" rule.

## Current TunaOS candidates

Re-verified live on 2026-09-02 with
[`scripts/gfi-pool-report.sh`](../scripts/gfi-pool-report.sh), which applies
`archived:false` and drops assigned issues. It reports **6 contributable
`good first issue` tasks org-wide, below its threshold of 8**:

| repo | contributable GFI | share | also `help wanted` |
|---|---|---|---|
| `tuna-os/tunaOS` | 3 ([#1798](https://github.com/tuna-os/tunaos/issues/1798), [#1799](https://github.com/tuna-os/tunaos/issues/1799), [#1800](https://github.com/tuna-os/tunaos/issues/1800)) | 50% | 3 |
| `tuna-os/docs` | 2 ([#231](https://github.com/tuna-os/docs/issues/231), [#275](https://github.com/tuna-os/docs/issues/275)) | 33% | 1 (#231) |
| `tuna-os/spindle` | 1 ([#174](https://github.com/tuna-os/spindle/issues/174)) | 17% | 0 |

The launch target above counts only issues carrying **both** `good first
issue` and `help wanted`, so the number that matters is **4 against a target
of 10–15**, spread over two repositories rather than the required three.
`tunaOS` holds 3 of those 4 — 75%, past the "no more than half" rule — and all
three are the same task type (unit tests for a shell script), so a contributor
who does not want to write Bats tests sees one option org-wide.

`spindle` is not in the participation scope listed above. It was created
2026-08-26 and carries one GFI without `help wanted`; decide whether to admit
it to scope and pair the label, or leave it out of the announced view.

### The pool is being drained faster than it is seeded

The 08-14 census in this file recorded 9 contributable tasks in `docs`. Six of
them were closed by the project's own agent PRs between 08-30 and 09-02:

| Agent PR | Starter issues it closed |
|---|---|
| [docs#349](https://github.com/tuna-os/docs/pull/349) | docs#217 |
| [docs#350](https://github.com/tuna-os/docs/pull/350) | docs#255, docs#256, docs#257 |
| [docs#351](https://github.com/tuna-os/docs/pull/351) | docs#259 |
| [docs#352](https://github.com/tuna-os/docs/pull/352) | docs#264, closed `NOT_PLANNED` as "already addressed" |

All four were authored by `hanthor-hive-agent[bot]` under the `[scanner]`
prefix. This is the mechanism behind the drop from 9 to 2 in `docs`, and it
will re-drain whatever is seeded next unless curation and automation are
separated — for example by having agent scanners skip any issue carrying
`good first issue`, or by a `reserved-for-humans` label they honour. Tracked
in [tunaos#2304](https://github.com/tuna-os/tunaos/issues/2304).

Seeding rate alone does not fix this: the 08-14 snapshot met the threshold and
the pool still fell below it in under three weeks.

Re-run this census at the 09-08 audit; the tables here are dated snapshots,
not static promises.

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
now open, no competing tasks), `docs` (reseed against the six consumed tasks),
and `corral`. **Assign named seeders before the 09-08 audit** (#1537), and
keep two alternates available for tasks that are claimed or found to be too
broad. Track net pool against consumption, not gross issues seeded — the
08-14 snapshot cleared the threshold and the pool still fell below it.

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
| By 2026-09-01 | Confirm registration and label guidance | strategist — **overdue as of 2026-09-02**, while `hacktoberfest` labels and the `COMMUNITY.md` banner are already public |
| By 2026-09-08 | Audit the six repositories and select 10–15 tasks plus two alternates — **re-check net pool vs consumption** and preserve the proven docs conversion loop (#1537, #1714) | guide + repository maintainers |
| Before any reseeding | Agree how agent scanners avoid consuming curated starter tasks (#2304) — reseeding without this refills a pool that drains again | strategist + repository maintainers |
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
results without the filter, 12 with it. Re-measured 2026-09-02: **7 without
the filter, 6 with it** — the archived repository is still inflating the
unfiltered count, and the pool itself is now half what it was.

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
