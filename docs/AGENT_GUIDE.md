# TunaOS Agent Guide

Authoritative reference for AI agents working on the TunaOS repository. All other agent-specific files (`CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.github/copilot-instructions.md`) point here.

---

## What This Project Is

TunaOS is a **bootc-based OS image builder** — it produces bootable OCI container images that serve as complete, immutable desktop Linux operating systems deployable via bootc/rpm-ostree. This is not traditional software; the build output is a container image, not a binary.

---

## Variants and Flavors

### Variants (base OS)

| Variant | Base | Status |
|---|---|---|
| `yellowfin` | AlmaLinux Kitten 10 | Stable |
| `albacore` | AlmaLinux 10 | Stable |
| `skipjack` | CentOS Stream 10 | Beta |
| `bonito` | Fedora 44 | In progress |
| `grouper` | Ubuntu 26.04 (bootcified, `Containerfile.ubuntu`) | Experimental, amd64-only |

### Flavors (layered via 4-stage DAG; see `.github/build-config.yml` for full matrix)

| Layer | Flavors | Contents |
|---|---|---|
| Stage 1 — base | `base` | Minimal OS (all variants) |
| Stage 2 — HWE/nvidia base + desktops | `base-hwe`, `base-nvidia`, `gnome`, `gnome50`, `cosmic`, `kde`, `niri`, `xfce` | DE packages; HWE coreos kernel; nvidia NVIDIA base |
| Stage 3 — HWE/nvidia desktops | `<de>-hwe`, `<de>-nvidia` (e.g. `gnome-hwe`, `kde-nvidia`) | DE layered on HWE/nvidia base |
| Stage 4 — combined | `gnome-nvidia-hwe` | GNOME + nvidia + HWE (layers on `gnome-hwe`) |

Flavor availability varies per variant — consult `.github/build-config.yml`.
- `bonito` has fewer HWE/nvidia combos (no `gnome50`, fewer non-GNOME HWE layers).
- HWE flavors ship the `coreos/fedora` kernel + `ublue-os/akmods-nvidia-open`.
- `xfce` on EL10 is the **hanthor/xfce-wayland** port (xfwl4 compositor) from
  repo.tunaos.org — EL10 x86_64 only, hence its platform restrictions.
  bonito/grouper ship stock X11 XFCE. See `docs/PIPELINE.md`.
- `grouper` builds only `gnome`, `kde`, `niri`, `xfce` (apt branches in
  `build_scripts/*.sh`; `cosmic.sh` has no apt branch).

---

## Setup

Install `just` via Homebrew for consistency with CI:

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install just
```

**NEVER** extract tools directly into the repository root — always use `/tmp` to avoid overwriting project files.

Other requirements:
- `podman` — required for container builds
- `shellcheck` — required for linting (`sudo apt-get install -y shellcheck`)
- Root privileges — required for ISO/VM image generation

---

## Commands

```bash
# Format and validate — run before every commit (mandatory)
just fix        # Format shell scripts and Justfile
just check      # shellcheck, yamllint, jq, actionlint

# Build a single variant + flavor (fastest test)
just yellowfin base

# Build a chain (each depends on previous stage)
just yellowfin base && just yellowfin gnome && just yellowfin gnome-nvidia

# Build shortcuts (all default to base flavor)
just yellowfin [flavor]
just albacore [flavor]
just skipjack [flavor]
just bonito [flavor]

# Batch builds
just build-all           # All stable variants, all flavors
just build-all-base      # Base flavor only for all variants

# ISO / VM generation (requires root, adds 20-30 min)
sudo just iso <variant> <flavor> <local|ghcr>
sudo just iso-tacklebox <variant> <flavor> <local|ghcr> <tag>
sudo just qcow2 <variant> <flavor> <local|ghcr>

# Verification (the same gates CI enforces before publishing)
just lint                          # shellcheck + yamllint, mirrors lint.yml
just test                          # bats + pytest, mirrors test.yml
just verify-disk <image.qcow2>     # QEMU boot gate for a disk image
./scripts/iso-e2e.sh <file.iso>    # QEMU boot gate for a live ISO

