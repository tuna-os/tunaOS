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
| [CI_SPEC.md](CI_SPEC.md) | CI behavior specification |
| [TESTING.md](TESTING.md) | ISO end-to-end test harness |
| [rhel-setup.md](rhel-setup.md) | RHEL 10 (Redfin) local-build instructions |
| [ROLL_YOUR_OWN.md](ROLL_YOUR_OWN.md) | Guide to building custom TunaOS variants for your own use |
| [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md) | Historical record of the May 2026 sprint + remaining roadmap items |
| [agents/](agents/) | Hive agent guides (issue-tracker, triage-labels, domain) |
| [adr/](adr/) | Architecture Decision Records |

For current project priorities see [ROADMAP.md](../ROADMAP.md). For how to build
and contribute see [CONTRIBUTING.md](../CONTRIBUTING.md).
