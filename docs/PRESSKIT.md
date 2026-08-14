# TunaOS Press Kit

> Status: **draft** — maintainer review before first use.
> Tracking issues: [#1534](https://github.com/tuna-os/tunaOS/issues/1534) (tech press),
> [#1535](https://github.com/tuna-os/tunaOS/issues/1535) (Linux YouTubers),
> [#1646](https://github.com/tuna-os/tunaOS/issues/1646) (this kit).
> Prepared: 2026-08-14.

This is the one-pager for anyone writing, filming, or recording about
TunaOS — Linux tech press (It's FOSS, OMG! Linux, Linux Magazine, Phoronix),
Linux YouTubers (DistroTube, The Linux Experiment, Chris Titus Tech), and
podcasters. All facts below are maintainer-verified as of 2026-08-14.

## One-liner

**TunaOS** is a family of atomic, image-based (bootc) Linux desktops that
bring **current desktops to Enterprise Linux lifecycles** — GNOME 51 on
AlmaLinux/CentOS Stream before the EL point release, plus KDE, COSMIC,
Niri, XFCE, and Pantheon flavors on a dozen base distributions.

## The pitch

Linux servers run on decade-long lifecycles. Linux desktops move on
six-month cadences. TunaOS closes that gap: every variant is a
container-native **bootc** image with atomic updates, verified (keyless-
signed) upgrades, and rollback — while tracking current desktop releases on
enterprise bases. It is a fork of Bluefin (Universal Blue) with a
manifest-driven, multi-distro build pipeline.

## Headline stories (pick one)

1. **GNOME 51 on EL10 — before upstream** (Sept 12, 2026): TunaOS packages
   the full GNOME 51 stack (mutter, gtk4, libadwaita, nautilus, gdm, orca)
   for AlmaLinux/CentOS Stream via its own RPM build chain, so enterprise
   desktops get GNOME on the upstream schedule.
2. **ARM everywhere**: Apple Silicon (M1/M2) images via bootc-installer-asahi
   and Snapdragon X Elite (X13s-class) laptop builds — bootc desktops on the
   two fastest-growing ARM Linux hardware classes.
3. **Keyless supply chain**: every RPM/DEB is signed with Sigstore/cosign
   keyless signing (verified against Rekor, SBOMs included) — no long-lived
   signing keys, a real chain of trust for desktops.
4. **Pantheon on Ubuntu LTS (Gurnard)**: the elementary-OS desktop as an
   atomic bootc image on Ubuntu 24.04 LTS.
5. **bootc-migrate**: migrate between Bluefin/Dakota and TunaOS without
   reinstalling — container-native rebase, one transaction.
6. **13 variants, one model**: from Arch and Gentoo to Debian, openSUSE,
   and EL — same atomic update model everywhere.

## Variant matrix (as of 2026-08-14)

| Variant | Base | Desktop | Arch |
|---|---|---|---|
| Albacore | AlmaLinux 10 | GNOME | amd64, arm64 |
| Yellowfin | AlmaLinux Kitten 10 | GNOME | amd64, arm64 |
| Skipjack | CentOS Stream 10 | KDE | amd64, arm64 |
| Redfin | RHEL 10 | GNOME (local build) | amd64, arm64 |
| Bonito | Fedora 44 / Rawhide | Niri (also GNOME/KDE) | amd64, arm64 |
| Hummingbird | Fedora (container-native) | GNOME | amd64, arm64 |
| Grouper | Ubuntu 26.04 | GNOME | amd64 |
| Gurnard | Ubuntu 24.04 LTS | Pantheon | amd64, arm64 |
| Marlin | Arch Linux | GNOME/KDE | amd64 |
| Flounder / Sid | Debian 13 / Sid | GNOME | amd64 |
| Sailfin | openSUSE Tumbleweed | GNOME/KDE | amd64 |
| Guppy | Gentoo | GNOME/KDE | amd64 |
| Tromsø / XFCE Linux | BuildStream builds | KDE / XFCE | amd64 |

Desktop flavors across bases: GNOME, KDE Plasma, COSMIC (Rust, from
System76, built via Tideforge), Niri (scrollable tiling), XFCE (Wayland via
xfwl4), Pantheon.

## Fast facts

- **~55 GitHub stars** (flat; growth is the Q4 focus, target ≥100) — 14+
  repos in the org
- **Daily verified builds**: multi-arch images published to GHCR, verified
  boot reports on every release, ISO boot gates
- **DistroWatch**: listing draft in-repo, submission in progress
- **Keyless signing** on the native RPM/DEB repos (R2-hosted), replacing the
  legacy COPR backports
- **Single-maintainer project today** — actively seeking first external
  contributors; 8-task good-first-issue pool ahead of Hacktoberfest 2026
- **Based on**: Bluefin/Universal Blue (upstream), bootc (CNCF Sandbox),
  AlmaLinux, Fedora, CentOS Stream

## Key links

| Asset | URL |
|---|---|
| Website / downloads | https://tunaos.org |
| Blog | https://tunaos.org/blog |
| GitHub org | https://github.com/tuna-os |
| Main repo | https://github.com/tuna-os/tunaOS |
| Adopters | https://github.com/tuna-os/tunaOS/blob/main/ADOPTERS.md |
| Branding (SVGs) | https://github.com/tuna-os/branding |
| Community chat | https://matrix.to/#/%23tunaos:reilly.asia |
| Contributor guide | https://github.com/tuna-os/tunaOS/blob/main/CONTRIBUTING.md |

## Contact

- **Primary**: Matrix `#tunaos:reilly.asia` (public, maintainer-active)
- **Issues/PRs**: GitHub (tuna-os org) — fastest for technical questions
- **Mastodon**: `@tunaos@fosstodon.org` (registration in progress, #1634)

## Boilerplate blurb

> TunaOS is a family of atomic, image-based Linux desktops that pair
> current desktop environments with Enterprise Linux lifecycles. Built on
> bootc container-native technology, every TunaOS variant ships atomic
> updates, keyless-signed verified upgrades, and rollback — with GNOME,
> KDE Plasma, COSMIC, Niri, XFCE, and Pantheon flavors across AlmaLinux,
> Fedora, CentOS Stream, Ubuntu, Debian, Arch, Gentoo, openSUSE, and more.
> TunaOS is a fork of Bluefin (Universal Blue), published by the tuna-os
> community. Learn more at tunaos.org.

## Interview / demo talking points

- Show a `bootc upgrade` + rollback in 2 minutes (any variant)
- Show GNOME 51 running on AlmaLinux 10 (the EL10 backport story)
- Show keyless signing verification (cosign verify against Rekor)
- Show the ARM build (Apple Silicon / Snapdragon) booting

## For YouTubers

- **DistroTube**: immutable-desktop landscape / how TunaOS fits (08-08 blog
  post is the map)
- **The Linux Experiment**: GNOME 51 on EL10 + the ARM story
- **Chris Titus Tech**: bootc-migrate (Bluefin → Dakota) + keyless signing
- Screen/ISO assets: tuna-os/branding SVGs; screenshots in blog posts
  (license: repo-specific, CC0 unless noted — check each asset)

---
*Prepared by the outreach agent (ACMM L6 — full mode) for tuna-os/tunaOS.*
