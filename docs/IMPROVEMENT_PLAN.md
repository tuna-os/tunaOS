# TunaOS — Robustness, Security & E2E Testing Plan

> **📅 Last updated: 2026-06-10**
> This document is a historical record of the May 2026 improvement sprint.
> Much of the planned work has been completed. See individual phase status
> below and [ROADMAP.md](../ROADMAP.md) for current priorities.

Status: 2026-05-24 — substantial progress. Eighteen commits landed on
main across two sessions plus two upstream PRs merged. Phases 1, 2,
3a, 4.1, 4.2 effectively complete; 4.4 partial; remaining work below.

This plan covers the multi-step work requested in May 2026:
build-failure robustness, dakota-style end-to-end ISO testing, ISO
building via tacklebox for every variant, and security hardening.

---

## Shipped (this work, on main)

Commits between `12a8e92` (prior HEAD) and `ffdb9e6` (current HEAD).

| Commit | Phase | What |
|---|---|---|
| `539bb42` | hygiene | Removed stale `build.log`, `SBOM_CHANGELOG_IMPLEMENTATION.md`, `conductor/`. Fixed malformed `.gitignore` line, added `.claude/` / `.antigravitycli/`. |
| `33e11a1` | 1.1 | Pre-remove `gnome-shell-common` (48.x EL10) before installing the COPR's `gnome-shell-49` so the file-conflict that was breaking skipjack builds no longer fires. **Now superseded** by upstream `Obsoletes:` (PR below). |
| `fd7c4cc` | 1 | New `dnf_retry` helper in `lib.sh` (4 attempts, exponential backoff, metadata clear). Used for the RHEL/Alma main desktop install that pulls `gum` from EPEL — the actual cause of albacore CI failures. |
| `901d075` | 2 | E2E harness: `tunaos-live-ready.service` systemd unit, `scripts/iso-e2e.sh` QEMU+OVMF host runner with screenshot+serial-log capture, `.github/workflows/iso-e2e.yml` workflow with R2 ISO download and artifact upload. |
| `4363b64` | 2 | Narrowed iso-e2e PR trigger paths so it only fires when the harness itself changes. |
| `f85b851` | 4.2 | Pinned 4 unique third-party GitHub Actions to commit SHAs across 9 workflows. Closes the floating-ref supply-chain risk for `ublue-os/container-storage-action@main`, `hanthor/changelog-action@master`, and v* tags. |
| `1be982c` | 4.1 | RHSM credentials via BuildKit secret. Justfile materialises a mode-0600 tempfile and passes `--secret id=rhsm`; Containerfile mounts it at `/run/secrets/rhsm` for one RUN only. No more leaks via `podman inspect` *or* `podman history --no-trunc`. |
| `f967658` | 3a | New `scripts/build-iso-tacklebox.sh` + `just iso-tacklebox` recipe. Pinned SHA / source build in `/var/cache/tunaos/tacklebox`. Added *alongside* `just live-iso`, not as a replacement. |
| `8efe55f` | docs | Plan doc updated mid-session. |
| `970042d` | 2 + KDE | Two fixes in one commit: filter mismatched matrix cells in `iso-e2e.yml` and fetch the exact `<variant>-<flavor>-latest.iso` name (the rclone glob was over-matching `-nvidia-latest.iso`). Plus KDE Plasma live-environment block in `live-iso/common/src/build.sh` — SDDM autologin, kscreenlocker off, power profile no-sleep, suspend targets masked — lifted from `hanthor/tromso-iso`. |
| `0c9466e` | catch-up fix | `fire-copilot-batch.py` exits 0 with a warning instead of raising when `COPILOT_PAT` is missing or rejected. Unblocked Watch Aurora / Bluefin-LTS / Zirconium workflows that had been failing on every scheduled run since 2026-05-18. |
| `711e88b` | 2 | Install `qemu-utils` in `iso-e2e.yml` so `qemu-img create` doesn't silently no-op. Surface the missing-binary case in `iso-e2e.sh` with exit 77. |
| `5629307` | catch-up fix | Broaden the auth-failure signal set in `fire-copilot-batch.py` — `gh auth status` reports invalid tokens with friendlier strings than the raw API's "401 Bad credentials". |
| `bbf6691` | 3a→ | `build-iso-tacklebox.sh` now prefers `ghcr.io/tuna-os/tacklebox:latest` (published by the upstream PR landed this session). Source build still available via `TACKLEBOX_FROM_SOURCE=1`. |
| `27a8947` | catch-up | Watch-upstream commit filter now skips `chore(ci):`, `fix(ci):`, `chore(release):`, `fix(workflow):`, merge commits, and similar. Saves Gemini API calls on commits Gemini was reliably deciding not to port. |
| `ffdb9e6` | 4.4 | `set -euo pipefail` on `lib.sh`, `00-workarounds.sh`, `scripts/rechunk.sh`. Other `build_scripts/*.sh` left at their existing mix pending per-file verification. |

