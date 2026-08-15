# Adoption call: who is running TunaOS?

**Status**: ready for maintainer publication
**Tracking**: [tunaOS#1367](https://github.com/tuna-os/tunaos/issues/1367)

This is a warm-channel call for organizations and teams already running or
evaluating TunaOS. It supports the Q4 “Mature” evidence review without
inventing adopters or treating a download as proof of production use.

## Where and when to publish

Publish as a GitHub Discussion in the **Show-and-tell** category, then share
the Discussion link in the TunaOS Matrix room and the next community or
release post. Use existing community relationships and public channels only;
do not cold-DM people or claim that a named organization uses TunaOS without
their permission.

The call should run for at least two weeks before the Q4 checkpoint. Keep it
open afterward so new adopters have a stable path to self-identify. The
Discussion is the source of truth for responses; comments and Matrix replies
should link back to it.

## Discussion title and body

Use this copy, replacing the date and links before publishing:

```markdown
# Who's running TunaOS? Add yourself to ADOPTERS.md

Are you or your organization running TunaOS in production, development, or
evaluation? We are collecting voluntary, public adopter reports before the Q4
“Mature” checkpoint.

If you would like to be listed, reply with this template:

Organization or public name:
Use case (production, development, or evaluation):
Variant(s) and desktop(s):
Since (YYYY-MM):
Public link (optional):
What is working well or what should we improve? (optional):

Please share only information you are authorized to publish. A maintainer will
confirm the wording with you before opening a small follow-up PR to
[ADOPTERS.md](https://github.com/tuna-os/tunaos/blob/main/ADOPTERS.md). You can
also open that PR yourself. We will not add a person or organization from a
private message, telemetry, registry pull, or an unverified claim.

If you prefer not to be named, a maintainer can record an anonymous count in
the monthly adoption snapshot; anonymous use will not be presented as a named
Production User.
```

## Matrix and release-note CTA

Use a short pointer in Matrix `#tunaos:reilly.asia` or a release/community
post:

> Are you already running or evaluating TunaOS? Tell us what you use and
> whether we may list it publicly in [the “Who’s running TunaOS?” Discussion]
> ([DISCUSSION_URL]). We will confirm the wording with you before updating
> [ADOPTERS.md](https://github.com/tuna-os/tunaos/blob/main/ADOPTERS.md).

The Q3 checkpoint recap or release notes should use the same CTA and link to
the Discussion. Do not duplicate a response template in several posts, since
that fragments the record.

## Consent and verification rules

1. A maintainer acknowledges each response and asks the respondent to confirm
   the exact public name, category, variants, and start month.
2. A named Production User requires explicit confirmation from an authorized
   representative. A GitHub username alone is not evidence of organizational
   production use.
3. Development and evaluation reports are welcome and should stay in those
   sections unless the respondent later confirms production use.
4. Never infer an adopter from downloads, stars, container pulls, CI jobs, or
   an organization appearing in the ecosystem table.
5. If a respondent withdraws consent, remove or amend the entry in a follow-up
   PR and note the change in the next snapshot without retaining private
   details.

## Follow-up workflow

- [ ] Create the Discussion in **Show-and-tell** and record its URL in issue
      #1367.
- [ ] Share the URL in Matrix and the next community/release post.
- [ ] Acknowledge responses and request confirmation of the proposed wording.
- [ ] Open one small PR per confirmed adopter, linking the Discussion comment
      and issue #1367; do not bundle unconfirmed entries.
- [ ] Record response count, confirmed named entries, anonymous responses, and
      conversion to ADOPTERS.md in the next monthly adoption snapshot.
- [ ] Refresh the Q4 “Mature” claim only after comparing the evidence against
      the documented target; otherwise state the gap and re-baseline it.

## Tracking record

| Date | Channel / Discussion URL | Responses | Confirmed named entries | Anonymous reports | ADOPTERS.md PRs | Notes |
|---|---|---:|---:|---:|---:|---|
| [YYYY-MM-DD] | [URL] | [N] | [N] | [N] | [#PRs] | [follow-up] |

The count measures participation in the call, not adoption itself. Keep named
entries and anonymous responses separate in every report.
