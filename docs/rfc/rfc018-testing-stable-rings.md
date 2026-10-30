# RFC 018: `:testing` and `:stable` image rings

- **Status:** Draft. A maintainer must approve the approach (decisions below).
- **Issue:** [#4154](https://github.com/tuna-os/tunaOS/issues/4154)
- **Branch:** `rfc018-testing-stable-rings`
- **Owner:** @hanthor
- **Related:** [#4072](https://github.com/tuna-os/tunaOS/issues/4072) (SDLC tracker), [#4116](https://github.com/tuna-os/tunaOS/pull/4116) (ledger, HIVE-6 / TUNA-3), [`VERSIONING.md`](../../VERSIONING.md), [`runbooks/rollback-a-bad-image-promotion.md`](../../runbooks/rollback-a-bad-image-promotion.md), [#2263](https://github.com/tuna-os/tunaOS/issues/2263), [#2250](https://github.com/tuna-os/tunaOS/issues/2250)
- **Decision:** None yet. This RFC becomes ADR 0016 when a maintainer approves.

## Problem

Every image that passes CI goes to users the same night:

- The Promote job (`tag-image` in `reusable-build-image.yml`) copies the
  `:<flavor>-testing` candidate onto the bare `:<flavor>` tag in the same run
  that built it.
- The bare tag is what the README, `docs/USER-GUIDE.md`, `MIGRATION.md`, the
  weekly ISOs (`publish-iso-groups.yml`) and every `bootc upgrade` track.

The rollback runbook says it directly: "There is no separate 'stable' gate
between promotion and that exposure."

CI gates catch a lot, but not everything. They miss regressions outside the
desktop contract, hardware faults that QEMU does not reproduce, and security
issues found after release. Today those reach every user within a day.

`VERSIONING.md` promises Weekly and LTS tiers, but no workflow writes them, and
the owner has decided against LTS.

## Decision taken by the owner

There are two rings and no LTS:

| Ring | Who tracks it | What it gets |
|---|---|---|
| `:testing` | people who want each day's build: maintainers, early adopters, Hive's own canaries | every image that passes CI, the same day |
| `:stable` | everyone else, including the default for new installs and ISOs | a `:testing` image only after it has soaked with no reported regression |

## Current tags (what this RFC changes)

| Tag | Today | Gated |
|---|---|---|
| `:<flavor>-<platform>` | per-platform build output | no |
| `:<flavor>-testing` | the **candidate** manifest that the boot, desktop and Asahi gates read | no |
| `:<flavor>`, `:<flavor>-<arch>`, `:<flavor>[-<arch>]-YYYYMMDD`, alias images | written by Promote from the candidate | yes |

The name `-testing` is already taken by the ungated candidate. That is not a
tag users should track, so the user-facing ring needs that name freed or a
different name.

## Options

### A. Bare tag becomes `:stable`; the gated nightly becomes `-testing`; the candidate becomes `-candidate` (recommended)

- The candidate manifest and all three gates move from `:<flavor>-testing` to
  `:<flavor>-candidate`.
- Promote writes `:<flavor>-testing` and the dated tags
  `:<flavor>[-<arch>]-YYYYMMDD`, but **not** the bare tag.
- A new `promote-stable.yml` moves the bare `:<flavor>`, its arch tags and
  its alias images to a soaked dated tag by digest.
- Pros:
  - Every existing install, every doc and every ISO lands on `:stable` with
    no user action. New installs default to the soaked ring.
  - It matches what the docs already say: `gnome` is described as "(stable)".
- Cons:
  - It renames the candidate: 16 lines in `reusable-build-image.yml` and one
    each in `build-variant.yml` and `asahi-hw-nightly.yml` (comments
    included) change.
  - Existing users get updates later, after the soak. That is the intent.

### B. Keep the bare tag as the nightly; add `:<flavor>-stable`

- Purely additive, with nothing renamed.
- Default users stay on the unsoaked ring, and every doc, `bootc switch`
  example and the ISO pipeline must move to `-stable` before the ring
  protects anyone.
- The gated nightly is still not named `testing`, so the two rings would be
  `:<flavor>` and `:<flavor>-stable`.

### C. Literal global `:testing` / `:stable` tags

These would not work. Tags are per flavor (`albacore:gnome`, `albacore:kde`,
…), so one `:stable` per image path cannot name a desktop.

## Proposed design (option A)

### Promotion rule

`promote-stable.yml` runs per cell (variant × flavor), the same matrix
`build-config.yml` builds. It runs on a schedule and can be run by hand. For
each cell it promotes the newest dated `:testing` image that meets all of
these:

1. **Soaked.** It has been the cell's `:testing` image for at least
   `soak_days`. The default is 3 days, set per variant in `tunaos.toml`.
2. **No newer regression.** No open issue labelled `release-blocker` names the
   cell (by `variant:flavor` in the title or by a `variant/<v>` label).
3. **Post-publish checks green.** The latest `desktop-contract-sweep` result
   for the cell is `pass`, and the cell's `bootc-lifecycle` sweep is not
   failing.
4. **Soak-After honoured.** Every commit between the current `:stable`
   revision and the candidate's `org.opencontainers.image.revision` label is
   checked for a `Soak-After: <N>d` trailer. The candidate waits for the
   longest one. A PR that changes boot, LUKS or the update path can ask for a
   longer soak this way.

Promotion copies by digest (`skopeo copy --all`) from the dated tag to
`:<flavor>`, its arch tags and its alias images, then verifies the digests,
the same way the rollback runbook does by hand today. A cell that fails a rule
keeps its current `:stable`. The run logs which rule held which cell and exits
green, as upstream Hive's own `promote-stable.yml` does.

**Cadence.** The default is daily at 06:00 UTC. The weekly ISO
(`publish-iso-groups.yml`, Sunday 23:00 UTC) builds from `:stable`, so an ISO
never ships an image that has not soaked. School's `iso-weekend` freeze window
(Saturday and Sunday) keeps architect, strategist and outreach from adding
risk right before it.

### Rollback

Rollback repoints `:stable` (the bare tag) to the previous dated tag:
`promote-stable.yml` with `cell` and `dated_tag` inputs plus a required
`reason`. `:testing` keeps moving. The runbook changes from "repoint the
only user-facing tag" to "repoint `:stable`; `:testing` users roll back
locally with `bootc rollback`".

### Where Hive fits (HIVE-6)

- Hive agents add `Soak-After:` to PRs that change `build_scripts/desktop/**`,
  `files/usr/bin/tunaos-luks-*`, the bootloader or the update path. This is
  a kick-template rule on School and needs no Hive code.
- The revert sheriff (tuna-os/hive#170) protects `main`. The rings protect
  users from what `main` ships. A `release-blocker` issue is the only signal
  promotion needs from either a person or Hive.

## Rollout

| Phase | Change | User-visible |
|---|---|---|
| 1 | The candidate moves to `-candidate`. Promote also writes `-testing` and keeps writing the bare tag. | No. `:<flavor>-testing` becomes a gated nightly ring that people can opt into. |
| 2 | `promote-stable.yml` in **dry-run**: it logs what it would promote for each cell, for one week. | No |
| 3 | Promote stops writing the bare tag; `promote-stable.yml` writes it. Update `VERSIONING.md` (drop Weekly/LTS, add the two rings), `docs/IMAGE-TAGS.md`, the rollback runbook and the "stable version" wording in `reusable-build-image.yml`. | Yes. Default users move to the soaked ring. |
| 4 | The `Soak-After:` trailer and the Hive kick rule. | No |

**Measures** (reported on #4072):

- regressions caught on `:testing` before they reached `:stable`: issues
  filed against a digest that never got promoted;
- median days from `:testing` to `:stable` per cell;
- cells held, and by which rule.

## Decisions for the maintainer

1. **Mapping.** Option A (the bare tag is `:stable`, the candidate is renamed)
   or option B (the bare tag stays nightly, plus `-stable`)?
2. **Default soak.** 3 days, set per variant? For example, longer for
   `yellowfin`, the enterprise base.
3. **Cadence.** Daily promotion (proposed), or weekly before the Sunday ISO?
4. **ISOs.** Should the weekly ISOs build from `:stable` (proposed)? The
   nightly R2 ISOs stay on the per-platform build tag.
5. **Name clash.** `VARIANT-LIFECYCLE.md` uses "Stable" as a variant maturity
   stage. Rename that stage (for example to "Mature") so that "stable" means
   only the ring?
