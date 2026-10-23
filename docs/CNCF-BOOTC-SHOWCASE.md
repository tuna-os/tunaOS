# CNCF / bootc desktop case study draft

Prepared for [#1340](https://github.com/tuna-os/tunaOS/issues/1340) and
[#3115](https://github.com/tuna-os/tunaOS/issues/3115). **Draft, not
submitted.** For external submission, use
[#3240](https://github.com/tuna-os/tunaOS/issues/3240).

## Positioning and sources

[CNCF lists bootc at Sandbox maturity](https://www.cncf.io/projects/bootc/).
That describes bootc's project status; it does not establish CNCF endorsement,
certification, or sponsorship of TunaOS. TunaOS is a downstream image factory.
Its relationship to bootc belongs under upstream dependencies, as recorded in
[ADOPTERS.md](../ADOPTERS.md). It is not an organizational adopter of TunaOS.

Use [bootc-dev/bootc](https://github.com/bootc-dev/bootc) for upstream
coordination. Its [adopter
list](https://github.com/bootc-dev/bootc/blob/main/ADOPTERS.md) already includes
Universal Blue and desktop implementations. Ask where a TunaOS entry fits before
a proposal for another desktop list in the README. The [desktop strategy
pack](BOOTC-DESKTOP-STRATEGY.md) has a tailored request and blog draft. For the
broader proposal, use [#2886](https://github.com/tuna-os/tunaOS/issues/2886).

## Submission copy: Desktop Linux through an OCI image factory

### Challenge

Desktop image builders need a way to compose an OS, deliver updates, and verify
that the desktop still works. Different base distributions bring different
package managers and integration requirements. TunaOS explores a common workflow
for image delivery across those differences.

### Approach

TunaOS combines bases with desktops and hardware layers in bootc images. The
[build configuration](../tunaos.toml) describes combinations across Enterprise
Linux, Fedora, Debian, Ubuntu, Arch, openSUSE, and Gentoo. The configuration
describes composition. It does not establish verification or support for every
combination.

[bootc](https://bootc.dev/bootc/) provides transactional OS updates using OCI
images. TunaOS's [pipeline](PIPELINE.md) builds desktop images around that
model; consumers can use the [verification guide](VERIFY-ARTIFACTS.md) to check
signatures and attestations. A signature verifies the provenance of an artifact.
To establish readiness, test the desktop separately.

The enterprise evaluation path includes Redfin, the RHEL 10 configuration. It is
**local-build only**, as the [project README](../README.md) and [Redfin
guide](rhel-setup.md) specify. Do not offer a public Redfin image or infer a
vendor support agreement from the base distribution.

### Evidence to attach before submission

The focus is architecture. Deployment claims need measurements and consent from
an adopter. Do not claim success at fleet scale without that evidence.

- Select a cell from current [matrix evidence](MATRIX-STATUS.md) and include its
  source revision, image digest, architecture, and dated test-run URLs.
- Attach installed boot, upgrade, and rollback observations for that cell,
  including failures and limits under [GREEN-CRITERIA.md](GREEN-CRITERIA.md).
  A build or a screenshot cannot prove the lifecycle.
- Use [ADOPTION-METRICS.md](../ADOPTION-METRICS.md) for adoption measures and
  consent-confirmed [adopter entries](../ADOPTERS.md) for deployment claims.
  Image pulls and GitHub stars do not establish production users or fleet size.

The former draft's edition totals, claims about signatures for every artifact,
and “100%” rollback guarantee had no linked measurements. This draft replaces
them with evidence requirements. Rollback changes the OS deployment; it is not a
backup of user data or a guarantee that every hardware configuration recovers.

## Editorial and outreach handoff

Use the [content claim checklist](CONTENT-CLAIM-CHECKLIST.md). A maintainer
chooses the recipient, confirms the editorial route with CNCF, reviews the
evidence, and sends or authorizes the pitch. Do not assume Sandbox has a
case-study submission portal, a publication commitment, or a reserved event
slot.

Proposed pitch:

> Would an architecture article about desktop Linux images built with bootc fit
> your editorial scope? TunaOS can show its multi-base build configuration and a
> measured example of a desktop lifecycle. We would welcome upstream terminology
> review and will distinguish tested behavior from planned work.

Coordinate any talk with [the FOSDEM draft](CFP-FOSDEM-2027.md) and #1135 after
a check of the event's current CFP. Record the sent date, public thread,
response, and published URL in [the outreach
ledger](ADOPTION-OUTREACH-STATUS.md). A pitch does not count as a published case
study or an agreed partnership.
