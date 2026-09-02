# ADR 0005: Flavor equality — no primary desktop tier

- Status: accepted (implemented)
- Date: 2026-08-11
- Last updated: 2026-08-12
- Directive: [#1315](https://github.com/tuna-os/tunaOS/issues/1315)
- Tracker: [#1316](https://github.com/tuna-os/tunaOS/issues/1316)
- Implementation: [#1322](https://github.com/tuna-os/tunaOS/pull/1322) (catalog parity gate), [#1336](https://github.com/tuna-os/tunaOS/pull/1336) (README/`.github/build-config.yml` de-tiering)

## Context

TunaOS ships 37 published editions across 9+ desktop environments (GNOME,
KDE, XFCE, COSMIC, Niri, Pantheon, …) built on multiple bases (AlmaLinux,
Fedora, CentOS Stream, Debian, Ubuntu, Arch, Gentoo). Despite that breadth,
project framing — ROADMAP claims, README tables, the release pipeline, and
issue templates — treated **GNOME as the primary/tier-1 desktop**: it had a
daily scheduled release pipeline, first-class documentation, and every other
desktop was described relative to it.

This tiering was contradicted by reality in three ways:

1. **Variant admission gate** (VARIANT-LIFECYCLE.md, #1196/#1270) treats all
   flavors equally — any variant admitted to the catalog must carry a ROADMAP
   row, an owner, and acceptance criteria. There is no "tier-1" slot.
2. **Catalog drift**: new variants (hummingbird/Fedora, gurnard/Ubuntu-Pantheon)
   began building and shipping before the admission gate existed (#1341), and
   the ROADMAP's "all desktops downloadable" claim could not be verified
   edition-by-edition (24 of 37 published editions were too small to contain
   their desktop; #1294).
3. **Release cadence asymmetry**: only the GNOME flavor had a scheduled
   pipeline; kde/xfce/cosmic/niri releases went stale 30+ days (#1254).

## Decision

**All supported flavors are equal tiers.** GNOME-first framing is retired:

1. Documentation and README variant tables stop ordering or labeling desktops
   as primary/secondary (#1336).
2. A **catalog parity gate** (#1322) enforces that every variant row in the
   ROADMAP has a matching build-config entry and published artifact, closing
   the "claimed but not downloadable" failure mode.
3. Flavor-equal release **cadence parity** is a tracked follow-up goal
   (#1254, #1316) — GNOME's daily pipeline is not a tier marker, it is an
   unfinished asymmetry to close.

Explicitly rejected alternatives:

- **Declaring GNOME the flagship** (keeping tier-1 framing): entrenches the
  adoption friction for the majority of the variant portfolio and contradicts
  the admission gate already in force.
- **Descoping non-GNOME flavors**: abandons working builds and the KDE/XFCE/
  COSMIC communities that already consume them; the ROADMAP's desktop
  portfolio is a differentiator, not debt.

## Consequences

**Positive** — removes the largest single source of confusion for
non-GNOME users; aligns documentation, gate, and pipeline policy on one rule;
makes the catalog self-verifying via the parity gate.

**Negative** — closes the *framing* asymmetry but not the *pipeline*
asymmetry: non-GNOME release cadence (#1254) remains open work; the parity
gate adds a CI obligation that every future variant must satisfy at
admission, not after the fact.

---
*Recorded by strategist agent per RFC lifecycle policy (RFC-PROCESS.md, #1093/#1094).*
