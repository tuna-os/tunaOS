# ADR 0006: Date-based versioning with stability tiers, not SemVer

- Status: accepted (policy merged)
- Date: 2026-06-08
- Last updated: 2026-08-13
- Issue: [#274](https://github.com/tuna-os/tunaOS/issues/274)
- Policy: [VERSIONING.md](../../VERSIONING.md) (merged via #338)

## Context

tunaOS images are rebuilt daily from upstream sources, and there are no
feature releases. Each build takes in the changes from upstream since the last
build. Tags were date-based (`<variant>-<YYYYMMDD>`, e.g. `gnome-20260528`),
with no semantic version numbers. #274 flagged this as insufficient for an
enterprise-facing project. A bare date tells the reader nothing about
stability, about changes that break compatibility, or about what an
organization can safely pin to.

Other projects (Fedora Silverblue, Bluefin) tie the cadence of their releases
to upstream Fedora releases (40, 41, 42...). tunaOS has no equivalent upstream
cadence to hang a major/minor number on. It tracks several base distros
(AlmaLinux, CentOS Stream, Fedora, Ubuntu) that rebuild continuously instead
of on a fixed release schedule.

## Decision

**Keep date-based tags as the version scheme, and add three named tiers of
stability. Do not adopt SemVer.**

- **Daily** — `<variant>-<YYYYMMDD>`, every successful daily build. Highest
  freshness, highest change rate.
- **Weekly** — `<variant>-weekly-<YYYYWW>`, a snapshot of the week's most
  stable daily build. The recommended tag for regular users.
- **LTS** — `<variant>-lts-<quarter>`, a quarterly stable snapshot for
  enterprise deployments that need a longer, more predictable pin.

There is no major/minor version number. There is no natural boundary for
SemVer across the upstream bases, and each base carries its own version. Date
tags are chronological, not semantic. The release notes describe the changes
that break compatibility (kernel bumps, desktop-environment major upgrades,
filesystem layout changes); the tag itself does not encode them.

### Alternative considered and rejected

#274 proposed a **hybrid SemVer + date scheme**: `major.minor` for feature
releases (e.g. `v2.1`), a date suffix to pin a build (`v2.1-20260528`), and
container tags that hold both. tunaOS did not adopt it.

A SemVer major/minor would need a defined "release" boundary, and something
whose compatibility the number tracks. But tunaOS ships a continuous rebuild
across several base distros with independent upstream cadences. It is not a
single artifact with a version that tunaOS itself controls the compatibility
contract for.

A SemVer number on top of that would be arbitrary (incremented by feel, not by
a real compatibility rule). The other option is to invent a compatibility
contract that the project does not otherwise need. The three-tier scheme
answers the real asks behind #274, without that overhead. Those asks are "what
can I pin to for stability" (Weekly) and "what can an enterprise deployment
rely on longer-term" (LTS).

## Consequences

**Positive** — freshness and traceability are direct: `gnome-20260606` tells
you exactly when the build ran, with no version-negotiation step. The tier
system gives users and enterprises a dial for stability (Daily/Weekly/LTS).
The project does not have to define or keep SemVer guarantees of compatibility
that it cannot make across upstream bases with independent versions.

**Negative** — date tags give no shortcut to sort by version number ("is 2.1
newer than 1.9?") the way SemVer does. Consumers must compare dates or rely on
the tier label instead. Migration guidance for users who move from
SemVer-versioned projects (Fedora Silverblue/Kinoite) has to explain the tier
scheme. It cannot map the tiers onto a familiar major/minor number.
VERSIONING.md's Migration section does this with an explicit `rebase` example
instead of a comparison of version numbers.

---
*Backfilled per RFC-PROCESS.md / #1094 (ADR coverage gap) — source: VERSIONING.md, #274 (closed via PR #338, merged 2026-06-08).*
