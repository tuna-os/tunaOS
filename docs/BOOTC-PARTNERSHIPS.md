# bootc ecosystem partnership proposals

Prepared material for [#2886](https://github.com/tuna-os/tunaOS/issues/2886).
These are outreach drafts for a maintainer to adapt in an existing community
conversation. They do not record contact, endorsement, or an agreed partnership.
The issue's November 1 cross-promotion and Q1 2027 lead targets remain goals,
not publication commitments.

## Shared introduction and evidence

> TunaOS is an image factory for bootc-based desktop operating systems. We would
> like to contribute a desktop use case to the bootc ecosystem and exchange
> practical lessons about image composition, validation, and updates. Would a
> short technical write-up or documentation contribution be useful to your
> community? We can adapt it to your contribution process and credit reviewers.

Use [VISION.md](../VISION.md) and [the pipeline](PIPELINE.md) for the architecture,
[the build configuration](../tunaos.toml) for composition examples, and
[the verification criteria](GREEN-CRITERIA.md) for what testing establishes.
Choose any demo cell from current [matrix evidence](MATRIX-STATUS.md) at send time;
include its artifact digest and boot/upgrade/rollback results with the write-up.
Do not turn a successful build into a claim about installed hardware.

Run the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md) before sending.
Avoid “largest adoption”, “flagship”, guaranteed rollback, enterprise readiness,
and upstream reference-implementation status without evidence and agreement.
An upstream dependency or a linked draft is not an endorsement.

## Partner-specific proposals

### bootc-dev/bootc: desktop use case

> Could a TunaOS desktop case study be useful in your adopter documentation or
> community discussion? We can contribute a small Containerfile-to-desktop
> example, explain the validation boundaries, and share measured update and
> rollback results. Which contribution format would be most useful?

Start from the project named in #2886, using an existing warm conversation;
confirm its current contribution guidance before choosing a discussion category.
Offer one reviewed documentation link or community post as the first deliverable.
Reuse the topic outline in [the CNCF showcase draft](CNCF-BOOTC-SHOWCASE.md),
but recheck its claims under the checklist above before copying any prose or
metrics. A CNCF blog submission is a separate editorial request.

### Universal Blue: shared documentation

> We would like to exchange documentation links about building and evaluating
> bootc desktops. TunaOS focuses on an image factory with configurable desktops and
> multiple base configurations. Is there a recurring contributor question where
> a narrowly scoped recipe comparison would help both communities?

Propose one jointly reviewed recipe comparison with links to each project's own
installation and contribution guidance. Ask the community to review its own
positioning; avoid a migration pitch or assuming a contributor handoff agreement.

### Project Bluefin: complementarity and contributor routing

> Could we review a short explanation of where TunaOS's image-factory approach
> and Bluefin's experience fit different needs? We would like to credit upstream
> work accurately and help contributors report problems to the right project.
> A shared documentation note on issue routing could be a useful first step.

Keep this conversation distinct from Universal Blue's broader community outreach.
Use a concrete dependency example from [image-versions.yaml](../image-versions.yaml)
in the review, rather than implying all TunaOS images derive from Bluefin.
Ask reviewers to confirm descriptions and links before proposing cross-publication.

### Asahi Linux: installer compatibility

> TunaOS is working on an experimental M1/M2 path through
> bootc-installer-asahi. Could we compare installer interface expectations and
> identify a useful compatibility report to contribute? We would like to link
> to the right upstream guidance and report limitations accurately.

Attach [the hardware caveats](HARDWARE.md) and
[the implementation tracker](https://github.com/tuna-os/tunaOS/issues/781).
M1/M2 support is in progress; do not advertise a supported installation path.
Agree on a test scope and a reproducible report before proposing documentation
cross-links. Hardware validation and installer publication are separate from
image builds. Do not ask users to test destructive installation steps in a pitch.

### Other bootc communities: exchange findings

For Fedora/CoreOS and other server or desktop communities, start with a specific
shared technical question, such as image validation or desktop composition.
Offer a small documented finding and ask whether a reciprocal technical session
would help. Choose one interested community after the first conversations;
do not send the same promotional message to multiple unrelated channels.

## Three-post collaboration outline: “Immutable desktops at scale”

1. **From Containerfile to desktop:** show a bounded build configuration example, explain
   bootc's role and credit upstream. Invite a bootc reviewer to correct terminology.
2. **Validation before promotion:** walk through one measured cell, artifact
   verification, and upgrade/rollback observations. Include failures and limits;
   avoid fleet-scale or enterprise adoption claims without an actual case study.
3. **Shared ecosystem, different goals:** invite Universal Blue/Bluefin input
   on contributor routing and an Asahi compatibility sidebar if reviewers agree.
   Describe enterprise use cases as evaluation scenarios, not customer outcomes.

Coordinate ownership and placement with the content team before promising a
publication date. Each post needs a technical reviewer, source links for claims,
and consent for partner quotations, names, and logos. Cross-link the published
posts only after both sides agree to the wording.

## Execution and completion evidence

A maintainer coordinates official partnerships, as #2886 requests. The sender
uses an existing public conversation or established community relationship;
no cold DMs. Before contact, select the recipient/channel, review the tailored
copy, and check for an existing thread to avoid duplicate outreach.

Record each send and response as a dated comment on #2886 with a durable public
URL, the exact ask, the responsible follow-up owner, and the next action. Keep
private correspondence private; obtain consent for a public summary. Use those
receipts rather than maintaining a second hand-written live status table here.

The issue stays open until there is evidence for its external outcomes:

- A published cross-promotion URL, publication date, and partner acknowledgement.
- A bootc community response or reference showing awareness of the desktop use case.
- A consenting partnership lead and a concrete Q1 2027 follow-up, such as a joint
  case study or talk proposal. Name a person publicly only with their consent.

A sent message alone does not meet the publication goal. Record a decline or
missed target honestly, and revise the next action with the maintainer rather
than counting a proposal as a partnership.
