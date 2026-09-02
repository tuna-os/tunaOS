# Contributing to TunaOS

Thank you for contributing to TunaOS — an image factory that produces bootc-based desktop OS images.

## Quick Start

```bash
brew install just podman shellcheck shfmt yq
git clone https://github.com/tuna-os/tunaOS.git && cd tunaOS
just fix && just check
```

## Contributor onboarding

New here? Start with an **[org-wide good first issue](https://github.com/issues?q=org%3Atuna-os+is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)** — a curated, maintainer-sized task covering documentation parity, a small script fix, or test coverage. Before starting, leave a comment saying you are taking the issue so the work is not duplicated. The current pool and census are tracked in the [Hacktoberfest 2026 contributor plan](docs/HACKTOBERFEST-2026.md); new bounded tasks are labelled `good first issue` during the [weekly contributor triage](#weekly-contributor-triage) below.

The current starter runway lives in the **[org-wide good first issue](https://github.com/issues?q=org%3Atuna-os+is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)** pool, mostly in `tuna-os/docs` (docs-parity and guide tasks — e.g. desktop quick-starts, verification guides, cheat sheets). These tasks are intentionally independent of the image build pipeline and are curated for first-time contributors. If one is claimed or closed, pick another bounded task from the same search.

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

`just ci` runs what the PR gate runs — `check`, the CI contract, and every
unit suite — so a green `just ci` locally is a green PR, minus the
scheduled build matrix. The rest of the contributor contract:

| Command | What it is |
|---|---|
| `just setup` | install the tools the checks and tests need, print versions |
| `just test-fast` | the Python suites only, stop at the first failure |
| `just test` | bats + pytest, same as CI |
| `just test-contract` | every green gate exists, is reachable, meets its freshness SLA |
| `just test-random [seed]` | the suites in a seeded random order (the nightly lane) |
| `just test-cell <variant> <flavor>` | the desktop contract against one published image, as the nightly sweep runs it |
| `just test-e2e <iso>` | boot an ISO under QEMU and assert the live environment reaches readiness |

## Every incident becomes a regression test

A bug that let an unusable or wrongly-promoted image ship is not fixed until a
test proves the old failure mode cannot silently recur. Put that test in
[`tests/regressions/`](tests/regressions/README.md), named after the issue
(`test_issue_<number>_<what_must_not_recur>.py`), with a docstring that cites
the issue and the run or log that measured the failure. The seed example is
#858 (marlin:kde shipped with no Wayland session): the regression test runs
the desktop contract's own check against a filesystem with no session file
and holds that it fails. `tests/test_regression_convention.py` enforces the
naming.

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
