# Contributing to TunaOS

Thank you for contributing to TunaOS — an image factory that produces bootc-based desktop OS images.

## Quick Start

```bash
brew install just podman shellcheck shfmt yq
git clone https://github.com/tuna-os/tunaOS.git && cd tunaOS
just fix && just check
```

## Pre-Commit (mandatory)

```bash
just fix     # format shell scripts and Justfile
just check   # shellcheck, yamllint, actionlint
```

## Building Images

```bash
just build yellowfin gnome           # single flavor (~25 min warm cache)
just build yellowfin kde linux/amd64 # specific platform
just build yellowfin all             # all flavors
```

## Adding a Desktop Environment

No shell scripting required. Write a YAML manifest:

```bash
# 1. Create the manifest
cat > manifests/desktops/budgie.yaml <<EOF
display_manager: gdm
packages:
  fedora:
    packages: [budgie-desktop, budgie-extras, gdm]
  el10:
    packages: [budgie-desktop, gdm]
    optional: [budgie-extras]
  apt:
    - budgie-desktop
    - gdm3
versionlock: [glib2]
EOF

# 2. Add stage to Containerfile (copy from existing DE pattern)
# 3. Add flavor to .github/build-config.yml
# 4. That's it — install-desktop.sh handles the rest
```

## Architecture

The build system is **manifest-driven**:

```
manifests/desktops/*.yaml  →  install-desktop.sh  →  image
```

Key scripts:
- `scripts/resolve-flavor.sh` — routes flavor to Containerfile + build params
- `scripts/resolve-image.sh` — resolves image refs from 3 config sources
- `scripts/build-image-inner.sh` — the build engine (env-var driven)
- `build_scripts/desktop/install-desktop.sh` — generic DE installer (reads YAML)
- `build_scripts/lib.sh` — shared helpers (OS detection, pkg abstraction)

Full architecture: [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md)

## Pull Request Process

1. Fork and create a feature branch
2. Run `just fix && just check`
3. Open PR against `main`
4. CI validates (lint, unit tests, image build on PR)
5. Merge queue handles the rest (automerge for passing PRs)

## Testing

```bash
just test          # all tests (bats + pytest)
just test-bats     # shell script tests
just verify-disk image.qcow2  # QEMU boot verification
```

## Documentation

- [Vision](VISION.md) — project philosophy
- [Agent Guide](docs/AGENT_GUIDE.md) — architecture reference
- [Pipeline](docs/PIPELINE.md) — CI/CD details
- [Testing](docs/TESTING.md) — test harness

## Community

- [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [Matrix: #tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)

## License

[Apache 2.0](LICENSE)
