# Plan: PRs for open tunaOS issues

Spec + implementation plan for turning the actionable open issues on
`tuna-os/tunaOS` into PRs. Written 2026-06-13.

## Triage of open issues

| Issue | Title | PR-able? | Plan |
|-------|-------|----------|------|
| #462 | [sec-check] Mutable `:latest` tag for wolfi-base | ✅ Yes — small | Pin to digest |
| #461 | [sec-check] `secrets: inherit` in generated workflows | ✅ Yes — medium | Declare + pass explicit secrets |
| #463 | [quality] `build_scripts/`: 17 scripts, zero tests | ⚠️ Large | Out of scope for now (see notes) |
| #464 | [quality] `scripts/`: 4 scripts lacking BATS tests | ◑ Maybe — focused slice | Optional: `verify-iso.sh` test |
| #272 | [strategist] Bonito (Fedora 44) variant incomplete | ❌ Epic | Not a single PR |
| #454 | Weekly Boot Report | ❌ Auto-generated report | No PR |
| #457 | Hive Advisory Report | ❌ Auto-generated report | No PR |

Each actionable fix lands as its **own PR** (one issue → one PR), branched from
`main`, closing the issue via `Closes #N`.

---

## PR 1 — #462: Pin wolfi-base to a SHA256 digest

### Problem
`.github/workflows/reusable-build-image.yml:326` runs the `summarize` job in
`cgr.dev/chainguard/wolfi-base:latest`. `:latest` is mutable; the job runs
`--privileged --security-opt seccomp=unconfined`, so a repointed/compromised
image could tamper with artifacts or exfiltrate secrets.

### Change
- Resolve the current digest:
  ```bash
  skopeo inspect --no-tags docker://cgr.dev/chainguard/wolfi-base:latest \
    --format '{{.Digest}}'
  # or: podman pull … && podman inspect … --format '{{.Digest}}'
  ```
- Replace line 326:
  ```yaml
  # before
  image: cgr.dev/chainguard/wolfi-base:latest
  # after
  image: cgr.dev/chainguard/wolfi-base@sha256:<digest>  # :latest as of 2026-06-13
  ```
- Add a trailing comment noting the tag/date so Renovate (or a human) can bump it.

### Verification
- `yamllint`/`actionlint` on the workflow.
- Confirm Renovate is configured to track digest pins (check `renovate.json`);
  if it has a `helmv3`/`docker` digest rule, the pin will be auto-updated. If
  not, note it in the PR so the pin doesn't rot.

### Risk
Low. Pure pin; behaviour identical until the digest is intentionally bumped.

---

## PR 2 — #461: Remove `secrets: inherit` from generated build workflows

### Problem
`scripts/generate-workflows.py:37` emits `secrets: inherit` into every
generated `build-<variant>.yml` (albacore, bonito, skipjack, yellowfin). Those
workflows call `build-variant.yml`, which therefore receives **all** repo
secrets (COSIGN/SIGNING key, RHSM creds, R2 keys, tokens) regardless of need —
violating least privilege.

### Secret inventory (verified)
`build-variant.yml` is the only callee of the generated workflows. It uses
exactly **5** secrets and calls only `reusable-build-image.yml`:

| Secret | Used at | Purpose |
|--------|---------|---------|
| `SIGNING_SECRET` | passed to `reusable-build-image.yml` (lines 197/224/248/272) | cosign image signing |
| `R2_ACCESS_KEY_ID` | container-storage-action + rclone (299/318/338/433) | R2 upload |
| `R2_SECRET_ACCESS_KEY` | same | R2 upload |
| `R2_ENDPOINT` | same | R2 upload |
| `R2_BUCKET` | same | R2 upload |

`reusable-build-image.yml` declares only `SIGNING_SECRET` in its
`workflow_call.secrets` and otherwise uses the auto-provided `GITHUB_TOKEN`
(not an inheritable secret). No other reusable workflow is involved.

### Change
1. **`build-variant.yml`** — add a `secrets:` block under `on.workflow_call`
   declaring all 5 (mark `required: false` to match the existing
   `SIGNING_SECRET` pattern and avoid breaking manual dispatch):
   ```yaml
   on:
     workflow_call:
       inputs: { … }            # unchanged
       secrets:
         SIGNING_SECRET:        { required: false }
         R2_ACCESS_KEY_ID:      { required: false }
         R2_SECRET_ACCESS_KEY:  { required: false }
         R2_ENDPOINT:           { required: false }
         R2_BUCKET:             { required: false }
   ```
   (No change to how the secrets are *used* inside the file.)
2. **`scripts/generate-workflows.py:37`** — replace the template's
   `    secrets: inherit` with an explicit mapping:
   ```yaml
       secrets:
         SIGNING_SECRET: ${{ secrets.SIGNING_SECRET }}
         R2_ACCESS_KEY_ID: ${{ secrets.R2_ACCESS_KEY_ID }}
         R2_SECRET_ACCESS_KEY: ${{ secrets.R2_SECRET_ACCESS_KEY }}
         R2_ENDPOINT: ${{ secrets.R2_ENDPOINT }}
         R2_BUCKET: ${{ secrets.R2_BUCKET }}
   ```
   (Mind the `${{{{ }}}}` escaping — the template is a `str.format` string, so
   literal `${{ }}` must be written as `${{{{ }}}}`.)
3. **Regenerate** the 4 files: `python3 scripts/generate-workflows.py` (or the
   `just generate-workflows` recipe), then commit the regenerated
   `build-{albacore,bonito,skipjack,yellowfin}.yml`.

### Verification
- `git diff` shows only `secrets: inherit` → explicit mapping in the 4 generated
  files + the generator + the new declaration block in `build-variant.yml`.
- `actionlint` passes (it validates `secrets:` mappings against the callee's
  declared secrets — this is why step 1 is mandatory).
- Sanity: every secret the generated workflow passes is declared in
  `build-variant.yml`, and every `secrets.X` used in `build-variant.yml` is in
  the declared set.

### Risk
Medium — touches the live build pipeline's credential flow. If a secret is
missed, signing or R2 upload silently fails. Mitigated by the verified
inventory above and `actionlint`. Worth a maintainer review before merge.

---

## PR 3 (optional) — #464: BATS test for `verify-iso.sh`

### Problem
`scripts/verify-iso.sh` (161 lines) gates ISO quality but has no BATS test,
unlike its sibling `verify-image.sh`.

### Plan
- Mirror the existing `verify-image.sh` BATS test structure (find it under
  `tests/`) for parity of style (mocking `podman`/`xorriso`, arg parsing,
  error paths).
- Scope to `verify-iso.sh` only; leave `run-vm.sh`, `pipeline-overview.sh`,
  `simulate-matrix.sh`, and the broader `build_scripts/` coverage (#463) as
  follow-ups, since those are higher-effort and benefit from a maintainer
  steer on desired coverage depth.

### Risk
Low — test-only, no production code change. Defer unless explicitly wanted.

---

## Out of scope (this round)
- **#463** — 17 build scripts; high effort, needs a coverage-strategy decision.
- **#272** — strategic epic (Bonito completeness); not a single PR.
- **#454 / #457** — automated reports, not code.

## Sequencing
1. PR 1 (#462) — independent, lowest risk, merge first.
2. PR 2 (#461) — independent; request maintainer review for the credential flow.
3. PR 3 (#464) — optional, only if test coverage is wanted now.
