# TunaOS Adopters

> A list of organizations and projects that use TunaOS in production, development, or evaluation.
>
> If you or your organization is using TunaOS, we'd love to add you to this list!
> See the [adoption call](docs/ADOPTION-CALL.md) to self-identify in the public
> Show-and-tell Discussion, or submit a PR with the same consent details.

## Production Users

_(None listed yet — see the [adoption call](docs/ADOPTION-CALL.md) and be the first!)_

## Development & Evaluation

| Organization | Use Case | Variant(s) | Since |
|---|---|---|---|
| [@hanthor](https://github.com/hanthor) (Project Maintainer) | Personal daily driver — development, testing, and dogfooding all variants | Yellowfin GNOME, Albacore GNOME, Skipjack KDE | 2026-04 |
| [TunaOS Hive Agents](https://github.com/tuna-os) | Automated CI/CD — build, test, and release pipeline runs on TunaOS infrastructure | Yellowfin GNOME, Albacore GNOME | 2026-05 |

## Ecosystem & Downstream Projects

| Project | Relationship | Link |
|---|---|---|
| [Universal Blue](https://universal-blue.org/) | Upstream inspiration — TunaOS is a fork of Bluefin LTS | [github.com/ublue-os](https://github.com/ublue-os) |
| [Bluefin](https://projectbluefin.io) | Direct upstream — bootc-based desktop foundation | [github.com/ublue-os/bluefin-lts](https://github.com/ublue-os/bluefin-lts) |
| [AlmaLinux OS](https://almalinux.org) | Base OS — Albacore, Yellowfin variants built on AlmaLinux 10 / Kitten | [almalinux.org](https://almalinux.org) |
| [Fedora Project](https://fedoraproject.org) | Base OS — Bonito variant built on Fedora | [fedoraproject.org](https://fedoraproject.org) |
| [CentOS Stream](https://centos.org) | Base OS — Skipjack variant built on CentOS Stream 10 | [centos.org](https://centos.org) |
| [Homebrew](https://brew.sh) | Package manager — baked into all images | [brew.sh](https://brew.sh) |
| [Flathub](https://flathub.org) | App distribution — pre-enabled in all images | [flathub.org](https://flathub.org) |
| [BuildStream](https://buildstream.build) | Build tool — used by Tromsø (KDE) and XFCE Linux variants | [buildstream.build](https://buildstream.build) |
| [bootc-dev/bootc](https://github.com/bootc-dev/bootc) | Upstream bootc project — bootable container technology foundation (CNCF Sandbox) | [github.com/bootc-dev/bootc](https://github.com/bootc-dev/bootc) |
| [System76 / COSMIC](https://system76.com/cosmic) | Desktop environment — COSMIC variant of TunaOS | [github.com/pop-os/cosmic-epoch](https://github.com/pop-os/cosmic-epoch) |
| [KDE Community](https://kde.org) | Desktop environment — Tromsø variant built on KDE Plasma 6 | [kde.org](https://kde.org) |
| [XFCE Community](https://xfce.org) | Desktop environment — XFCE Linux variant built on XFCE 4.20 | [xfce.org](https://xfce.org) |
| [Project Bluefin (Dakota)](https://github.com/projectbluefin/dakota) | Reference implementation — Tromsø and XFCE Linux modeled on Dakota's BuildStream approach | [github.com/projectbluefin/dakota](https://github.com/projectbluefin/dakota) |
| [Debian](https://www.debian.org) | Base OS — Flounder / Flounder Sid variants built on Debian | [debian.org](https://www.debian.org) |
| [Gentoo](https://www.gentoo.org) | Base OS — Guppy variant built on Gentoo | [gentoo.org](https://www.gentoo.org) |
| [Arch Linux](https://archlinux.org) | Base OS — Marlin variant built on Arch Linux | [archlinux.org](https://archlinux.org) |
| [Ubuntu](https://ubuntu.com) | Base OS — Ubuntu variant image | [ubuntu.com](https://ubuntu.com) |
| [Niri](https://github.com/YaLTeR/niri) | Desktop environment — scrollable-tiling Wayland compositor (Bonito variant) | [github.com/YaLTeR/niri](https://github.com/YaLTeR/niri) |
| [elementary OS](https://elementary.io) | Desktop environment — Pantheon desktop for the Gurnard (Ubuntu 24.04 LTS) variant | [elementary.io](https://elementary.io) |
| [Fedora COPR](https://copr.fedorainfracloud.org) | Package distribution (legacy/compatibility) — GNOME 49/50 backports for CentOS Stream 10 / Fedora bases; being retired in favor of the native RPM + Cloudflare R2 pipeline below | [copr.fedorainfracloud.org](https://copr.fedorainfracloud.org) |
| [Cloudflare R2](https://www.cloudflare.com/developer-platform/products/r2/) | Package/artifact distribution — native EL10 RPM repository (GNOME 51 onward), ISOs, and boot screenshots | [cloudflare.com/r2](https://www.cloudflare.com/developer-platform/products/r2/) |
| [Tideforge](https://tideforge.org) | Build service — COSMIC packages built from source for the EL10 desktop cells | [tideforge.org](https://tideforge.org) |
| [GHCR](https://ghcr.io) | Image registry — all published TunaOS image flavors | [github.com/orgs/tuna-os/packages](https://github.com/orgs/tuna-os/packages) |
| [Asahi Linux](https://asahilinux.org) | Hardware enablement — bootc-installer-asahi's payload layout is modeled on fedora-asahi/nixos-asahi conventions; targets M1/M2 Macs via Asahi's kernel/firmware work | [github.com/AsahiLinux](https://github.com/AsahiLinux) |

## Adding Your Organization

To add your organization to this list:

1. Open a PR adding your entry to the **Production Users** or **Development & Evaluation** table
2. Include the variant(s) you use and a brief description of your use case
3. (Optional) Add any relevant links (blog posts, case studies, conference talks)

Questions? Reach out on [Matrix](https://matrix.to/#/%23tunaos:reilly.asia) or open a discussion.

---

*Maintained by the TunaOS community. Last updated: 2026-08-11.*
