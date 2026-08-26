# DistroWatch — Project Submission Draft

> Status: **draft** — for maintainer review before submission.
> Tracking issue: [#1333](https://github.com/tuna-os/tunaOS/issues/1333) (DistroWatch listing submission).
> Target: DistroWatch "Waiting in the Wings" / new-project listing (distrowatch.com).
> Prepared: 2026-08-12. Suggested submission window: Fedora 45 release week (~Oct 20+) so the listing reflects the freshest ISO set.

## Project description (~200 words, submission-ready)

TunaOS is an immutable, bootable-container desktop Linux distribution built
for the enterprise. Instead of a classic package-installed root filesystem,
TunaOS ships complete desktop images as OCI containers — the same technology
that runs the datacenter — and applies them atomically with bootc. Updates
are transactional: one image, one rollback, verified upgrades, and the
desktop can never be left half-upgraded.

Variants cover the desktop spectrum on a common base: GNOME with backports
onto Enterprise Linux lifecycles (AlmaLinux 10 and CentOS Stream 10),
KDE Plasma 6, the Rust-built COSMIC, the scrollable-tiling Niri compositor,
XFCE 4.20, plus Ubuntu-, Debian-, Gentoo-, Arch-, and Fedora-based flavors.
Published container images are multi-arch (x86_64 and aarch64). Downloadable
ISOs are x86_64 today — the artifact matrix that builds them is still
amd64-only (#1378), so an aarch64 listing would promise a download that does
not exist. Apple Silicon (M1/M2) work is in progress rather than shipped: the
build config marks the Asahi flavor "EXPERIMENTAL: kernel + glue only; boot
payloads pending #777", and the macOS installer app has not yet been proven on
real hardware.

Under the hood, TunaOS is manifest-driven: a YAML file defines a variant,
the pipeline turns it into a published, signed, multi-arch image, and CI
verifies every release. For teams already running Kubernetes, the Corral
project manages desktop and service VMs as declarative resources on the
same cluster estate, with snapshots and GPU passthrough as code.

TunaOS is free and open source under the Apache-2.0 license, with a daily
rolling build cadence (plus weekly and quarterly-LTS stability tiers),
verified boot reports, and an active community on Matrix.

## Metadata for the listing

| Field | Value |
|---|---|
| **Name** | TunaOS |
| **Homepage** | https://tunaos.org |
| **Source** | https://github.com/tuna-os/tunaOS |
| **Download** | https://tunaos.org/download (x86_64 ISOs) |
| **Image registry** | https://github.com/orgs/tuna-os/packages (GHCR) |
| **Status** | Active (daily rolling builds; weekly/quarterly-LTS stability tiers) |
| **Origin** | USA / global maintainer community |
| **Desktop environments** | GNOME, KDE Plasma, COSMIC, Niri, XFCE, Pantheon |
| **Package management** | bootc image-based (rpm-ostree-style), atomic |
| **Architectures** | Images: x86_64, aarch64. ISOs: x86_64 (aarch64 ISO builds tracked in #1378) |
| **License** | Apache-2.0 |
| **First release** | 2026 |
| **Based on** | AlmaLinux 10, CentOS Stream 10, Fedora, Ubuntu, Debian, Gentoo, Arch |
| **Related projects** | bootc (CNCF Sandbox), Bluefin/Universal Blue, Corral |

## Variant matrix (for the listing)

Copied from [ROADMAP.md](../ROADMAP.md)'s variant table, which states that it
"is the canonical per-variant status; tunaos.org wiki and blog copy must track
it". An earlier hand-written version of this section had drifted from it:
Skipjack listed Stable (canonical: Beta), Marlin listed Alpha (Beta), Gurnard
listed as a headline new variant (Experimental, #1341), five variants missing,
and COSMIC/Niri/XFCE listed as separate variants when they are desktop flavors
available across variants — which would have told DistroWatch this project has
distributions it does not have.

| Variant | Base | Desktops | Status |
|---------|------|----------|--------|
| Yellowfin | AlmaLinux Kitten 10 | GNOME, KDE, COSMIC, Niri, XFCE | Stable |
| Albacore | AlmaLinux 10 | GNOME, KDE, COSMIC, Niri, XFCE | Stable |
| Skipjack | CentOS Stream 10 | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Bonito / Bonito Rawhide | Fedora 44 / Rawhide | GNOME, KDE, COSMIC, Niri | Beta |
| Sailfin | openSUSE Tumbleweed (rolling) | GNOME, KDE, Niri, XFCE | Beta |
| Guppy | Gentoo Linux (source-based) | GNOME, KDE, Niri, XFCE | Beta |
| Grouper | Ubuntu 26.04 | GNOME, KDE, Niri, XFCE | Beta (RFC 010) |
| Marlin | Arch Linux (rolling), CachyOS overlay | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Flounder / Flounder Sid | Debian 13 Trixie / Sid | GNOME, KDE, COSMIC, Niri, XFCE | Beta |
| Hummingbird | Fedora Hummingbird (container-native bootc) | Base, GNOME, COSMIC | Experimental (see #1341) |
| Gurnard | Ubuntu 24.04 Noble | Base, Pantheon | Experimental (see #1341) |

**Status terms** follow [VARIANT-LIFECYCLE.md](../VARIANT-LIFECYCLE.md):
`Stable` means GA, `Beta` means published for testing. Experimental variants
predate the admission gate and have no named owner yet — worth saying plainly
to an editor rather than listing them alongside GA products.

## Suggested pitch to DistroWatch Weekly editors

> "TunaOS brings the bootable-container model to the enterprise desktop:
> GNOME and KDE on 10-year Enterprise Linux lifecycles, updated atomically
> like a container fleet. New this quarter: an Ubuntu 24.04 + Pantheon
> variant (Gurnard, experimental) and in-progress Apple Silicon support."

Deliberately not "Apple Silicon installer support" — that reads as shipped, and
a DistroWatch reader would reasonably try to download it. Pitch the experimental
things as experimental; an editor who finds out otherwise remembers.

## Submission checklist

- [ ] Maintainer review of description and variant matrix
- [ ] Re-check the variant matrix against ROADMAP.md's canonical table — it is
      copied, not authored here, and drifted once already
- [ ] Confirm current download URLs + image tags before submission
- [ ] Submit via DistroWatch project submission form
- [ ] Add tunaos.org/download link to any public project listings
- [ ] Record submission date + referral traffic in ADOPTION-METRICS.md (funnel tier 1, #1311)
