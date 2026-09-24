# Security Policy

## Supported Versions

TunaOS builds daily images and weekly ISO publications. The pipeline publishes
images with per-flavor tags (e.g. `gnome`, `kde`, `gnome-hwe`). Only the most
recent build of each flavor is actively supported. See [`VERSIONING.md`](VERSIONING.md)
for the tag scheme.

| Variant | Base OS | Status |
|---|---|---|
| Yellowfin | AlmaLinux Kitten 10 | ✅ Supported |
| Albacore | AlmaLinux 10 | ✅ Supported |
| Skipjack | CentOS Stream 10 | ⚠️ Beta |
| Bonito | Fedora 44 | ⚠️ In progress |
| Redfin | RHEL 10 | 🔒 Local-build only |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

Instead, report them privately via GitHub Security Advisories:

1. Go to the [Security tab](https://github.com/tuna-os/tunaOS/security)
2. Click **Report a vulnerability**
3. Provide a detailed description of the issue, including steps to reproduce

You can expect:
- **Acknowledgment** within 48 hours
- **Status update** within 5 business days
- **Resolution timeline** based on severity

## Security Model

TunaOS images are:
- Built in CI from pinned base images (see `image-versions.yaml`)
- Signed with [Sigstore Cosign](https://github.com/sigstore/cosign) using the workflow identity from GitHub Actions
- Scanned for vulnerabilities via security tools in GitHub
- Published with signed attestations in SPDX SBOM format

There is no private key or password to leak or rotate. Fulcio issues a certificate
for the OIDC identity in GitHub Actions. Rekor records the signature in its
transparency log. See [`docs/VERIFY-ARTIFACTS.md`](docs/VERIFY-ARTIFACTS.md) for
verification commands.

## Supply Chain Security

- Base images pinned by digest in `image-versions.yaml`
- Actions from third parties pinned to commit SHAs
- Release promotion needs successful signature and SBOM verification
- Build secrets use BuildKit secret mounts, never environment variables
- Do not embed workflow credentials in URLs; use header authentication in Git (for example, `http.extraheader`)
- RPM packages from official AlmaLinux/CentOS/Fedora repositories and verified COPRs

## Disclosure Policy

We follow coordinated disclosure:
1. A reporter submits the report privately
2. Maintainers investigate and develop a fix
3. Maintainers deploy the fix to new builds
4. Maintainers publish an advisory after deployment

See [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md) for build architecture details.
