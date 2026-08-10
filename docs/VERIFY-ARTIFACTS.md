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