Validation on every commit: `shellcheck --exclude=SC1091`, `shfmt -d`,
`yamllint`, `actionlint`, `just --unstable --fmt --check`.

## Shipped upstream

- **`tuna-os/github-copr#23`** (merged): `Obsoletes: gnome-shell-common < %{major_version}` + matching `Provides:` in both gnome-49 and gnome-50 specs. Replaces the local workaround in commit `33e11a1`; that workaround can be removed once the COPR rebuilds and a fresh skipjack build confirms the file-conflict is gone.
- **`tuna-os/tacklebox#1`** (merged): two-stage `Containerfile` + `release-image.yml` publishing `ghcr.io/tuna-os/tacklebox:latest` on every main push and `:vX.Y.Z` on tags. Multi-arch (linux/amd64 + linux/arm64) with build-provenance attestation. Downstream `build-iso-tacklebox.sh` switched to the published image in commit `bbf6691`.

---

## Build failures that need deeper work

| Variant | Root cause | Where |
|---|---|---|
| `skipjack` | `gnome-shell-50.x` conflicts with `gnome-shell-common-48.3` on the same files (`/usr/share/glib-2.0/schemas/org.gnome.shell.gschema.xml`). Intrinsic to upstream packaging; needs COPR coordination. | `gnome.sh` line 32–44 invokes `gnome50-el10-compat`; both pull the new gnome-shell while CentOS Stream 10 ships the older one. |
| `bonito` | `bootc container lint --fatal-warnings` reports `Checks failed: 3`. The `\|\| true` mask is gone (now routed through `lint_image` in `lib.sh`, which surfaces every finding into the build-log group + step summary; #272). Findings are visible but not yet build-fatal — set `BOOTC_LINT_FATAL=1` for bonito once the three are fixed. | `cleanup.sh` → `lint_image` (`lib.sh`) |
| `yellowfin` | Actually succeeded in the last logged run (cache sync complete). The "Unknown variant" error in `build.log` was a separate invocation typo. | n/a |

Proposed treatment: phase 1 below.

---

## Phase 1 — Finish robustness work

Goal: clean baseline builds for every variant without `|| true` masking
real failures.

1. **Diagnose & fix skipjack gnome-shell conflict.** Two paths:
   - Update `tuna-os/github-copr` `gnome50-el10-compat`
     to obsolete `gnome-shell-common < 49` so DNF auto-removes the older
     conflicting package. Preferred.
   - Or, in `gnome.sh`, `dnf -y remove gnome-shell-common` before the
     compat install (only on `IS_CENTOS` / `IS_ALMALINUXKITTEN`). Fallback.
2. **Surface bonito's three lint failures.** ✅ Done — `cleanup.sh` now
   calls `lint_image` (`lib.sh`), which runs `bootc container lint
   --fatal-warnings`, prints the full findings in a collapsed log group,
   and mirrors them into `$GITHUB_STEP_SUMMARY`. **Remaining:** read the
   three findings off a bonito CI run, fix the underlying tmpfiles.d /
   var-state issues, then set `BOOTC_LINT_FATAL=1` for bonito so the lint
   becomes the product-quality gate it should be.
3. **Move the "remove `/var/lib/insights` etc." cleanup** out of the
   per-variant `cleanup.sh` block — `skipjack`'s log shows 7 warnings
   from `file ... remove failed: No such file or directory` because the
   paths don't exist on CentOS. Guard with `if [ -e "$path" ]`.
4. **Idempotent `tracker-extract-3.service` preset** — silence the
   benign-but-noisy warning on `albacore` by shipping a `preset-all`
   ignore line in `system_files/usr/lib/systemd/system-preset/`.

Estimate: 1 day, contained to `build_scripts/` + `github-copr` PR.

---

## Phase 2 — Dakota-style E2E ISO smoke tests

`projectbluefin/dakota-iso` ships a complete reference implementation that
I've already read (see `.github/workflows/test-luks-install.yml` and the
QEMU `luks-*-qemu` recipes in its `justfile`). Key patterns to lift:

