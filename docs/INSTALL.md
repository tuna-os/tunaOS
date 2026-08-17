# Installing TunaOS

Everything below the quick start that used to live on the front page: building
your own media, switching an existing system, verifying what you downloaded,
and registry authentication. For choosing an image, day-2 updates, rollbacks
and apps, start with the [User Guide](USER-GUIDE.md).

## Use a pre-built ISO

Browse the currently published installation media on the download page:

**[📦 tunaos.org/download](https://tunaos.org/download)**

## Build your own ISO or VM image

**In your browser — no tools, no root, nothing uploaded:**

**[🛠️ tunaos.org/iso-builder](https://tunaos.org/iso-builder)** — point it
at any TunaOS image (or your own bootc image), pick your flatpaks, and it
authors a bootable live ISO entirely in WebAssembly using the same
[tacklebox](https://github.com/tuna-os/tacklebox) engine CI uses.
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

If you're already running a compatible bootc system:

```bash
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
```

## Verifying downloads

TunaOS images and ISOs are keylessly signed (Sigstore Cosign, GitHub Actions
OIDC identity — no project key or password) and published with SBOMs, so you
can verify what you're running instead of trusting the download blindly.

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

**Container images** are signed by digest, with a signed SPDX SBOM
attestation attached to each platform image:

```bash
digest=$(skopeo inspect docker://ghcr.io/tuna-os/yellowfin:gnome | jq -r .Digest)
cosign verify "ghcr.io/tuna-os/yellowfin@${digest}" \
  --certificate-identity \
    "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main" \
  --certificate-oidc-issuer \
    "https://token.actions.githubusercontent.com"
```

Full commands, the SBOM-attestation example, and the exact trust boundary
(which identities/issuers are accepted and why) are in
[VERIFY-ARTIFACTS.md](VERIFY-ARTIFACTS.md).

## Container registry authentication

Images are published on GitHub Container Registry (GHCR). To pull images with
`bootc` or `podman`:

```bash
# Authenticate to GHCR (requires a GitHub personal access token with read:packages scope)
echo "$GITHUB_TOKEN" | podman login ghcr.io -u YOUR_USERNAME --password-stdin

# Or use the GitHub CLI
gh auth token | podman login ghcr.io -u YOUR_USERNAME --password-stdin
```

See [GitHub Container Registry docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)
for more details.

### Troubleshooting: `501 Unsupported client range` on pull

TunaOS images publish as `zstd:chunked` for faster delta pulls, but GHCR's
blob CDN doesn't support the multi-range HTTP requests that chunked pulls
use. Most `podman`/`bootc` builds fall back to a normal full-blob pull
automatically, but some do not and hard-fail with:

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
