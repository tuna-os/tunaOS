# ADR 0006: Date-based versioning with stability tiers, not SemVer

- Status: accepted (policy merged)
- Date: 2026-06-08
- Last updated: 2026-08-13
- Issue: [#274](https://github.com/tuna-os/tunaOS/issues/274)
- Policy: [VERSIONING.md](../../VERSIONING.md) (merged via #338)

## Context

tunaOS images are rebuilt daily from upstream sources — there are no feature
releases, and each build simply incorporates whatever upstream changed since
the last one. Tags were date-based (`<variant>-<YYYYMMDD>`, e.g.
`gnome-20260528`) with no semantic versioning, which #274 flagged as
insufficient for an enterprise-facing project: a bare date conveys nothing
about stability, breaking changes, or what an organization can safely pin to.
Competing projects (Fedora Silverblue, Bluefin) tie versioned release
cadences to upstream Fedora releases (40, 41, 42...); tunaOS has no
equivalent upstream cadence to hang a major/minor number on, since it
tracks multiple base distros (AlmaLinux, CentOS Stream, Fedora, Ubuntu)
rebuilding continuously rather than on a fixed release schedule.

## Decision

**Keep date-based tags as the versioning scheme, and add three named
stability tiers instead of adopting SemVer.**

- **Daily** — `<variant>-<YYYYMMDD>`, every successful daily build. Highest
  freshness, highest change rate.
- **Weekly** — `<variant>-weekly-<YYYYWW>`, a snapshot of the week's most
  stable daily build. The recommended tag for regular users.
- **LTS** — `<variant>-lts-<quarter>`, a quarterly stable snapshot for
  enterprise deployments that need a longer, more predictable pin.

There is no major/minor version number — date tags are chronological, not
semantic — because there is no natural SemVer boundary to attach one to
across multiple independently-versioned upstream bases. Breaking changes
(kernel bumps, desktop-environment major upgrades, filesystem layout
changes) are communicated via release notes rather than encoded in the tag
itself.

### Alternative considered and rejected

#274 proposed a **hybrid SemVer + date scheme**: `major.minor` for feature
releases (e.g. `v2.1`), a date suffix for pinning (`v2.1-20260528`), and
container tags carrying both. This was not adopted. A SemVer major/minor
would need a defined "release" boundary and something whose compatibility
the number tracks — but tunaOS ships a continuous rebuild across several
base distros with independent upstream cadences, not a single versioned
artifact tunaOS itself controls the compatibility contract for. Bolting a
SemVer number onto that would either be arbitrary (incremented by feel, not
by a real compatibility rule) or would require inventing a compatibility
contract the project doesn't otherwise need. The three-tier scheme answers
#274's actual underlying asks — "what can I pin to for stability" (Weekly),
"what can an enterprise deployment rely on longer-term" (LTS) — without
that overhead.

## Consequences

**Positive** — freshness and traceability are direct (`gnome-20260606` tells
you exactly when it was built, with no version-negotiation step); the tier
system gives users and enterprises a stability dial (Daily/Weekly/LTS)
without requiring the project to define or maintain SemVer compatibility
guarantees it can't actually make across independently-versioned upstream
bases.

**Negative** — no version number ordering shortcut ("is 2.1 newer than
1.9?") the way SemVer gives one; consumers must compare dates or rely on
the tier label instead. Migration guidance for users coming from
SemVer-versioned projects (Fedora Silverblue/Kinoite) has to explain the
tier scheme rather than mapping onto a familiar major/minor number, which
VERSIONING.md's Migration section addresses with an explicit `rebase`
example rather than a version-number comparison.

---
*Backfilled per RFC-PROCESS.md / #1094 (ADR coverage gap) — source: VERSIONING.md, #274 (closed via PR #338, merged 2026-06-08).*
