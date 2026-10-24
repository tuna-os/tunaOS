# bootc desktop strategy and publication drafts

Prepared for [#3115](https://github.com/tuna-os/tunaOS/issues/3115). **Unsent
drafts for maintainer review.** This pack adds the desktop documentation request
and technical blog copy to the existing [CNCF case
study](CNCF-BOOTC-SHOWCASE.md). For broader introductions, use
[#2886](https://github.com/tuna-os/tunaOS/issues/2886), with proposals in [PR
#3711](https://github.com/tuna-os/tunaOS/pull/3711). Reuse that conversation.

## Upstream desktop documentation request

Recipient: [bootc-dev/bootc](https://github.com/bootc-dev/bootc), the current
upstream repository. Its
[ADOPTERS.md](https://github.com/bootc-dev/bootc/blob/main/ADOPTERS.md) lists
projects for desktops, such as Universal Blue. Recheck that file, open
issues/PRs, and contribution guidance before contact. Reuse a thread that
addresses this topic.

Suggested title: **Desktop use-case discoverability and a TunaOS example**

> Would a short desktop-use-case link from the README or documentation be
> useful? Your adopter list already includes desktop implementations such as
> Universal Blue, including Bluefin. We would like to help readers find that
> material and offer TunaOS as an additional image-factory example.

> TunaOS combines bases with desktops and hardware layers in bootc images:
> https://github.com/tuna-os/tunaOS. Its configuration and verification criteria
> are public, and readiness varies by combination. We can contribute a short
> description with a link to a measured example of a desktop lifecycle.

> Would you prefer an adopter-list PR, a desktop documentation section, or a
> community write-up? We can follow your preferred format and ask each named
> project to review its description. We seek a link in the documentation. This
> request implies no endorsement or production reference.

If upstream prefers an adopter entry, confirm the category and evidence with
maintainers. Do not invent an adoption year or classify TunaOS as a production
end-user. Suggested description for review:

> TunaOS — an image factory that composes bootc desktop operating systems from
> multiple base distributions. Configuration and verification evidence:
> https://github.com/tuna-os/tunaOS.

## Universal Blue / Bluefin alignment request

Proposed message: **bootc offers a common model for OS delivery to community and
enterprise desktops.**

Each project keeps its own product goals, support boundaries, and contribution
process. A common delivery model does not make base distributions or desktop
configurations interchangeable.

Copy for an authorized sender to adapt for the relevant community, or for
@castrojo if a maintainer selects that recipient:

> Would you review an article about the desktop ecosystem with us? We want to
> credit Universal Blue and Bluefin accurately, compare image composition and
> validation practices, and route contributors to the right upstream. A shared
> technical session could follow if that is useful to you. FOSDEM 2027 is one
> possible venue, subject to the actual CFP, speaker consent, and acceptance.
> Would a recipe comparison or a joint demo be a useful start?

Do not infer a relationship from inherited commits or CODEOWNERS entries; see
the correction in [the FOSDEM draft](CFP-FOSDEM-2027.md). Agree on speakers and
copy before a joint CFP through
[#1135](https://github.com/tuna-os/tunaOS/issues/1135). This draft establishes
no speaker, devroom, or conference acceptance.

## Blog draft: Why we built TunaOS on bootc

TunaOS starts with an image-factory question: how can we combine bases with
desktops, kernels, and drivers through a common build process? Our
[vision](../VISION.md) describes those inputs; the
[configuration](../tunaos.toml) records the combinations. bootc gives these OS
images a common delivery interface.

[bootc](https://bootc.dev/bootc/) uses OCI images to deliver transactional
updates to hosts. The kernel and userspace become the host operating system; the
desktop does not run inside an application container. That lets an image builder
use Containerfiles and a registry. The builder still needs to validate the
installed system.

We chose that workflow because it connects composition, artifact review, and
delivery. The [pipeline](PIPELINE.md) turns configuration into desktop image
builds. A digest identifies an artifact. Consumers can
[verify](VERIFY-ARTIFACTS.md) its provenance. Neither fact establishes that the
desktop boots, updates, and rolls back successfully; those claims need the
separate [quality criteria](GREEN-CRITERIA.md).

“bootc versus OSTree” is an incomplete comparison. Upstream's
[introduction](https://bootc.dev/bootc/) describes OSTree as its default storage
backend and also documents a composefs backend. A/B deployment and transactions
are designs for updates. They do not specify a complete workflow for composition
and delivery. Our choice here is the OCI workflow; we do not claim that other
update designs are inherently less reliable. An OS deployment rollback also does
not undo application data changes or replace backups.

We draw on [Universal Blue](https://universal-blue.org/) and
[Bluefin](https://projectbluefin.io/), credited in our vision, and on [Dakota's
BuildStream approach](https://github.com/projectbluefin/dakota), credited in our
[ecosystem references](../ADOPTERS.md). TunaOS explores composition across base
families; that work benefits from upstream recipes, review, and shared findings.
It does not establish an agreed partnership with those projects.

Enterprise Linux is one evaluation path within that factory. Redfin is a RHEL 10
configuration with a [local-build workflow](rhel-setup.md), not a public image
offer. A base OS choice does not establish enterprise readiness or a support
agreement. Readiness belongs to a specific tested combination and its evidence.

The next useful collaboration is concrete: make desktop examples easier to find,
compare one recipe, and report one measured lifecycle. We welcome upstream
review of that work. With a shared model for delivery, communities can solve
common questions and keep their different desktop goals.

## Publication and outcome receipts

This directory holds maintainer references, not the published website. After
technical review and the [claim checklist](CONTENT-CLAIM-CHECKLIST.md), the site
owner can adapt the blog draft in
[tuna-os/docs](https://github.com/tuna-os/docs) for tunaos.org/blog. Record its
published URL. A merge of this file does not publish a post. Use [the CNCF
draft](CNCF-BOOTC-SHOWCASE.md) for the separate editorial ask.

Keep #3115 open for external outcomes. A maintainer selects recipients and
authorizes public contact under the existing [#3240
handoff](https://github.com/tuna-os/tunaOS/issues/3240). Record public receipts
with dates in [the outreach ledger](ADOPTION-OUTREACH-STATUS.md) and #3115:

- Upstream: the issue/PR and accepted desktop link, or the maintainer response.
- CNCF: the editorial response and published case-study URL, if accepted.
- Talks: speakers who consent, plus accepted or delivered sessions.
  The two-presentation target needs event receipts.
- Blog: the published post and agreed cross-links.
- Reach: dated before/after star measurements under
  [ADOPTION-METRICS.md](../ADOPTION-METRICS.md). The 100-star target remains a goal;
  stars cannot establish the source of referrals or prove adoption.

Record declines and missed targets as such. Drafts, sends, and dependency links
do not count as endorsements or completed partnerships.
