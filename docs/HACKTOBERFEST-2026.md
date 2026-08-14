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

Re-verified live on 2026-08-14 (T-8 checkpoint) against the 09-15 seeding
target. **Consumption is now outpacing seeding**: five previously-listed
candidates (#1350, #1366, #1385, #1496, #1351) have been claimed and merged
since 08-13 — proof the loop converts end-to-end, but the pool must be
maintained *net of consumption*, not gross-seeded once. Current org-wide
`good first issue` pool: **~8 usable** (docs 5, wootc 2, protota 1; tunaos
shows only meta-tracker #1308 which is a planning issue, not a starter task)
vs the **15–20 needed by 09-15** (#1537). gtk-office-suite and
tunaos-packages remain at **zero** curated tasks. This table must be
re-checked at the 09-08 audit, not treated as static.

| Issue | Task | Contribution shape | Status |
|---|---|---|---|
| [#1308](https://github.com/tuna-os/tunaos/issues/1308) | Reconcile the published-edition documentation/download checklist | research + documentation | open |
| [#1351](https://github.com/tuna-os/tunaos/issues/1351) | Add a Gurnard/Pantheon desktop guide in `tuna-os/docs` | documentation | open |
| [#1496](https://github.com/tuna-os/tunaos/issues/1496) | Link six orphaned docs (TRIAGE-POLICY.md, FEDORA-BASE-POLICY.md, docs/CI_SPEC.md, docs/PIPELINE.md, docs/LUKS-TPM.md, docs/ci-troubleshooting.md) into README | one-file documentation | open |
| [docs#204](https://github.com/tuna-os/docs/issues/204) | Add Pantheon edition to the Gurnard variant entry on the download page | documentation | open |
| [docs#207](https://github.com/tuna-os/docs/issues/207) | Add a Marlin (Arch Linux) variant page | documentation | open |
| [docs#170](https://github.com/tuna-os/docs/issues/170) | FAQ: Apple Silicon / Snapdragon X Elite support | documentation | open |
| [docs#158](https://github.com/tuna-os/docs/issues/158) | Pantheon keyboard-shortcuts cheat sheet | documentation | open |
| [docs#157](https://github.com/tuna-os/docs/issues/157) | FAQ: fold in top GitHub Discussion questions | documentation | open |

~~[#1350](https://github.com/tuna-os/tunaos/issues/1350)~~,
~~[#1366](https://github.com/tuna-os/tunaos/issues/1366)~~, and
~~[#1385](https://github.com/tuna-os/tunaos/issues/1385)~~ — merged, no
longer available to claim.

The eight items above met the 09-15 floor as of 08-13 but **no longer do
as of 08-14** — five have been consumed and tunaos is back to the meta-tracker
only. `gtk-office-suite` and `tunaos-packages` still have **zero** open
`good first issue` tasks each (verified 08-14) — not because nothing is
suitable, but because nobody has curated one yet. `corral` also has zero
viable GFI candidates (only a Renovate dashboard and one large VDI-plugin
epic). `wootc` went from zero to **2** (sec-check #154/#153, 08-14) once its
missing `CONTRIBUTING.md` was fixed (tuna-os/wootc#150). **Recommended:
assign a named seeder for gtk-office-suite + tunaos-packages before the
08-22 Q3 checkpoint** (#1537), and seed from `iso-builder` and `Tavern` too
before the 09-08 audit. Keep two alternates available for tasks that are
claimed or found to be too broad.

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
| By 2026-09-08 | Audit the six repositories and select 10–15 tasks plus two alternates — **re-check net pool vs consumption** (5 consumed 08-13→08-14; #1537) | guide + repository maintainers |
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