- **QEMU + OVMF + KVM** boot of the live ISO; no libvirt required so it
  runs on GitHub-hosted runners with KVM enabled.
- **Readiness probe**: a serial-console marker (`DAKOTA_LIVE_READY`) OR
  SSH connect on a hostfwd port. We add `TUNA_LIVE_READY` in a tiny
  systemd unit that writes to `/dev/console`.
- **Screenshot via QEMU monitor**: `socat - UNIX-CONNECT:$monitor <<<
  "screendump /tmp/foo.ppm"`. Convert to PNG with ImageMagick, commit
  to a `ci-screenshots` branch, link from PR comments.
- **Serial logs as artifacts** via `actions/upload-artifact@v4`.

What I'd add to TunaOS:

### 2a. `scripts/iso-e2e.sh`
New top-level script that takes `<variant> <flavor>` and an existing ISO
path; daemonises a QEMU instance, waits for the live env marker, exercises
**three** install paths, and emits artifacts.

The three install paths we should cover (one per matrix leg, parallel):

1. **Anaconda kickstart install** — boots `tests/anaconda-ks.cfg`, lets
   the existing kickstart drive auto-partition + reboot, verifies the
   installed disk boots and `gdm` reaches the login screen.
2. **bootc-direct install** — the live env runs `bootc install to-disk
   /dev/vda` (the path the GNOME Initial Setup wizard would also take).
   Verifies the no-installer path.
3. **LUKS install** — same as dakota-iso but using anaconda's encryption
   prompt instead of fisherman. Catches dracut/cryptsetup regressions.

### 2b. `.github/workflows/iso-e2e.yml`
Mirrors `dakota-iso/.github/workflows/test-luks-install.yml`:
- Matrix over `{yellowfin, albacore} × {gnome, gnome-hwe}` (the variants
  that publish ISOs per `.github/build-config.yml`).
- `pull_request` trigger gated by `paths:` filter on the build inputs
  (`Containerfile*`, `build_scripts/**`, `live-iso/**`, `system_files*/**`).
- Weekly schedule for regression detection.
- Posts PR comment with screenshots + serial-log tail.

### 2c. `tests/live-ready/`
New systemd oneshot unit + dropin that prints `TUNA_LIVE_READY` to the
serial console once gdm + NetworkManager + flatpak remotes are ready.
Installed into the live ISO container only — gated by `ENABLE_LIVE_READY=1`
ARG in `live-iso/common/Containerfile`.

### 2d. `tests/iso-verify.py`
Replaces today's stub in `tests/lima-template.yaml` (which is currently
just a Lima config, not a verifier). Connects to the QEMU monitor + serial
log; asserts:
- `gdm.service` reached `active` within 90 s
- No `Failed to start` in the journal
- The fstab / `bootc status` matches the expected image-info JSON.

Estimate: 3–5 days, mostly QEMU/CI debugging.

---

## Phase 3 — Tacklebox-based ISO builds for all variants

`tuna-os/tacklebox` (which I now realise is a sibling repo in the same
org) is a Go-based bootc → ISO/block-image builder. It's strictly more
powerful than the current `image-builder-cli`-based ISO path because it
supports multi-env media, but for single-env ISOs it's also simpler and
removes the patched `image-builder-dev` from the critical path.

What changes for TunaOS:

### 3a. Adopt tacklebox in `live-iso/`
Replace `live-iso/common/build.sh` + `live-iso/common/Containerfile` (and
the patched `image-builder-cli` clone inside `scripts/build-live-iso.sh`)
with a thin wrapper that:

