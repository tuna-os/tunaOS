# LWN feature research and author handoff

Issue: [#3113](https://github.com/tuna-os/tunaos/issues/3113).
Status: internal preparation; no pitch sent and no publication agreed.
Related: [the broader media handoff in PR #3676](https://github.com/tuna-os/tunaos/pull/3676)
tracks #3019. Coordinate sends with that owner to avoid duplicate contact.

## Submission constraint

The [LWN author guide](https://lwn.net/op/AuthorGuide.lwn), checked on
2026-10-23, rejects machine-generated pitches and articles. This document is
machine-generated internal research.

**Do not submit this text or the pitch notes below to LWN.**

A human author must research the topic and write
an original pitch and article under that policy. Maintainer approval alone
does not make this draft eligible for submission.

The guide asks authors to contact `authors@lwn.net`, with a detailed
pitch before an article. The issue proposes `editors@lwn.net`; use the author
route for a contributed feature unless LWN directs the author elsewhere.
It asks for a topic, coverage, and the author's relevant experience. Its
general length is about 1,500 words; it favors news and analysis over tutorials.

## Pitch notes for the human author

- Topic: how bootable-container desktops change administration for Enterprise
  Linux, with TunaOS as the example to examine.
- Hook: desktop composition can change apart from a long-lived base through
  an image pipeline. Does that make desktop fleets easier
  to operate, and what evidence would establish that?
- Coverage: bootc deployment semantics, AlmaLinux evaluation, local Redfin
  builds, and desktop and kernel choices. Examine encrypted-install tests,
  application containers, support, and hardware limits.
- Interviews: consult a maintainer and an independent evaluator. Ask for
  reproducible evidence and consent before you name an organization.
  Disclose the author's project affiliation and supply their own experience.
- Materials: use the sources below as research leads, with current artifact
  evidence and screenshots from [the press kit](../PRESSKIT.md). Do not
  describe an evaluation as a production deployment or an endorsement.

## Internal feature research draft

<!-- ste-disable: internal feature research explores the technical reporting voice for LWN readers -->

### Desktop composition becomes an image problem

Enterprise Linux desktops present a familiar tension. Administrators want a
base they can maintain for years, while users want desktop environments and
hardware support that move faster. Installing a newer desktop is only part
of the problem: someone must integrate its services, display manager,
graphics stack, and update behavior. Doing that independently on each
workstation makes the fleet harder to reproduce. TunaOS approaches the
problem as an image factory, assembling a base operating system, a desktop,
and optional kernel or driver layers into bootable container images.

The project's [architecture guide](../AGENT_GUIDE.md) describes this
composition model. Its enterprise-family examples include Yellowfin, based
on AlmaLinux Kitten 10, and Albacore, based on AlmaLinux 10. Those names
identify different upstream bases, rather than successive release channels.
The interesting question is whether moving desktop integration into an image
build gives administrators a more testable deployment unit. A container
build succeeding cannot answer that question by itself; the desktop must
still start, install, update, and recover on the intended machines.

### An operating system delivered through a registry

TunaOS uses bootc to deliver an operating system through an Open Container
Initiative image. The registry becomes a distribution mechanism for the
host's system content, including its kernel and userspace. This is not an
application container that needs another desktop operating system beneath
it. The image is the input to a machine's bootable deployment. That makes
familiar container practices useful for operating systems: a build recipe,
an image digest, and a registry can describe what a group of machines should
receive.

The [update guide](../USER-GUIDE.md#4-day-2-administration) describes staging an update and
activating it at reboot. Retaining the previous deployment provides a
recovery path, but it does not make all state transactional.
[Upstream bootc documentation](https://bootc.dev/bootc/bootc-filesystem.7.html)
distinguishes image content from persistent state: `/var` is shared across
deployments, and `/etc` normally preserves local configuration through a
merge. Rolling back the operating system therefore does not restore a user's
documents or undo an application's database migration. Fleet recovery plans
must test those boundaries.

### Building the desktop instead of repairing each host

The [pipeline](../PIPELINE.md) separates base construction, desktop assembly,
and hardware overlays. Configuration in [tunaos.toml](../../tunaos.toml)
selects variants and flavors. A desktop flavor is an image tag: for example,
the configured Albacore GNOME reference is `ghcr.io/tuna-os/albacore:gnome`.
An image name in configuration is a build input, not proof that a particular
digest has been published or passed its boot tests. Administrators need
both the composition recipe and evidence for the artifact they intend to
install.

This approach offers a useful place to encode organizational decisions. A
team could maintain a derived image with its required system packages and
defaults, test that result, then offer the same artifact to a pilot group.
The integration work still exists, but it moves toward a shared pipeline.
Different desktop environments also remain different products to validate:
their sessions, portals, display managers, and graphics requirements cannot
be inferred from the success of another flavor. More choice increases the
test surface as well as the range of potential users.

### From an AlmaLinux evaluation to a Redfin build

An enterprise evaluation can begin with Yellowfin or Albacore while the team
learns the image model and measures its application requirements. Selection
should follow the desired upstream lifecycle and the evidence for a specific
desktop and architecture. Neither is a substitute for checking the chosen
hardware, peripheral software, or recovery workflow. A lab should preserve
the tested image digest and installer evidence so that a later failure can
be compared with a known result, rather than with a tag whose contents may
have changed.

Redfin uses RHEL 10 through the same EL10 build path, but the project's
[Redfin guide](../rhel-setup.md) describes a local-build route, not a public
download. An evaluator considering that route needs appropriate registry
access, subscriptions, and a private build and distribution process. The
organization must establish its own entitlement and support arrangements;
the presence of a RHEL base does not establish support for TunaOS's desktop
additions. This is a deployment progression to investigate, not a promise
that switching an AlmaLinux installation to Redfin is a validated migration.

### Hardware enablement changes the validation target

The [overlay Containerfile](../../Containerfile.overlay) makes the kernel
and driver choices explicit image inputs. Hardware enablement, or HWE,
flavors can combine a desktop with a different kernel layer; driver flavors
introduce another compatibility boundary. That can help address the mismatch
between a conservative base and a newer workstation, but a kernel change
also changes what must be tested. Graphics modules, suspend, networking, and
the boot chain belong in the pilot's acceptance criteria. A successful
generic virtual-machine boot provides only part of that evidence.

The project's [hardware reference](../HARDWARE.md) illustrates why scope
matters. Apple Silicon work is described as in progress, and its Intel T2
image's virtual-machine results do not establish validation on a physical T2
Mac. Neither should become a general enterprise hardware-support claim.
For an administrator, the relevant question is narrower: does the exact
image, kernel, driver, firmware, and machine combination work for the
required workload? An image factory can make that combination reproducible;
it cannot replace the measurements that establish its suitability.

### What encrypted-install testing actually establishes

The [LUKS end-to-end workflow](../../.github/workflows/luks-e2e.yml) documents
a concrete installation experiment. It builds development media, boots a
virtual machine, invokes the Fisherman installer backend with an encryption
recipe, then reboots the installed disk and checks passphrase unlock and
login. This exercises Linux Unified Key Setup encryption across an install
and boot boundary, rather than merely checking that an encryption package
exists. The distinction matters: an encrypted disk that never reaches the
installed desktop is not a usable workstation.

That workflow's existence is not evidence that every matrix cell currently
passes. It also uses development media with SSH available to drive the
backend. A passing backend run does not establish that a user can complete
the graphical installer on published media. The [test guide](../AGENT_GUIDE.md#testing-an-iso-dev-media-vs-published-media)
distinguishes those paths. Trusted Platform Module auto-unlock is another
separate assertion: [the encryption notes](../LUKS-TPM.md) describe an
additional boot without a passphrase and variant-specific limits. Reporting
should identify which assertion a linked run actually proves.

### Application containers inside an image-managed host

An image-managed desktop still needs a practical place for user software.
The EL10 [base-package script](../../build_scripts/10-base-packages.sh)
includes Podman and Distrobox in its package selection. These provide a
concrete starting point for examining application or development containers
on the installed host, while system packages remain part of the image build.
The phrase "nested containers" needs care here: delivering the host as an
OCI image does not mean the installed operating system itself runs inside a
container engine.

Workloads that actually run a container engine inside another container are
a separate case to measure. They can depend on storage drivers, privileges,
control groups, and security policy. Likewise, a Distrobox environment that
shares a user's files should not be presented as an isolation guarantee.
The useful enterprise question is which applications can live outside the
host's system package set, and which need integration into the derived
image. Demonstrating those paths with representative workloads would add
more evidence than simply listing container tools.

### Credibility depends on evidence after the build

TunaOS's [green criteria](../GREEN-CRITERIA.md) distinguish building an image
from proving its desktop, installation, and lifecycle behavior. Missing,
skipped, or stale results do not constitute affirmative evidence. That
provides a reporting framework: inspect a selected artifact's tests instead
of applying a single readiness label to the entire project. The
[artifact-verification guide](../VERIFY-ARTIFACTS.md) adds another axis,
checking digests and workflow identities for signatures and attestations.
Provenance and runtime correctness answer different questions; neither
establishes the other.

The remaining enterprise story needs independent evaluation, not invented
adoption figures. A useful pilot would record the tested machines, image
digests, installation results, application compatibility, update and
rollback behavior, and unresolved failures. Any published organization name
needs consent under the [adopter process](../../ADOPTERS.md). That would let
readers assess the actual operational trade-off: desktop integration moves
into an artifact pipeline, while persistent data, hardware behavior, and
support ownership remain responsibilities to resolve. Those boundaries are
the substance of an Enterprise Linux desktop feature, and the questions a
human reporter should pursue.

For an independent evaluation, one useful comparison would keep the hardware
and workload fixed while changing only the deployment approach. Record the
time needed to produce a candidate image, install it, apply a routine update,
and recover from a deliberately unsuitable candidate in a disposable lab.
Compare that with the team's existing package-managed workflow. Include the
time spent maintaining the build pipeline, not just the time spent at the
workstation. The result could reveal where centralizing integration helps,
and where it merely transfers work to another team. Those are proposed
measurements, not results reported by this repository. Publishing the method
and unsuccessful cases alongside any gains would make a future case study
useful to other administrators, even if its conclusions apply only to one
desktop, one hardware family, and a limited set of applications.

<!-- ste-enable -->

## Outreach handoff and timing

- [ ] A human maintainer selects an author and confirms their availability.
- [ ] The author rechecks LWN's guide, researches the topic, and writes
  an original pitch. Do not attach this internal draft.
- [ ] Before contact, run the [claim checklist](../CONTENT-CLAIM-CHECKLIST.md).
  Record digests for candidate images, architectures, current run URLs, and
  hardware limits. This document reports source design, not a fresh boot test.
- [ ] Send the human-written pitch through the current author channel. Record
  sender role, date, and a non-private receipt in issue #3113. Keep personal
  contact details and correspondence out of public GitHub comments.
- [ ] Ask LWN about scope and timing before work on the article. The
  issue's Q4 2026 window is a preference, not a reserved feature slot. From
  2026-10-23, eight weeks ends on 2026-12-18. A slot in late November or
  early December needs agreement from LWN on a shorter lead time.
- [ ] Follow up once after about two weeks unless LWN requests another
  cadence. Record the response; contact alone does not establish coverage.
- [ ] After acceptance, agree byline, terms, length, and deadline with LWN.
  The human author owns the final article and its source checks.

## Measure outcomes

Use issue #3113 for dated receipts and links, and the rules in
[the outreach ledger](../ADOPTION-OUTREACH-STATUS.md) for public evidence.
These are targets from the issue, not recorded results:

| Outcome | Target | Evidence to record |
|---|---|---|
| Published feature | One | LWN article URL and publication date |
| Reader discussions | At least three | Distinct GitHub Discussion URLs whose authors identify LWN as their source, within 30 days of publication |
| DistroWatch follow-up | At least two listing mentions | Distinct public mention URLs; coordinate with [the submission effort](../DISTROWATCH-SUBMISSION.md) and record attribution only when stated |
| Redfin inquiry | At least one IT buyer inquiry | Date and consent-safe summary; keep private contact information private and distinguish an inquiry from adoption |

Do not repeat the issue's star count, archive-search claim, or production
adopter count as current facts. Verify any such claim from its source before
the human author uses it. Publication, referral activity, and adoption remain
separate measures. Keep #3113 open until the owner records outreach and
outcomes or a maintainer changes its scope.
