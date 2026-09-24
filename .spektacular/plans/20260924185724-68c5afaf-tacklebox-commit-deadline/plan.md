---
created_date: "2026-09-24"
document_status: final
closed_date: "2026-09-24"
---

# Plan: 20260924185724-68c5afaf-tacklebox-commit-deadline

<!-- Metadata -->
<!-- Created: 2026-09-24T19:12:08Z -->
<!-- Commit: 56a47921 -->
<!-- Branch: rfc011-spektacular -->
<!-- Repository: https://github.com/tuna-os/tunaOS -->

## Overview

Port the fix for tunaOS#1893 to main: tacklebox's post-customize `podman commit` gets a 30-minute deadline instead of its fixed 600 seconds, and every exported `TBOX_*` build knob reaches tacklebox whether it runs as the pinned host binary or as the published container. Large desktop ISO builds on main currently fail at that commit step although the image is fine; the fix existed only on v4 (#2507) and an unmerged PR branch (#2598). Everyone who builds a tunaOS ISO, in CI or locally, benefits.

## Conventions

- **Regression test per incident, with a `Falsification:` line** — #1893 shipped failing ISO builds; `tests/regressions/test_issue_1893_customize_commit_deadline.py` must follow the naming/docstring rules checked by `tests/test_regression_convention.py`.
- **Pin tools in `image-versions.yaml`, nowhere else** — the fix is a tacklebox pin bump; it must stay the only pin and respect the fd95174 FLOOR.
- **Do not skip, disable or weaken a failing test or gate** — existing tacklebox bats/pytest suites must pass unmodified except where the behaviour intentionally changes.
- **Assert the applied effect, not the presence of a string** — drives behavioural bats tests (what reaches podman/the binary) instead of only `grep -q` on the script.
- **Write a SYMPTOM/CAUSE/FIX troubleshooting row** — #1893 cost several debugging cycles; add §4 row 42 to `docs/ci-troubleshooting.md` (spec omitted this; convention requires it).
- **Keep Markdown within the STE prose budget** — the new `docs/TACKLEBOX-CONTRACT.md` section and troubleshooting row are linted against `.ste-budget` (1650), which must not be raised.
- **Run `just fix && just check`** — shell changes must pass the pinned shfmt v3.14.1 and shellcheck.
- **Evidence style** — comments state the constraint and the measured evidence (600.0 s commits, tacklebox#300), not the story.
- **Land on main; port adapted** — v4/pr/2598 commits are reference only.
- Dropped as not relevant: generated-files, green-criteria gates, yq-not-python, destructive-path guards, check-main-then-rebase (no PR is opened in this exercise).

## Architecture & Design Decisions

All code changes land in the single registered repo, `tunaos`, inside one function: `tunaos_run_tacklebox` in `scripts/lib/tacklebox.sh`. The function gains two blocks, placed after the existing outer-deadline validation and before the execution-path branch. First, a **function-local, exported default**: `local TBOX_CUSTOMIZE_COMMIT_TIMEOUT="${TBOX_CUSTOMIZE_COMMIT_TIMEOUT:-1800}"`, validated against `^(0|[1-9][0-9]*)$` with the same `ERROR: ... ; return 2` shape the outer `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS` check already uses, then `export`ed. `local` makes bash restore the caller's value and attributes on return, which keeps the library's documented "no side effects on the caller" contract; `export` makes the host-binary path (`TACKLEBOX_FROM_SOURCE=1`) inherit it with no further code. Second, a **prefix-matched forwarding loop** over `compgen -e` that turns every exported `TBOX_*` name into `--env NAME=value` for the container path, spliced between the volume mounts and the image ref, plus one log line listing the forwarded `NAME=value` pairs on both paths. Because the default is exported before the loop runs, the container path receives it through the same mechanism as any caller-set knob.

The tacklebox pin in `image-versions.yaml` moves from `f3dd168` to `ae93e9b` (tuna-os/tacklebox#300), the first commit that reads `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`; it descends from both `fd95174` (the floor) and `f3dd168`, verified against a clone of the tacklebox repository. This is the load-bearing change for CI, since every ISO workflow runs the pinned host binary. The pin stays the single source of truth (convention: pin tools in `image-versions.yaml`); no workflow gets a SHA or a knob value.

Key trade-offs. (1) tunaOS validates the value even though tacklebox parses it too, because tacklebox silently falls back to 600 on anything unparseable — a typo would reproduce #1893 with no error. (2) Forwarding is name-agnostic rather than an allow-list: new upstream knobs work without a tunaOS change, at the cost that anything exported as `TBOX_*` (including `iso-e2e.sh`'s `TBOX_E2E_*`) is forwarded and echoed to logs; the contract doc states that the prefix must never carry secrets. `--env-host` is excluded because it would carry `GITHUB_TOKEN` in. (3) The outer `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS` (default 4800) stays the hard bound, so `0` (no inner deadline) cannot make a build unbounded.

The port is hand-applied rather than cherry-picked: main's adapter matches v4's pre-#2507 file, but the docs diverged under the STE prose pass and the v4 troubleshooting row numbering does not exist on main, and the #2598 commit lives on `pr/2598`, not v4. Tests are strengthened beyond v4's string greps: behavioural bats cases call the real function with a stubbed `podman` and a fake host binary. See research.md#alternatives-considered-and-rejected for cherry-pick, `--env-host`, allow-list, per-workflow defaults and non-local export.

## Component Breakdown

- **Tacklebox adapter (`tunaos_run_tacklebox`)** — changed. Owns choosing the execution path (pinned host binary or published container), the outer deadline, and now the tacklebox environment: it supplies the commit-deadline default, rejects a malformed value before anything runs, forwards exported `TBOX_*` knobs into the container, and logs which knobs are in play. It is the only component the two ISO build scripts (single-flavor and grouped) call, so both inherit the change with no edits of their own.
- **Tacklebox pin (`image-versions.yaml` downloads entry)** — changed. Owns which tacklebox revision the host-binary path builds. Moves to the first revision that honours `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`, keeping its floor/Renovate commentary. Read by the adapter; unchanged mechanism.
- **Adapter test suite (bats)** — changed. Owns the adapter's behavioural contract: default applied on both paths, overrides and `0` passed through, invalid values rejected with exit 2 before tacklebox starts, prefix-only and exported-only forwarding, no whole-environment passthrough, no leak into the caller.
- **Regression test for tunaOS#1893 (pytest)** — new. Owns "this incident cannot silently recur": runs the real adapter against a stub container runtime and checks the default reaches tacklebox, and checks the pin is not the old literal-600 revision. Follows the regressions-directory convention and is itself checked by the convention test.
- **Tacklebox contract document** — changed. Gains an environment contract: the knobs, the two execution paths, that knobs must be exported, that values are logged (so no secrets under the prefix), why not `--env-host`, and the commit-deadline default/override/outer-bound rules.
- **CI troubleshooting playbook** — changed. Gains one SYMPTOM/CAUSE/FIX row for the 600-second commit failures.
- **Weekly desktop screenshots workflow comment** — changed (comment only). Its note that the container path drops `TBOX_*` becomes false after this change; update it as #2507 did, keeping the job on the host path for its separate resolver reason.

## Data Structures & Interfaces

No new types. The change is to an **environment-variable interface** between the tunaOS adapter and tacklebox; the adapter's function signature is unchanged.

**Adapter call (unchanged):** `tunaos_run_tacklebox <recipe_file> <out_dir> <iso_out>` → exit status of tacklebox; `2` on invalid configuration; `124`/`137` when the outer deadline fires.

**Environment inputs read by the adapter:**

| Name | Role | Status |
|---|---|---|
| `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS` | Outer bound on the whole tacklebox run (positive integer). | existing |
| `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` | Inner bound on tacklebox's post-customize `podman commit`, seconds; `0` = no inner bound. Adapter supplies a default when unset. | new default + validation |
| `TBOX_*` (any exported name with this prefix) | Tacklebox build knob; forwarded verbatim to tacklebox on both paths. | new forwarding (container path) |
| `TACKLEBOX_FROM_SOURCE`, `TACKLEBOX_SHA`, `TACKLEBOX_IMAGE`, `TACKLEBOX_CACHE` | Execution-path selection and pin override. | existing, unchanged |

**Container invocation shape (changed):** `podman run --rm --privileged … <volume mounts> [--env TBOX_NAME=value …] <image> build …` — forwarded knobs sit between the mounts and the image ref so podman, not tacklebox, parses them.

**Log line (new, stderr):** `==> Tacklebox environment: TBOX_A=1 TBOX_B=2 …` printed on both paths when at least one knob is present. This is a diagnostic surface, so the `TBOX_` prefix is declared non-secret.

**Pin (changed value, same shape):** `image-versions.yaml` → `downloads.tacklebox: "<40-hex sha>"`.

## Implementation Detail

The adapter keeps its existing shape — validate inputs, pick an execution path, build one command array, run it under the outer deadline — and the new work slots into the "validate inputs" stage. A reader sees, in order: outer deadline (existing), commit-deadline default and validation (new), environment collection (new), path selection (existing, container array gains one spliced element), a one-line log of forwarded knobs (new), then the unchanged run/timeout handling. No new module, helper file or function is introduced.

**Patterns followed, not invented.** The commit-deadline validation copies the outer deadline's pattern exactly: parameter expansion with a default, an anchored regex, an `ERROR:` line naming the variable, and `return 2` — so both knobs fail the same way. The "must not change the caller's environment" rule, already stated in the library header and tested for sourcing, is extended to calls by using a function-local variable that is exported only for the function's lifetime.

**One new pattern:** name-agnostic environment forwarding, collecting exported names by prefix into an argument array rather than listing knobs. It is the first place the repo forwards environment into a container by rule instead of by name; the comment explains why (upstream knobs work unchanged, `--env-host` would leak credentials) and the contract doc makes the prefix a declared, non-secret namespace.

**Tests move from string-presence toward behaviour.** The existing adapter tests mostly grep the script. The new cases source the real library and call the real function with a stub container runtime (records its argv) and a fake host binary (records its `TBOX_*` environment), which is the "assert the applied effect" convention. The v4 loop-extraction tests are kept for the prefix and name-agnostic properties; the regression test is pytest, per the regressions-directory convention.

## Dependencies

- **tuna-os/tacklebox @ `ae93e9b` (tacklebox#300)** — external; provides `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` (0 = off, invalid = silent 600). Already merged on tacklebox main; descends from the `fd95174` floor and the current `f3dd168` pin. No change needed; must exist before the pin bump (it does).
- **Published image `ghcr.io/tuna-os/tacklebox:latest`** — external; the container path's default. Verified revision `cd31821` (descends from `ae93e9b`), so it honours the knob; not changed here.
- **v4 commit `771017b4` (#2507)** and **`pr/2598` commit `8bdd559d` (#2598)** — reference implementations to port; nothing must land on v4 first.
- **Existing adapter pieces** — the outer deadline (`TUNAOS_TACKLEBOX_TIMEOUT_SECONDS`) and the pin lookup; both used unchanged.
- **Test tooling** — bats, pytest with PyYAML, shellcheck, shfmt v3.14.1 (pinned), and the shared STE linter for Markdown; all already used by `just check`/`just test`.
- **Prior specs/plans** — none; this is the first spec and plan in the store.
- **Design documents this plan was built on: none.** The spec carries no design references (`spektacular design ref list` → `refs: []`, `unresolved: 0`).

## Testing Approach

**Test types.** (1) Behavioural shell tests (bats) for the adapter, calling the real sourced function with a stub container runtime that records its arguments and a fake host binary that records the `TBOX_*` environment it received — no image pull, no root, no network. (2) One pytest regression test for tunaOS#1893 in the regressions directory, with the `tunaOS#1893` docstring and a `Falsification:` line, checked by the existing convention test. (3) Existing structural bats tests (loop extraction, splice position, no `--env-host`) ported from v4 for the properties that are about code shape. (4) Static checks: shellcheck and the pinned shfmt on the changed shell file; the shared STE linter on changed Markdown.

**Most coverage goes to the adapter**, because it is the only component with logic and the only place both ISO scripts pass through. Load-bearing guarantees, in plain language:
- With no caller setting, tacklebox receives a 1800-second commit deadline on both the container path and the host-binary path.
- `0` and another positive integer are passed through unchanged; a non-integer or negative value stops the adapter with exit 2 and a message naming the variable, and tacklebox (container or binary) is never started.
- Exported `TBOX_*` names reach the container as `--env` flags; an unexported `TBOX_*` name, a non-prefixed name such as `GITHUB_TOKEN`, and a lookalike such as `PATH_LOOKALIKE_TBOX` do not.
- After the function returns, the caller's `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` is exactly what it was before (unset stays unset; a caller value is preserved).
- The pin is a 40-hex SHA and is not the old literal-600 revision.

**Fit with conventions.** Bats for shell, pytest for Python (ADR 0008); regression file naming and `Falsification:` per the regressions README; no existing test is skipped or weakened — the one v4 grep test that pins the old "positive integer" wording stays valid because the outer-deadline message is unchanged.

**Deliberate gaps.** Pin ancestry (descends from `fd95174` and from the knob commit) needs the tacklebox repository and network, so it is not an automated test; it is verified once during implementation and recorded next to the pin. Real ISO builds are not run locally (root, loop devices, multi-GB pulls).

**Spec success metrics.**
- *No ISO build on main fails with tacklebox's commit-step timeout for two weeks after merge* — **Manual — captured in the implementation test plan** (needs CI history after merge).
- *Workflows that set a `TBOX_*` knob see it take effect on the container path, confirmed from the build log's echoed knobs* — the forwarding and the log line are covered by a **behavioural test** (stubbed podman argv and captured stderr); confirming it in a real workflow log is **Manual — captured in the implementation test plan**.
- Acceptance criterion "next large-desktop ISO build does not fail at the commit step" — **Manual — captured in the implementation test plan**.

## Milestones & Phases

### Milestone 1: A tacklebox knob set for a build takes effect however tacklebox runs

**What changes**: Today a workflow or developer that exports a `TBOX_*` setting (for example `TBOX_CUSTOMIZE_NETWORK=host`) gets it honoured only when tacklebox runs as a host binary; on the default container path it is silently ignored. After this milestone every exported `TBOX_*` setting reaches tacklebox on both paths, the build log lists which settings were in play, and nothing else from the runner's environment (tokens, credentials) is passed in. The tacklebox contract document explains the rule.

**Validation point**: The adapter's bats suite shows exported `TBOX_*` names on the stubbed container command line, and unexported or non-prefixed names absent; the full existing suite still passes.

#### - [x] Phase 1.1: Forward exported TBOX_* knobs into the tacklebox container
**Repo:** tunaos

The adapter collects every exported variable whose name starts with `TBOX_` and passes each to the container as an explicit environment flag, placed where the container runtime (not tacklebox) reads it. Both paths log the forwarded knobs once, so an unset knob is visible in the build log. The whole-environment option stays unused, so tokens and credentials never enter the container.

*Technical detail:* [context.md#phase-11](./context.md#phase-11-forward-exported-tbox_-knobs-into-the-tacklebox-container)

**Acceptance criteria**:
- [x] An exported `TBOX_` setting appears on the container command line as an environment flag before the image name.
- [x] An unexported `TBOX_` setting, a lookalike name that only contains `TBOX_`, and `GITHUB_TOKEN` do not appear.
- [x] A brand-new `TBOX_` name is forwarded without any change to the adapter.
- [x] The build log lists the forwarded settings on both execution paths.
- [x] Every test that passed on main before this phase still passes.

#### - [x] Phase 1.2: Document the tacklebox environment contract
**Repo:** tunaos

The tacklebox contract document gains a section describing the knobs tacklebox reads from its environment, the two ways tunaOS runs tacklebox, the exported-only and prefix-only forwarding rule, that values are logged so the prefix must never carry secrets, and why the whole environment is not passed. The screenshots workflow's comment, which says the container path drops these settings, is corrected.

*Technical detail:* [context.md#phase-12](./context.md#phase-12-document-the-tacklebox-environment-contract)

**Acceptance criteria**:
- [x] A reader of the contract document can tell which settings reach tacklebox, on which path, and why credentials must not use the prefix.
- [x] No document or workflow comment still claims the container path ignores `TBOX_` settings.
- [x] The new prose passes the project's Simplified Technical English check without raising the budget.

### Milestone 2: Large desktop ISO builds get 30 minutes to commit their customized image

**What changes**: ISO builds of multi-gigabyte desktops stop failing at exactly 600 seconds in tacklebox's post-customize commit (tunaOS#1893). The pinned tacklebox moves to a revision that accepts a commit deadline, and the adapter gives it 1800 seconds unless the caller chooses another value (`0` turns the inner limit off; the existing outer limit still bounds the whole build). A malformed value fails immediately with a clear message instead of being silently ignored. A regression test and a troubleshooting row record the incident.

**Validation point**: bats and the #1893 regression test show 1800 reaching tacklebox on both paths, overrides passing through, bad values exiting 2 before tacklebox starts, and the caller's environment unchanged afterwards; shellcheck, shfmt and the STE linter are clean. The first CI ISO build of a large desktop after merge completes its commit step (manual).

#### - [x] Phase 2.1: Default and validate the commit deadline, and pin a tacklebox that honours it
**Repo:** tunaos

The adapter supplies a 1800-second commit deadline when the caller sets none, accepts `0` or any positive whole number as an override, and stops with a clear error on anything else before tacklebox starts. The value lives only for the duration of the call, so scripts that source the library are not changed by it. The tacklebox pin moves to the first revision that reads the setting, which also descends from the documented floor.

*Technical detail:* [context.md#phase-21](./context.md#phase-21-default-and-validate-the-commit-deadline-and-pin-a-tacklebox-that-honours-it)

**Acceptance criteria**:
- [x] With no caller setting, tacklebox receives a 1800-second commit deadline on both the container and the host-binary path.
- [x] `0` and `2400` reach tacklebox unchanged.
- [x] `abc` and `-5` stop the build with exit status 2 and a message naming the setting, and tacklebox is never started.
- [x] After the call returns, a caller that had no setting still has none, and a caller's own value is unchanged.
- [x] The pinned tacklebox revision reads the setting and is at or above the documented floor.

#### - [x] Phase 2.2: Record incident #1893 with a regression test, contract text and a troubleshooting row
**Repo:** tunaos

A regression test named for tunaOS#1893 runs the real adapter against a stub container runtime and fails if the 1800-second default does not reach tacklebox, or if the pin falls back to the revision with a fixed 600-second limit. The contract document states the default, the override rules and the outer bound. The CI troubleshooting playbook gains a symptom/cause/fix row for the 600-second commit failures.

*Technical detail:* [context.md#phase-22](./context.md#phase-22-record-incident-1893-with-a-regression-test-contract-text-and-a-troubleshooting-row)

**Acceptance criteria**:
- [x] The regression test passes on the fixed tree and its stated falsification has been demonstrated by reverting the default.
- [x] The repository's regression-test convention check accepts the new test.
- [x] Someone searching the troubleshooting playbook for a 600-second `podman commit` failure finds the cause and the fix.
- [x] Shell and Markdown lint (shellcheck, pinned shfmt, STE budget) are clean for every changed file.

## Open Questions

None that block implementation. The candidates were resolved during planning:

- *Does the container path's default image honour the knob?* Resolved: `ghcr.io/tuna-os/tacklebox:latest` carries `org.opencontainers.image.revision=cd31821` (created 2026-09-23), and `ae93e9b` is an ancestor of `cd31821`.
- *Is the new pin at or above the floor?* Resolved: `fd95174` and `f3dd168` are ancestors of `ae93e9b`, which is on tacklebox `main`.

One question can only be answered after merge, and is tracked as a manual check rather than a blocker: whether 1800 seconds is enough for every large desktop cell on CI runners. If a cell still fails at exactly 1800 s, the implementer (or on-call) should not raise the default blindly — STOP, record the measured duration in the troubleshooting row, and ask the maintainer whether that cell needs a per-workflow override or a runner change.

## Out of Scope

- Making ISO builds or `podman commit` faster (spec non-goal).
- Changing tacklebox itself or its upstream 600-second default (spec non-goal; tacklebox#300 already made it settable).
- Merging the rest of the `v4` branch, or `pr/2598`, into main (spec non-goal); only #2507 and #2598 behaviour is ported.
- Adding new `TBOX_*` knobs or setting per-workflow values (spec non-goal).
- Replacing the hard-coded fallback tacklebox SHA in the adapter (`3b45982`, used only when the pin file is not found from the working directory). It is below the `fd95174` floor and lacks the knob; follow-up issue to be filed: "tacklebox adapter: resolve image-versions.yaml relative to the library and drop the stale fallback SHA".
- Preserving caller-set `TBOX_*` overrides across `sudo --preserve-env=<list>` in the grouped-ISO publish workflow. The in-library default still applies after sudo, so #1893 is fixed; only a per-job override would be lost. Follow-up with the item above.
- Moving the weekly desktop screenshots job off the host-binary path (it stays there for a separate nested-resolver reason; only its comment is corrected).

## Changelog

### 2026-09-24 — Phase 1.1: Forward exported TBOX_* knobs into the tacklebox container

**What was done**: `tunaos_run_tacklebox` now collects every exported `TBOX_*` variable into `--env NAME=value` flags spliced before the image ref on the container path, and logs the forwarded knobs on both paths. Ported the four #2507 bats tests and added a behavioural test that runs the real function with a stub podman.

**Deviations**: Comment text shortened relative to v4 (the #1893 knob sentence moves in with Phase 2.1). Added a behavioural bats test beyond v4's structural ones.

**Files changed**:
- `scripts/lib/tacklebox.sh`
- `tests/bats/test_build_iso_tacklebox.bats`

**Discoveries**: bats `setup()` cd's into a temp dir, so behavioural tests must pass absolute paths. `root check: detects non-root and errors` fails whenever the suite runs as root (EUID is read-only), on unmodified main too.

### 2026-09-24 — Phase 1.2: Document the tacklebox environment contract

**What was done**: Added an "Environment contract" section to `docs/TACKLEBOX-CONTRACT.md` (two execution paths, exported-only prefix forwarding, no secrets under `TBOX_`, no `--env-host`) written in STE style, and corrected the weekly-desktop-screenshots workflow comment that said the container path drops `TBOX_*`.

**Deviations**: v4's section text was rewritten rather than copied because main's docs follow the STE prose pass; the "one knob does not exist yet" paragraph was dropped (superseded by Phase 2.2).

**Files changed**:
- `docs/TACKLEBOX-CONTRACT.md`
- `.github/workflows/weekly-desktop-screenshots.yml`

**Discoveries**: The STE linter runs locally via `scripts/run-ste-lint.sh` (clones tuna-os/.github at the pinned SHA; `TUNAOS_STE_CACHE_DIR` relocates the cache). Repo total 1644/1650; the new section added 0 findings (contract doc 15 before and after).

### 2026-09-24 — Phase 2.1: Default and validate the commit deadline, and pin a tacklebox that honours it

**What was done**: `tunaos_run_tacklebox` now sets a function-local, exported `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` defaulting to 1800, rejects anything but `0|[1-9][0-9]*` with exit 2 before any podman/binary call, and the tacklebox pin moved from `f3dd168` to `ae93e9b` (tuna-os/tacklebox#300). Six bats cases added (one structural from #2598, five behavioural: container default, host-binary default via a fake binary, 0/2400 passthrough, abc/-5/1.5 rejected with podman never called, caller env restored).

**Deviations**: Error message also echoes the bad value and says `0` disables the inner deadline (v4 printed only the rule). Pin comment rewritten to record the verified ancestry (fd95174, 4fa6041, f3dd168 all ancestors of ae93e9b).

**Files changed**:
- `scripts/lib/tacklebox.sh`
- `image-versions.yaml`
- `tests/bats/test_build_iso_tacklebox.bats`

**Discoveries**: Mutation-checked: removing the default, removing `local`, or removing the `--env` splice each turns 2-5 of the new cases red. `local` + `export` inside a function restores both the value and the non-exported attribute of a caller's variable on return (bash 5.2). The `image-versions.yaml` comment's pointer "scripts/lib/common.sh:229" for the fallback is stale — the lookup now lives in `scripts/lib/tacklebox.sh:38`; left for the out-of-scope fallback follow-up.

### 2026-09-24 — Phase 2.2: Record incident #1893 with a regression test, contract text and a troubleshooting row

**What was done**: Added `tests/regressions/test_issue_1893_customize_commit_deadline.py` (behavioural container-path test with a stub podman; structural pin test), a "Commit deadline" subsection in `docs/TACKLEBOX-CONTRACT.md`, and §4 row 42 in `docs/ci-troubleshooting.md`.

**Deviations**: Row is numbered 42 (v4's 43 follows a v4-only row 42). The regression test also forces `TACKLEBOX_FROM_SOURCE=0` (v4's inherited the caller's value, so it could silently take the host path) and asserts exactly one `podman run` line; docstring restructured to the README's shipped/measured/holds shape. On landing (PR #2682) the row became 48: rows 42–47 went to PRs that merged or opened first.

**Files changed**:
- `tests/regressions/test_issue_1893_customize_commit_deadline.py`
- `docs/TACKLEBOX-CONTRACT.md`
- `docs/ci-troubleshooting.md`

**Discoveries**: Use `python3 -m pytest` (as `just test` does); the `pytest` on PATH in this sandbox is a uv tool venv without PyYAML. Both falsifications demonstrated (delete `:-1800` -> adapter test fails; revert pin to f3dd168 -> pin test fails). STE total stays 1644/1650; new prose adds 0 findings.
