# TunaOS Bootc Container Images

TunaOS builds bootable OCI container images that serve as immutable desktop Linux OSes (bootc/rpm-ostree). This is not traditional software.

> **Full agent guide:** [`docs/AGENT_GUIDE.md`](../docs/AGENT_GUIDE.md) — read this for complete details on architecture, troubleshooting, and external dependencies.

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information.

## Variants and Flavors

| Variant | Base OS | Status |
|---|---|---|
| `yellowfin` | AlmaLinux Kitten 10 | Stable |
| `albacore` | AlmaLinux 10 | Stable |
| `skipjack` | CentOS Stream 10 | Experimental |
| `bonito` | Fedora 43 | Incomplete |

Flavors chain: `base` → `dx` (+ Docker/VSCode) → `gdx` (+ NVIDIA/CUDA)

## Pre-Commit (mandatory)

```bash
just fix && just check   # always run before committing
```

## Key Commands

```bash
just yellowfin base                        # build a single variant (fastest test)
just yellowfin base && just yellowfin dx && just yellowfin gdx  # full chain
sudo just iso yellowfin base local         # generate ISO (requires root)
just clean                                 # remove build artifacts
just --list                                # all available commands
```

## Build Timing

- Cold cache: ~45-60 min. Warm cache: ~25-35 min.
- **NEVER cancel a build early.** CI timeout is 60 minutes.

## When to Build

- **Always** when changing `Containerfile*`, `build_scripts/*`, `system_files*`
- **Never** for docs-only or workflow-only changes

## Setup

Install `just` via Homebrew (matches CI). **Never** extract tools into the repo root.

## External Package Sources (COPRs)

GNOME builds for skipjack/yellowfin use custom COPR packages from **[github.com/tuna-os/github-copr](https://github.com/tuna-os/github-copr)** (`gnome49-el10-compat`, `gnome50-el10-compat`). Check there first when debugging RPM conflicts.

## Critical Don'ts

- NEVER cancel builds early
- NEVER extract tools into the repo root
- NEVER skip `just fix` + `just check` before committing
- NEVER commit build artifacts (`.build/`, `.rpm-cache/`)