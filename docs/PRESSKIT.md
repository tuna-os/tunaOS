# TunaOS Press Kit

> Status: **draft** — maintainer review before first use.
> Tracking issues: [#1534](https://github.com/tuna-os/tunaOS/issues/1534) (tech press),
> [#1535](https://github.com/tuna-os/tunaOS/issues/1535) (Linux YouTubers),
> [#1646](https://github.com/tuna-os/tunaOS/issues/1646) (this kit).
> Prepared: 2026-08-14. Facts re-verified 2026-08-14 against
> [ROADMAP.md](https://github.com/tuna-os/tunaOS/blob/main/ROADMAP.md) (the
> canonical per-variant status table) per the maintainer's press-claim guard.

This is the one-pager for anyone writing, filming, or recording about
TunaOS — Linux tech press (It's FOSS, OMG! Linux, Linux Magazine, Phoronix),
Linux YouTubers (DistroTube, The Linux Experiment, Chris Titus Tech), and
podcasters.

## One-liner

**TunaOS** is a family of atomic, image-based (bootc) Linux desktops that
bring **current desktops to Enterprise Linux lifecycles** — GNOME 51 on
AlmaLinux/CentOS Stream before the EL point release, plus KDE, COSMIC,
Niri, XFCE, and Pantheon flavors across eleven base distributions.

## The pitch

Linux servers run on decade-long lifecycles. Linux desktops move on
six-month cadences. TunaOS closes that gap: every variant is a
container-native **bootc** image with atomic updates, verified (keyless-
signed) upgrades, and rollback — while tracking current desktop releases on
enterprise bases. It is a fork of Bluefin (Universal Blue) with a
manifest-driven, multi-distro build pipeline.

## Headline stories (pick one)

1. **GNOME 51 on EL10 — before the EL point release** (Sept 12, 2026):
   TunaOS packages the full GNOME 51 stack (mutter, gtk4, libadwaita,
   nautilus, gdm, orca) for AlmaLinux/CentOS Stream via its own RPM build
   chain, so enterprise desktops get GNOME on the upstream schedule instead
   of waiting for the next EL point release.
2. **ARM is next**: Snapdragon X Elite (X13s-class) laptop builds are
   bootc desktops on one of the fastest-growing ARM Linux hardware classes,
   and an **experimental** Apple Silicon (M1/M2) installer
   (bootc-installer-asahi) ships kernel + glue today — boot payloads are
   still pending ([#777](https://github.com/tuna-os/tunaos/issues/777)), so
   Apple Silicon is an engineering preview, not a shipped product.
3. **Keyless supply chain**: every RPM/DEB is signed with Sigstore/cosign
   keyless signing (verified against Rekor, SBOMs included) — no long-lived
   signing keys, a real chain of trust for desktops.
4. **Pantheon on Ubuntu LTS (Gurnard)**: the elementary-OS desktop as an
   atomic bootc image on Ubuntu 24.04 LTS (currently **Experimental**,
   per the variant lifecycle).
5. **bootc-migrate**: migrate between Bluefin/Dakota and TunaOS without
   reinstalling — container-native rebase, one transaction.
6. **11 variants, one model**: from Arch and Gentoo to Debian, openSUSE,
   and EL — same atomic update model everywhere.

## Variant matrix (canonical, as of 2026-08-14)

Status terms follow [VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md): **Stable**
means GA, **Beta** means published for testing on tunaos.org/download,
**Experimental** means building but pre-admission-gate. This table tracks
the canonical table in [ROADMAP.md](../ROADMAP.md).

| Variant | Base | Status |
|---|---|---|
| Yellowfin | AlmaLinux Kitten 10 | Stable |
| Albacore | AlmaLinux 10 | Stable |
| Skipjack | CentOS Stream 10 | Beta |
| Bonito / Bonito Rawhide | Fedora 44 / Rawhide | Beta |
| Sailfin | openSUSE Tumbleweed (rolling) | Beta |
| Guppy | Gentoo Linux (source-based) | Beta |
| Grouper | Ubuntu 26.04 | Beta |
| Marlin | Arch Linux (rolling), CachyOS overlay | Beta |
| Flounder / Flounder Sid | Debian 13 Trixie / Sid | Beta |
| Hummingbird | Fedora Hummingbird (container-native) | Experimental |
| Gurnard | Ubuntu 24.04 Noble | Experimental |

Desktop **flavors** available across bases (not separate variants): GNOME,
KDE Plasma, COSMIC (Rust, from System76, built via Tideforge), Niri
(scrollable tiling), XFCE (Wayland via xfwl4), and Pantheon (on Gurnard).

**Architecture**: container images are multi-arch (amd64 + arm64). **ISOs
are amd64-only today** — aarch64 ISO publishing is tracked in
[#1592](https://github.com/tuna-os/tunaos/issues/1592) and not yet shipped,
so press copy must not promise aarch64 ISOs.

**Related projects** (separate repos in the tuna-os org, not TunaOS
variants): [Tromsø](https://github.com/tuna-os/tromso) (KDE) and
[XFCE Linux](https://github.com/tuna-os/xfce-linux) (lightweight XFCE
image, BuildStream-built).

## Fast facts

- **~55 GitHub stars** (flat; growth is the Q4 focus, target ≥100) — 37
  active repos in the org (per ROADMAP, 2026-08-12)
- **Daily CI builds**: multi-arch images published to GHCR; verified boot
  reports on every release; ISO boot gates
- **DistroWatch**: listing draft in-repo, submission in progress
- **Keyless signing** on the native RPM/DEB repos (R2-hosted), replacing
  the legacy COPR backports
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
- Show the ARM story: Snapdragon X Elite build, plus the experimental
  Apple Silicon installer preview

## For YouTubers

- **DistroTube**: immutable-desktop landscape / how TunaOS fits (08-08 blog
  post is the map)
- **The Linux Experiment**: GNOME 51 on EL10 + the ARM story
- **Chris Titus Tech**: bootc-migrate (Bluefin → Dakota) + keyless signing
- Screen/ISO assets: tuna-os/branding SVGs; screenshots in blog posts
  (license: repo-specific, CC0 unless noted — check each asset)

---
*Prepared by the outreach agent (ACMM L6 — full mode) for tuna-os/tunaOS.
Fact-checked against ROADMAP.md canonical variant table on 2026-08-14 —
variant names/statuses and the amd64-only-ISO constraint match the
maintainer's press-claim guard.*
