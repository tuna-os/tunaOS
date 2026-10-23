# Contributing to TunaOS

Thank you for your contribution to TunaOS — an image factory that builds bootc-based images for desktop operating systems.

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

**[Donate time with your AI CLI](https://hub.tunaos.org/#contribute).**

Your machine runs one task at a time using your signed-in AI coding CLI.
The relay alternates between eligible **School** (OS) and **Reef** (apps)
hives after each task. If one hive has no work, the other can continue.

The guide covers prerequisites, verified `just` setup, credentials, provider
costs, and how to stop with Ctrl+C. Your subscription quota or API charges apply.
Never post account credentials or API keys in issues or pull requests.

## Quick Start

```bash
brew install just podman shellcheck shfmt yq
git clone https://github.com/tuna-os/tunaOS.git && cd tunaOS
just fix && just check
```

## Contributor onboarding

New here? Start with an **[org-wide good first issue](https://github.com/issues?q=org%3Atuna-os+is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)** — a curated, maintainer-sized task for documentation parity, a small script fix, or test coverage. Before you start, leave a comment to say you take the issue, so that nobody duplicates the work. The [Hacktoberfest 2026 contributor plan](docs/HACKTOBERFEST-2026.md) tracks the current pool and census. The [weekly contributor triage](#weekly-contributor-triage) below labels new bounded tasks `good first issue`.

The current starter runway lives in the **[org-wide good first issue](https://github.com/issues?q=org%3Atuna-os+is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22)** pool. Most of it is in `tuna-os/docs` (docs-parity and guide tasks — e.g. desktop quick-starts, verification guides, cheat sheets). These tasks are intentionally independent of the image build pipeline, and maintainers curate them for first-time contributors. If another contributor claims one, or if it closes, pick another bounded task from the same search.

For the repository map, voluntary mentorship ladder, requests for a mentor, office
hours, and review escalation, see [the ecosystem guide](CONTRIBUTING-ADVANCED.md).

### Fork → PR loop

1. Fork `tuna-os/tunaos` on GitHub and clone your fork.
2. Create a focused branch: `git switch -c docs/short-description`.
3. Make the smallest change that satisfies the issue's acceptance criteria.
4. Run the checks listed below, then commit and push the branch to your fork.
5. Open a PR against `tuna-os/tunaos:main`, link the issue with `Fixes #NNN`, and include the checks you ran.
6. Keep the branch available while review is in progress; you can push follow-up fixes to the same PR.

You do not need write access to the upstream repository. GitHub's fork-based PR flow is the normal path for external contributors. If CI fails, include the job that failed and a short reproduction in the PR instead of a silent retry. If GitHub rejects a push because the GitHub App does not have `workflows` permission, follow the [runbook for workflow publication](docs/CI-WORKFLOW-PUBLISHING.md). Workflow YAML in the repository cannot grant that App-level permission.

For the Hacktoberfest 2026 backlog, see the [contributor plan](docs/HACKTOBERFEST-2026.md) for current candidates, acceptance standards, and event dates.

Work through the [pre-write claim checklist](docs/CONTENT-CLAIM-CHECKLIST.md) before you write a guide or a campaign post. Do the same for any text that names an image reference, a shipped tool, hardware support, or readiness. Maintainers closed a run of five guide PRs for the same two defects. The first is an image reference the project does not publish; the second is toolchains the images do not ship. The checklist is those defects written down.

Ways to contribute without changes to the build pipeline:

- **Compute through Hive** — [donate time with your AI CLI](https://hub.tunaos.org/#contribute) through the hub's existing round-robin setup; no code needed
- **Docs & guides** — the [docs site](https://github.com/tuna-os/docs) has its own `good first issue` backlog and takes content PRs for guides, FAQs, and variant pages. Run the [claim checklist](docs/CONTENT-CLAIM-CHECKLIST.md) before you write
- **Community** — help triage [open issues](https://github.com/tuna-os/tunaOS/issues), answer questions in [Matrix](https://matrix.to/#/%23tunaos:reilly.asia), or improve the [adopters list](ADOPTERS.md) if your org uses TunaOS
- **Labels** — anyone outside the project can take issues tagged `help wanted`

When you pick an issue, say so in a comment (prevents double work) and ask in Matrix if you get stuck — someone is usually around.

### Weekly contributor triage

The maintainer keeps one 30-minute slot each week for contributor work. During that slot:

1. Review new issues and label at least one bounded task `good first issue` when its scope and acceptance criteria are clear.
2. Check the claimed starter issues for unanswered questions, stale claims, or duplicate work.
3. Review open contributor PRs, respond to blockers, and keep CI failures distinguishable from code-review requests.
4. Refresh the starter links above when tasks finish, move to another repository, or give way to newer tasks.

This is a lightweight queue-management commitment, not a promise of immediate review. Contributors should expect an acknowledgement or status update within the next weekly triage slot.

### Weekly hold-review sweep

The triage maintainer reserves 15 minutes each week for an
async hold-review sweep. Review every open PR with `hold`, oldest hold
first. For a hive-wide sweep, the coordinator repeats this procedure in each
authorized repository; this repository's policy does not grant write access
elsewhere. Record the repositories covered and any not yet reviewed.

When you apply `hold`, leave a PR comment with:

- **Reason and evidence:** the check/run that failed, dependency, or exact decision.
- **Owner:** the person or team who can unblock it.
- **Unhold trigger:** an observable condition, such as a linked CI fix that passes.
- **Next review:** a date no later than the next weekly sweep.

Use the label event in the PR timeline to measure dwell since the current
hold began. PR creation time and last update time are not hold age. Query
PRs from GitHub for current evidence:

```bash
gh pr list --repo tuna-os/tunaos --state open --label hold --limit 1000 \
  --json number,url,title,labels
```

For each PR, read its discussion, timeline, latest checks and linked blockers,
then record one disposition in a comment:

1. **Ready:** evidence meets the trigger; an authorized reviewer removes `hold`
   and requests review. Existing checks, approval requirements and merge gates
   still apply; contributors never merge their own PRs.
2. **CI or external dependency:** retain `hold`, link the blocker and its
   owner, and set the next review date. Group PRs with the same blocker. Review the
   infrastructure fix first. After it lands, recheck each PR's CI
   before you remove its hold; do not assume it unholds automatically.
3. **Decision required:** retain `hold`, add `needs-direction` (a maintainer
   creates the label if absent), and state the precise question and decision
   owner. The label requests a decision. It does not give permission to bypass it.
4. **Superseded or resolved:** verify the replacement or resolution, then an
   authorized reviewer closes with an explanation and evidence link. Age alone
   is not grounds for closure; preserve unique work and discussion.

A hold without a reason comment after 48 hours is overdue for review. Ask its
setter for the missing reason, owner and trigger, and escalate to the triage
maintainer at the next sweep. Do not auto-close it: the
[triage policy](TRIAGE-POLICY.md#3-resolution-verified-closure-not-calendar-age-closure)
calls for verification before closure.

Post a dated summary of each sweep in the issue (for this rollout,
[#2911](https://github.com/tuna-os/tunaos/issues/2911)). Include:

- Repositories covered and open holds in each.
- Oldest current hold date and number of holds over 30 days.
- Holds without reason comments and decisions that need owners.
- Links to disposition comments.
- New holds and holds released or closed since the last sweep.
- Number of PRs merged over the same seven-day window.

Compare the same repository scope week over week. Check merge counts as well
as hold counts to detect a queue that has stopped.

The rollout target from #2911 is fewer than 10 hive-wide holds within a week
of the linked CI fixes. The merge target is at least two main-branch merges
per day. Measure these goals without bypass of review or closure rules.
If the queue misses a target, name the blockers and owners in the next summary.

## Pre-Commit (mandatory)

```bash
just fix     # format shell scripts and Justfile
just check   # shellcheck, yamllint, actionlint
```

`just ci` runs what the PR gate runs — `check`, the CI contract, and every
unit suite. A green `just ci` locally is a green PR, minus the
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

## Prose checks (STE)

Run `just ste` before you submit Markdown changes. It uses the shared linter
revision from `.github/workflows/ste.yml`, with the same `.ste-budget` as CI.
The budget covers the whole repository. It only goes down; do not raise it
to pass a content PR. There is no repository-local `.stelint` path config.

Apply this policy by the purpose of the text:

| Location or purpose | STE policy |
|---|---|
| README, CONTRIBUTING, API docs, runbooks, and technical instructions | Keep STE checks. Fix new findings. |
| `docs/outreach/`, CFP abstracts, blog and campaign copy | A reasoned opt-out is allowed for audience-facing copy. |
| Design guides, including wallpaper contributions | Keep checks on setup and submission steps. An opt-out is allowed for the creative brief or art direction. |

A directory name alone does not skip checks. In a mixed page, mark only the
content that needs a different voice. Use the exact lowercase directives:

```markdown
<!-- ste-disable: conference abstract uses the event audience's terms -->
Audience-facing abstract goes here.
<!-- ste-enable -->
```

For a page made entirely of such content, put this directive on its first line:

Start with `<!-- ste-disable-file:`, add a page-specific reason, and close
that same line with `-->`. For example, the reason can state that campaign
copy uses the target audience's voice.

State a specific reason for that page or region.
The uppercase `<!-- STE-DISABLE -->` form does not work. File opt-outs appear
with their reasons in the linter report. Reviewers still check claims, links,
and technical accuracy in all content; an STE opt-out only changes prose checks.

## Every incident becomes a regression test

A bug that let an unusable or wrongly-promoted image ship stays open until a
test proves the old failure mode can never recur in silence. Put that test in
[`tests/regressions/`](tests/regressions/README.md), named after the issue
(`test_issue_<number>_<what_must_not_recur>.py`), with a docstring that cites
the issue and the run or log that measured the failure. The seed example is
#858 (marlin:kde shipped with no Wayland session). The regression test runs
the desktop contract's own check against a filesystem with no session file,
and holds that it fails. `tests/test_regression_convention.py` enforces the
naming.

## Roadmap before launch

Before you publish a new product or distribution channel, confirm that its
repository has `ROADMAP.md` at the root of its default branch. This applies to
desktop tools, shared infrastructure, Flatpak/Flathub apps, downloadable binaries,
and package-manager entries. Include the roadmap link and the links to the release
prerequisite issues in the release PR so reviewers can check the gate before publication.
Keep stability goals, important dependencies, and acceptance evidence in that
local roadmap; do not infer readiness from the file's existence.

For the organization-wide audit, run `python3 scripts/gen-roadmap-coverage.py`
in tunaos and review the generated [coverage inventory](ROADMAP.md#per-repo-roadmaps).
It checks every active public repository, including tools such as bluefin-cli
and wootc, using each repository's default branch. Track remaining omissions in
[#2820](https://github.com/tuna-os/tunaos/issues/2820). Coverage is broader than
shipped products: a missing roadmap is a plan gap, not proof that a product
has shipped. Do not turn live cross-repository coverage into a PR gate; use
`--check-structure` for changes to the generated block here.

## Building Images

```bash
just build yellowfin gnome           # single flavor (~25 min warm cache)
just build yellowfin kde linux/amd64 # specific platform
just build yellowfin all             # all flavors
```

## Adding a Desktop Environment

You do not need shell scripts. Write a YAML manifest:

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
# 3. Add flavor to tunaos.toml
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
5. Merge queue handles the rest (automerge when PRs pass)

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
- [Tests](docs/TESTING.md) — test harness

## Community

- [Donate time through Hive](https://hub.tunaos.org/#contribute)
- [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [Matrix: #tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)

## License

[Apache 2.0](LICENSE)

### Primary config

Edit `tunaos.toml` for matrix changes. Run `python3 scripts/config.py validate`
to check it, or `python3 scripts/config.py show` to view the build input.
`python3 scripts/config.py generate` writes the ignored compatibility file.
Build setup runs this step too. Do not edit that generated file.

Python 3.10+ uses Tomli from this repository. The source has a fixed version.
Config reads need no parser installation and never download code.
See [parser updates](docs/VENDORED-PARSER.md) before a version change.
This parser runs on the build host;
it is not an image package choice. Packages and brand settings still
follow the staged [migration plan](docs/PRIMARY-CONFIG-MIGRATION.md).
