<div align="center">
<picture>
  <source srcset="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.webp" type="image/webp">
  <img src="https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif" alt="🐟" width="128" height="128">
</picture>

## TunaOS
### *Cloud-native, immutable desktop Linux images*

*One desktop experience with bootc across Enterprise Linux and community distributions*

---

[![License](https://img.shields.io/github/license/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/blob/main/LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/stargazers)
[![Issues](https://img.shields.io/github/issues/tuna-os/tunaOS?style=for-the-badge)](https://github.com/tuna-os/tunaOS/issues)
[![Adoption evidence](https://img.shields.io/badge/adoption-0_production%2C_2_evaluation-2ea44f?style=for-the-badge)](ADOPTERS.md)
[![Discord](https://img.shields.io/badge/Discord-join-5865F2?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/MXSTqB8Nv)

</div>

> 🎃 **Hacktoberfest 2026:** Join us! Is this your first open-source PR? See our [good first issues](https://github.com/tuna-os/tunaOS/issues?q=is%3Aissue+is%3Aopen+label%3A%22good+first+issue%22). You can also join the office hours for maintainers in October on Matrix.

## About TunaOS

TunaOS builds **bootc-based desktop operating systems** with atomic updates and straightforward rollbacks. Choose an Enterprise Linux base for long-term stability or an alternative distribution for a faster release cadence. Both choices use the same image-based management model.

[Visit tunaos.org](https://tunaos.org/) or read the [launch announcement](https://tunaos.org/blog/modern-enterprise-linux-desktops-with-tunaos).

- **Modern Desktops**: GNOME, KDE Plasma, COSMIC, Niri, and XFCE — equal first-class options across distribution bases
- **Up-to-Date Desktop Stack**: Fresh desktop features and updates backported to Enterprise and community bases
- **Homebrew**: Baked into the image — all your CLI apps and fonts are a `brew` command away
- **Flathub by Default**: Full Flathub access out of the box — get any Flatpak available on the net
- **HWE and NVIDIA Options**: Hardware Enablement kernels and NVIDIA drivers + CUDA as image tags

## Choose your image

| Variant | Base OS | Registry Path | Desktops | Architectures |
| :--- | :--- | :--- | :--- | :--- |
| 🐠 **Yellowfin** | AlmaLinux Kitten 10 | `ghcr.io/tuna-os/yellowfin` | GNOME (x86_64 only, see note), KDE, COSMIC, Niri, Tuna (x86_64 only), XFCE | x86_64, x86_64/v2, arm64 |
| 🐟 **Albacore** | AlmaLinux 10 (RHEL 10) | `ghcr.io/tuna-os/albacore` | GNOME (x86_64 only, see note), KDE, COSMIC, Niri, Tuna (x86_64 only), XFCE | x86_64, x86_64/v2, arm64 |
| 🍣 **Skipjack** | CentOS Stream 10 | `ghcr.io/tuna-os/skipjack` | GNOME (x86_64 only, see note), KDE, COSMIC, Niri, Tuna (x86_64 only), XFCE | x86_64, arm64 |
| 🎣 **Bonito** | Fedora 44 | `ghcr.io/tuna-os/bonito` | GNOME, KDE, COSMIC, Niri, Tuna (x86_64 only), XFCE | x86_64, arm64 |
| 🐦 **Hummingbird** | Fedora Hummingbird (experimental) | `ghcr.io/tuna-os/hummingbird` | Base, GNOME, COSMIC | x86_64 (see note) |
| 🎏 **Wahoo** | Fedora ELN — EL11 preview (experimental, no codecs) | `ghcr.io/tuna-os/wahoo` | Base, GNOME, KDE, COSMIC, Tuna (x86_64 only) | x86_64, arm64 |
| 🔒 **Redfin** | Red Hat Enterprise Linux 10 | *Local-Build Only* | GNOME, KDE, COSMIC, Niri, XFCE | x86_64, arm64 |
| 🪸 **Grouper** | Ubuntu 26.04 | `ghcr.io/tuna-os/grouper` | GNOME, KDE, COSMIC, Tuna, XFCE | x86_64 |
| 🤖 **Gurnard** | Ubuntu 24.04 (Noble Numbat, experimental) | `ghcr.io/tuna-os/gurnard` | Base, Pantheon | x86_64, arm64 |
| 🚀 **Marlin** | Arch Linux (Rolling) | `ghcr.io/tuna-os/marlin` | GNOME, KDE, COSMIC, Niri, Tuna, XFCE | x86_64 |
| 🐡 **Flounder** | Debian 13 (Trixie) | `ghcr.io/tuna-os/flounder` | KDE, Tuna, XFCE | x86_64 |
| ☢️ **Flounder Sid** | Debian Sid (Unstable) | `ghcr.io/tuna-os/flounder:*-sid` | GNOME, KDE, Tuna, XFCE | x86_64 |
| 🐉 **Bonito Rawhide** | Fedora Rawhide | `ghcr.io/tuna-os/bonito:*-rawhide` | GNOME, KDE, COSMIC, Niri, Tuna (x86_64 only), XFCE | x86_64, arm64 |
| ⛵ **Sailfin** | openSUSE Tumbleweed | `ghcr.io/tuna-os/sailfin` | GNOME, KDE, COSMIC, Niri, Tuna, XFCE | x86_64 |
| 🌈 **Guppy** | Gentoo Linux | `ghcr.io/tuna-os/guppy` | GNOME, KDE, XFCE | x86_64 |
| 🏔️ **Tromsø** | freedesktop-sdk (BuildStream), built in [tuna-os/tromso](https://github.com/tuna-os/tromso) | `ghcr.io/tuna-os/tromso` | KDE | x86_64 |
| 🐭 **XFCE Linux** | freedesktop-sdk (BuildStream), built in [tuna-os/xfce-linux](https://github.com/tuna-os/xfce-linux) | `ghcr.io/tuna-os/xfce-linux` | XFCE | x86_64 |

GNOME on the EL10 variants comes from the tunaOS GNOME 50 package tier.
GitHub Actions builds this tier without COPR. The tier supports only x86_64
today, so the `gnome` and `gnome-hwe` images have only x86_64 support.
The `gnome-asahi` image is off until the tier adds aarch64
([tunaos-packages#673](https://github.com/tuna-os/tunaos-packages/issues/673)).
Every GNOME image uses GNOME 50 or newer. The project does not promote older versions.

Hummingbird is x86_64 only. This includes its base. The aarch64 package
snapshot has no `xfsprogs`, and the base stage needs it. No hummingbird arm64
image builds today. The architecture is absent, not thinner. See
[docs/HUMMINGBIRD.md](docs/HUMMINGBIRD.md).

Tags are `<desktop>[-hardware]` — e.g. `yellowfin:gnome-hwe`,
`albacore:kde-nvidia`. Full tag reference: [docs/IMAGE-TAGS.md](docs/IMAGE-TAGS.md).
Hardware requirements and ARM laptop status: [docs/HARDWARE.md](docs/HARDWARE.md).

> [!NOTE]
> **Redfin (RHEL 10)** is local-build only due to EULA restrictions. To build it locally, run `just build redfin <desktop>` (see [rhel-setup.md](docs/rhel-setup.md)).

## Live build matrix

The configured matrix now has 147 image cells. Eleven of them are Tuna Desktop (formerly Roost) cells for amd64: `marlin:tuna`, `yellowfin:tuna`, `albacore:tuna`, `skipjack:tuna`, `wahoo:tuna`, `bonito:tuna`, `bonito:tuna-rawhide`, `grouper:tuna`, `flounder:tuna`, `flounder:tuna-sid` and `sailfin:tuna`. The `tuna_rollout` record in `.github/build-config.yml` gives each other variant its reason to stay unsupported. The `guppy:gnome` cell is back (2026-10-07, #2450). The former `marlin:roost` tags get no more updates; existing installs must follow the [explicit switch and recovery procedure](experiences/tuna/README.md#switch-an-existing-roost-install). The status snapshot below is from before those additions and does not prove image publication or a successful boot. Tuna Desktop adds no ISO or LUKS cells.

<!-- build-status:start -->

_Each cell reports the newest conclusive main-branch run that asserted it, so a flavor-filtered rebuild does not blank the cells it never scheduled. This table omits cancelled runs. **Latest run** names the variant's newest conclusive run. A green cell has a successful promotion to the published tag. **Failed** means that a job ran and failed. **Not reached** means that no recent run asserted the cell, usually because an earlier stage stopped it._

| Variant | Green image cells | Latest run | Failing | Not reached |
| :--- | ---: | :--- | :--- | :--- |
| 🐠 `yellowfin` | **19/19** | [✅ 2026-10-17](https://github.com/tuna-os/tunaOS/actions/runs/39002887881) | — | — |
| 🐟 `albacore` | **19/19** | [✅ 2026-10-17](https://github.com/tuna-os/tunaOS/actions/runs/39012158502) | — | — |
| 🍣 `skipjack` | **17/17** | [✅ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38912184041) | — | — |
| 🎏 `wahoo` | **4/5** | [❌ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38906627617) | tuna | — |
| 🎣 `bonito` | **17/17** | [✅ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38923430235) | — | — |
| 🐦 `hummingbird` | **1/3** | [❌ 2026-10-15](https://github.com/tuna-os/tunaOS/actions/runs/38660870261) | gnome | cosmic |
| ⛵ `sailfin` | **7/7** | [✅ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38973819810) | — | — |
| 🌈 `guppy` | **3/4** | [❌ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38894192116) | — | gnome |
| 🐉 `bonito-rawhide` | **13/15** | [❌ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38950334306) | tuna | gnome |
| 🤖 `gurnard` | **2/2** | [✅ 2026-10-17](https://github.com/tuna-os/tunaOS/actions/runs/39018141731) | — | — |
| 🪸 `grouper` | **8/8** | [✅ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38958728560) | — | — |
| 🚀 `marlin` | **17/17** | [✅ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38940177445) | — | — |
| 🐡 `flounder` | **6/6** | [✅ 2026-10-16](https://github.com/tuna-os/tunaOS/actions/runs/38982594704) | — | — |
| ☢️ `flounder-sid` | **5/8** | [❌ 2026-10-17](https://github.com/tuna-os/tunaOS/actions/runs/38990365549) | — | gnome-nvidia,kde-nvidia,xfce-nvidia |

**Sibling images from separate repositories.** These TunaOS-family bootc images use BuildStream on freedesktop-sdk. They do not use packages from a distribution. Thus, the matrix above has no cells for them, and `green-criteria.yml` does not score them. Each repository runs its own checks for the build, live ISO, plain installation, and LUKS installation. The status shows the latest complete build from the main branch of that repository.

| Image | Built by | Desktop | Latest main build |
| :--- | :--- | :--- | :--- |
| 🏔️ `ghcr.io/tuna-os/tromso` | [tromso](https://github.com/tuna-os/tromso) | KDE | [✅ 2026-10-15](https://github.com/tuna-os/tromso/actions/runs/38684318450) |
| 🐭 `ghcr.io/tuna-os/xfce-linux` | [xfce-linux](https://github.com/tuna-os/xfce-linux) | XFCE | [✅ 2026-10-16](https://github.com/tuna-os/xfce-linux/actions/runs/38835702023) |

**Built 138/147 · composite green 125/147 (93% built)** — The remainder has **3 failures** and **6 never reached** (stale: 0); no job asserted the latter. We show the two values separately. A cell with no job has no test, but it can still work.

**Factory health: 125/147 cells green**

**Install-tested: 110/110 · Lifecycle-tested: 49/52 · Never tested: 25**

**Known regressions: 11 `blocking`, 94 advisory**

**Last full sweep: 46 days ago (2026-09-01)**

The score for composite green uses published cells, per [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md). [`.github/green-criteria.yml`](.github/green-criteria.yml) provides the score. Today, these criteria prevent publication: `boots`, `builds`, `desktop`, `no_silent_omissions`, `parity`. A cell must satisfy each criterion.

Skipped cells and cells with no test do not count as green. The full per-axis board is [docs/MATRIX-STATUS.md](docs/MATRIX-STATUS.md). This snapshot of CI shows one point in time. It does not promise a support tier.

<!-- build-status:end -->

## Get started

- **Install from an ISO:** [📦 tunaos.org/download](https://tunaos.org/download)
- **Install from Windows (no USB drive needed):** [🪟 wootc installer](https://github.com/tuna-os/wootc) (download from [releases](https://github.com/tuna-os/wootc/releases) / read the [Migration Guide](MIGRATION.md#from-windows-wootc))
- **Build your own ISO in the browser:** [🛠️ tunaos.org/iso-builder](https://tunaos.org/iso-builder)
- **Switch an existing bootc system:**

  ```bash
  sudo bootc switch ghcr.io/tuna-os/yellowfin:gnome
  ```

For local media builds, signature and SBOM checks, registry authentication,
and pull help, read [docs/INSTALL.md](docs/INSTALL.md).

## Contributing

Contributions welcome! See [`CONTRIBUTING.md`](CONTRIBUTING.md) for development
environment setup, the build workflow and pre-commit checklist, pull request
guidelines, and an architecture overview.

## Community and support

- 🐛 **Report Issues:** [GitHub Issues](https://github.com/tuna-os/tunaOS/issues)
- [m] **Chat**: [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)
- 🎮 **Discord:** [TunaOS](https://discord.gg/MXSTqB8Nv)

Related communities: [Universal Blue Discord](https://discord.gg/WEu6BdFEtp) ·
[AlmaLinux Atomic SIG](https://chat.almalinux.org/almalinux/channels/sigatomic)

## Documentation

Start here:

- [User Guide](docs/USER-GUIDE.md) — image choice, installation, updates, rollback, apps, and encryption
- [Developer Guide](docs/DEVELOPER-GUIDE.md) — the complete pipeline with architecture diagrams
- [Installation](docs/INSTALL.md) — media builds, verification, and registry access
- [Hardware Support](docs/HARDWARE.md) — requirements and ARM laptop status
- [Matrix Status](docs/MATRIX-STATUS.md) — quality status for each variant×desktop cell
- [Roadmap](ROADMAP.md) — project direction and feature status
- [Vision](VISION.md) — project philosophy

The full index of every guide, policy, and project plan is at
[docs/README.md](docs/README.md).

---

<div align="center">
<img width="400" height="400" alt="Tuna_OS_Logo" src="https://github.com/user-attachments/assets/0c0de438-25ae-429d-b7a5-fe32ea85547f" />

*Made by James in his free time*


*Powered by [Bootc](https://github.com/bootc-dev/bootc)*


<a href="https://github.com/bootc-dev/bootc">
<img width="100" height="130" alt="Bootc_Logo" src="https://raw.githubusercontent.com/containers/common/main/logos/bootc-logo-full-vert.png" />
</a>

---

This repository and many [tuna-os](https://github.com/tuna-os) repositories
use **[Hive](https://hive.tunaos.org)** for development and maintenance. Hive
is a development platform for AI agents. It uses
[KubeStellar](https://kubestellar.io/) for orchestration.

---

*Inspired by [Bluefin](https://projectbluefin.io) and the [Universal Blue](https://universal-blue.org/) Community*

*Licensed under [Apache 2.0](https://github.com/tuna-os/tunaOS/blob/main/LICENSE)*

</div>

<!-- hive-contribute-plea: donated-compute appeal, keep in sync across repos -->
## Contribute compute — no code needed

No time to write code? You can still push this project's backlog forward. A TunaOS AI-agent hive works on this repository. Lend the hive your AI subscription or API tokens, and your machine runs tasks from this project's backlog.

- 🏫 [Contribute compute to the school hive](https://school.tunaos.org/contribute)
