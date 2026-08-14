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
| [INSTALLER_SCREENSHOTS.md](INSTALLER_SCREENSHOTS.md) | Visual step-by-step walkthrough of the GUI installer for GNOME and Cosmic |
| [build-pipeline.md](build-pipeline.md) | CI/CD workflow and build-stage overview |
| [ci-troubleshooting.md](ci-troubleshooting.md) | Diagnosing and fixing common CI failures |
| [mkosi-investigation.md](mkosi-investigation.md) | Notes from the mkosi-based image build investigation |
| [PIPELINE.md](PIPELINE.md) | Build pipeline reference: stages, workflows, artifact flow |
| [EDUCATION-PITCH.md](EDUCATION-PITCH.md) | Education & teaching lab adoption brief for CS departments (#1600) |
| [BRANCH-PROTECTION.md](BRANCH-PROTECTION.md) | Current-state audit + proposal for main-branch protection & required CI (#1167) |
| [BRANCH-POLICY.md](BRANCH-POLICY.md) | Branch naming conventions, RFC disposition, and 30-day staleness rules |
| [CI_SPEC.md](CI_SPEC.md) | CI behavior specification |
| [TESTING.md](TESTING.md) | ISO end-to-end test harness |
| [MATRIX-STATUS.md](MATRIX-STATUS.md) | Which variant×desktop combinations are actually verified — and which have never been tested |
| [ASAHI-HARDWARE-TIERS.md](ASAHI-HARDWARE-TIERS.md) | Real Apple Silicon hardware CI: rented Scaleway rental + personal-machine tiers, and the m1n1/boot.bin safety rule both must follow |
| [ASAHI-EL10-OBS-PROJECT.md](ASAHI-EL10-OBS-PROJECT.md) | Open Build Service project for EL10 Asahi packages (#777) |
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
| [CFP-SCALE-21X.md](CFP-SCALE-21X.md) | SCaLE 21x CFP draft, adapted from the FOSDEM abstract |
| [DISTROWATCH-SUBMISSION.md](DISTROWATCH-SUBMISSION.md) | DistroWatch project submission draft |
| [ADOPTION-OUTREACH-STATUS.md](ADOPTION-OUTREACH-STATUS.md) | Evidence ledger for DistroWatch, CNCF, and adopter outreach |
| [REDDIT-LEMMY-PLAYBOOK.md](REDDIT-LEMMY-PLAYBOOK.md) | Release-announcement playbook for Reddit / Lemmy |
| [XFCE-OLD-LAPTOP-PITCH.md](XFCE-OLD-LAPTOP-PITCH.md) | Old-laptop and e-waste repurposing pitch for the XFCE Linux companion project (#1682) |
| [YOUTUBER-REVIEW-KIT.md](YOUTUBER-REVIEW-KIT.md) | Linux YouTuber review kit — verified working downloads, ARM story (#1535) |
| [FEDORA-MAGAZINE-PITCH.md](FEDORA-MAGAZINE-PITCH.md) | Guest-post pitch draft for Fedora Magazine |
| [ELEMENTARY-CROSSPOST.md](ELEMENTARY-CROSSPOST.md) | Gurnard cross-post draft for the elementary OS community |
| [MATRIX-WEEKLY-DIGEST.md](MATRIX-WEEKLY-DIGEST.md) | Matrix weekly-digest post template |
| [HACKTOBERFEST-2026.md](HACKTOBERFEST-2026.md) | Hacktoberfest 2026 contributor runbook |
| [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) | Historical record of the May 2026 sprint + remaining roadmap items |
| [agents/](agents/) | Hive agent guides (issue-tracker, triage-labels, domain) |
| [adr/](adr/) | Architecture Decision Records |

For current project priorities see [ROADMAP.md](../ROADMAP.md). For how to build
and contribute see [CONTRIBUTING.md](../CONTRIBUTING.md).
