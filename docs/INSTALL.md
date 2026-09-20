# Installing TunaOS

This page contains information that used to be in the quick start on the front
page. It covers custom media, system conversion, download verification,
and registry authentication. For image selection, day-2 updates, rollbacks,
and apps, see the [User Guide](USER-GUIDE.md).

## Use a pre-built ISO

Browse the installation media that the project now publishes on the download
page:

**[📦 tunaos.org/download](https://tunaos.org/download)**

## Install from Windows (wootc)

You can use **[wootc](https://github.com/tuna-os/wootc)** to install TunaOS
directly from Windows. You do not need to put an ISO on a USB flash drive or
change the partitions on your disk.

- Download the installer from the [wootc releases](https://github.com/tuna-os/wootc/releases)
- Run `tunaos-installer.exe` as Administrator, select your desktop and variant, and reboot into TunaOS
- See the [Migration Guide (From Windows)](../MIGRATION.md#from-windows-wootc) and [wootc documentation](https://github.com/tuna-os/wootc) for full details

## Build your own ISO or VM image

**In your browser — no tools, no root, nothing uploaded:**

**[🛠️ tunaos.org/iso-builder](https://tunaos.org/iso-builder)** — select any
TunaOS image or your own bootc image, and then select your flatpaks. The builder
uses WebAssembly to create a bootable live ISO with the
[tacklebox](https://github.com/tuna-os/tacklebox) engine that CI uses.
[User guide](https://tunaos.org/docs/iso-builder).

**Or locally with [tacklebox](https://github.com/tuna-os/tacklebox):**

```bash
# ISO (requires root)
sudo tacklebox build --iso tunaos-yellowfin-gnome.iso \
  --bootable-environment-image ghcr.io/tuna-os/yellowfin:gnome \
  --bootable-environment-desktop gnome \
  --output-base .build/iso
```

Or use the included helper script:

```bash
sudo ./scripts/build-iso-tacklebox.sh yellowfin gnome ghcr gnome
```

For QCOW2 VM images, use bootc directly:

```bash
# QCOW2 (VM image)
sudo bootc image build-to-qcow2 \
  --output-format qcow2 \
  ghcr.io/tuna-os/yellowfin:gnome
```

## Switch an existing system

If you already use a compatible bootc system:

```bash
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
```

## Verifying downloads

GitHub Actions uses Sigstore Cosign and its OIDC identity to sign TunaOS images
and ISOs without a project key or password. Each artifact has an SBOM. You can
verify the software on your system without implicit trust in the download.

**ISOs** ship with a `.iso.sha256` checksum and a `.iso.sigstore.json`
verification bundle alongside the image:

```bash
sha256sum --check --strict tunaos-example.iso.sha256

cosign verify-blob tunaos-example.iso \
  --bundle tunaos-example.iso.sigstore.json \
  --certificate-identity \
    "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-artifacts.yml@refs/heads/main" \
  --certificate-oidc-issuer \
    "https://token.actions.githubusercontent.com"
```

Cosign signs each **container image** by digest. Each platform image also has
an attached, signed attestation for its SPDX SBOM:

```bash
digest=$(skopeo inspect docker://ghcr.io/tuna-os/yellowfin:gnome | jq -r .Digest)
cosign verify "ghcr.io/tuna-os/yellowfin@${digest}" \
  --certificate-identity \
    "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main" \
  --certificate-oidc-issuer \
    "https://token.actions.githubusercontent.com"
```

Full commands, the SBOM-attestation example, and the exact trust boundary are
in [VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md). The trust boundary identifies
the identities and issuers that verification accepts and explains the reasons.

## Container registry authentication

TunaOS publishes images on GitHub Container Registry (GHCR). To pull images with
`bootc` or `podman`:

```bash
# Authenticate to GHCR (requires a GitHub personal access token with read:packages scope)
echo "$GITHUB_TOKEN" | podman login ghcr.io -u YOUR_USERNAME --password-stdin

# Or use the GitHub CLI
gh auth token | podman login ghcr.io -u YOUR_USERNAME --password-stdin
```

See the [documentation for GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
for more details.

### Troubleshooting: `501 Unsupported client range` on pull

TunaOS images publish as `zstd:chunked` for faster delta pulls, but GHCR's
blob CDN doesn't support the multi-range HTTP requests that chunked pulls
use. Most `podman`/`bootc` builds automatically fall back to a standard pull
of the full blob, but some do not and fail with:

```
Error: copying system image from manifest list: partial pull of blob sha256:...:
read zstd:chunked manifest: fetching partial blob: received unexpected HTTP status: 501 Unsupported client range
```

If you hit this, disable partial/chunked pulls client-side in
`/etc/containers/storage.conf`:

```toml
[storage.options.pull_options]
enable_partial_images = "false"
```

Tracked in [tuna-os/tunaos#579](https://github.com/tuna-os/tunaos/issues/579).
