# Release Automation — Q4 2026

**Tracker**: [tunaOS#1186](https://github.com/tuna-os/tunaos/issues/1186)<br>
**Milestone**: Q4 2026 — Mature<br>
**Owner**: ci-maintainer

This is the definition of done for the Q4 release-automation goal. It turns
the date-based tags in [`VERSIONING.md`](../VERSIONING.md) into a release process
whose omissions are visible to CI and whose published output is verifiable.

## Acceptance criteria

- **Cadence**: the scheduled workflow tries the daily date-based
  release for each admitted stream. A no-build day may stay green.
  The workflow must fail after the freshness window of eight days
  (`MAX_RELEASE_AGE_DAYS`).
- **Asset completeness**: every non-dry-run release must contain at least one
  uploaded asset and an SPDX SBOM asset. The workflow verifies the GitHub
  Release through the API. An action that succeeds can not hide an empty release.
- **Fail-on-drop**: when a build ran but no usable SBOM can be found, the
  release job fails (`reason=no-sbom`). This distinguishes a dropped release
  from a legitimate no-build day and keeps the signal required by #1147.
- **Traceability**: the release tag follows
  `<stream>-<YYYYMMDD>`, and the release summary records the stream, tag,
  source build run, and SBOM package count.

The implementation lives in
`.github/workflows/generate-changelog-release.yml`. Stream coverage and
release cadence parity remain tracked separately where a stream is not yet
admitted to the scheduled matrix.
