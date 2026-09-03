# TunaOS documentation

📖 **User documentation lives at [tunaos.org](https://tunaos.org)** — a Docusaurus
site in the [`tuna-os/docs`](https://github.com/tuna-os/docs) repo. Installation
guides, variant overviews, system requirements, and companion-project docs all
live there. That is the canonical, user-facing home; this folder is **not**
mirrored to it.

The old in-repo mdBook (`docs/book/`) was removed once tunaos.org went live — it
duplicated the same user-facing content. (Its GitHub Pages deploy workflow was
already retired separately.)

## What's in this folder

These are **developer/maintainer references** that aren't part of the
user-facing site:

| Doc | What it covers |
|-----|----------------|
| [AGENT_GUIDE.md](AGENT_GUIDE.md) | Repo architecture: variants, flavors, build stages, key files |
| [HUMMINGBIRD.md](HUMMINGBIRD.md) | Fedora Hummingbird variant architecture, rolling release model, and package snapshot state |
| [architecture/reusable-build-image-decomposition.md](architecture/reusable-build-image-decomposition.md) | Architectural plan for decomposing reusable-build-image.yml monolith |
| [INSTALLER_SCREENSHOTS.md](INSTALLER_SCREENSHOTS.md) | Visual step-by-step walkthrough of the GUI installer for GNOME and Cosmic |
| [build-pipeline.md](build-pipeline.md) | CI/CD workflow and build-stage overview |
| [ci-troubleshooting.md](ci-troubleshooting.md) | Diagnosing and fixing common CI failures |
| [CI-WORKFLOW-PUBLISHING.md](CI-WORKFLOW-PUBLISHING.md) | Recovering GitHub App permission for workflow-file fixes (#1557) |
| [mkosi-investigation.md](mkosi-investigation.md) | Notes from the mkosi-based image build investigation |
| [PIPELINE.md](PIPELINE.md) | Build pipeline reference: stages, workflows, artifact flow |
| [EDUCATION-PITCH.md](EDUCATION-PITCH.md) | Education & teaching lab adoption brief for CS departments (#1600) |
| [CONTENT-CLAIM-CHECKLIST.md](CONTENT-CLAIM-CHECKLIST.md) | What a guide or campaign post must verify before it claims it — image refs, shipped tooling, hardware, readiness (#2289) |
| [BRANCH-PROTECTION.md](BRANCH-PROTECTION.md) | Current-state audit + proposal for main-branch protection & required CI (#1167) |
| [BRANCH-POLICY.md](BRANCH-POLICY.md) | Branch naming conventions, RFC disposition, and 30-day staleness rules |
| [CI_SPEC.md](CI_SPEC.md) | CI behavior specification |
| [JUSTFILE-MODULARIZATION.md](JUSTFILE-MODULARIZATION.md) | Justfile module standard and cross-repo migration checklist (#508) |
| [R2-COST-VISIBILITY.md](R2-COST-VISIBILITY.md) | Cloudflare R2 cost, retention, and ownership runbook (#1618) |
| [TESTING.md](TESTING.md) | ISO end-to-end test harness |
| [MATRIX-STATUS.md](MATRIX-STATUS.md) | Which variant×desktop combinations are actually verified — and which have never been tested |
| [EDITION-VARIANT-PAGE-CHECKLIST.md](EDITION-VARIANT-PAGE-CHECKLIST.md) | Every published edition from the tunaos-packages#133 audit vs its tunaos.org variant page & download link (#1308) |
| [ASAHI-HARDWARE-TIERS.md](ASAHI-HARDWARE-TIERS.md) | Real Apple Silicon hardware CI: rented Scaleway rental + personal-machine tiers, and the m1n1/boot.bin safety rule both must follow |
| [ASAHI-EL10-OBS-PROJECT.md](ASAHI-EL10-OBS-PROJECT.md) | Open Build Service project for EL10 Asahi packages (#777) |
| [BRANCH-HYGIENE.md](BRANCH-HYGIENE.md) | Operational checklist for finding and cleaning stale branches |
| [rhel-setup.md](rhel-setup.md) | RHEL 10 (Redfin) local-build instructions |
| [ROLL_YOUR_OWN.md](ROLL_YOUR_OWN.md) | Guide to building custom TunaOS variants for your own use |
| [SECURE-BOOT.md](SECURE-BOOT.md) | Secure Boot support by variant |
| [LUKS-TPM.md](LUKS-TPM.md) | Disk encryption & TPM2 auto-unlock |
| [VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md) | Verify TunaOS artifacts — signatures and SBOM attestations |
| [INSTALLER-FRONTENDS.md](INSTALLER-FRONTENDS.md) | Installer frontends (cosmic/kde/niri/xfce): verification & parity |
| [SCREENSHOTS.md](SCREENSHOTS.md) | TunaOS screenshot gallery |
| [IMAGE-FACTORY-GATE.md](IMAGE-FACTORY-GATE.md) | Image factory completion gate & definition of done (#1283) |
| [IMAGE-FACTORY-LIFECYCLE-GATE.md](IMAGE-FACTORY-LIFECYCLE-GATE.md) | Image factory lifecycle coverage & required gate (#1278) |
| [../VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md) | Variant/flavor admission, capacity, promotion, and deprecation policy (#1196, #1175) |
| [CFP-FOSDEM-2027.md](CFP-FOSDEM-2027.md) | FOSDEM 2027 CFP draft |
| [CFP-DEMO-SCRIPT.md](CFP-DEMO-SCRIPT.md) | Shot list for the 3–5 min CFP demo video, shared by both 2027 submissions |
| [CFP-SCALE-24X.md](CFP-SCALE-24X.md) | SCaLE 24x CFP draft, adapted from the FOSDEM abstract |
| [CFP-SEAGL-2026.md](CFP-SEAGL-2026.md) | SeaGL 2026 CFP proposal and submission checklist |
| [PRESSKIT.md](PRESSKIT.md) | Project facts, descriptions, screenshots, and media contacts |
| [DISTROWATCH-SUBMISSION.md](DISTROWATCH-SUBMISSION.md) | DistroWatch project submission draft |
| [GNOME-51-RELEASE-CONTENT.md](GNOME-51-RELEASE-CONTENT.md) | GNOME 51.0 release-week content and packaging hook (#1334) |
| [CNCF-BOOTC-SHOWCASE.md](CNCF-BOOTC-SHOWCASE.md) | CNCF bootc ecosystem showcase and case study draft (#1340) |
| [CHAINGUARD-COLLABORATION.md](CHAINGUARD-COLLABORATION.md) | Chainguard supply-chain security collaboration angle brief (#1339) |
| [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md) | Evidence ledger for DistroWatch, CNCF, and adopter outreach |
| [PANTHEON-FEEDBACK-LOOP.md](PANTHEON-FEEDBACK-LOOP.md) | How Gurnard's Pantheon packaging findings get back to elementary (#1469) |
| [SNAPDRAGON-X13S-OUTREACH.md](SNAPDRAGON-X13S-OUTREACH.md) | Draft plan for reaching the Snapdragon X13s Linux community |
| [TECH-PRESS-PITCHES.md](TECH-PRESS-PITCHES.md) | Pitch pack for Linux technology press, with guardrails on what we may claim |
| [ADOPTION-CALL.md](ADOPTION-CALL.md) | Public call for adopters and evaluation feedback |
| [ALMALINUX-COMMUNITY-INTRO.md](ALMALINUX-COMMUNITY-INTRO.md) | Introduction draft for the AlmaLinux community |
| [FEDIVERSE-PLAYBOOK.md](FEDIVERSE-PLAYBOOK.md) | Release-announcement playbook for Fediverse communities |
| [REDDIT-LEMMY-PLAYBOOK.md](REDDIT-LEMMY-PLAYBOOK.md) | Release-announcement playbook for Reddit / Lemmy |
| [XFCE-OLD-LAPTOP-PITCH.md](XFCE-OLD-LAPTOP-PITCH.md) | Old-laptop and e-waste repurposing pitch for the XFCE Linux companion project (#1682) |
| [YOUTUBER-REVIEW-KIT.md](YOUTUBER-REVIEW-KIT.md) | Linux YouTuber review kit — verified working downloads, ARM story (#1535) |
| [FEDORA-MAGAZINE-PITCH.md](FEDORA-MAGAZINE-PITCH.md) | Guest-post pitch draft for Fedora Magazine |
| [FEDORA45-TESTING-CALL.md](FEDORA45-TESTING-CALL.md) | Fedora 45 Beta testing call guide for Bonito variant (#1609) |
| [GNOME51-BETA-TESTING-CALL.md](GNOME51-BETA-TESTING-CALL.md) | GNOME 51 beta testing call for the EL10 backport tier (#1717) |
| [ELEMENTARY-CROSSPOST.md](ELEMENTARY-CROSSPOST.md) | Gurnard cross-post draft for the elementary OS community |
| [MARLIN-CACHYOS-POST.md](MARLIN-CACHYOS-POST.md) | Marlin announcement draft for the CachyOS community |
| [SHOWHN-LAUNCH.md](SHOWHN-LAUNCH.md) | Show HN launch draft and posting checklist |
| [MATRIX-WEEKLY-DIGEST.md](MATRIX-WEEKLY-DIGEST.md) | Matrix weekly-digest post template |
| [HACKTOBERFEST-2026.md](HACKTOBERFEST-2026.md) | Hacktoberfest 2026 contributor runbook |
| [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) | Historical record of the May 2026 sprint + remaining roadmap items |
| [Q4-2026-PROMOTION-CALENDAR.md](Q4-2026-PROMOTION-CALENDAR.md) | Fedora 45, Hacktoberfest, All Things Open, and KubeCon NA promotion plan |
| [agents/](agents/) | Hive agent guides (issue-tracker, triage-labels, domain) |
| [adr/](adr/README.md) | Architecture Decision Records |
| [architecture/shared-just-recipes.md](architecture/shared-just-recipes.md) | Delivery contract for shared Just modules across tuna-os repositories (#1977, #508) |
| [USER-GUIDE.md](USER-GUIDE.md) | Choosing an image, installing, updating, rolling back, apps, encryption |
| [DEVELOPER-GUIDE.md](DEVELOPER-GUIDE.md) | The whole pipeline and its plumbing, with diagrams |
| [INSTALL.md](INSTALL.md) | Building media locally, artifact verification, registry auth, pull troubleshooting |
| [HARDWARE.md](HARDWARE.md) | System requirements and ARM laptop support status |
| [IMAGE-TAGS.md](IMAGE-TAGS.md) | Image tag reference: desktop and hardware suffixes |
| [TACKLEBOX-CONTRACT.md](TACKLEBOX-CONTRACT.md) | Contract between TunaOS image builds and Tacklebox media tooling |
| [GREEN-CRITERIA.md](GREEN-CRITERIA.md) | What "green" means for a cell — the criteria behind the composite score |
| [GREEN-MASTER-PLAN.md](GREEN-MASTER-PLAN.md) | The workstreams driving the matrix to green |
| [Q3_CHECKPOINT-2026-08-22.md](Q3_CHECKPOINT-2026-08-22.md) | In-repo copy of the Q3 "Expand Coverage" decision sheet |

## Policies & planning (repo root)

These live at the repository root rather than in this folder:

- [ROADMAP.md](../ROADMAP.md) — project direction and feature status
- [VISION.md](../VISION.md) — project philosophy
- [GOAL.md](../GOAL.md) — current objective
- [CONTRIBUTING.md](../CONTRIBUTING.md) — how to set up, build, and contribute
- [VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md) — Stable/Beta/Alpha admission gates and deprecation rules
- [RFC-PROCESS.md](../RFC-PROCESS.md) — how RFCs are proposed, reviewed, and decided
- [PACKAGE-SOURCING.md](../PACKAGE-SOURCING.md) — package origin rules, Tideforge-first, and allowlist (#1319)
- [TRIAGE-POLICY.md](../TRIAGE-POLICY.md) — triage states and SLAs (adopted, #1195)
- [FEDORA-BASE-POLICY.md](../FEDORA-BASE-POLICY.md) — adopted N+rawhide sequencing for Fedora-based variants (#1171)
- [VERSIONING.md](../VERSIONING.md) — tag scheme and stability tiers
- [MIGRATION.md](../MIGRATION.md) — switching from other distros
- [SECURITY.md](../SECURITY.md) — vulnerability reporting and supported versions
- [ADOPTERS.md](../ADOPTERS.md) / [ADOPTION-METRICS.md](../ADOPTION-METRICS.md) — who uses TunaOS and how adoption is measured
- [COMMUNITY.md](../COMMUNITY.md) — contribution ladder, metrics, communication
- [MAINTAINERS.md](../MAINTAINERS.md) — maintainer playbook and bus factor plan
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md) — community standards
- [Q3_CHECKPOINT-2026-08-22.md](../Q3_CHECKPOINT-2026-08-22.md) — decision sheet for the Q3 "Expand Coverage" milestone (#1299)

For current project priorities see [ROADMAP.md](../ROADMAP.md). For how to build
and contribute see [CONTRIBUTING.md](../CONTRIBUTING.md).