1. Pulls `ghcr.io/tuna-os/tacklebox:latest` (a release artifact tacklebox
   already publishes via its `ci.yml`).
2. Generates a recipe per `(variant, flavor)` from a template like:

   ```json
   {
     "media_name": "{{variant_upper}}-{{flavor}}",
     "shared_store": { "format": "ext4" },
     "bootable_environments": [
       {
         "id": "{{variant}}-{{flavor}}",
         "image": "{{image_ref}}",
         "desktop": "{{desktop_flavor}}",
         "modes": ["live"]
       }
     ]
   }
   ```

3. Invokes `tacklebox build <recipe> --iso <output.iso>`.

### 3b. New Justfile recipes
```
iso variant flavor='gnome' repo='local' tag='':
    ./scripts/build-iso-tacklebox.sh {{variant}} {{flavor}} {{repo}} {{tag}}

iso-all:
    # Build ISOs for every variant×flavor that has build_iso: true in
    # .github/build-config.yml. Replaces the per-variant manual invocation.
```

The existing `live-iso variant flavor repo tag dev` recipe stays as a
compatibility alias for one release cycle, then is removed.

### 3c. Per-variant ISO publishing in CI
`.github/workflows/publish-isos.yml` today only publishes
`yellowfin-gnome` and `albacore-gnome`. With tacklebox-driven builds
generating ISOs in ~10 minutes (vs ~30 today), enable ISO publishing
for every variant×flavor where the `build-config.yml` matrix has
`build_iso: true`. The matrix already exists — we'd consume it in
`publish-isos.yml`.

### 3d. Verify the tacklebox-built ISOs
Reuse Phase 2's `iso-e2e.sh` against tacklebox output. Tacklebox's own
`verify` command (`tacklebox verify <iso>`) is a complementary sanity
check we should also call as a pre-step.

Risks:
- Tacklebox is young (created 2026-05-10 per its GitHub metadata). We
  need to vendor a release SHA, not `:latest`.
- Tacklebox is multi-env-first; for single-env ISOs we're using a tiny
  slice of its surface area. Watch for regressions affecting that slice.
- ISO size: tacklebox uses `mksquashfs` directly (vs anaconda's
  installer ISO format). Live ISO size will change; downstream rclone
  publishing may need an updated size hint.

Estimate: 1–2 weeks. Tacklebox integration is mostly mechanical; the
publishing matrix change touches the most CI surface area.

---

## Phase 4 — Security hardening

Findings from the audit pass (severity descending):

1. **RHSM credentials in build history** (P1). Phase 0 removed them from
   `ENV`, but they're still substituted into the `RUN` command and visible
   in `podman history --no-trunc`. Fix: convert to BuildKit secrets:
   ```
   RUN --mount=type=secret,id=rhsm,target=/run/secrets/rhsm \
     bash -c "source /run/secrets/rhsm && install_base_packages_no_de"
   ```
   Justfile sets the secret from `$RHSM_*` env at build time. Touches:
   `Containerfile`, `Justfile`, `build_scripts/10-base-packages.sh`,
   `.github/workflows/reusable-build-image.yml` (CI side).
2. **Unpinned GitHub Actions** (P2). 32 actions referenced by `@v4` /
   `@v7` rather than commit SHA. Some are first-party (`actions/*`),
   relatively safe; some are third-party (`google-github-actions/run-
   gemini-cli@v0.1.22`, `jlumbroso/free-disk-space@main`) — those are
   the priority. Pin every third-party action to a SHA, document the
   versioned upgrade in `renovate.json5`.
3. **`--security-opt label=disable` everywhere** (P3). Used in every
   `podman build` in the Justfile and most workflow steps. SELinux
   labelling is disabled because the build mounts the repo in. The
   safer pattern is `:Z` on the bind mount, which relabels just that
   path. Plumb through where feasible; document where it isn't.
4. **`set -eo pipefail` (no `-u`)** in several `build_scripts/*` (P3).
   Unset-variable errors slip through silently. Standardise on
   `set -euo pipefail` and add `:-` fallbacks where intentional.
5. **`bootc container lint --fatal-warnings || true`** (P2). Already
   called out in Phase 1; tracking here for closure.
