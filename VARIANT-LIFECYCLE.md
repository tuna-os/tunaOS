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

Also covers **output / deployment architectures** — bootc/ostree images vs.
mkosi DDI (`Format=disk`, systemd-sysupdate + dm-verity + UKI, the particleOS
model), systemd-sysext / portable services, and any other way a variant can be
shipped. The mkosi build-backend investigation (#999, #1227) is explicitly in
scope: adopting a new output architecture is a portfolio commitment and passes
the Proposal admission gate below, even though it reuses existing roots.

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
   distributable (Zorin, #944, is a live counter-example: its public apt repo
   packages index is empty across all components, dists, and architectures, and
   essential components like `zorin-appearance` and session definitions are not
   published).
4. **A tracking issue** filed with the `roadmap` label before the first commit.

New **output architectures** (e.g. a mkosi DDI sidecar per variant, #999/#1227)
count as proposals too: they multiply the boot/publish/signing surface (#1187,
#1193) and must clear the same gate — ROADMAP row, owner, acceptance criteria,
capacity — before the first build job lands.

#### Admission record

The following additions were already present in the build matrix when this
policy was written. They are recorded here so the gate is actionable rather
than silently grandfathering them. Until each row has a capacity sign-off, its
status is **held**: existing build definitions may be tested, but the flavor
must not be promoted or gain additional ISO coverage.

| Addition (opened 2026-08-08) | Tracker | Owner | Incremental cells | Acceptance evidence | Status |
|---|---|---|---:|---|---|
| `grouper:gnome-zfs` | #1185 | ci-maintainer | 1 image; 0 ISO | Install-to-ZFS boot E2E (#625), LUKS E2E, desktop contract | Held pending capacity sign-off |
| `marlin:gnome-nvidia` | #1191 | ci-maintainer | 1 image + 1 ISO (amd64) | NVIDIA driver load, boot gate, LUKS E2E, desktop contract | Held pending capacity sign-off |
| `flounder:gnome-nvidia` | #1191 | ci-maintainer | 1 image + 1 ISO (amd64) | NVIDIA driver load, boot gate, LUKS E2E, desktop contract | Held pending capacity sign-off |
| `flounder-sid:gnome-nvidia` | #1191 | ci-maintainer | 1 image; 0 ISO (amd64) | NVIDIA driver load, boot gate, LUKS E2E, desktop contract | Held pending capacity sign-off |

The cell count is the minimum incremental matrix impact, not a claim that the
work is free: an ISO cell also consumes grouped-ISO or on-demand publishing
and boot-gate capacity. The owner must attach a capacity note to the tracker
before changing a row to **admitted**. That note must record, for the current
matrix revision:

1. image, ISO, boot-gate, LUKS-E2E, and desktop-contract cell counts;
2. expected CI minutes and peak concurrent jobs;
3. the available CI/runner envelope and the milestone work it could displace;
4. the first review date and the rollback/descope trigger.

For these four retroactive records, the interim decision is **no promotion or
new ISO surface through 2026-09-30**. A later capacity sign-off may admit the
existing cells without reopening the general Q3 flavor freeze.

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

### 5. Release currency (all published flavors)

Every flavor published on tunaos.org/download that is also advertised on the
GitHub Releases channel must carry a **current release asset**:

- **GitHub Releases parity** — the scheduled release pipeline
  (`generate-changelog-release.yml`) must cover every flavor marked `Stable` or
  `Beta` in ROADMAP, not just the gnome default. A flavor whose release has
  gone **>30 days stale** (no new `<flavor>-<YYYYMMDD>` tag) is either
  (a) published by explicit `workflow_dispatch`, or (b) explicitly designated
  **tunaos.org-only** in ROADMAP with a documented rationale.
- **No silent skips** — the release workflow warns-and-exits-0 on skipped
  flavors (see #1254); a skip must leave an actionable trail (issue or
  notification) so deprioritization is a decision, not an accident.
- **Deliberate deprioritization** — if a flavor is intentionally released
  less frequently (e.g., `*-nvidia` monthly, base variants on upstream
  cadence), record the expected currency in its ROADMAP row.

Until the pipeline is extended, the gap observed on 2026-08-10 (kde/xfce/
cosmic/niri releases 36 days stale vs gnome-20260809 current) is a known
violation tracked in #1254.

## Matrix economics

The publish/test matrix (9+ bases × 5 desktops × nvidia/ZFS dimensions, 179
ISOs and growing) is a first-class cost. Variant admission decisions must cite
capacity (CI minutes, boot-gate slots, LUKS-E2E cells, desktop-contract
coverage) — a hard requirement of the admission gate until #1174 provides real
usage data.

## Enforcement

Policy is only as good as its checks. The admission gate is a **PR-time
requirement**, enforced by reviewers and the strategist, not an after-the-fact
audit:

- **Portfolio-change PRs** (adds/removes a base variant, desktop flavor,
  hardware/kernel profile such as T2/Asahi/HWE, or output architecture) must
  carry the `roadmap` label and link a tracking issue that names the ROADMAP
  row, owner, and acceptance criteria **before merge**.
- **Scope is explicit**: hardware/kernel profiles (Apple Silicon Asahi #781,
  Apple T2 `*-t2`, HWE) are in-scope flavors unless the ROADMAP row for the
  base variant says otherwise. If a hardware profile is intentional but
  capacity-constrained, it still gets a ROADMAP row + tracking issue; the
  interim "no new flavors through 2026-09-30" gate applies.
- **No paper gates**: a flavor that lands without a ROADMAP row or `roadmap`
  label is a governance breach to be fixed retroactively (tracking issue +
  row) within one week, not silently accepted. First observed breach:
  `bonito:gnome-t2` (PR #1256), tracked in #1270.

## Maintenance

This policy is maintained by the strategist agent and reviewed quarterly at
milestone planning (next: Q4 2026 kickoff). Criteria changes are filed as
issues on the roadmap tracker (#1159).

---
*Drafted by strategist agent (ACMM L6 — full mode). Tracks #1175 and #1196.*
