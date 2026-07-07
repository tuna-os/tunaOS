# Agent Guidelines for TunaOS

> The authoritative agent guide lives at [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md). Read that file for complete architecture, setup, and troubleshooting.

## Quick Reference

```bash
just fix && just check   # format + validate (mandatory before every commit)
just test                # bats + pytest (same as CI)
just build yellowfin gnome  # build a single flavor
just --list              # show all available commands
```

## Architecture (July 2026)

The build system is **manifest-driven**:

```
manifests/desktops/*.yaml  →  install-desktop.sh  →  image
```

Key scripts:
- `scripts/resolve-flavor.sh` — flavor → build params (tested: 18 bats cases)
- `scripts/resolve-image.sh` — consolidated image ref lookups
- `scripts/build-image-inner.sh` — the build engine (env-var driven)
- `build_scripts/install-desktop.sh` — generic DE installer
- `build_scripts/lib.sh` — shared library (OS detection, pkg abstraction)

Containerfiles:
- `Containerfile` — main (base + all DE stages)
- `Containerfile.overlay` — HWE/nvidia parameterized layer
- `Containerfile.ubuntu` — Ubuntu/Debian bootcification

Build pipeline: [`docs/PIPELINE.md`](docs/PIPELINE.md)

## Adding a Desktop

Write `manifests/desktops/<name>.yaml`. No shell script needed. See existing manifests for the format.

## Agent Skills

### Issue tracker
GitHub Issues for `tuna-os/tunaos`, operated via `gh` CLI.

### Triage labels
`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`.
