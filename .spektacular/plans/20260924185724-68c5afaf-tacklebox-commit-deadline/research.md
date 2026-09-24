---
created_date: "2026-09-24"
document_status: final
closed_date: "2026-09-24"
---

# Research: 20260924185724-68c5afaf-tacklebox-commit-deadline

## Alternatives considered and rejected

- **Cherry-pick 771017b4 then 8bdd559d onto main.** Rejected. 771017b4 applies to the code but its `docs/TACKLEBOX-CONTRACT.md` hunk fails (`git apply --check`: "patch failed: docs/TACKLEBOX-CONTRACT.md:52") because main's doc was rewritten for the STE prose pass ("require updating" -> "need updating"). 8bdd559d fails in 4 of 6 files, and its ci-troubleshooting row is numbered 43 after a v4-only row 42 that main does not have. Also, 8bdd559d is NOT on `origin/v4` at all: `git branch -r --contains 8bdd559d` -> only `origin/pr/2598`; it is an unmerged PR branch stacked on v4.
- **`podman run --env-host`.** Rejected (spec constraint; 771017b4 message): hands the container `GITHUB_TOKEN` and registry logins.
- **Allow-list of known knob names (`--env TBOX_CUSTOMIZE_TIMEOUT` etc.).** Rejected: every new tacklebox knob would need a tunaOS change; the v4 design is prefix-match so a knob added upstream works unchanged (771017b4 message, v4 bats "passthrough is name-agnostic").
- **Set the 1800 default in each workflow's `env:` instead of the library.** Rejected: 9 workflows build ISOs (`grep TACKLEBOX_FROM_SOURCE .github/workflows`), `publish-iso-groups.yml:218` runs under `sudo --preserve-env=<list>` which would drop it, and local `just` builds would keep 600.
- **`export TBOX_CUSTOMIZE_COMMIT_TIMEOUT=...` without `local`.** Rejected: leaks into the caller (the library is sourced by `common.sh`; header comment scripts/lib/tacklebox.sh:4-5 says it must have no side effects).
- **Keep v4's grep-only bats tests for the new behaviour.** Rejected as the only coverage: they assert strings are present (`grep -q 'TBOX_CUSTOMIZE_COMMIT_TIMEOUT:-1800'`), which the regression convention calls structural; the spec's acceptance criteria are behavioural (exit 2, what reaches podman/binary, caller env after return). Keep the v4 loop-eval tests, add behavioural ones that call the real function with stubbed podman and a fake host binary.

## Chosen approach — evidence

