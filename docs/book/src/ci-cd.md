# CI/CD Pipelines

TunaOS uses GitHub Actions for automated building, testing, and distribution of container images and ISO artifacts.

## Architecture

Workflows are **generated** from a central configuration file:

```
.github/build-config.yml  ──→  scripts/generate-workflows.py  ──→  .github/workflows/build-*.yml
```

This keeps per-variant workflow files in sync and reduces duplication.

## Workflows

### Build Images

**Workflow:** `reusable-build-image.yml` (reusable) + `build-{variant}.yml` (per variant)

Triggered on:
- Push to `main` (affected variants only)
- Pull requests (affected variants only)
- Scheduled (daily)
- Manual dispatch (`workflow_dispatch`)

The reusable workflow:
1. Builds the container image for a matrix of platforms (`linux/amd64`, `linux/amd64/v2`, `linux/arm64`)
2. Applies `chunkah` rechunking
3. Signs images with [cosign](https://github.com/sigstore/cosign)
4. Generates SBOM attestations
5. Pushes to `ghcr.io/tuna-os/<variant>:<flavor>`

### Build Live ISOs

**Workflow:** `publish-isos.yml`

Triggered on:
- Schedule (bi-weekly)
- Manual dispatch

Downloads the latest container image from GHCR, runs tacklebox to produce an ISO, and uploads to Cloudflare R2 (`download.tunaos.org`).

### ISO E2E Testing

**Workflow:** `iso-e2e.yml`

Triggered on:
- PRs touching ISO-related files
- Schedule (weekly)

Downloads published ISOs, boots them in QEMU+OVMF, and verifies:
- Live environment reaches desktop (gdm/sddm)
- Serial console markers
- Screenshot capture

### Snapshot Upstreams

**Workflow:** `snapshot-upstreams.yml`

Triggered on schedule. Monitors upstream repositories for changes and generates porting recommendations.

### Code Quality

Every PR run:
- **CodeQL** — security analysis (Python, JavaScript/TypeScript)
- **ShellCheck** — shell script linting
- **shfmt** — shell script formatting
- **yamllint** — YAML validation
- **actionlint** — GitHub Actions workflow validation

## Local CI Simulation

Run the CI matrix locally:

```bash
just simulate-matrix
```

Run all checks:

```bash
just check
```

Fix formatting automatically:

```bash
just fix
```

## Cache Strategy

- **RPM cache**: Local builds use `.rpm-cache` volume; CI uses GitHub Actions cache
- **Build cache**: Podman BuildKit cache mounted at `/var/cache/tunaos`
- **Cache sync**: `scripts/sync-build-cache.sh` pushes/pulls cache for CI reuse

## Artifact Signing

All images are signed with cosign using keyless signing (OIDC). Signatures are published to the Rekor transparency log and can be verified:

```bash
cosign verify \
  --certificate-identity https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/tuna-os/yellowfin:gnome
```

Public key available in `cosign.pub`:

```bash
cosign verify --key cosign.pub ghcr.io/tuna-os/yellowfin:gnome
```

## Release Publishing

### Container Images

Published to `ghcr.io/tuna-os/` on every successful main build. Tags:

| Tag pattern | When |
|-------------|------|
| `<flavor>` | Every build (e.g., `gnome`, `kde`) |
| `<sha-short>` | Every build (immutable reference) |
| `latest` | Latest build of default flavor |

### ISOs

Published bi-weekly to Cloudflare R2 (`download.tunaos.org`). Currently published variants:

| Variant | Flavors |
|---------|---------|
| Yellowfin | gnome, gnome-hwe |
| Albacore | gnome, gnome-hwe |

ISO expansion to all `build_iso: true` flavors is tracked in the improvement plan.
