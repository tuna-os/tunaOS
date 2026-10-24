# Fedora 45 release-window outreach

Tracks [#3089](https://github.com/tuna-os/tunaos/issues/3089). This is a
maintainer handoff for the release window, not a record of sent outreach.
Publication needs a named sender and review of the candidate evidence.

## Positioning and sources

Lead with TunaOS as an image factory for bootable OCI desktops. Invite Fedora
users to review desktop integration and share voluntary evaluation reports.
The Fedora 45 release window is the occasion for the call; it does not establish
Fedora 45 support in a TunaOS image.

The source configuration at `82842b13` makes these distinctions:

| Project | Evidence | Showcase angle |
|---|---|---|
| Bonito | [tunaos.toml](../tunaos.toml), `variants.bonito`: `quay.io/fedora/fedora-bootc:44` | Fedora-based desktop integration; name the actual base and tested desktop. |
| Bonito Rawhide | `variants.bonito-rawhide` in the same config uses `fedora-bootc:rawhide` | A rolling development lane; Rawhide is not a Fedora 45 release candidate. |
| Tromso | `sibling_images` in the same config and the [Tromso README](https://github.com/tuna-os/tromso/blob/main/README.md) | KDE Plasma on freedesktop-sdk with BuildStream; a separate bootc project with its own checks. |

This is source evidence for the text, not a table of current image health.
Before publication, resolve the candidate's base again from the source commit
and image metadata. Do not label Tromso as Fedora-based or carry Bonito's test
results over to it. Do not imply Fedora, KDE, or another project's endorsement.

Follow [FEDORA-BASE-POLICY.md](../FEDORA-BASE-POLICY.md) and
[#1171](https://github.com/tuna-os/tunaos/issues/1171) for a Fedora base
transition. A tracker closure alone does not establish GA: use the promotion
criteria in [VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md).

## Release-relative schedule and ownership

Use the [Fedora 45 schedule](https://fedorapeople.org/groups/schedule/f-45/f-45-key-tasks.html)
and the [Fedora announcement list](https://lists.fedoraproject.org/archives/list/announce@lists.fedoraproject.org/)
to confirm the upstream release. Define **R** as the confirmed date of the
upstream release, not an estimate from the issue or the Q4 calendar. Move the post and
digest together if Fedora moves R. Fedora's date and TunaOS readiness are
separate gates. Do not publish a support announcement to meet a calendar date.

This plan proposes work slots. Record the assignee and date in #3089
before any send. These roles need volunteers.

| Window | Responsible role | Work and completion evidence |
|---|---|---|
| Before R | Outreach coordinator | Select a sender, check for prior contact in #1137 and the outreach ledger, prepare one canonical post and one Show-and-tell URL. |
| Before R | Bonito technical reviewer | Fill the evidence packet below for each candidate cell; approve the base/version wording. |
| Before R | Tromso maintainer | Choose whether to include a sibling demo and attach its own evidence; omit it if that evidence is absent. |
| R through R+2 days | Authorized sender | Publish the reviewed post and digest only if the gates pass; record public URLs and sent dates. Otherwise hold the product/demo pitch and use the existing-user call alone. |
| R+7 days | Community triager | Reply to reports, route reproducible faults to issues, and offer a bounded first contribution. Record open questions and PR links. |
| R+14 days | Metrics owner | Record responses, consent-confirmed adopter PRs, contributor pickups and merges in the next monthly snapshot. Record no response as an outcome. |

Use the same schedule in the [Q4 promotion calendar](Q4-2026-PROMOTION-CALENDAR.md).
Keep the adopter conversation open after this window.

## Evidence packet and showcase sequence

Complete the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md) and
[Fedora readiness review](FEDORA-OUTREACH-READINESS.md) before a candidate
appears in the call, demo, or press copy. Each featured cell needs:

- Source commit, base version, image digest, desktop, architecture, and build
  run URL. Use [IMAGE-TAGS.md](IMAGE-TAGS.md) for the reference shape.
- Current lint, boot, desktop, and install results for that same candidate,
  with full logs and exit codes. Use the generated
  [matrix](MATRIX-STATUS.md) and [green criteria](GREEN-CRITERIA.md) directly.
  A successful build alone is insufficient.
- A tested download and matching verification instructions from
  [VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md). Check the actual linked bytes.
- A screenshot or short video from that candidate, with capture date and
  desktop/architecture caption. Remove private data. Do not substitute a
  mockup for a live session.
- Remaining limitations and reviewer approval. Do not offer an untested
  hardware, desktop, update, or rollback guarantee.

Rehearse a short showcase. Explain the base and image model, then boot the
candidate in a disposable VM. Show the desktop task that the evidence covers.
Show its recorded update/rollback test and limitations. End with the shared adopter
and contributor links.

Do not ask a new tester to switch their primary system.
Use the current [install guide](INSTALL.md) for a reviewed trial path.

For Tromso, use its own repository's build, live-ISO, plain-install, and
LUKS-install evidence. The `sibling_images` contract in `tunaos.toml` keeps
those checks outside the TunaOS variant matrix. A missing Tromso packet removes
that demo from the showcase; it does not stop a verified Bonito segment.
If Bonito's packet fails, hold its trial CTA and media pitch. The voluntary
call to people who already use TunaOS can proceed after text review.

## Shared Show-and-tell and contributor copy

Reuse the [adoption call](ADOPTION-CALL.md) and its consent template. Create a
Discussion in Show-and-tell, or reuse the one from
[#1367](https://github.com/tuna-os/tunaos/issues/1367); link all channels back
to it. Add this introduction after review of the candidate facts:

> During the Fedora 45 release window, we invite reports from people
> who already run or evaluate TunaOS. Bonito is our Fedora-based variant;
> its release notes name the base version from the test. Tromso is a
> separate KDE desktop built on freedesktop-sdk. Tell us which project,
> desktop, architecture, and use case you evaluate, and what needs improvement.
> Please use the reply template below and share only details you may publish.

Append the reviewed candidate notes and evidence links; remove any project
that is not part of the reviewed showcase. The existing response template
keeps production, development, and evaluation separate. Ask respondents to add
the image digest and source channel if they know them; both fields are optional.
Route Tromso faults to its tracker and Bonito faults to this repository.

For new contributors, link the [contributor guide](../CONTRIBUTING.md) and the
[org-wide good first issue pool](https://github.com/issues?q=org%3Atuna-os+is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22).
A triager should check that an issue remains open and unclaimed before they offer
it. Ask for one reproducible report, docs correction, or regression test.
Track the issue pickup and follow-up PR; do not count a reply as a merged
contribution or an adopter. Use the next weekly slot for contributor triage to
follow up. Do not promise immediate review.

## Publication release-note draft

Replace every bracketed field and remove optional sections before review.
This describes the measured candidate, not a new Fedora 45 product launch.

> **Desktop evaluation notes from TunaOS for the Fedora 45 release window**

> TunaOS builds bootable OCI images for desktops. This showcase covers Bonito on
> [ACTUAL_FEDORA_BASE], with [DESKTOP_AND_ARCHITECTURE]. The candidate is
> [IMAGE_DIGEST], built from [SOURCE_COMMIT]. Its release stage is
> [LIFECYCLE_STAGE]. Test results and limitations: [EVIDENCE_URL].

> Changes since [PREVIOUS_CANDIDATE]: [CHANGES_WITH_MERGED_PR_LINKS].
> Trial and artifact verification: [TESTED_DOWNLOAD_AND_GUIDE_URLS].
> Known limitations: [LIMITATIONS_AND_ISSUES].

> [OPTIONAL_TROMSO_SEGMENT_WITH_ITS_OWN_BASE_DIGEST_AND_EVIDENCE].

> Do you already use or evaluate these desktops? Share a voluntary report at
> [SHOW_AND_TELL_URL]. To contribute a report or a small fix, start at
> [CONTRIBUTOR_GUIDE_AND_CURRENT_ISSUE_URL].

Use one canonical post for the blog, Matrix pointer, and release digest.
Do not turn the draft's placeholders into claims or reuse historical claims
from the [press kit](PRESSKIT.md) without the candidate evidence.

## Media handoff and outcome record

For Fedora Magazine, coordinate through
[#1137](https://github.com/tuna-os/tunaos/issues/1137). Do not send a duplicate
pitch. Check the [contribution guide for the Magazine](https://docs.fedoraproject.org/en-US/fedora-magazine/contributing/)
and [proposal area](https://discussion.fedoraproject.org/c/workflows/magazine/57)
before you select the submission route. Rework the
[historical pitch](FEDORA-MAGAZINE-PITCH.md) around the release-note facts above.
Do not call Bonito an official Fedora flavor or promise an editorial slot.

For Linux ecosystem publications, coordinate with
[#3019](https://github.com/tuna-os/tunaos/issues/3019) and the
[press pitch pack](TECH-PRESS-PITCHES.md). Attach the same reviewed notes,
screenshot captions, limitations, and an authorized contact. Suggested opener:

> Would a technical look at bootable-container desktops interest your readers
> during the Fedora 45 release window? We can provide a Bonito candidate with
> its actual Fedora base, test evidence, and limitations, plus an optional
> freedesktop-sdk/KDE comparison from Tromso. The attached notes distinguish
> the projects and link to a voluntary adopter call.

Before a send, the sender checks the rules of the outlet, prior contact,
and recipient.
Follow up once after seven days if the outlet allows it; do not mass-send.
Record the sent date, public thread or article URL, response or no response,
and next action in [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md).
Keep private addresses and private replies out of the public record.

At R+14, use [ADOPTION-METRICS.md](../ADOPTION-METRICS.md) for the monthly
snapshot. Separate referrals and downloads from voluntary reports, named
consent-confirmed entries, anonymous reports, and contributor PRs. Count each
respondent once across channels. Unknown referral data stays unknown; do not
add telemetry to the OS for this campaign. A prepared draft is not a sent pitch,
an evaluation report is not production use, and a sibling project is not an
external adopter.