6. **Scorecard score** (P3). `scorecard.yml` runs but isn't gating.
   Once the above are addressed, fail the workflow on regressions.

Estimate: 3–5 days, mostly mechanical PR work + one cosign/rekor
verification pass.

---

## Phase 5 — Documentation & developer-experience polish

Optional but improves the bus factor:

- Update `docs/AGENT_GUIDE.md` Troubleshooting section with the
  `dnf_retry` behaviour and where to look in `.build-logs/`.
- Add `docs/TESTING.md` explaining the Phase 2 e2e harness:
  how to run `just iso-e2e <variant> <flavor>` locally, how to read
  serial logs, how to interpret screenshot artifacts.
- Add a `tests/README.md` documenting `anaconda-ks.cfg`,
  `live-iso-verify.yaml`, and the new `live-ready/` unit.

Estimate: 1 day, can land alongside any of the above.

---

## Remaining work (next session)

Most impactful items first:

1. **Phase 3b — Tacklebox CI integration.** Wire `just iso-tacklebox`
   into a workflow that builds and publishes an ISO for every
   variant×flavor with `build_iso: true` in `.github/build-config.yml`.
   Right now only `yellowfin-gnome` and `albacore-gnome` get published
   (in `publish-isos.yml`); the matrix already supports more. Likely
   touches `.github/workflows/publish-isos.yml` and `iso-e2e.yml`.
2. **Phase 2 follow-up — kickstart mode.** `scripts/iso-e2e.sh
   --kickstart KS` is currently stubbed (exit 3). Implement: copy
   kickstart to a virtual floppy, append `inst.ks=hd:fd0` to kernel
   cmdline, watch for `/var/log/anaconda` completion via the QEMU
   monitor. Reuse `tests/anaconda-ks.cfg` as the default.
3. **Phase 2 follow-up — per-PR ISO build.** Currently `iso-e2e.yml`
   downloads from R2, which means PR changes aren't actually tested.
   Add a `pull_request`-triggered job that builds the ISO locally (via
   the new `iso-tacklebox` path — much faster than the anaconda path)
   and runs the harness against that. ~25 min budget on a free runner.
4. **Phase 4.3 — `--security-opt label=disable`.** Used in every
   `podman build` in the Justfile and most workflow steps. SELinux
   labelling is disabled because the build mounts the repo in. The
   safer pattern is `:Z` on the bind mount, which relabels just that
   path. Plumb where feasible; document where it isn't.
5. **Phase 4.4 — `set -euo pipefail` consistency.** Several
   `build_scripts/*` files use `set -eo pipefail` only — unset-variable
   errors slip through silently. Standardise on `set -euo pipefail`
   and add `:-` fallbacks where intentional.
6. **Phase 1.2 — surface bonito's three lint failures.** Remove the
   `|| true` from `cleanup.sh:117` for `IS_FEDORA`, capture the exact
   warnings, fix the underlying tmpfiles.d / var-state issues. The
   `.build-logs/` snapshot is from March 2026; later commits to
   `cleanup.sh` may have already resolved these. Verify against a
   fresh build before removing the mask.
7. **Phase 5 — docs polish.** ✅ COMPLETE (PR #319 + follow-up commit `a7c87f0`). AGENT_GUIDE Troubleshooting updated with dnf_retry, flavor table modernized to 4-stage DAG, Key Files expanded with Containerfile.hwe, Commands examples fixed (dx/nvidia→gnome/gnome-nvidia). docs/TESTING.md and tests/README.md added. build-pipeline.md fully rewritten: 5 variants, unified build-variant.yml, tacklebox, iso-e2e.

## Upstream work (separate repos)

- **`tuna-os/github-copr`** — add `Obsoletes: gnome-shell-common < %{major_version}`
  to `src/gnome-49/gnome-shell/gnome-shell.spec` and the matching
  `gnome-50` spec. Once that lands, the workaround in `build_scripts/desktop/gnome.sh:48`
  (commit `33e11a1`) can be removed.
- **`tuna-os/tacklebox`** — publish a release container image so we
  don't have to `go build` from source each time. The `scripts/build-iso-tacklebox.sh`
  fallback to building from source will still work as a development
  shortcut, but releases are nicer for CI.
