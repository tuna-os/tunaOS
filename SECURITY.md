# Security Policy

## Supported Versions

TunaOS images are built daily with weekly ISO publications. Images are
published with per-flavor tags (e.g. `gnome`, `kde`, `gnome-hwe`).
Only the most recent build of each flavor is actively supported.
See [VERSIONING.md](VERSIONING.md) for the full tagging scheme.

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
- Built in CI from pinned base images (see `registry-map.yaml`)
- Signed with [cosign](https://github.com/sigstore/cosign) (public key: `cosign.pub`)
- Scanned for vulnerabilities via GitHub's built-in scanning
- Published as SBOM-attested OCI images

## Supply Chain Security

- Base images pinned by digest in `registry-map.yaml`
- Third-party GitHub Actions pinned to commit SHAs
- Build secrets use BuildKit secret mounts, never environment variables
- RPM packages from official AlmaLinux/CentOS/Fedora repositories and verified COPRs

## Disclosure Policy

We follow coordinated disclosure:
1. Reporter submits vulnerability privately
2. We investigate and develop a fix
3. Fix is deployed to new builds
4. Advisory is published after deployment

See [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md) for full build architecture details.
