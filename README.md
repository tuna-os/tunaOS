<div align="center">
<picture>
  <source srcset="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.webp" type="image/webp">
  <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif" alt="🐟" width="128" height="128">
</picture>

## TunaOS
### *Cloud-native, immutable desktop Linux images*

*One bootc-native desktop experience across Enterprise Linux and community distributions*

---

[![License](https://img.shields.io/github/license/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/blob/main/LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/issues)
[![Adoption evidence](https://img.shields.io/badge/adoption-0_production%2C_2_evaluation-2ea44f?style=for-the-badge)](ADOPTERS.md)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/MXSTqB8Nv)

</div>

## About TunaOS

TunaOS builds **bootc-based desktop operating systems** with atomic updates and straightforward rollbacks. Choose an Enterprise Linux base for long-term stability or a community distribution for a faster release cadence, while keeping the same image-based management model.

[Visit tunaos.org](https://tunaos.org/) or read the [launch announcement](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos).

### Features

- **Modern Desktops**: GNOME, KDE Plasma, COSMIC, Niri, and XFCE — equal first-class options across distribution bases
- **Up-to-Date Desktop Stack**: Fresh desktop features and updates backported to Enterprise and community bases
- **Homebrew**: Baked into the image — all your CLI apps and fonts are just a `brew` command away
- **Flathub by Default**: Full Flathub access out of the box — get any Flatpak available on the net
- **HWE Option**: Hardware Enablement kernel for newer hardware support
- **NVIDIA Option**: NVIDIA drivers and CUDA for graphics and AI workflows

## Images and variants

TunaOS provides a variety of bootc-based operating system images. Use the table below to choose your base distribution and desktop environment.

### Live build matrix

<!-- build-status:start -->

_Generated from the latest conclusive main-branch build for each variant (cancelled runs are skipped over). A cell is green when its image was successfully promoted to the published tag; **failing** means a job ran and failed; **not reached** means no job asserted the cell at all, usually because an earlier stage stopped it._

| Variant | Green image cells | Latest run | Failing | Not reached |
| :--- | ---: | :--- | :--- | :--- |
| 🐠 `yellowfin` | **12/20** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921480845) | — | xfce,gnome-nvidia,gnome-nvidia-hwe,cosmic-nvidia,kde-nvidia,niri-nvidia,xfce-hwe,xfce-nvidia |
| 🐟 `albacore` | **12/20** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921426398) | — | xfce,gnome-asahi,gnome-nvidia,gnome-nvidia-hwe,cosmic-nvidia,kde-nvidia,xfce-hwe,xfce-nvidia |
| 🍣 `skipjack` | **9/18** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921443740) | — | gnome,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,gnome-nvidia-hwe,cosmic-nvidia,kde-nvidia,niri-nvidia |
| 🎣 `bonito` | **6/15** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921611894) | — | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce,gnome-nvidia |
| 🐦 `hummingbird` | **1/5** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921714054) | — | gnome,kde,niri,cosmic |
| 🦈 `sailfin` | **0/7** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921624452) | — | base,gnome,gnome-asahi,kde,niri,xfce,cosmic |
| 🌈 `guppy` | **2/4** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31953925629) | — | gnome,kde |
| 🐉 `bonito-rawhide` | **6/14** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921565037) | — | base,base-hwe,base-nvidia,gnome,cosmic,kde,niri,xfce |
| 🐟 `gurnard` | **2/2** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921682626) | — | — |
| 🐟 `grouper` | **6/7** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921685119) | — | gnome-zfs |
| 🚀 `marlin` | **16/16** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921609702) | — | — |
| 🐡 `flounder` | **7/7** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921688547) | — | — |
| ☢️ `flounder-sid` | **5/7** | [❌ 2026-08-16](https://github.com/tuna-os/tunaOS/actions/runs/31921565050) | — | gnome,xfce |

**Current image coverage: 84/142 cells (59%)** — of the remainder, **0 failing** and **58 never reached** (no job asserted them). The two are reported separately on purpose: a never-reached cell is untested, not broken. This is a point-in-time CI snapshot, not a support-tier promise.

<!-- build-status:end -->

| Variant | Base OS | Registry Path | Desktops | Architectures |
| :--- | :--- | :--- | :--- | :--- |
| 🐠 **Yellowfin** | AlmaLinux Kitten 10 | `ghcr.io/tuna-os/yellowfin` | GNOME, KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🐟 **Albacore** | AlmaLinux 10 (RHEL 10) | `ghcr.io/tuna-os/albacore` | GNOME, KDE, COSMIC, Niri | x86_64, x86_64/v2, arm64 |
| 🍣 **Skipjack** | CentOS Stream 10 | `ghcr.io/tuna-os/skipjack` | GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🎣 **Bonito** | Fedora 44 | `ghcr.io/tuna-os/bonito` | GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🐦 **Hummingbird** | Fedora Hummingbird (experimental) | `ghcr.io/tuna-os/hummingbird` | Base, GNOME, KDE, COSMIC, Niri | x86_64, arm64 |
| 🔒 **Redfin** | Red Hat Enterprise Linux 10 | *Local-Build Only* | GNOME, KDE, COSMIC, Niri, XFCE | x86_64, arm64 |
| 🐟 **Grouper** | Ubuntu 26.04 | `ghcr.io/tuna-os/grouper` | GNOME, KDE, Niri, XFCE | x86_64 |
| 🐟 **Gurnard** | Ubuntu 24.04 (Noble Numbat, experimental) | `ghcr.io/tuna-os/gurnard` | Base, Pantheon | x86_64, arm64 |
| 🚀 **Marlin** | Arch Linux (Rolling) | `ghcr.io/tuna-os/marlin` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| 🐡 **Flounder** | Debian 13 (Trixie) | `ghcr.io/tuna-os/flounder` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| ☢️ **Flounder Sid** | Debian Sid (Unstable) | `ghcr.io/tuna-os/flounder:*-sid` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64 |
| 🐉 **Bonito Rawhide** | Fedora Rawhide | `ghcr.io/tuna-os/bonito:*-rawhide` | GNOME, KDE, COSMIC, Niri, XFCE | x86_64, arm64 |
| 🦈 **Sailfin** | openSUSE Tumbleweed | `ghcr.io/tuna-os/sailfin` | GNOME, KDE, Niri, XFCE | x86_64 |
| 🌈 **Guppy** | Gentoo Linux | `ghcr.io/tuna-os/guppy` | GNOME, KDE | x86_64 |

> [!NOTE]
> **Redfin (RHEL 10)** is local-build only due to EULA restrictions. To build it locally, run `just build redfin <desktop>` (see [rhel-setup.md](docs/rhel-setup.md)).

### Suffix Rules (Image Tags)

Image tags are constructed as `<desktop>[-hardware]`:

1. **Desktop Suffixes**:
   * `gnome`: GNOME (stable)
   * `kde`: KDE Plasma
   * `cosmic`: COSMIC Desktop
   * `niri`: Niri (tiling Wayland compositor)
   * `xfce`: XFCE (Wayland experimental)
   * `pantheon`: Pantheon desktop (elementary OS) — Gurnard variant, experimental
   * `base`: Plain system image with no desktop environment pre-installed (available for most variants)

2. **Hardware Suffixes** (append to any desktop suffix):
   * *(none)*: Standard generic kernel build
   * `-hwe`: Hardware Enablement (newer kernel stack)
   * `-nvidia`: NVIDIA drivers + CUDA pre-configured
   * `-nvidia-hwe`: NVIDIA drivers on HWE kernel stack

*Example tags:* `yellowfin:gnome-hwe`, `albacore:kde-nvidia`, `marlin:cosmic`

---

## System requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| **CPU** | x86_64, ARM64 | x86_64, ARM64 |
| **RAM** | 4 GB | 8 GB+ |
| **Storage** | 20 GB | 50 GB+ |

### Supported hardware (ARM laptops)

| Hardware | Status | Docs |
|----------|--------|------|
| Snapdragon X Elite (e.g. Lenovo ThinkPad X13s) | Supported via [Bonito](https://tunaos.org/docs/bonito) (ARM64) | [Snapdragon X Elite FAQ](https://tunaos.org/docs/faq); the dedicated [bonito-x13s](https://tunaos.org/docs/bonito-x13s) / [dakota-x13s](https://tunaos.org/docs/dakota-x13s) pages are archived |
| Apple Silicon (M1, M2) | In progress via [Asahi Linux](https://asahilinux.org/) — see note below | [bootc-installer-asahi](https://github.com/tuna-os/bootc-installer-asahi) |
| Apple Silicon (M3 and newer) | Not supported (no Asahi support for M3+ yet) | — |

> **Apple Silicon status.** [ROADMAP.md](ROADMAP.md) is the canonical source
> and lists Apple Silicon support as 🟡 **in progress**
> ([#781](https://github.com/tuna-os/tunaOS/issues/781)), so this row says the
> same thing rather than a flat "Supported". Concretely, what exists today:
> the `-asahi` images build and are gated in CI (Bonito & Grouper, 36/36
> verified, [#776](https://github.com/tuna-os/tunaOS/issues/776)), and the
> installer track has D0–D2 and D4 done. What does not exist yet: the D3
> macOS installer app, any tagged release of `bootc-installer-asahi`, and any
> validation on real Apple hardware — that repo's deepest test is qemu +
> U-Boot, which it describes as "the deepest fidelity achievable without
> Apple hardware". Installing today means driving the Asahi installer path
> by hand. If you have M1/M2 hardware to test on, #781 is the place to help.

---

## Installation

### Use a pre-built ISO

Browse the currently published installation media on the download page:

**[📦 tunaos.org/download](https://tunaos.org/download)**

### Build your own ISO or VM image

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

### Switch an existing system

If you're already running a compatible bootc system:

```bash
sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
```

### Verifying downloads

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
[docs/VERIFY-ARTIFACTS.md](docs/VERIFY-ARTIFACTS.md).

## Container registry authentication

Images are published on GitHub Container Registry (GHCR). To pull images with `bootc` or `podman`:

```bash
# Authenticate to GHCR (requires a GitHub personal access token with read:packages scope)
echo "$GITHUB_TOKEN" | podman login ghcr.io -u YOUR_USERNAME --password-stdin

# Or use the GitHub CLI
gh auth token | podman login ghcr.io -u YOUR_USERNAME --password-stdin
```

See [GitHub Container Registry docs](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry) for more details.

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

## Contributing

Contributions welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for:
- Development environment setup
- Build workflow and pre-commit checklist
- Pull request guidelines
- Architecture overview

## Community and support

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [m] **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)
- 🎮 **Discord:** [TunaOS](https://discord.gg/MXSTqB8Nv)

Related Communities:
- 🎮 **Discord:** [Universal Blue Community](https://discord.gg/WEu6BdFEtp)
- 💬 **AlmaLinux Atomic SIG:** [AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## Documentation

### Project Docs
- [TunaOS Blog](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos) — launch announcement and design philosophy comparison
- [Vision](VISION.md) — project philosophy: erasing the mystique of the Linux distribution
- [Goal](GOAL.md) — current objective: LUKS E2E fisherman migration
- [Contributor Guide](CONTRIBUTING.md) — how to set up, build, and contribute
- [Roll Your Own Guide](docs/ROLL_YOUR_OWN.md) — build your own custom TunaOS variant
- [Agent Guide](docs/AGENT_GUIDE.md) — complete architecture and contributor reference
- [Build Pipeline](docs/build-pipeline.md) — CI/CD workflow overview
- [Build Pipeline Reference](docs/PIPELINE.md) — the build matrix, verification gates, and publish flow in detail
- [mkosi Investigation](docs/mkosi-investigation.md) — mkosi as a build backend and DDI output: findings, not a production change (#999)
- [Testing Guide](docs/TESTING.md) — ISO end-to-end test harness
- [Secure Boot](docs/SECURE-BOOT.md) — which variants support Secure Boot out of the box
- [Disk Encryption & TPM2](docs/LUKS-TPM.md) — LUKS2 passphrase setup and TPM2 auto-unlock
- [CI/CD Spec](docs/CI_SPEC.md) — target/aspirational workflow spec; see Build Pipeline above for what's actually deployed
- [CI Troubleshooting Playbook](docs/ci-troubleshooting.md) — quick reference for diagnosing recurring CI failures
- [Improvement Plan](docs/IMPROVEMENT_PLAN.md) — roadmap and development progress
- [Redfin Setup](docs/rhel-setup.md) — RHEL 10 local-build instructions
- [Developer Docs](https://tunaos.org/docs/tunaos/building) — build and contribution guide

### Policies & Planning
- [Roadmap](ROADMAP.md) — project direction and feature status
- [Q3 2026 Checkpoint](Q3_CHECKPOINT-2026-08-22.md) — decision sheet for the Q3 "Expand Coverage" milestone (#1299)
- [Variant Lifecycle Policy](VARIANT-LIFECYCLE.md) — Stable/Beta/Alpha admission gates and deprecation rules
- [RFC Process](RFC-PROCESS.md) — how RFCs are proposed, reviewed, and decided
- [Package Sourcing Policy](PACKAGE-SOURCING.md) — package origin rules, Tideforge-first, and allowlist (#1319)
- [Issue Triage Policy](TRIAGE-POLICY.md) — triage states and SLAs (draft, #1195)
- [Fedora Base Currency Policy](FEDORA-BASE-POLICY.md) — adopted N+rawhide sequencing for Fedora-based variants (#1171)
- [Versioning](VERSIONING.md) — tag scheme and stability tiers
- [Migration Guide](MIGRATION.md) — switching from other distros
- [Security Policy](SECURITY.md) — vulnerability reporting and supported versions
- [Branch Protection](docs/BRANCH-PROTECTION.md) — rulesets and required CI audit (#1167)
- [Branch Hygiene](docs/BRANCH-HYGIENE.md) — branch lifecycle, naming rules, and stale branch triage (#1530)
- [Q3 Checkpoint Policy](docs/Q3_CHECKPOINT-2026-08-22.md) — decision integrity and merge-eligible scoring rule (#1683)
- [Adopters](ADOPTERS.md) — organizations using TunaOS
- [Adoption Metrics](ADOPTION-METRICS.md) — how adoption is measured and reported (#1174)
- [Code of Conduct](CODE_OF_CONDUCT.md) — community standards

### Community & Governance
- [Community](COMMUNITY.md) — contribution ladder, metrics, communication
- [Maintainers](MAINTAINERS.md) — maintainer playbook and bus factor plan

### External Resources
- [AlmaLinux Kitten 10 Differences](https://wiki.almalinux.org/development/almalinux-os-kitten-10.html#how-is-almalinux-os-kitten-different-from-centos-stream)
- [Project Bluefin Documentation](https://docs.projectbluefin.io)
- [Universal Blue](https://universal-blue.org/)
- [bootc](https://github.com/bootc-dev/bootc)

---

<div align="center">
<img width="400" height="400" alt="Tuna_OS_Logo" src="https://github.com/user-attachments/assets/0c0de438-25ae-429d-b7a5-fe32ea85547f" />

*Made by James in his free time*


*Powered by [Bootc](https://github.com/bootc-dev/bootc)*


<a href="https://github.com/bootc-dev/bootc">
<img width="100" height="130" alt="Bootc_Logo" src="https://raw.githubusercontent.com/containers/common/main/logos/bootc-logo-full-vert.png" />
</a>

---

### 🤖 Powered by KubeStellar / Hive

This repository and many of the [tuna-os](https://github.com/tuna-os) repositories are developed and maintained using **[Hive](https://hive.tunaos.org)** — an AI-driven development platform orchestrated via [KubeStellar](https://kubestellar.io/).

Hive deploys a suite of specialized AI agents (guide, architect, sec-check, quality, ci-maintainer, strategist) onto a local Kubernetes cluster. These agents triage issues, implement fixes, review PRs, manage CI pipelines, and maintain documentation — all working autonomously through GitHub.

<img width="100" alt="Hive" src="https://avatars.githubusercontent.com/in/3942065" />

Every commit, PR, and issue in this repo benefits from multi-agent collaboration coordinated through Hive.

*Learn more: [hive.tunaos.org](https://hive.tunaos.org) | [KubeStellar](https://kubestellar.io/)*

---

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community*

*Licensed under [Apache 2.0](https://github.com/tuna-os/tunaOS/blob/main/LICENSE)*

</div>
