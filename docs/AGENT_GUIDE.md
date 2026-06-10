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
| `skipjack` | CentOS Stream 10 | Experimental |
| `bonito` | Fedora 44 | Experimental |

### Flavors (layered via 4-stage DAG; see `.github/build-config.yml` for full matrix)

| Layer | Flavors | Contents |
|---|---|---|
| Stage 1 — base | `base` | Minimal OS (all variants) |
| Stage 2 — HWE/GDX base + desktops | `base-hwe`, `base-gdx`, `gnome`, `gnome50`, `cosmic`, `kde`, `niri` | DE packages; HWE coreos kernel; GDX NVIDIA base |
| Stage 3 — HWE/GDX desktops | `<de>-hwe`, `<de>-gdx` (e.g. `gnome-hwe`, `kde-gdx`) | DE layered on HWE/GDX base |
| Stage 4 — combined | `gnome-gdx-hwe` | GNOME + GDX + HWE (layers on `gnome-hwe`) |

Flavor availability varies per variant — consult `.github/build-config.yml`.
- `bonito` has fewer HWE/GDX combos (no `gnome50`, fewer non-GNOME HWE layers).
- HWE flavors ship the `coreos/fedora` kernel + `ublue-os/akmods-nvidia-open`.

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
just yellowfin base && just yellowfin gnome && just yellowfin gnome-gdx

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

- **Central matrix config:** `.github/build-config.yml` — single source of truth; adding a variant only requires updating this file
- **Orchestrator:** `.github/workflows/build-variant.yml` — DAG with 4 stages + artifact builds; needs-based stage ordering
- **Reusable job:** `.github/workflows/reusable-build-image.yml` — multi-platform (amd64, amd64v2, arm64), cosign sign, SBOMs
- **Trigger wrappers:** per-variant workflows (`build-yellowfin.yml`, etc.) call `build-variant.yml`
- CI timeout: **60 minutes maximum** per build

### Key Files

| File/Dir | Purpose |
|---|---|
| `Justfile` | All build commands and task automation |
<<<<<<< HEAD
| `Containerfile` | Main multi-stage build definition (base, gnome, kde, niri, cosmic) |
| `Containerfile.gdx` | GDX flavor definition (NVIDIA drivers + CUDA + gnome/kde/niri/cosmic DE stages) |
| `Containerfile.hwe` | HWE layer definition (coreos kernel, akmods + gnome/kde/niri/cosmic DE stages) |
| `Containerfile.final` | Labels-only stage — applies OCI annotations to rechunked base image |
| `Containerfile.dx` | ⚠️ DEPRECATED — reference only. Superseded by Containerfile.gdx. No CI consumers. |
>>>>>>> 07f3b68 ([guide] fix: stagger variant cron schedules (F7), add flavor validation (F8), sync AGENT_GUIDE (F6))
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
