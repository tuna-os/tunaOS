# Adoption metrics snapshots

Latest snapshot: **2026-10-03**. Activity covers `2026-09-01` through the day before `2026-10-01`. Counter values are a point-in-time baseline.

| Signal | Value |
|---|---:|
| GitHub stars | 57 |
| GitHub forks | 5 |
| GitHub watchers | 1 |
| GitHub Release ISO assets / cumulative downloads | 3 / 0 |
| GitHub Release SBOM assets / cumulative downloads | 176 / 185 |
| Discussions opened in window | 0 |
| External non-bot PRs merged across tuna-os in window | 11 |
| External non-bot contributors across tuna-os in window | @HuntedRaven7, @KiKaraage, @castrojo, @eseiker |
| External production/evaluation adopters | 0 |

## Interpretation

GitHub Release counters are cumulative. Subtract the same counter in consecutive JSON snapshots to get activity between collection times. The release inventory now contains **3 ISO assets**; SBOM and release-card downloads do not count as ISO downloads or adoption. TunaOS stores its ISOs in R2. Variant and desktop rankings remain unavailable until the project connects an export from the access logs.

TunaOS collects no OS-level identifier or event. Stars, downloads, and site visits are discovery proxies, not proof of installation or continued use. GitHub marks accounts as `User` or `Bot`; a non-bot account is not proof that a human wrote its pull requests.

## Data gaps

- **R2 ISO downloads:** We have not connected an export from R2; the counters for release assets cannot replace it.
- **Docs visits:** We have not connected the Web Analytics export from Cloudflare.
- **Installs:** No install telemetry by design; the consent decision remains open.

## Provenance

[`scripts/generate-adoption-snapshot.py`](../../scripts/generate-adoption-snapshot.py) generates the dated data in [`snapshots/`](snapshots/). The monthly workflow runs on the first day of each month and proposes the changed snapshot through a pull request.
