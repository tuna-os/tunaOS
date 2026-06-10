# CI/CD Pipelines

TunaOS uses GitHub Actions for automated building, testing, and distribution of container images and ISO artifacts.

## Architecture

The CI pipeline is driven by a **central configuration file** (`.github/build-config.yml`) which defines all variants, flavors, platforms, and build stages. A single reusable workflow (`build-variant.yml`) handles all image builds using matrix strategies generated from this config.

Per-variant trigger workflows (`build-yellowfin.yml`, etc.) are thin wrappers that call the reusable workflow with the variant name — they exist primarily for independent cron schedules and manual dispatch.

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

ISOs are built through two paths:

1. **`build-variant.yml` → `build_artifacts` job** — builds ISOs and QCOW2s as part of the main build pipeline, after all image stages complete. Uses tacklebox. Runs on weekly schedule and manual dispatch.

2. **`publish-isos.yml`** — standalone ISO publishing workflow. Triggered on:
   - Schedule (weekly, Sunday 22:00 UTC)
   - Manual dispatch

Downloads the published container image from GHCR, runs tacklebox to produce an ISO, and uploads to Cloudflare R2 (`download.tunaos.org`).

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

- **RPM cache**: Local builds use `.rpm-cache` volume shared across all variants; preserved by `just clean`, removed by `just clean-cache`
- **Build cache**: Podman BuildKit cache mounted at `/var/cache/tunaos`

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
| `<flavor>` | Every build (e.g., `gnome`, `kde`, `gnome-hwe`) — each flavor is its own tag |
| `<flavor>-<platform>` | Per-architecture tag (e.g., `gnome-linux-amd64`) |
| `<sha-short>` | Every build (immutable reference) |

There is no monolithic `latest` tag — each flavor has its own independent tag.

### ISOs

Published weekly to Cloudflare R2 (`download.tunaos.org`). Currently published variants:

| Variant | Flavors |
|---------|---------|
| Yellowfin | gnome, gnome-hwe |
| Albacore | gnome, gnome-hwe |

ISO expansion to all `build_iso: true` flavors is tracked in the improvement plan.
