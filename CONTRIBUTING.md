# Contributing to TunaOS

Thank you for contributing to TunaOS — an image factory that produces bootc-based desktop OS images.

## Quick Start

```bash
brew install just podman shellcheck shfmt yq
git clone https://github.com/tuna-os/tunaOS.git && cd tunaOS
just fix && just check
```

## Contributor onboarding

New here? Start with a **[good first issue](https://github.com/tuna-os/tunaOS/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)** or **[help wanted](https://github.com/tuna-os/tunaOS/issues?q=is%3Aissue+is%3Aopen+label%3A%22help+wanted%22)** issue — a curated, maintainer-sized task covering documentation parity, a small script fix, or test coverage. Before starting, leave a comment saying you are taking the issue so the work is not duplicated.

The current starter runway includes:

- [#1496](https://github.com/tuna-os/tunaOS/issues/1496) — link orphaned docs in the README Documentation section
- [#1308](https://github.com/tuna-os/tunaOS/issues/1308) — seed and maintain the good-first-issue backlog
- [#1351](https://github.com/tuna-os/tunaOS/issues/1351) — add a Gurnard/Pantheon desktop guide

This list is a snapshot, not a second issue tracker. Use the label queries
above for the current queue; weekly triage must remove completed links and add
new bounded tasks rather than letting this list go stale.

The repository checks this queue weekly. To verify it locally (requires the
GitHub CLI and read access), run:

```bash
GITHUB_REPOSITORY=tuna-os/tunaos ./scripts/check-gfi-pool.sh
```

The check is a read-only alarm, not an auto-labeler. If either onboarding
label falls below three open issues, add or refresh a bounded task during
weekly triage before changing the contributor-facing links.

These tasks are intentionally independent of the image build pipeline. If one is claimed or closed, use the same issue search to choose another bounded task.

### Fork → PR loop

1. Fork `tuna-os/tunaos` on GitHub and clone your fork.
2. Create a focused branch: `git switch -c docs/short-description`.
3. Make the smallest change that satisfies the issue's acceptance criteria.
4. Run the checks listed below, then commit and push the branch to your fork.
5. Open a PR against `tuna-os/tunaos:main`, link the issue with `Fixes #NNN`, and include the checks you ran.
6. Keep the branch available while review is in progress; follow-up fixes can be pushed to the same PR.

You do not need write access to the upstream repository. GitHub's fork-based PR flow is the normal path for external contributors. If CI fails, include the failing job and a short reproduction in the PR rather than silently retrying it.

For the Hacktoberfest 2026 backlog, see the [contributor plan](docs/HACKTOBERFEST-2026.md) for current candidates, acceptance standards, and event dates.

Ways to contribute without touching the build pipeline:

- **Docs & guides** — the [docs site](https://github.com/tuna-os/docs) has its own `good first issue` backlog and takes content PRs for guides, FAQs, and variant pages
- **Community** — help triage [open issues](https://github.com/tuna-os/tunaOS/issues), answer questions in [Matrix](https://matrix.to/#/%23tunaos:reilly.asia), or improve the [adopters list](ADOPTERS.md) if your org uses TunaOS
- **Labels** — issues tagged `help wanted` are explicitly open for external contribution

When you pick an issue, say so in a comment (prevents double work) and ask in Matrix if you get stuck — someone is usually around.

### Weekly contributor triage

The maintainer reserves one 30-minute slot each week for contributor work. During that slot:

1. Review new issues and label at least one bounded task `good first issue` when its scope and acceptance criteria are clear.
2. Check claimed starter issues for unanswered questions, stale claims, or duplicate work.
3. Review open contributor PRs, respond to blockers, and keep CI failures distinguishable from code-review requests.
4. Refresh the starter links above when tasks are completed, superseded, or moved to another repository.

This is a lightweight queue-management commitment, not a promise of immediate review. Contributors should expect an acknowledgement or status update within the next weekly triage slot.

## Pre-Commit (mandatory)

```bash
just fix     # format shell scripts and Justfile
just check   # shellcheck, yamllint, actionlint
```

## Building Images

```bash
just build yellowfin gnome           # single flavor (~25 min warm cache)
just build yellowfin kde linux/amd64 # specific platform
just build yellowfin all             # all flavors
```

## Adding a Desktop Environment

No shell scripting required. Write a YAML manifest:

```bash
# 1. Create the manifest
cat > manifests/desktops/budgie.yaml <<EOF
display_manager: gdm
packages:
  fedora:
    packages: [budgie-desktop, budgie-extras, gdm]
  el10:
    packages: [budgie-desktop, gdm]
    optional: [budgie-extras]
  apt:
    - budgie-desktop
    - gdm3
versionlock: [glib2]
EOF

# 2. Add stage to Containerfile (copy from existing DE pattern)
# 3. Add flavor to .github/build-config.yml
# 4. That's it — install-desktop.sh handles the rest
```

## Architecture

The build system is **manifest-driven**:

```
manifests/desktops/*.yaml  →  install-desktop.sh  →  image
```

Key scripts:
- `scripts/resolve-flavor.sh` — routes flavor to Containerfile + build params
- `scripts/resolve-image.sh` — resolves image refs from 3 config sources
- `scripts/build-image-inner.sh` — the build engine (env-var driven)
- `build_scripts/desktop/install-desktop.sh` — generic DE installer (reads YAML)
- `build_scripts/lib.sh` — shared helpers (OS detection, pkg abstraction)

Full architecture: [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md)

## Pull Request Process

1. Fork and create a feature branch
2. Run `just fix && just check`
3. Open PR against `main`
4. CI validates (lint, unit tests, image build on PR)
5. Merge queue handles the rest (automerge for passing PRs)

## Testing

```bash
just test          # all tests (bats + pytest)
just test-bats     # shell script tests
just verify-disk image.qcow2  # QEMU boot verification
```

## Documentation

- [Vision](VISION.md) — project philosophy
- [Agent Guide](docs/AGENT_GUIDE.md) — architecture reference
- [Pipeline](docs/PIPELINE.md) — CI/CD details
- [Testing](docs/TESTING.md) — test harness

## Community

- [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [Matrix: #tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)

## License

[Apache 2.0](LICENSE)
