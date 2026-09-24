---
created_date: "2026-09-24"
document_status: draft
---

# Feature: Tacklebox commit deadline on main (tunaOS#1893)

<!--
  OVERVIEW
  A concise 2-3 sentence summary of the feature. Answer three questions:
    1. What is being built?
    2. What problem does it solve?
    3. Who benefits and why does it matter?
  Avoid implementation details — this should be readable by any stakeholder.
-->
## Overview

Bring the fix for tunaOS#1893 to main: give tacklebox's post-customize `podman commit` a 30-minute deadline instead of its 600-second default, and make exported `TBOX_*` build knobs reach tacklebox however it runs (host binary or container). Today main's ISO builds fail in that commit step on large desktop layers even though the image is fine; the fix exists only on the v4 branch (#2507, #2598) and did not cherry-pick. Everyone who builds a tunaOS ISO, in CI or locally, benefits.

<!--
  REQUIREMENTS
  Specific, testable behaviours the feature must deliver.
  Format: bold title on the checkbox line, detail indented below.
  Rules:
    - Use active voice: "Users can...", "The system must..."
    - Each requirement should be independently verifiable
    - Focus on WHAT, not HOW — avoid prescribing implementation
    - Keep each item atomic — one behaviour per line
-->
## Requirements

- [x] **`tunaos_run_tacklebox` gives tacklebox a post-customize**
  `tunaos_run_tacklebox` gives tacklebox a post-customize commit deadline of 1800 seconds when the caller sets none.
- [x] **A caller can set `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` to any**
  A caller can set `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` to any non-negative integer to override it; `0` disables the inner deadline; anything else is rejected with a clear error before tacklebox starts.
- [x] **Every **exported** variable whose name starts with `TBOX_`**
  Every **exported** variable whose name starts with `TBOX_` reaches tacklebox on both execution paths: the host binary (`TACKLEBOX_FROM_SOURCE=1`) and the published container image.
- [x] **The container path never receives the runner's whole**
  The container path never receives the runner's whole environment.
- [x] **The default does not persist in the caller's environment**
  The default does not persist in the caller's environment after the function returns.
- [x] **The pinned tacklebox commit honours**
  The pinned tacklebox commit honours `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` and stays at or above the fd95174 floor.
- [x] **`docs/TACKLEBOX-CONTRACT.md` documents the environment**
  `docs/TACKLEBOX-CONTRACT.md` documents the environment contract: which knobs exist, that they must be exported, that they are echoed to logs.

<!--
  CONSTRAINTS
  Hard boundaries the solution must operate within. These are non-negotiable.
  Format: one bullet point per constraint.
  Examples:
    - Must integrate with the existing authentication system
    - Cannot introduce breaking changes to the public API
    - Must support the current minimum supported runtime versions
  Leave blank if there are no constraints.
-->
## Constraints

- No `--env-host`: it would give the tacklebox container `GITHUB_TOKEN` and registry credentials.
- `TBOX_*` values are echoed into build logs for diagnosis, so no secret may ever be passed under that prefix.
- The library must not change its caller's environment after it returns (it is sourced by several scripts).
- The tacklebox pin is a floor, not a ceiling: never below fd95174.
- Keep `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS` as the outer bound so disabling the inner deadline cannot make a build unbounded.
- main is the canonical branch; v4's commits are the reference, not something to merge wholesale.

<!--
  ACCEPTANCE CRITERIA
  The specific, binary conditions that define "done".
  Format: bold title on the checkbox line, verifiable detail indented below.
  Each criterion must be:
    - Independently verifiable (pass/fail, not subjective)
    - Traceable back to a requirement above
    - Testable by someone who didn't write the code
-->
## Acceptance Criteria

- [x] **Running `tunaos_run_tacklebox` with no**
  Running `tunaos_run_tacklebox` with no `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` passes `TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800` to tacklebox on both paths (bats, with podman and the binary stubbed).
- [x] **`TBOX_CUSTOMIZE_COMMIT_TIMEOUT=0` and `=2400` are passed**
  `TBOX_CUSTOMIZE_COMMIT_TIMEOUT=0` and `=2400` are passed through unchanged; `=abc` and `=-5` fail with exit 2 and a message naming the variable, and tacklebox is never started.
- [x] **An exported `TBOX_FOO=bar` appears as `--env TBOX_FOO=bar`**
  An exported `TBOX_FOO=bar` appears as `--env TBOX_FOO=bar` on the container command line; an unexported `TBOX_BAR` and a non-`TBOX_` variable such as `GITHUB_TOKEN` do not.
- [x] **After the function returns, `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`**
  After the function returns, `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` is unset in the caller if it was unset before.
- [ ] **`image-versions.yaml`'s tacklebox pin is a descendant of**
  `image-versions.yaml`'s tacklebox pin is a descendant of fd95174 and of the commit that added the knob (checked by an existing or new test).
- [ ] **The existing tacklebox bats and Python suites pass; the**
  The existing tacklebox bats and Python suites pass; the next ISO build of a large desktop (e.g. yellowfin:kde) does not fail at the commit step.

<!--
  TECHNICAL APPROACH
  High-level technical direction to guide the planning agent. Include:
    - Key architectural decisions already made
    - Preferred patterns or technologies if known
    - Integration points with existing systems
    - Known risks or areas of uncertainty
  Format: one bullet point per direction/steer.
  Leave blank if you want the planner to propose the approach.
-->
## Technical Approach

Port v4's two changes to `scripts/lib/tacklebox.sh` in order, adapting to main's current file rather than cherry-picking: first the `TBOX_*` forwarding from #2507 (771017b4), a name-agnostic loop over `compgen -e` that builds `--env NAME=value` pairs for the container path, then #2598's (8bdd559d) function-local default and validation for `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`, exported so the host-binary path inherits it. Bump the tacklebox pin in `image-versions.yaml` to the commit #2598 used (ae93e9b, a descendant of f3dd168 on tacklebox main). Bring over the bats cases and `tests/regressions/test_issue_1893_customize_commit_deadline.py`, and the environment-contract section of `docs/TACKLEBOX-CONTRACT.md`.

<!--
  SUCCESS METRICS
  How you will know the feature is working well after delivery. Be specific:
    - Quantitative: "p99 latency < 200ms", "error rate < 0.1%"
    - Behavioural: "users complete the flow without support intervention"
  Format: one bullet point per metric.
  Leave blank if not applicable.
-->
## Success Metrics

- No ISO build on main fails with tacklebox's commit-step timeout for two weeks after merge (today several large desktop ISOs do; tunaOS#1893).
- Workflows that set a `TBOX_*` knob (for example `TBOX_CUSTOMIZE_NETWORK=host` in weekly-desktop-screenshots.yml) see it take effect on the container path, confirmed from the build log's echoed knobs.

<!--
  NON-GOALS
  Explicitly state what this spec does NOT cover. This is as important as
  the requirements — it prevents scope creep and sets clear expectations.
  Format: one bullet point per exclusion.
  Examples:
    - "Mobile support is out of scope (tracked in #456)"
    - "Internationalisation will be addressed in a follow-up spec"
  Leave blank if there are no explicit exclusions to call out.
-->
## Non-Goals

- Making ISO builds or `podman commit` faster.
- Changing tacklebox itself or its defaults upstream.
- Merging the rest of the v4 branch into main.
- Adding new `TBOX_*` knobs.

