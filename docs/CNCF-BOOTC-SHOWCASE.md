# bootc ecosystem showcase — TunaOS as a downstream desktop integration

> Status: **reviewed draft; external outreach not approved or sent**.
> Issue: [#2840](https://github.com/tuna-os/tunaOS/issues/2840).
> Reviewed: 2026-10-03.

## Positioning

[bootc](https://www.cncf.io/projects/bootc/) is a CNCF Sandbox project for
transactional operating-system updates through OCI container images. TunaOS is
an independent downstream consumer. It builds bootc desktop images across
several Linux distribution families.

TunaOS is not a CNCF or bootc reference implementation. CNCF and the bootc
project do not endorse TunaOS. The proposed showcase is a downstream
integration report that can give upstream maintainers feedback about desktop,
multi-distribution, and virtual-machine use cases.

Current facts must come from generated or maintained sources instead of fixed
counts in this draft:

- See the [README variant table](../README.md#variants) for the configured
  image families, registry paths, desktops, and architectures.
- [Matrix status](MATRIX-STATUS.md) reports which cells of published images
  meet the current criteria for builds, boots, desktops, and omissions.
- See [pipeline documentation](PIPELINE.md) for details about image
  publication and signatures.
- [Artifact verification](VERIFY-ARTIFACTS.md) gives the commands and identity
  constraints for signatures and SBOM attestations.

## Technical story

### Operating-system delivery through OCI

TunaOS uses Containerfiles to assemble complete images of operating systems.
It publishes the images to an OCI registry. An installed system can use `bootc upgrade`,
`bootc switch`, and `bootc rollback`. This gives the showcase a desktop example
of the image-based lifecycle that bootc provides.

### Coverage across different base systems

The image factory uses bootc-compatible bases where they exist and adds the
bootc layout to other base systems. The build matrix covers several desktop,
base-system, and architecture combinations. The generated matrix status must
remain the source for what is available and verified; a successful build alone
is not a support or readiness claim.

### Publication evidence

The pipeline for publication uses keyless Cosign to sign the OCI images that
it promotes.
It also produces SPDX SBOMs and attaches attestations in a separate job. The
attestation job is intentionally outside the path required for promotion.
Thus, outreach must not claim that every published tag always has a current
SBOM attestation. Readers
can use the repository's verification guide to check a specific artifact.

### VM testing and operation

[Corral](https://github.com/tuna-os/corral) is a separate project in the TunaOS
organization. Its bootc extension can install an OCI operating-system image
into a local QEMU or KubeVirt VM and run boot checks. This integration does not show the definition of custom resources for
Kubernetes in TunaOS. It also does not show
that a TunaOS image passed a current KubeVirt test. Any demo must identify the
tested image digest and link its result.

## Draft upstream pitch

**Subject:** Downstream report: bootc desktop images across multiple Linux
bases

> TunaOS is an independent downstream project that builds desktop operating
> systems as bootc OCI images. We propose a short integration report about the
> image lifecycle, layout problems on different Linux bases, and our
> verification gates. CNCF and bootc do not endorse TunaOS, and TunaOS is not a
> bootc reference implementation. Our current results are in the generated
> TunaOS matrix status. Would this report be useful as a bootc GitHub Discussion
> or community call topic, and which format would maintainers prefer?

The sender should add links to this repository, [matrix
status](MATRIX-STATUS.md), and [artifact verification](VERIFY-ARTIFACTS.md).
Use a specific image or metric only after the sender checks it on the send
date.

## Coordination path

1. A TunaOS maintainer approves the proposal and names the sender.
2. The sender opens a public topic in [GitHub Discussions for
   bootc](https://github.com/bootc-dev/bootc/discussions). This is the preferred
   first contact because it leaves durable evidence.
3. If useful, the sender links that topic in the official
   [`#bootc-dev` channel in CNCF
   Slack](https://cloud-native.slack.com/archives/C08SKSQKG1L). The sender can
   also bring it to the [bootc community call](https://github.com/bootc-dev/bootc/tree/main/meetings).
4. Pitch the CNCF blog only if bootc maintainers recommend that route.
5. The sender records the date, public URL, response, and next action in
   [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md). A response does
   not make bootc or CNCF a TunaOS adopter.

## Maintainer decision

Choose one outcome in [#2840](https://github.com/tuna-os/tunaOS/issues/2840):

- **Approve:** confirm the text, sender, and first channel.
- **Revise:** name the claims or audience that need changes.
- **Defer or decline:** record the reason; do not send the pitch.

This file remains draft material until a maintainer records that decision. No
contributor or automation should represent the project in an external channel
from this draft.
