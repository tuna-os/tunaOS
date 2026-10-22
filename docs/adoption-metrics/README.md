# Adoption snapshots

[The 2026-10-22 baseline](snapshots/2026-10-22.md) is a preliminary snapshot.
The first monthly checkpoint remains **2026-11-01**. Each report has a JSON
receipt with source URLs, UTC collection times, ISO asset IDs, and the commit
used to read `ADOPTERS.md`. The Markdown report comes from the same data.

## Collect and publish

From the repository root, with a token that can read public Discussions:

```sh
GH_TOKEN="$GH_TOKEN" python3 scripts/adoption-snapshot.py --output-dir docs/adoption-metrics/snapshots
```

The [monthly workflow](../../.github/workflows/adoption-metrics.yml) runs on
the first day of each month at 09:00 UTC. It also supports manual runs. It
uses read permissions and writes a run summary and a 90-day artifact. A failed
request to GitHub fails the job; it does not publish a zero or a partial report.
The workflow does not commit files or open PRs.

The strategist reviews each report. Download the artifact before
it expires, commit both dated files through a PR, and link the report from
`ADOPTION-METRICS.md` and the ROADMAP Community section. The guide role can
then publish the reviewed report on the site. A run summary is available on
the Actions run before the publication PR merges.

## Read the evidence

- GitHub asset counters are lifetime counts for retained assets. The count for
  ISOs excludes checksums, release cards and SBOMs. Deleted assets disappear; a
  difference between snapshots does not count all downloads for the month.
- The count for Discussions covers threads and top-level comments in this repository.
  They include project announcements and support. They exclude replies and
  cannot measure conversion from the adoption call without a linked record.
- The adopter counter reads only Production Users and Development & Evaluation
  in `ADOPTERS.md`. It excludes the maintainer and Hive entries by their links,
  plus the entire ecosystem section. Review the counter if internal entries
  or table structure change. Entries rely on the existing consent review;
  the script does not verify that an organization runs TunaOS.
- The report marks missing inputs unavailable. Do not substitute zero, infer installs,
  or rank variants from stars or metadata downloads.

## Inputs still needed for the November checkpoint

The ci-maintainer supplies an export of R2 downloads by variant and desktop.
The guide supplies an export of pageviews and referrals for the tracker and docs.
This change needs no provider credentials or changes to provider settings.
The strategist supplies a reviewed census of contributions from external humans.

The warm-channel call has [publication copy and consent rules](../ADOPTION-CALL.md).
Its URL in Show-and-tell, responses, confirmed named entries,
anonymous reports and linked adopter PRs remain publication/follow-up work.
Record each separately, with zero responses distinguished from an unpublished
call. A response rate needs a known audience denominator.
Do not add an organization without its confirmation.

The [existing countme service](../../services/countme/README.md) is a separate
signal. Its closed-week reports are not unique people or monthly users. This
collector adds no OS telemetry or cookies and stores no respondent
identity, private messages or access logs.
