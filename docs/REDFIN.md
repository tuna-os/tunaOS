# Redfin: Enterprise Linux positioning and alpha tracking

Redfin is the RHEL 10 local-build path in TunaOS. It gives entitled evaluators
an Enterprise Linux desktop image-factory workflow to investigate; it does not
establish Red Hat endorsement, a support agreement, or enterprise readiness.
Tracking: [#1123](https://github.com/tuna-os/tunaos/issues/1123) and
[#3002](https://github.com/tuna-os/tunaos/issues/3002).

## Build and variant scope

Follow [rhel-setup.md](rhel-setup.md) for registry authentication, local builds,
local ISO generation, Corral evaluation, and the local image-factory timer.
The documented desktop choices are GNOME, KDE, Niri, COSMIC and XFCE, with a
base target and hardware overlays. A documented build target alone is not a
verified desktop: evaluate each desktop and architecture separately.

The base resolver's explicit off-matrix Redfin case in
[`scripts/get-base-image.sh`](../scripts/get-base-image.sh) selects
`registry.redhat.io/rhel10/rhel-bootc:latest`. This is a RHEL bootc path;
substituting UBI would require separate implementation and validation.
Redfin is intentionally absent from the public matrix in
[`tunaos.toml`](../tunaos.toml). `.github/build-config.yml` is generated
compatibility output, not the place to add a local-only support row.

Keep the existing [local-build distribution policy](rhel-setup.md): do not
add public CI builds, publish Redfin images or ISOs, or request RHSM credentials
on shared runners as part of this outreach work. Any change to distribution or
subscription handling needs a separate owner review of the applicable terms.

## Q4 alpha acceptance record

The [Q4 roadmap](../ROADMAP.md) tracks a local-build alpha. Attach evidence to
#1123 rather than maintaining a hand-copied table of live readiness here.
For each evaluated desktop and architecture, record:

- Source commit, base digest, build command, platform and successful build log.
- Local ISO creation command, checksum and boot/install verification log;
  retain artifacts privately under the evaluator's applicable terms.
- Installed desktop session, networking and reboot results, plus an update
  and rollback exercise with the before/after image identities.
- Local image-factory timer result and a sanitized failure log if rebuilding
  or updating fails. Never attach auth.json, subscription data or credentials.
- Known limitations and the precise tested environment. Apply
  [GREEN-CRITERIA.md](GREEN-CRITERIA.md) before making readiness claims.

Local ISO verification is the milestone deliverable. A public alpha ISO is
outside this scope under the existing policy; there is no downloadable Redfin
release promised by this plan.

## Partnership sequence

Use cases to evaluate are a locally rebuilt workstation, repeatable desktop
image management, and a Corral VM evaluation following the existing setup
guide. Describe these as evaluation goals until the acceptance record supports
the specific claim. A Corral example alone does not establish a supported
KubeVirt enterprise workstation product.

| Audience | Proposed conversation | Evidence before an announcement |
| --- | --- | --- |
| AlmaLinux community | Share EL10 desktop build lessons; distinguish Yellowfin (Kitten) and Albacore (AlmaLinux) from RHEL-based Redfin | Verify the relevant AlmaLinux cell through the generated matrix and link the existing [community introduction](ALMALINUX-COMMUNITY-INTRO.md) |
| Red Hat ecosystem contacts | Ask for technical feedback on the entitled local-build workflow and subscription boundaries | Named Redfin alpha evidence record; owner review of distribution and support wording |
| Corral contributors | Request feedback on reproducible local VM evaluation | Sanitized VM creation, boot and update results for the named image |
| Enterprise infrastructure press | Propose a case study about measured desktop image management | Reproducible results, evaluator consent and limitations; use the [press pitch guidance](TECH-PRESS-PITCHES.md) |

An authorized project representative owns external contact and publication.
This document prepares that work; it records no partnership, outreach delivery,
external endorsement or publication commitment. After local alpha evidence is
available, attach the proposed message and evidence links to #3002 for owner
review before any external announcement. Do not announce Redfin as an AlmaLinux
image or claim a public download exists.
