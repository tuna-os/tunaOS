# Fedora outreach readiness

Tracks [#3001](https://github.com/tuna-os/tunaos/issues/3001). This brief
prepares a request for technical review by fedora-desktop. A maintainer must attach the evidence below before they contact anyone.

## Resolve the completeness claim

The original issue points to [#272](https://github.com/tuna-os/tunaos/issues/272),
which GitHub marks closed. [PR #412](https://github.com/tuna-os/tunaos/pull/412)
merged as `f349c787`; [PR #2553](https://github.com/tuna-os/tunaos/pull/2553)
merged as `7d935d82`. Both commits are ancestors of `main`. These are historical
fixes, not proof that a candidate image passes today's checks.

In particular, `build_scripts/99-cleanup.sh` calls `lint_image` in
`build_scripts/lib.sh`. The helper prints the full lint findings to the build
log and GitHub step summary, but defaults to warning only unless
`BOOTC_LINT_FATAL=1`. A successful build therefore cannot prove that
`bootc container lint --fatal-warnings` passed. Do not repeat the issue's old
claim of exactly three failures without a new measurement of the candidate.

[ROADMAP.md](../ROADMAP.md) describes Bonito as Beta. A tracker closure
does not promote a variant to GA. Use the promotion criteria in
[VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md), the applicable gates in
[GREEN-CRITERIA.md](GREEN-CRITERIA.md), and generated
[MATRIX-STATUS.md](MATRIX-STATUS.md) to assess readiness. Follow
[FEDORA-BASE-POLICY.md](../FEDORA-BASE-POLICY.md) for the order of releases.
A release date for Fedora does not establish Bonito support for that release.

## Evidence required before contact

For each desktop and architecture named in the request, the contributor must:

1. Resolve the published tag using [IMAGE-TAGS.md](IMAGE-TAGS.md). Record its
   immutable digest, source commit, architecture, and build run URL.
2. Run `bootc container lint --fatal-warnings` against that exact image using
   the build's container privileges. Attach the full output and exit code.
   If it fails, file or link a focused fix with the failed checks and digest.
   Keep the handoff on hold until the same checks pass.
3. Attach current build, boot, desktop, and install evidence for the same
   cell, following [GREEN-CRITERIA.md](GREEN-CRITERIA.md). A skipped, stale,
   or untested criterion leaves the handoff on hold. Do not substitute a
   different flavor or architecture's results.
4. Compare the results with the lifecycle promotion criteria. Describe Bonito as Beta
   until maintainers record its promotion. Scope any evaluation request to
   the verified cells and disclose remaining limitations.
5. Replace any contributor-count claim with a dated, reproducible query
   and reviewed PR links. A GitHub association alone does not establish
   Fedora affiliation. Count Fedora contributors only with public evidence
   of that affiliation; otherwise omit the count.

Use the generated matrix and linked run evidence directly. Do not maintain a
second hand-written table of green cells here. Recheck the evidence if the
candidate digest changes or the evidence exceeds its freshness limit.

## Positioning and contributor request

Describe TunaOS as an image factory and Bonito as its Fedora-based Beta
variant. Center a technical review on the measured desktop and bootc behavior.
Do not imply Fedora endorsement, Bluefin/Aurora feature parity, a migration
recommendation, or a community of external contributors.

After the evidence passes review, a maintainer can adapt this text:

> We build Bonito, a Fedora-based Beta variant in the TunaOS image factory.
> We would value feedback on a specific verified desktop and architecture.
> The attached digest and run evidence cover lint, boot, desktop, and install
> checks; the handoff also lists the remaining limitations. Is there an
> appropriate place for a request for technical review?

Attach the actual evidence and limitations before you send the request.
Ask for a bounded contribution: reproduce a desktop issue, add a regression test,
and submit a fix through the [contributor guide](../CONTRIBUTING.md). Review open issues
and PRs first so the request does not duplicate work. Do not promise an
unverified flavor or ask users to migrate as the first contribution.

The maintainer selects the recipient, sends the request, and records its public
URL and date in [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md).
Keep follow-up Fedora visibility work in
[#3052](https://github.com/tuna-os/tunaos/issues/3052) and Fedora release-window
coordination in [#3089](https://github.com/tuna-os/tunaos/issues/3089).
A prepared brief, a reply, and a consent-confirmed adopter are separate outcomes;
follow [ADOPTION-METRICS.md](../ADOPTION-METRICS.md) to record them.
