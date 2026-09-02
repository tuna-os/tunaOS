# Maintainers

## Active Maintainer

- **James Reilly** ([@hanthor](https://github.com/hanthor)) — Project lead, all areas

## Maintainer Playbook

### Release Process

1. Builds run nightly, each variant on its own staggered cron hour (`build-*.yml` workflows)
2. Monday boot report (`weekly-boot-report.yml`) validates all variants×desktops
3. ISOs are auto-published via `live-iso-bootc.yml`
4. GitHub Releases created via `generate-changelog-release.yml`

### Emergency: If builds fail

1. Check the failing variant's build log (`gh run view <id> --log-failed`)
2. Common causes (in order of likelihood):
   - **COPR chroot missing**: RPM repos dropped a target. Fix in `build_scripts/` or pin in `image-versions.yaml`
   - **chunkah resolution**: `registry_ref` returning empty. Hardcoded fallback in `Justfile`.
   - **arm64 runner**: `taiki-e/install-action` for just. Fixed by homebrew install.
3. Trigger individual variant rebuild: `gh workflow run "Build Yellowfin" -f flavor=all`

### Adding a new variant

1. Add entry to `.github/build-config.yml` `variants` array
2. Add base image to `image-versions.yaml`
3. Run `just generate-workflows` and commit generated files
4. OS detection in `build_scripts/lib.sh` may need a new `IS_*` flag

### Adding a new desktop

1. Write a manifest at `manifests/desktops/<desktop>.yaml` (packages per base OS, display manager, versionlock)
2. Add a stage to the Containerfile (copy from an existing desktop's pattern)
3. Add the flavor to `.github/build-config.yml` — `install-desktop.sh` handles the rest (see CONTRIBUTING.md)

### Contributor Onboarding & Issue Triage

1. **Weekly contributor triage**: The maintainer holds a weekly 30-minute triage slot to review open PRs, respond to external contributors, and label new bounded tasks as `good first issue` per [CONTRIBUTING.md](CONTRIBUTING.md).
2. **Issue triage SLAs**: Issue lifecycle, verification-before-closure discipline, and tiered response SLAs (P0: 48h, P1: 7d, P2: 30d) are codified in [TRIAGE-POLICY.md](TRIAGE-POLICY.md).
3. **Architectural Governance**: Decisions are tracked in Architecture Decision Records under [docs/adr/](docs/adr/README.md) following [RFC-PROCESS.md](RFC-PROCESS.md).

### Multi-agent development (Hive)

Hive agents (guide, architect, sec-check, quality, ci-maintainer) run against this repo. They create PRs with labels matching their agent name. Review and merge like any other PR.

## Backup Access

- **GitHub org**: `tuna-os` owned by [@hanthor](https://github.com/hanthor)
- **GHCR**: `ghcr.io/tuna-os` — all images published here
- **Domain**: `tunaos.org`
- **R2 storage**: Cloudflare R2 bucket for ISOs

## Bus Factor Mitigations

- **Automated CI/CD**: CI is fully automated with no manual release steps; releases and boot reports run on schedule.
- **Declarative Configuration**: All configuration is stored in YAML files (`build-config.yml`, `image-versions.yaml`, manifests) rather than tribal knowledge.
- **Dependency Management**: Image versions pinned in `image-versions.yaml` with automated Renovate updates.
- **Decision Transparency**: All architectural designs and historical rationales are documented in durable ADRs ([docs/adr/](docs/adr/README.md)).
- **Documented Triage & Governance**: Issue triage policy ([TRIAGE-POLICY.md](TRIAGE-POLICY.md)) and RFC process ([RFC-PROCESS.md](RFC-PROCESS.md)) enable reproducible decision-making.
- **Contributor Runway**: External contributor onboarding path, fork→PR loop, and Hacktoberfest runbook ([CONTRIBUTING.md](CONTRIBUTING.md), [docs/HACKTOBERFEST-2026.md](docs/HACKTOBERFEST-2026.md)) to expand contributor base.
- **Hive Agent Automation**: Hive agents provide continuous automated PR creation and verification for routine tasks.
