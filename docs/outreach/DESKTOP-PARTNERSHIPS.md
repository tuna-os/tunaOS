# Desktop community outreach handoff

Draft for [#3018](https://github.com/tuna-os/tunaOS/issues/3018).
This handoff has no contact or publication receipt.
An authorized maintainer must approve the sender, channel, and final copy
before external contact, as required by [the agent guide](../AGENT_GUIDE.md#community--outreach-initiatives-687).
Keep #3018 open until the sender records each contact and outcome.

## Evidence to attach before sending

Use the [content claim checklist](../CONTENT-CLAIM-CHECKLIST.md).
[Flavor equality](../../.spektacular/knowledge/decisions/adr-0005-flavor-equality.md)
sets project priorities; it does not prove that each desktop passes its checks.

- Read `tunaos.toml` for the selected variant and desktop. Attach the source
  commit, image digest, architecture, and desktop version to each demo.
- Link the selected cell's current [matrix evidence](../MATRIX-STATUS.md)
  and [green criteria](../GREEN-CRITERIA.md). State any failed or missing checks.
  Do not turn a configured flavor into a claim of production readiness.
- Capture a boot and login on that image, plus screenshots and test logs.
  Include update and rollback results only if tested on that installation.
- Check image paths with [IMAGE-TAGS.md](../IMAGE-TAGS.md) before adding
  download or switch instructions. This draft contains no install commands.
- Treat [Tromsø](https://github.com/tuna-os/tromso) as a sibling whole-OS
  product. `tunaos.toml` registers its BuildStream/freedesktop-sdk build;
  use that repository's build and install evidence for a Tromsø demo.
  The TunaOS variant matrix does not establish Tromsø readiness.

## KDE Plasma

Route: [KDE Press Room](https://kde.org/contact/) lists `press@kde.org`
for stories and official contact. Ask the press team to route the request to the promotion team.
Do not send a technical support request to this address.

Subject: **Plasma on bootc: TunaOS and Tromsø showcase proposal**

> Hello KDE team,
>
> TunaOS builds images of desktop operating systems for delivery through bootc. We would like to
> share a Plasma deployment story and ask whether a joint technical post
> would be useful to your community. Our sibling project Tromsø uses
> BuildStream and freedesktop-sdk; our distro-based builds use a separate
> pipeline. We can provide source links and a demo with test evidence for
> the selected image, including its known limits.
>

> Would someone be willing to review the Plasma details and suggest a
> suitable KDE channel? We would also welcome advice on whether this fits
> a future Akademy submission or a discussion with KDE neon contributors.
> We are asking about interest, with no event slot or integration assumed.

Proposed article: **KDE Plasma on TunaOS: an image-based desktop workflow**.
Outline: distinguish Tromsø from distro-based images and show the selected
Plasma session. Explain the build and update path. Link test evidence and
known gaps, then invite review of desktop integration findings. Ask KDE to review
names and credits before any cross-post. An Akademy proposal must use the
event's published call; a neon discussion is a separate technical request.

## COSMIC / System76

Route: use the community links on the official
[COSMIC page](https://system76.com/cosmic) to ask who can review stories about downstream distributions. The page also links COSMIC distributions. Ask about
listing criteria only after a tested download and documentation are ready.

Subject: **COSMIC on TunaOS: proposal for a downstream story**

> Hello COSMIC team,
>
> TunaOS has COSMIC flavor definitions in its image build configuration.
> We would like to share a tested bootc deployment and learn which package
> or session findings would help COSMIC developers. We can supply a short
> demo, the exact image and desktop version, and logs for known gaps.
>
> Would you like to review a joint article about COSMIC in an
> image-based workstation workflow? Who should review a possible COSMIC
> distribution listing or a System76/Pop!_OS channel post?

Proposed article: **COSMIC in an image-based workstation workflow**.
Outline: selected base and COSMIC version; build inputs; login and desktop
demo; measured update behavior; open integration findings and upstream links.
Tie the enterprise Linux angle to the chosen base and measured behavior.
A COSMIC build does not prove certification for System76 hardware or integration
with Pop!_OS. It does not establish a co-author or a distribution partnership.

## Niri

Route: use the Discussions tab in [the upstream repository](https://github.com/niri-wm/niri).
That repository also links project documentation. Read the current community rules,
then ask in a suitable discussion channel if a downstream showcase is welcome.
Reserve upstream bug reports for reproducible compositor defects.

Subject: **Niri on bootc: downstream showcase and developer notes**

> Hello Niri community,
>
> We would like to share a Niri session on a tested image from TunaOS.
> Could a short showcase with source links, exact versions, and known
> limitations be useful here? We would also value review of developer notes
> that distinguish the image package set from compositor behavior.

Proposed showcase: **Niri on a bootc-based distribution**. Show login,
window navigation, and a tested update path on the same identified image.
The companion developer note should link the selected flavor configuration,
session setup, user configuration, and portal checks. Include reproduction
steps and logs; compare against an upstream-supported setup before filing
a compositor bug. Publish a user guide in [tuna-os/docs](https://github.com/tuna-os/docs)
after a contributor tests the commands. Follow that repository's contribution rules.

## Send, response, and completion

1. Assign a maintainer sender for each community in #3018. Check that issue
   and the [outreach ledger](../ADOPTION-OUTREACH-STATUS.md) for prior contact.
2. Attach the evidence above and approve the final message in #3018. Replace
   proposed demo details with measured results; remove unsupported claims.
3. Send one initial message per community through the approved channel.
   Record the date, sender, channel, and public receipt in #3018. For private
   mail, record a consent-safe summary and keep addresses and private replies
   out of the repository. A draft or a sent message is not an agreement.
4. Record the reply, decline, or no response. A sender may make one follow-up
   after 14 days, subject to the channel rules, then record no response and stop.
5. If a community accepts, agree on reviewer, venue, credits, scope, and
   publication timing. Record the approved copy and published URL. Use partner
   names, logos, quotes, and co-author credits only with permission.
6. Close #3018 after the sender records outcomes for all three communities.
   Each agreed publication or developer note needs a URL or a follow-up issue with an owner. Declines and no response are valid outcomes; neither
   counts as a partnership or an adopter.
