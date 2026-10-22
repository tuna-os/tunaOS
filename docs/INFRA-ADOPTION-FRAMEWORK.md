# Infrastructure adoption reporting — Q4 2026

This reporting contract supports [#3075](https://github.com/tuna-os/tunaos/issues/3075)
and the [Q4 adoption plan](../Q4-ADOPTION-PLAN.md). It extends the evidence
rules in [ADOPTION-METRICS.md](../ADOPTION-METRICS.md) to corral, remora,
spindle, finupdate and mariner. It does not certify production readiness or
replace each project's release policy.

## ADOPTERS.md contract

Each project copies [the template](templates/INFRA-ADOPTERS.md) to its root
`ADOPTERS.md`. Existing adopter lists can add these fields without replacing
their history. One record represents one adopter's deployment of one project;
updates replace that record rather than adding the same deployment again.

| Field | Meaning and allowed values |
|-------|----------------------------|
| adopter | Consenting public organization, project or individual; link its public report |
| version | Deployed release tag and release URL, or exact commit SHA and permalink for unreleased builds; never infer from latest release |
| deployment_type | `production` (ongoing real workload), `evaluation` (trial), or `development` (tests/CI) |
| relationship | `external` or `internal` (maintainer, project infrastructure or dogfooding) |
| count | Positive integer of deployed instances, or `unknown`; name the unit, e.g. hosts, installations or homeservers |
| since_date | Start date as `YYYY-MM-DD`, or `YYYY-MM` when only the month is known; `unknown` if unavailable |
| evidence | Public deployment report, operator confirmation, case study or reproducible CI run URL supporting the claim |
| verified_date | `YYYY-MM-DD` when the report was last checked |
| consent | Public source explicitly volunteering listing, or link to the adopter's approval on the entry PR |

Unknown counts and dates remain unknown; they are not zero. An empty list
means no consented reports, not that nobody uses the software. Stars,
downloads, bundling in an image and dependency relationships do not establish
use. Internal CI is useful evidence but never an external adopter. A release
tag alone does not prove deployment; an unreleased commit can document a real
trial without implying a stable release.

Do not publish private deployment details, contact addresses or operator
identities without consent. An adopter can request correction or removal in
the project issue tracker. Keep aggregate units separate: three homeservers
cannot be added to twenty desktop installations as a user count.

## Operator handoff

Alongside the list, each project links a README section or
`PRODUCTION-READINESS.md` covering:

- The supported release/channel and how to discover the installed version.
- A minimal evaluation setup, prerequisites and a smoke check with expected output.
- Upgrade, rollback/recovery and known limitations, with links to tested procedures.
- The support/incident channel and any evidence still needed before production use.

For corral, cover a VM/CI evaluation and cleanup; for spindle, cover a
homeserver evaluation, federation verification, backup and restore. Link
existing instructions where available. Do not substitute an adoption entry
for an operator runbook or claim that federation alone proves safe operation.
Finupdate and mariner can report commit-based evaluations while release
versioning is tracked in [#3068](https://github.com/tuna-os/tunaos/issues/3068).

## Reporting cadence and handoff

Project maintainers own their source records; the strategist owns collection
and the guide owns publication, matching the existing metrics plan. These are
reporting responsibilities, not new permissions or merge gates.

1. By **2026-10-31**, each of the five projects supplies a link to its merged
   list and operator guidance, or explicitly reports missing evidence. The
   target is at least one verified entry per project; an honest empty report
   is preferable to inventing a deployment to meet that target.
2. By **2026-11-01**, the strategist includes these sources in the monthly
   adoption snapshot for [#1348](https://github.com/tuna-os/tunaos/issues/1348).
3. Thereafter, project maintainers recheck entries by each month's last day;
   the strategist publishes the snapshot by the first day of the next month.
   A missing report is marked `not reported`, and evidence not reconfirmed
   within 31 days is marked `stale`, excluded from current verified totals,
   and linked to a follow-up issue. Neither is silently treated as zero.
4. Starting **Q1 2027**, a new infrastructure project's initial ROADMAP links
   its adopter list (which may be empty), operator guidance and reporting owner.

The snapshot records its collection date, source commit permalinks, verified
external production/evaluation entry totals, internal entries separately,
and missing/stale evidence. Generate totals from the collected source records;
do not maintain a second hand-copied table of project status here. Review each
record for consent, duplicate deployments and supporting version evidence
before counting it. The OS production-adopter criterion in
[Q4-MATURE-DEFINITION.md](../Q4-MATURE-DEFINITION.md) still requires an OS
production report; infrastructure usage cannot silently satisfy it.

## Completion boundary

This document and template provide the shared contract. Rollout requires
separate changes in the five project repositories and real operator reports;
this document does not assert those changes have landed. Track source PRs and
missing reports in #3075 until the October collection is complete. The snapshot
remains work under #1348 and metrics automation under #1174.
