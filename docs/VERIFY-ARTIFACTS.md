# Verify TunaOS artifacts

TunaOS OCI images are signed with Sigstore Cosign's keyless GitHub Actions
identity. No project signing key or password is required. Verification checks
both the artifact digest and the identity of the protected workflow that built
it.

## Install Cosign

Use Cosign 3.0.6 or newer. Follow the upstream installation instructions and
verify the Cosign binary before using it.

## Verify an OCI image

Always resolve and verify an immutable digest, even when starting from a
friendly tag:

```bash
image=ghcr.io/tuna-os/yellowfin:gnome
digest=$(skopeo inspect "docker://${image}" | jq -r .Digest)
ref="ghcr.io/tuna-os/yellowfin@${digest}"

cosign verify "${ref}" \
  --certificate-identity \
    "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main" \
  --certificate-oidc-issuer \
    "https://token.actions.githubusercontent.com"
```

The command must exit successfully. Do not replace the identity or issuer with
an unrestricted regular expression.

## Verify the SPDX SBOM attestation

Each published platform image has a signed SPDX JSON attestation:

```bash
cosign verify-attestation "${ref}" \
  --type spdxjson \
  --certificate-identity \
    "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-image.yml@refs/heads/main" \
  --certificate-oidc-issuer \
    "https://token.actions.githubusercontent.com"
```

Cosign prints the verified in-toto statement. Its `subject[].digest.sha256`
must match the digest in `ref`. The predicate contains the SPDX document for
that platform image.

## Trust boundary

The accepted identity is intentionally narrow:

- repository: `tuna-os/tunaOS`;
- workflow: `.github/workflows/reusable-build-image.yml`;
- ref: protected `refs/heads/main`;
- OIDC issuer: GitHub Actions.

A signature from a fork, pull-request ref, another repository, another
workflow, or another identity provider does not satisfy this policy.

## Verify an ISO

Every published ISO has two adjacent files:

- `<name>.iso.sha256` — the SHA-256 checksum manifest, and the signed payload;
- `<name>.iso.sigstore.json` — the keyless bundle from Cosign v3, **over that
  checksum file**, not over the ISO.

Download all three files into the same directory, then run:

```bash
cosign verify-blob tunaos-example.iso.sha256 \
  --bundle tunaos-example.iso.sigstore.json \
  --certificate-identity \
    "https://github.com/tuna-os/tunaOS/.github/workflows/reusable-build-artifacts.yml@refs/heads/main" \
  --certificate-oidc-issuer \
    "https://token.actions.githubusercontent.com"

sha256sum --check --strict tunaos-example.iso.sha256
```

The order matters. The bundle signs the **checksum file**, not the ISO. So the
first command proves the checksum came from our pipeline. The second binds the
ISO to that checksum. In the other order, a checksum of unknown origin decides
the answer.

The payload is the checksum because `cosign sign-blob` reads what it signs into
memory, and an ISO above roughly 7 GiB exhausts the runner. Fedora, Debian and
Arch publish signatures over checksums for the same reason.

Scheduled combined/deduplicated media is produced directly by
`publish-iso-groups.yml`. For those ISOs, use this exact identity instead:

```text
https://github.com/tuna-os/tunaOS/.github/workflows/publish-iso-groups.yml@refs/heads/main
```

The reusable artifact workflow signs only after the ISO passes its QEMU boot
gate; the grouped workflow follows the same ordering. The verified ISO,
checksum, and bundle are then uploaded together. A signing or local
verification failure prevents publication.
