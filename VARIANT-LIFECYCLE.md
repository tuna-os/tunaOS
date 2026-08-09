# tunaOS Variant Lifecycle Policy

**Status**: DRAFT — proposed 2026-08-09 by the strategist agent for review
**Owner**: tuna-os (hanthor) / strategist
**Tracks**: #1175 (promotion/exit), #1196 (admission/entry)

## Purpose

Define how base variants and flavors (desktop, GPU, filesystem) enter, mature,
and leave the tunaOS portfolio. Without entry and exit criteria the portfolio
grows without a capacity plan and no variant ever reaches GA — the treadmill
risk flagged in #1175, now observable on the **entry** side (#1185 ZFS root,
#1191 `*-nvidia`, opened the same day #1196 was filed).

## Scope

Applies to every row and dimension in the ROADMAP variant table: base variants
(Yellowfin, Albacore, Skipjack, Bonito, Sailfin, Guppy, Grouper, Marlin,
Flounder, Redfin) and flavors (desktop, `*-nvidia`, ZFS root, etc.).

## Lifecycle stages

| Stage | Meaning | Entry criteria | Exit criteria |
|-------|---------|----------------|---------------|
| **Proposal** | Planned, not yet built | ROADMAP row + owner + acceptance criteria; capacity confirmed (#1174) | Approved → Beta |
| **Beta** | Published for testing | Build + boot-gate green; on tunaos.org/download | Promotion criteria met → Stable |
| **Stable** | GA | — | Deprecation criteria met → Deprecated |
| **Deprecated** | No longer promoted | — | Removed from download after grace period |

## Stage rules

### 1. Proposal — admission gate (#1196)

A new base variant or flavor requires, **before any build work starts**:

1. **A ROADMAP row** with a named owner and acceptance criteria (one line minimum).
2. **Capacity confirmation** — the new build / boot-gate / LUKS-E2E /
   desktop-contract cells must fit existing CI capacity without displacing
   current milestone close-out. Interim gate: **no new flavors through
   2026-09-30** while the 5 open Q3 milestone items are in flight.
3. **Upstream base availability** — the distro/version must exist and be
   distributable (Zorin, #944, is a live counter-example).
4. **A tracking issue** filed with the `roadmap` label before the first commit.

### 2. Beta

- Image builds and boot-gate green on the publishing track.
- Published to tunaos.org/download (download pipeline verified working, #561).
- Desktop contract: at minimum a session starts (#916); `*-nvidia` and ZFS
  flavors additionally pass their flavor-specific smoke checks.

### 3. Stable — promotion criteria (#1175)

Promotion Beta → Stable requires **all** of:

- **Boot-gate green for 4 consecutive weeks** of daily runs with no regressions.
- **LUKS E2E green** for the variant.
- **Desktop-contract pass** — beyond session start: window painted (#1217),
  browser/CI ISO parity gate (#1204) where applicable.
- **≥1 user-proven install**, or a documented telemetry proxy until #1174
  (adoption metrics) lands.

### 4. Deprecated

A variant is deprecated when **any** of:

- Its base is superseded (e.g., Fedora 44 → Fedora 45, #1171).
- Its base reaches upstream EOL.
- No green run for 60 consecutive days (unmaintained).

Deprecation is announced in ROADMAP; ISOs leave the download matrix after a
2-release grace period; the ROADMAP row is marked `Deprecated`.

## Matrix economics

The publish/test matrix (9+ bases × 5 desktops × nvidia/ZFS dimensions, 179
ISOs and growing) is a first-class cost. Variant admission decisions must cite
capacity (CI minutes, boot-gate slots, LUKS-E2E cells, desktop-contract
coverage) — a hard requirement of the admission gate until #1174 provides real
usage data.

## Maintenance

This policy is maintained by the strategist agent and reviewed quarterly at
milestone planning (next: Q4 2026 kickoff). Criteria changes are filed as
issues on the roadmap tracker (#1159).

---
*Drafted by strategist agent (ACMM L6 — full mode). Tracks #1175 and #1196.*
