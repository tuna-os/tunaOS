# Hacktoberfest 2026 contributor plan

This runbook prepares the tuna-os organization for Hacktoberfest 2026
(October 1–31). It is maintained ahead of the event so contributors arrive at
a useful, reviewed backlog rather than an empty label search.

Planning issue: [tunaos#1331](https://github.com/tuna-os/tunaos/issues/1331)
Live seeding tracker: [tunaos#1537](https://github.com/tuna-os/tunaos/issues/1537)

## Launch target

Before October 1, maintainers should publish 10–15 open issues that are both
`good first issue` and `help wanted` in the participating repositories. The
backlog should include at least three repositories and no repository should
account for more than half of the tasks.

The seeding audit tracks these eight target repositories:

- [tunaos](https://github.com/tuna-os/tunaos)
- [docs](https://github.com/tuna-os/docs)
- [protota](https://github.com/tuna-os/protota)
- [wootc](https://github.com/tuna-os/wootc)
- [gtk-office-suite](https://github.com/tuna-os/gtk-office-suite)
- [tunaos-packages](https://github.com/tuna-os/tunaos-packages)
- [corral](https://github.com/tuna-os/corral)
- [bootc-installer](https://github.com/tuna-os/bootc-installer) — currently
  blocked because issues are disabled ([tunaos#1531](https://github.com/tuna-os/tunaos/issues/1531)).

`letters` is archived and removed from scope. `iso-builder` and `Tavern` remain
useful expansion sources, but are not substitutes for the eight-repository
gap audit above.

Apply the `hacktoberfest` repository or issue label only after the 2026
registration guidance is published. Until then, keep curation and eligibility
review separate from the promotional label.

## Live gap snapshot

The former tracker [#1362](https://github.com/tuna-os/tunaos/issues/1362) was
closed as completed while its broader target was still open. The T-8 checkpoint
recorded approximately six usable seeds; a fresh label recount on 2026-08-14
found **9 open `good first issue` tasks** across three repositories. That is
progress, but it is still below the **20+ seeds across eight target repos**
needed by 2026-09-15. Counts below are a snapshot, not a substitute for the
weekly audit in #1537.

| Target repo | Open `good first issue` | State | Next action |
|---|---:|---|---|
| tunaos | 2 | ✅ seeded | Keep two or more alternates available |
| docs | 6 | ✅ seeded | Keep tasks scoped and replace claimed items |
| protota | 1 | 🟡 seeded | Confirm acceptance criteria and a maintainer |
| wootc | 0 | 🔴 gap | Curate a bounded task now that CONTRIBUTING exists |
| gtk-office-suite | 0 | 🔴 gap | Scanner/maintainer to select and label a small task |
| tunaos-packages | 0 | 🔴 gap | Packaging maintainer to select a docs/test task |
| corral | 0 viable | 🟡 constrained | Do not force a GFI from the dashboard or large epic; find a smaller candidate or document descope |
| bootc-installer | N/A | 🔴 blocked | Resolve disabled issues or exclude it from the usable-pool denominator |

The count includes issues carrying the `good first issue` label. A task only
counts as **usable** after it passes the curation checklist below and has a
maintainer who can answer questions. A closed tracker, an unlabelled issue, or
an issue in a repository with disabled issue intake does not count.

| Issue | Task | Contribution shape | Status |
|---|---|---|---|
| [#1308](https://github.com/tuna-os/tunaos/issues/1308) | Reconcile the published-edition documentation/download checklist | research + documentation | open |
| [#1526](https://github.com/tuna-os/tunaos/issues/1526) | Add unit tests for `scripts/desktop-verify.py` | tests | open |
| [docs#217](https://github.com/tuna-os/docs/issues/217) | Niri window-manager quick-start for the Bonito variant | documentation | open |
| [docs#216](https://github.com/tuna-os/docs/issues/216) | Evaluate TunaOS in a VM — QEMU/KVM quick-start guide | documentation | open |
| [docs#214](https://github.com/tuna-os/docs/issues/214) | Add a “Choosing your TunaOS variant” decision guide | documentation | open |
| [docs#204](https://github.com/tuna-os/docs/issues/204) | Add Pantheon edition to the Gurnard variant entry on the download page | documentation | open |
| [docs#158](https://github.com/tuna-os/docs/issues/158) | Pantheon keyboard-shortcuts cheat sheet | documentation | open |
| [docs#157](https://github.com/tuna-os/docs/issues/157) | FAQ: fold in top GitHub Discussion questions | documentation | open |
| [protota#193](https://github.com/tuna-os/protota/issues/193) | Declare the project license in `LICENSE` and `package.json` | metadata | open |

~~[#1350](https://github.com/tuna-os/tunaos/issues/1350)~~,
~~[#1366](https://github.com/tuna-os/tunaos/issues/1366)~~, and
~~[#1385](https://github.com/tuna-os/tunaos/issues/1385)~~ — merged, no
longer available to claim.

The listed candidates are a starting pool, not a claim that the target is met.
Add tasks from `wootc`, `gtk-office-suite`, and `tunaos-packages` first; keep
two alternates per repository where practical; and record every new issue or
descope decision in #1537. `iso-builder` and `Tavern` can provide additional
alternates after the eight-target audit is back on track.

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
| By 2026-09-08 | Audit the eight target repositories and select 10–15 launch tasks plus two alternates | guide + repository maintainers |
| By 2026-09-15 | Apply final labels, add missing acceptance criteria, and publish the backlog | guide |
| 2026-09-15–30 | Announce participation on the blog and Matrix; link directly to the filtered issue view | outreach |
| 2026-10-01–31 | Triage claims, answer questions, and review starter PRs promptly | repository maintainers |
| By 2026-11-01 | Record results in the adoption funnel | strategist + guide |

Use the organization-wide filtered view when announcing the event, but link
the live tracker alongside it so a closed planning issue cannot hide the gap:

<https://github.com/issues?q=is%3Aissue+is%3Aopen+org%3Atuna-os+label%3A%22good+first+issue%22>

## Measurement

At launch, record the selected issue URLs and a count by repository. During
the event, record claims, first-time contributor PRs, merged PRs, and median
time to first maintainer response. After the event, record which contributors
returned for another issue or PR. These values feed the community rows in
[`ADOPTION-METRICS.md`](../ADOPTION-METRICS.md); do not treat GitHub stars or
raw PR volume as retention by themselves.