- main `scripts/lib/tacklebox.sh` == v4's file before 771017b4 (`git diff 771017b4~1 HEAD -- scripts/lib/tacklebox.sh` is empty), so the #2507 code hunk ports verbatim; only the #2598 comment edit and ordering need adapting.
- Container path: scripts/lib/tacklebox.sh:76-82 builds `podman run ... "$tacklebox_image"` with no env forwarding. Host path: :35-72 runs `$bin` as a child, inherits exported env.
- Outer bound already exists: scripts/lib/tacklebox.sh:25-29 (`TUNAOS_TACKLEBOX_TIMEOUT_SECONDS`, default 4800, positive-int validation, `return 2`) — the new validation mirrors this shape and exit code.
- tacklebox ae93e9b (tuna-os/tacklebox#300) `internal/install/customize.go`: `customizeCommitTimeoutSeconds()` reads `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`, accepts `n >= 0`, 0 = no `timeout` wrapper, **invalid values silently fall back to 600**. So validation on the tunaOS side is what makes a typo fail loudly.
- Pin ancestry verified in a scratch clone of tuna-os/tacklebox: fd95174 and f3dd168 are ancestors of ae93e9b; ae93e9b is on `origin/main`.
- CI builds use the pinned host binary, not the container: `TACKLEBOX_FROM_SOURCE=1` in installer-smoke, reusable-build-artifacts, live-iso-bootc, installer-screenshots, live-initramfs, iso-e2e, luks-e2e, publish-iso-groups, weekly-desktop-screenshots. The pin bump is therefore the load-bearing part for #1893 in CI; the container path (`TACKLEBOX_IMAGE`, default `ghcr.io/tuna-os/tacklebox:latest`) is local/dev default.
- v4 regression test (8bdd559d:tests/regressions/test_issue_1893_customize_commit_deadline.py) already runs the real adapter with a stub `podman` — reusable nearly as is.

## Files examined

- scripts/lib/tacklebox.sh:14-102 — the whole adapter; two exec paths; outer deadline; side-effect-free contract (:4-5).
- scripts/lib/tacklebox.sh:38-39 — pin read from `image-versions.yaml` relative to CWD; hard fallback `3b45982` is BELOW the fd95174 floor (verified ancestor) and lacks the knob.
- scripts/lib/common.sh — sources tacklebox.sh; build-iso-tacklebox.sh:221 and build-iso-group.sh:201 are the only callers of `tunaos_run_tacklebox`.
- image-versions.yaml:86-107 — tacklebox pin `f3dd168`, FLOOR comment (fd95174).
- tests/bats/test_build_iso_tacklebox.bats:341-382 — mode-selection and deadline tests (grep-style), side-effect-free sourcing test (:373).
- tests/regressions/README.md — naming, `tunaOS#N` docstring, `Falsification:` line; enforced by tests/test_regression_convention.py:79-83.
- docs/TACKLEBOX-CONTRACT.md:1-80 — recipe contract; no environment section on main.
- docs/ci-troubleshooting.md:160-200 — §4 table ends at row 41 on main.
- .github/workflows/weekly-desktop-screenshots.yml:129-162 — comment still says the container path drops TBOX_*; 771017b4 updates it.
- .github/workflows/publish-iso-groups.yml:218 — `sudo --preserve-env=GITHUB_REPOSITORY_OWNER,TACKLEBOX_FROM_SOURCE,TACKLEBOX_SHA`: a caller-set TBOX_* override does not survive; the in-library default still applies.
- scripts/iso-e2e.sh:77-88 — uses `TBOX_E2E_*` names; if exported in the same shell they would be forwarded and echoed (harmless, no secrets).

## External references

- tuna-os/tacklebox@ae93e9b (#300) — adds the knob; semantics of 0 and of invalid values.
- tunaOS#1893 (commit deadline failures), #2034 (ask for the knob), #2507 (forwarding, 771017b4 on v4), #2598 (default + pin, 8bdd559d on `pr/2598`), #1772 (outer deadline).

## Prior plans / specs consulted

- None: `spektacular plan file list` is empty; the only spec is this one. Knowledge base: gotchas/tacklebox-sha-in-workflow.md (pin in image-versions.yaml only), gotchas/sudo-resets-env-and-path.md (explains the publish-iso-groups override loss), conventions (regression test + Falsification, troubleshooting row, STE budget, fix && check).

## Open assumptions

- (Resolved in open_questions) `ghcr.io/tuna-os/tacklebox:latest` label `org.opencontainers.image.revision=cd31821` (created 2026-09-23T10:08Z); `ae93e9b` is its ancestor, so the container default honours the knob.
- ae93e9b's other changes between f3dd168 and it (renovate bumps, #324 live-build hardening) do not regress tunaOS ISO builds; only CI can prove this (acceptance criterion "next large-desktop ISO build does not fail at commit").
- Bash >= 4.4 on all runners (empty `"${arr[@]}"` under `set -u`). Local bash is 5.2.

## Drafting assumptions

### Chosen direction: local exported default + prefix forwarding in tunaos_run_tacklebox (architecture)
- **Decision**: Implement both behaviours inside `tunaos_run_tacklebox` (local+export default with validation, then compgen-e TBOX_* forwarding), bump the pin to ae93e9b, behavioural bats + regression test, doc section + troubleshooting row.
- **Rationale**: Single choke point used by both ISO scripts; matches v4 design reviewed in #2507/#2598; satisfies no-side-effect and no-env-host constraints.
- **Rejected**: per-workflow env defaults; allow-list forwarding; --env-host; global export.

### Conventions selected (architecture)
- **Decision**: Apply 9 conventions (see conventions.md); drop generated-files, green-criteria, yq, path-guard, rebase.
- **Rationale**: Only those touch shell adapter, pins, tests and docs changed here.
- **Rejected**: listing all 14 (noise).

### Add a troubleshooting row although the spec does not ask (architecture)
- **Decision**: Add §4 row 42 to docs/ci-troubleshooting.md.
- **Rationale**: AGENTS.md rule 6 convention; knowledge outranks the spec's omission; v4 did the same (row 43 there).
- **Rejected**: skipping it (violates convention).

### Port target is main, adapted, not cherry-picked (discovery)
- **Decision**: Re-implement #2507 + #2598 on main by hand, with main's doc wording and row numbering.
- **Rationale**: Patches do not apply (STE-rewritten doc, v4-only row 42); 8bdd559d is on `pr/2598`, not v4.
- **Rejected**: `git cherry-pick` (conflicts in 4/6 files); merging v4 (non-goal).

### Hard-coded fallback SHA left alone (discovery)
- **Decision**: Do not change the `3b45982` literal fallback in scripts/lib/tacklebox.sh:39 in this change; record it as a follow-up.
- **Rationale**: Non-goal scope; it only triggers when CWD is not the repo root, and both callers run from the root. Changing pin resolution is a separate behaviour change.
- **Rejected**: Replacing it with ae93e9b (duplicates the pin, violates "pin only in image-versions.yaml"); failing hard (behaviour change for out-of-root callers).

### Publish-iso-groups override loss not fixed here (discovery)
- **Decision**: Leave `sudo --preserve-env` lists alone.
- **Rationale**: The 1800 default is set inside the library after sudo, so #1893 is fixed; only a per-job override is lost, and no workflow sets one. Non-goal: no new knobs/workflow changes.
- **Rejected**: Adding `TBOX_*` to every `--preserve-env` list (scope creep).
### Include the weekly-desktop-screenshots comment update (components)
- **Decision**: Update the workflow comment (comment only) as #2507 did.
- **Rationale**: The comment would become false; leaving docs wrong violates the "leave docs better" rule. No behaviour change, so it does not breach the "no workflow changes" reading of the non-goals.
- **Rejected**: Moving that job to the container path (separate resolver reason; out of scope).

### Pin ancestry verified manually, not by an automated test (testing_approach)
- **Decision**: Automated test checks pin shape and "not the old literal-600 pin"; ancestry is checked once by hand and recorded.
- **Rationale**: Ancestry needs the tacklebox repo over the network; an offline-conditional test would be a skip in disguise (convention: do not skip tests).
- **Rejected**: Network test in pytest (flaky, CI has no guarantee of GitHub access in unit stage); vendoring a list of tacklebox SHAs (stale).

## Rehydration cues

- `git fetch origin v4 && git show 771017b4 8bdd559d` (8bdd559d is on `origin/pr/2598`).
- `sed -n 14,102p scripts/lib/tacklebox.sh`; `bats tests/bats/test_build_iso_tacklebox.bats`.
- `git clone --filter=blob:none https://github.com/tuna-os/tacklebox && git show ae93e9b -- internal/install/customize.go`.
- `spektacular knowledge always-applied --tier repo --filter tunaos`; `spektacular knowledge search tacklebox`.
