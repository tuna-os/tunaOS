---
created_date: "2026-09-24"
document_status: final
closed_date: "2026-09-24"
---

# Context: 20260924185724-68c5afaf-tacklebox-commit-deadline

## Current State Analysis

- `scripts/lib/tacklebox.sh:14-102` (main @ 56a47921) is byte-identical to v4's file before 771017b4: two execution paths (pinned host binary when `TACKLEBOX_FROM_SOURCE=1`, else `podman run ghcr.io/tuna-os/tacklebox:latest`), an outer deadline `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS` (default 4800, `return 2` on bad input), no `TBOX_*` forwarding and no commit-deadline default.
- `image-versions.yaml:104` pins tacklebox `f3dd168`, which has a literal 600 s commit deadline. `ae93e9b` (tacklebox#300) makes it `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`; invalid values silently fall back to 600.
- All nine CI ISO workflows set `TACKLEBOX_FROM_SOURCE=1`, so CI uses the pin; the container path is the local default and its `:latest` image (revision `cd31821`) already contains the knob.
- `docs/TACKLEBOX-CONTRACT.md` has no environment section; main's wording has been STE-edited so v4 doc hunks do not apply.
- `docs/ci-troubleshooting.md` §4 table ends at row 41 on main.
- `tests/bats/test_build_iso_tacklebox.bats` has 35 tests, mostly structural greps over the script.

## Per-Phase Technical Notes

### Phase 1.1: Forward exported TBOX_* knobs into the tacklebox container

**File changes**
- `scripts/lib/tacklebox.sh:31-33` — after `from_source=`, add the #2507 block from `771017b4`: comment (why, name-agnostic, not `--env-host`), `local -a tbox_env=() tbox_names=()`, `for _tbox_name in $(compgen -e); do [[ $_tbox_name == TBOX_* ]] || continue; tbox_env+=(--env "NAME=value"); tbox_names+=("NAME=value"); done`. Loop must start with a single tab + `for _tbox_name in` and end with tab + `done` (the v4 bats tests extract it with awk).
- `scripts/lib/tacklebox.sh:76-82` — insert `"${tbox_env[@]}"` after the recipe `-v` mount and before `"$tacklebox_image")`.
- `scripts/lib/tacklebox.sh:84` — before `build_cmd`, add `if ((${#tbox_names[@]})); then echo "==> Tacklebox environment: ${tbox_names[*]}" >&2; fi`.
- `tests/bats/test_build_iso_tacklebox.bats:370` (after "bounded, overrideable deadline") — add the four v4 tests from `771017b4` (section header "TBOX_* environment passthrough (tunaOS#2034)"): loop-eval forwarding, name-agnostic, splice-before-image, no `--env-host` in code lines.
- Same file — add behavioural test: source the library, stub `podman` on PATH (logs `$*`), `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS=30`, export `TBOX_FOO=bar`, set unexported `TBOX_BAR=x`, export `GITHUB_TOKEN=secret`; assert log has `--env TBOX_FOO=bar`, lacks `TBOX_BAR` and `GITHUB_TOKEN`, and stderr has `Tacklebox environment:`.

**Complexity**: Low. **Token estimate**: ~8k. **Agent strategy**: single agent, sequential.

### Phase 1.2: Document the tacklebox environment contract

**File changes**
- `docs/TACKLEBOX-CONTRACT.md:52-55` — after "…in the same change." and before `## Validation boundary`, add `## Environment contract` adapted from `771017b4` (main wording is STE-edited; keep sentences short and in STE style). Drop v4's "One knob does not exist yet" paragraph (it is superseded in Phase 2.2).
- `.github/workflows/weekly-desktop-screenshots.yml:142-147` — replace the claim that `podman run` never forwards env with #2507's wording: forwarding now exists (tunaOS#2034), job stays on the host path for the nested-resolver reason.
- Run the STE linter (`scripts/run-ste-lint.sh`) against `.ste-budget` 1650.

**Complexity**: Low. **Token estimate**: ~5k. **Agent strategy**: single agent.

### Phase 2.1: Default and validate the commit deadline, and pin a tacklebox that honours it

**File changes**
- `scripts/lib/tacklebox.sh` (after the outer-deadline check at :25-29, before the Phase 1.1 block) — add #2598's block from `8bdd559d`: comment; `local TBOX_CUSTOMIZE_COMMIT_TIMEOUT="${TBOX_CUSTOMIZE_COMMIT_TIMEOUT:-1800}"`; `[[ … =~ ^(0|[1-9][0-9]*)$ ]] || { echo "ERROR: TBOX_CUSTOMIZE_COMMIT_TIMEOUT must be a non-negative integer" >&2; return 2; }`; `export TBOX_CUSTOMIZE_COMMIT_TIMEOUT`. Update the Phase 1.1 comment's "#2034 asks…" sentence per 8bdd559d.
- `image-versions.yaml:104-107` — `tacklebox: "ae93e9b5bacef49746cb1b08dc805c3149d7c9c8"` and #2598's comment (knob + keeps f3dd168's k8s-file fix). Keep the Renovate line and FLOOR comment above.
- `tests/bats/test_build_iso_tacklebox.bats` — port 8bdd559d's grep test and add `TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800` to the loop-eval test; add behavioural tests: (a) container path default 1800 in podman argv; (b) host path: `TACKLEBOX_FROM_SOURCE=1`, `TACKLEBOX_SHA=<sha>`, `TACKLEBOX_CACHE=$tmp` holding an executable `tacklebox` whose `version` prints the sha and whose `build` writes `env | grep ^TBOX_` to a file → contains `TBOX_CUSTOMIZE_COMMIT_TIMEOUT=1800`; (c) `0` and `2400` pass through; (d) `abc`, `-5` → status 2, message names the variable, podman stub never called; (e) caller env after return: unset stays unset (`${VAR+set}` empty), preset `2400` stays `2400`.
- Pin ancestry: verify once with a tacklebox clone (`git merge-base --is-ancestor fd95174 ae93e9b`, same for f3dd168) — done during discovery; re-confirm and note in the PR body.

**Complexity**: Low–Medium (bash `local`/`export` scoping subtleties). **Token estimate**: ~10k. **Agent strategy**: single agent, sequential.

### Phase 2.2: Record incident #1893 with a regression test, contract text and a troubleshooting row

**File changes**
- `tests/regressions/test_issue_1893_customize_commit_deadline.py` — new, from `8bdd559d` (behavioural container-path test with stub `podman`; structural pin test `!= f3dd168…`). Docstring opens with `tunaOS#1893`, has `Falsification:`.
- `docs/TACKLEBOX-CONTRACT.md` Environment contract section — add the commit-deadline paragraph from 8bdd559d (600 upstream default, 1800 adapter default, overrides, `0`, outer bound) and list `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` among the knobs.
- `docs/ci-troubleshooting.md:200` — append §4 row **42** (v4 numbered it 43 after a v4-only row 42) with SYMPTOM (600.0 s `podman commit` on skipjack:xfce, marlin:gnome/kde), CAUSE (literal 600 s in tacklebox), FIX (pin ae93e9b, adapter default 1800, outer 4800 bound, regression test path).
- Verify: `pytest tests/regressions/test_issue_1893_customize_commit_deadline.py tests/test_regression_convention.py`; falsify by temporarily removing the `:-1800` default and confirming failure; `shellcheck`/`shfmt -d` on `scripts/lib/tacklebox.sh`; STE lint.

**Complexity**: Low. **Token estimate**: ~6k. **Agent strategy**: single agent.

## Testing Strategy

- Phase 1.1: bats — v4 loop-eval, name-agnostic, splice-position, no-`--env-host` tests; new behavioural test calling the real function with a stub `podman` (exported vs unexported vs `GITHUB_TOKEN`; log line).
- Phase 1.2: STE linter on `docs/TACKLEBOX-CONTRACT.md`; manual read for accuracy.
- Phase 2.1: bats behavioural — default on container path (podman argv) and host path (fake binary env dump), `0`/`2400` passthrough, `abc`/`-5` exit 2 with podman never invoked, caller env restored (unset and preset); v4 grep test kept. shellcheck + shfmt v3.14.1.
- Phase 2.2: pytest `tests/regressions/test_issue_1893_customize_commit_deadline.py` + `tests/test_regression_convention.py`; falsification by removing `:-1800` and seeing the test fail; pytest of other tacklebox-mentioning tests (`grep -l tacklebox tests/*.py`).
- Manual (implementation test plan): first CI large-desktop ISO build after merge passes the commit step; two-week no-600/1800-s-commit-failure metric; a workflow log shows the echoed `Tacklebox environment:` line.

## Project References

- Knowledge (repo `tunaos`): conventions/regression-test-per-incident, pin-tools-in-image-versions, never-skip-or-disable-a-gate, assert-applied-state, troubleshooting-row-for-every-diagnosis, ste-prose-budget, fix-and-check-before-commit, evidence-style, main-is-canonical; gotchas/tacklebox-sha-in-workflow, sudo-resets-env-and-path; glossary/tacklebox.
- Reference commits: `771017b4` (origin/v4, #2507), `8bdd559d` (origin/pr/2598, #2598); tacklebox `ae93e9b` (#300).

## Token Management Strategy

| Tier | Token Budget | Agent Strategy |
|------|-------------|----------------|
| Low | ~10k | Single agent, sequential |
| Medium | ~25k | 2-3 parallel agents |
| High | ~50k+ | Parallel analysis, sequential integration |

All four phases are Low (≈29k total); a single agent runs them in order because every phase edits the same shell function or its test file.

## Migration Notes

None. Callers need no change. Behaviour change for callers: a malformed `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` now fails the build (exit 2) instead of being ignored by tacklebox.

## Performance Considerations

No runtime cost. A legitimately slow commit may now run up to 1800 s instead of failing at 600 s; the outer 4800 s bound is unchanged.
