# TunaOS — Robustness, Security & E2E Testing Plan

Status: 2026-05-23 — proposal, not yet approved.

This plan covers the multi-step work the user requested in May 2026:
build-failure robustness, dakota-style end-to-end ISO testing, ISO building
for every variant via tacklebox, and security hardening. The low-risk
build-robustness fixes are already landed (see the **Already shipped**
section); everything else is staged for review and approval.

---

## Already shipped (this branch)

These are the low-risk fixes I implemented immediately because the failure
modes were obvious and the changes were contained.

1. **`build_scripts/lib.sh`** — added a `dnf_retry` helper that retries
   transient mirror failures (`SSL_ERROR_SYSCALL`, partial-file, slow
   mirror) up to 4 times with backoff, clearing metadata between attempts.
   Real transaction errors still fail fast.
2. **`build_scripts/00-workarounds.sh`** —
   - Moved the rpm-ostree kernel-install hook mask from `gnome.sh` to here,
     so **all** variants (including `bonito` base, which doesn't run
     `gnome.sh`) silence the `dracut-install: ERROR: installing '/root'`
     warning.
   - Extended the AlmaLinux-only DNF reliability settings (`timeout=300`,
     `retries=10`, `minrate=100`, `max_parallel_downloads=10`) to **all**
     RPM-based variants. EPEL and CentOS mirrors fail just as often.
3. **`build_scripts/10-base-packages.sh`** — wrapped the EPEL-multimedia
   install **and** the RHEL/Alma main desktop install in `dnf_retry`. The
   second one is what was killing `albacore` builds when `gum` /
   `distrobox` / `fastfetch` downloads stalled (EPEL has no retry today).
4. **`Containerfile`** — removed `ENV RHSM_USER/PASSWORD/ORG/ACTIVATION_KEY`
   from the `base-no-de` stage. Those bake credentials into the image
   config (visible to anyone who pulls the image via `podman inspect`).
   They're now passed inline to the one `RUN` that needs them.
   *Caveat:* this still leaks into `podman history --no-trunc`. Full fix
   below requires BuildKit secrets — staged for Phase 4.

Validation: `shellcheck --exclude=SC1091`, `shfmt -d`, `yamllint` all clean
on the changed files.

---

## Build failures that need deeper work

| Variant | Root cause | Where |
|---|---|---|
| `skipjack` | `gnome-shell-49.4` conflicts with `gnome-shell-common-48.3` on the same files (`/usr/share/glib-2.0/schemas/org.gnome.shell.gschema.xml`). Intrinsic to upstream packaging; needs COPR coordination. | `gnome.sh` line 32–44 invokes `gnome49-el10-compat` / `gnome50-el10-compat`; both pull the new gnome-shell while CentOS Stream 10 ships the older one. |
| `bonito` | `bootc container lint --fatal-warnings` reports `Checks failed: 3` — currently swallowed by `|| true` in `cleanup.sh`. The lint warnings hide actual image-quality regressions. | `cleanup.sh:60` |
| `yellowfin` | Actually succeeded in the last logged run (cache sync complete). The "Unknown variant" error in `build.log` was a separate invocation typo. | n/a |

Proposed treatment: phase 1 below.

---

## Phase 1 — Finish robustness work

Goal: clean baseline builds for every variant without `|| true` masking
real failures.

1. **Diagnose & fix skipjack gnome-shell conflict.** Two paths:
   - Update `tuna-os/github-copr` `gnome49-el10-compat` / `gnome50-el10-compat`
     to obsolete `gnome-shell-common < 49` so DNF auto-removes the older
     conflicting package. Preferred.
   - Or, in `gnome.sh`, `dnf -y remove gnome-shell-common` before the
     compat install (only on `IS_CENTOS` / `IS_ALMALINUXKITTEN`). Fallback.
2. **Surface bonito's three lint failures.** Remove the `|| true` from
   `cleanup.sh:60` for `IS_FEDORA`, capture the exact warnings, and fix
   the underlying tmpfiles.d / var-state issues. The lint is the
   product-quality gate for bootc images; it shouldn't be muted.
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

## Suggested ordering

```
Phase 1 (robustness)   ──┐
                         ├─► Phase 2 (e2e) ──┐
Phase 4 (security)    ───┘                   ├─► Phase 3 (tacklebox)
                                             │
                            Phase 5 (docs) ──┘
```

Phase 1 and Phase 4 can run in parallel — different files, different
failure modes. Phase 2 wants Phase 1 done first (clean builds make the
e2e signal trustworthy). Phase 3 wants Phase 2 ready so we can verify
tacklebox-built ISOs against the same harness. Phase 5 can interleave.

If forced to pick a single next step: **Phase 1.1** (fix the skipjack
GNOME conflict in `tuna-os/github-copr`) unblocks the most users
immediately and is a contained one-PR change.
