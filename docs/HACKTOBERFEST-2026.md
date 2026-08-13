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

Re-verified live on 2026-08-13 against #1354's 3→8 tagged-task target. Three
of the five originally-listed candidates (#1350, #1366, #1385) have since
been claimed and merged — proof the loop converts, but also a reminder that
this table needs to be re-checked, not treated as a static plan. The org-wide
`good first issue` pool sits at **6 open** (2 tunaos, 4 docs) as of this
update; two new tasks below (#1496, docs#207) bring it to **8**, meeting the
09-15 target with room to grow toward the 10–15 launch goal.

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

The eight items above meet the 09-15 floor but not yet the 10–15 launch
target from #1331, and `corral` still has zero viable GFI candidates (checked
directly: only a Renovate dashboard and one large VDI-plugin epic — see
#1354's verification comment). `gtk-office-suite` and `tunaos-packages`
currently have **zero** open `good first issue` tasks each — checked
directly (2026-08-13), no false positive: real open issues exist in both
repos but none are scoped/labeled as starter tasks yet, and unlike `corral`
this isn't because there's nothing suitable, it's because nobody has curated
one yet. `wootc` also had zero, plus was missing a `CONTRIBUTING.md`
entirely (fixed: tuna-os/wootc#150), which blocked it from meeting the
curation checklist's link requirement below. Add more tasks from
`iso-builder` and `Tavern` too before the 09-08 audit checkpoint, and keep
two alternates available for tasks that are claimed or found to be too
broad.

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
