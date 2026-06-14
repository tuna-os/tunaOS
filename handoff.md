# Handoff: Grouper (Ubuntu 26.04) CI — Tracer Bullet Loop

**Goal**: Get the grouper variant green end-to-end in CI — base builds, desktop
flavors build, ISOs publish. Method: TDD tracer bullets — one CI failure → one
fix → repeat.

**Build config**
- Variant: `grouper` (🐟), Ubuntu 26.04 "Resolute Raccoon"
- Base image: `docker.io/library/ubuntu:resolute` (via `Containerfile.ubuntu`)
- Platforms: `linux/amd64` only (experimental)
- Flavors: `base` (stage 1), `gnome` (stage 2, builds ISO)

## Current state

### ✅ Green
- **Stage 1 (base)**: builds, manifests, tags.
- **Stage 2 (gnome)**: builds, manifests, tags.
- ISO `podman unshare` no longer fails — nested-sudo `SUDO_USER` clobber fixed
  by calling `build-iso-tacklebox.sh` directly from the workflow (commit
  `356466a`) + subuid/subgid mappings for the runner (commit `04205ca`).

### 🔧 Latest fix (uncommitted at time of writing → see git log)
**ISO live squash: "image not known"** — `build_artifacts_s2` pulled the gnome
image into **root's** podman store (tacklebox `Pull()` runs `podman pull` as
root), but the live squash mounts it via `sudo -u runner podman unshare`, which
reads the **runner's rootless** store. Mismatch → `Error: ghcr.io/tuna-os/
grouper:gnome-linux-amd64: image not known`.

Fix: `scripts/build-iso-tacklebox.sh` now pre-pulls the registry image into the
invoking user's rootless store (when `REPO != local` and `SUDO_USER` is a real
user), mirroring how the `local` path lands the image in the user store. The
root-side pull tacklebox still does feeds the install/metadata steps; both
stores end up with the image.

Relevant tacklebox source (pinned SHA `75c837b`):
- `internal/install/bootc.go` `Pull()` — `podman pull` as root → root store.
- `internal/install/live.go` `InstallLive` + `RunUnshare` — squash via
  `sudo -u $SUDO_USER podman unshare` → user rootless store.
- `internal/install/user_podman.go` `UserCommandPrefix` — the drop-to-user logic.

## Key files modified (this effort)

| File | Purpose |
|------|---------|
| `scripts/build-iso-tacklebox.sh` | Absolute paths; pre-pull registry image into user rootless store for live squash |
| `.github/workflows/build-variant.yml` | PkgS2 ISO step — direct script call, subuid/subgid setup |
| `.github/workflows/reusable-build-image.yml` | Manifest job wolfi-base digest fix |
| `build_scripts/bootc/finalize.sh` | `/var/tmp` recreation after mount-system.sh wipe |
| `build_scripts/40-services.sh` | apt branch for Ubuntu service setup |
| `build_scripts/90-image-info.sh` | mkdir for /usr/share/ublue-os |
| `Containerfile.ubuntu` | jq install in base stage |
| `Justfile` | `sudo -E` in iso recipe |

## If the live squash still fails after this fix
- The runner-rootless pull needs GHCR auth **only if the package is private**.
  The grouper packages are currently public (root pull succeeded with no
  `podman login`). If they go private, add `sudo -u runner podman login ghcr.io`
  before the ISO step, or pass the image via `podman save | podman load`.
- Diagnose on the runner: `sudo -u runner podman unshare -- podman image exists
  ghcr.io/tuna-os/grouper:gnome-linux-amd64` and `sudo -u runner podman info`.

## Suggested skills
- `tdd` — each CI cycle is red→green.
- `diagnose` — for deeper podman storage / unshare issues.
