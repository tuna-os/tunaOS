# Adoption readiness

This is the Q4 2026 portfolio assessment for user-facing TunaOS variants. It
answers a stricter question than “did the image build?” and keeps the answer
traceable to the same evidence as the daily [matrix status](MATRIX-STATUS.md).

## Definition

A specific `variant:desktop` cell is **adoption-ready** only when all of these
conditions hold:

1. **Published artifact** — its image promotes to a public tag. The publication
   matrix offers its ISO.
2. **Usable system** — evidence proves that the desktop is present and the image
   boots. The package audit reports no silent omission.
3. **Installation** — the installer appears on screen. Encrypted and plain
   installs complete. The record includes a VM and a physical system. A LUKS test
   of only the backend does not prove that the GUI works.
4. **Operations and recovery** — update, rebase, and rollback pass. The user
   guide gives the recovery procedure.
5. **Honest support** — the public record names the track, owner, limits, and
   workarounds. A stale, skipped, or absent test does not pass.

The automated candidate uses eight axes: `builds`, `desktop`, `boots`, `iso`,
`install`, `lifecycle`, `parity`, and `no_silent_omissions`. It sets a stricter
bar than the standard green score. That score controls publication in CI; this
score supports an adoption claim.

Automation cannot prove a physical install, the plain-disk path, ownership, or
complete limits. Thus, a green candidate still needs a promotion ledger with
those four records. The ROADMAP can then call it adoption-ready. No cell has
such a ledger, so the portfolio has **zero adoption-ready cells by declaration**.
This status identifies an evidence gap. It does not say that all images fail.

## Shared user and support material

These links give one source for requirements across the five frontend repos:

- [User Guide](USER-GUIDE.md) — install, encryption, update, rollback, and
  problem diagnosis.
- [Installer frontend contract](INSTALLER-FRONTENDS.md) — UI and backend parity,
  including known per-desktop gaps.
- [Variant lifecycle policy](../VARIANT-LIFECYCLE.md) — promises for each
  availability track and the Beta/Stable promotion rules.
- [Matrix status](MATRIX-STATUS.md#3-known-systemic-gaps) — current systemic
  limitations and the evidence behind each result.
- [Hardware support](HARDWARE.md) — architecture and hardware boundaries.

The generator does not give a Beta date to a red or untested matrix. The
[ROADMAP](../ROADMAP.md) records decisions about dates. Each promotion date must
name an owner and link its evidence ledger. A build result cannot set the date.

## Scope boundary

This assessment covers the images in `.github/build-config.yml`. Bluefin,
Bluefin LTS, Bazzite, and Dakota are upstream or adjacent projects. They are not
TunaOS variant rows, so this page gives them no TunaOS status. Apple Silicon
uses the `-asahi` hardware flavors. See their separate
[hardware tiers](ASAHI-HARDWARE-TIERS.md); Dakota is not a TunaOS variant.

Legend:

- ✅ — all eight gates have current evidence of a pass.
- ❌ — at least one gate has a current failure.
- ⬜ — at least one gate has stale or absent evidence.
- — — the configuration declares no ISO cell.

<!-- BEGIN GENERATED — scripts/gen-adoption-readiness.py -->

*Generated from `.github/build-config.yml`, `.github/green-criteria.yml`, and `matrix-provenance.json`; do not edit this block by hand.*

## Current automated candidates

Among 33 ISO cells for desktops, **0** meet every automated adoption gate. 24 have a current failure. 9 lack current evidence for at least one gate.

A ✅ is only an **automated candidate**, not an adoption-ready declaration. Before promotion, add evidence for physical hardware, a plain install, the support owner, and the limits of that cell.

| Variant | gnome | kde | cosmic | niri | xfce |
|---|:--:|:--:|:--:|:--:|:--:|
| **albacore** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **bonito** | ❌ | ⬜ | ⬜ | ❌ | ⬜ |
| **bonito-rawhide** | ❌ | ❌ | ❌ | ❌ | ❌ |
| **flounder** | — | ❌ | — | — | — |
| **grouper** | ❌ | ⬜ | — | — | ❌ |
| **hummingbird** | ❌ | — | ❌ | — | — |
| **marlin** | ❌ | ❌ | — | — | — |
| **skipjack** | ❌ | ❌ | ⬜ | ❌ | ⬜ |
| **yellowfin** | ❌ | ⬜ | ⬜ | ❌ | ⬜ |

### Desktop-family roll-up

| Desktop | Ready candidates | Current failures | Unverified | ISO cells |
|---|---:|---:|---:|---:|
| Gnome | 0 | 8 | 0 | 8 |
| Kde | 0 | 5 | 3 | 8 |
| Cosmic | 0 | 3 | 3 | 6 |
| Niri | 0 | 5 | 0 | 5 |
| XFCE | 0 | 3 | 3 | 6 |

### Availability track

This is the support promise declared by `.github/build-config.yml`, not a quality score. Failure remains fail-closed on every track.

| Track | Variants with published desktop ISOs | Promise |
|---|---|---|
| release/stream | `albacore`, `bonito`, `flounder`, `grouper`, `skipjack`, `yellowfin` | Continuous promotion target; red scheduled builds are regressions. |
| rolling | `bonito-rawhide`, `marlin` | Best effort; upstream movement can interrupt promotion. |
| experimental | `hummingbird` | Evaluation only; no uptime or continued-publication promise. |

The per-axis verdict, evidence run, and measurement date for every cell remain in [MATRIX-STATUS.md](MATRIX-STATUS.md) and [matrix-provenance.json](matrix-provenance.json).

<!-- END GENERATED -->
