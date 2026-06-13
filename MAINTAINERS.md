# Maintainers

## Active Maintainer

- **James Reilly** ([@hanthor](https://github.com/hanthor)) — Project lead, all areas

## Maintainer Playbook

### Release Process

1. Builds run daily at 1am UTC (`build-*.yml` workflows)
2. Monday boot report (`weekly-boot-report.yml`) validates all variants×desktops
3. ISOs are auto-published via `live-iso-bootc.yml`
4. GitHub Releases created via `generate-release.yml`

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

1. Add to `.github/build-config.yml` flavors array for the variant
2. Create `build_scripts/<desktop>.sh` with `base` and `extra` cases
3. Call it from Containerfile or via `run_buildscripts_for()` in `lib.sh`

### Multi-agent development (Hive)

Hive agents (guide, architect, sec-check, quality, ci-maintainer) run against this repo. They create PRs with labels matching their agent name. Review and merge like any other PR.

## Backup Access

- **GitHub org**: `tuna-os` owned by [@hanthor](https://github.com/hanthor)
- **GHCR**: `ghcr.io/tuna-os` — all images published here
- **Domain**: `tunaos.org`
- **R2 storage**: Cloudflare R2 bucket for ISOs

## Bus Factor Mitigations

- CI is fully automated — no manual release steps
- All configuration is in YAML files (not tribal knowledge)
- Image versions pinned in `image-versions.yaml` with Renovate
- Build scripts are self-documenting with comments
- Hive agents provide automated PR creation for routine tasks