# Cleanup
just clean               # Remove build artifacts and images (preserves .rpm-cache)
just clean-cache         # Remove DNF/RPM cache only
just --list              # Show all available commands
```

---

## Pre-Commit Workflow (mandatory)

1. `just fix` — format code
2. `just check` — validate syntax
3. `git diff` — review changes
4. Commit only after both pass

`shellcheck` SC1091 is excluded (sourced file path detection).

---

## When to Build Images

| Change type | Build required? |
|---|---|
| `Containerfile*`, `build_scripts/*`, `system_files*` | **Yes — always** |
| `scripts/*` | Sometimes (if testing ISO/VM) |
| Docs, CI workflows, README | No |

---

## Build Timing

- **First build (cold cache):** ~45-60 minutes
- **Subsequent builds (warm cache):** ~25-35 minutes
- **NEVER cancel a build early** — CI timeout is 60 minutes; local builds should allow 90 minutes.
- RPM cache lives in `.rpm-cache/` (shared across all variants; preserved by `just clean`).

---

## Architecture

### Build Pipeline

1. Pull base image from Quay.io
2. Multi-stage `Containerfile`: `context` stage → `base-no-de` → `gnome`/`kde`/`niri`
3. Build scripts run in numbered order (`00-workarounds.sh` → … → `90-image-info.sh`)
4. `build_scripts/lib.sh` provides shared functions and OS detection via `/etc/os-release`
5. `system_files_overrides/` applies variant/flavor-specific file overlays
6. CI rechunks layers via `chunkah` for optimized distribution

### CI/CD

Full reference (workflow map, gating model, triage cheat-sheet): **[`docs/PIPELINE.md`](PIPELINE.md)**.

- **Central matrix config:** `.github/build-config.yml` — single source of truth; adding a variant only requires updating this file
- **Orchestrator:** `.github/workflows/build-variant.yml` — DAG with 4 stages + per-stage artifact (ISO) builds; needs-based stage ordering
- **Reusable image job:** `.github/workflows/reusable-build-image.yml` — multi-platform (amd64, amd64v2, arm64), SBOMs, and **publish gating**: manifests push as `:<flavor>-testing`, a QEMU boot gate must pass before the bare `:<flavor>` + date tags are promoted
- **Reusable ISO job:** `.github/workflows/reusable-build-artifacts.yml` — build ISO → boot gate → only then publish to R2/Releases
- **Trigger wrappers:** per-variant workflows (`build-yellowfin.yml`, etc.) call `build-variant.yml`
- CI timeout: **60 minutes maximum** per build; boot gates add ~15–25 min after manifest

### Key Files

| File/Dir | Purpose |
|---|---|
| `Justfile` | All build commands and task automation |
| `Containerfile` | Main multi-stage build definition (base, gnome, kde, niri, cosmic) |
| `Containerfile.nvidia` | NVIDIA flavor definition (NVIDIA drivers + CUDA + gnome/kde/niri/cosmic DE stages) |
| `Containerfile.hwe` | HWE layer definition (coreos kernel, akmods + gnome/kde/niri/cosmic DE stages) |
| `Containerfile.final` | Labels-only stage — applies OCI annotations to rechunked base image |
| `build_scripts/lib.sh` | Shared functions; OS detection logic |
| `build_scripts/overrides/` | Variant-specific script overrides |
| `system_files/` | Files copied into every image (`etc/`, `usr/`) |
| `system_files_overrides/` | Variant/flavor-specific file overlays |
| `scripts/get-base-image.sh` | Maps variant names to base container image URIs |
| `image-versions.yaml` | Pinned base image digests |
| `.github/build-config.yml` | Central CI matrix config |
| `renovate.json5` | Automated dependency update config |

### Environment Variables

Overridable at build time:

| Variable | Default |
|---|---|
| `GITHUB_REPOSITORY_OWNER` | `tuna-os` |
| `DEFAULT_TAG` | `latest` |
| `PLATFORM` | auto-detected from arch |
| `BASE_IMAGE` | `quay.io/almalinuxorg/almalinux-bootc` |
| `BASE_IMAGE_TAG` | `10` |

---

## External Package Sources (COPRs)

The CentOS Stream 10 (skipjack) and AlmaLinux Kitten 10 (yellowfin) GNOME builds rely on custom COPR packages defined in **[github.com/tuna-os/github-copr](https://github.com/tuna-os/github-copr)**:

- `gnome49-el10-compat` — compatibility shim for GNOME 49 on CentOS/AlmaLinux 10
- `gnome50-el10-compat` — compatibility shim for GNOME 50 on CentOS/AlmaLinux 10

When debugging RPM conflicts or missing packages in skipjack/yellowfin GNOME builds, **check the spec files in that repository first**.

---

## Shell Script Conventions

- All build scripts use `set -euo pipefail`
- Quote all variables
- Follow patterns in `build_scripts/lib.sh` for OS detection
- GNOME Shell extensions are Git submodules — conditionally initialized for non-GNOME builds

---

## Troubleshooting

### Build failures
- Check network connectivity (base image pull from Quay.io)
- Verify disk space (20GB+ required)
- Check parent image exists (base must exist before stage 2; stage 2 before stage 3)
- RPM conflicts in skipjack/yellowfin GNOME builds → check [github.com/tuna-os/github-copr](https://github.com/tuna-os/github-copr)
- Transient EPEL/RPM fetch failures → `dnf_retry` in `lib.sh` auto-retries up to 4 attempts with exponential backoff and metadata clear; check `.build-logs/` for retry traces

### Common pitfalls
- **NEVER cancel builds early**
- **NEVER extract tools into the repo root**
- **NEVER skip `just fix` + `just check` before committing**
- **NEVER commit build artifacts** (`.build/`, `.rpm-cache/` are gitignored)
- **New `build_scripts/*.sh` must be executable** (`chmod +x`) — the container
  runtime exits 126 launching a mode-644 script, and shellcheck/bats won't
  catch it
- **CI's shellcheck is 0.9.0** (Ubuntu apt), stricter on some patterns than
  local 0.11 — e.g. it flags `A && B || true` as SC2015. Reproduce with
  `podman run koalaman/shellcheck:v0.9.0`
- **QEMU screendumps need `-vga virtio`** — the default VGA framebuffer is
  black under UEFI GOP, which reads as a boot-gate failure
- **Never install `tuna-os.repo` on Fedora** (bonito) — its $releasever
  baseurl 404s and `skip_if_unavailable=False` breaks every later dnf call
