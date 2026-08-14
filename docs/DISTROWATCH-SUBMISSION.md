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
All published images are multi-arch (x86_64 and aarch64), with Apple Silicon
(M1/M2) support via an Asahi-based installer and Snapdragon X Elite laptop
support documented per variant.

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
| **Download** | https://tunaos.org/download (ISOs for all variants) |
| **Image registry** | https://github.com/orgs/tuna-os/packages (GHCR) |
| **Status** | Active (daily rolling builds; weekly/quarterly-LTS stability tiers) |
| **Origin** | USA / global maintainer community |
| **Desktop environments** | GNOME, KDE Plasma, COSMIC, Niri, XFCE, Pantheon |
| **Package management** | bootc image-based (rpm-ostree-style), atomic |
| **Architectures** | x86_64, aarch64 |
| **License** | Apache-2.0 |
| **First release** | 2026 |
| **Based on** | AlmaLinux 10, CentOS Stream 10, Fedora, Ubuntu, Debian, Gentoo, Arch |
| **Related projects** | bootc (CNCF Sandbox), Bluefin/Universal Blue, Corral |

## Variant matrix (for the listing)

| Variant | Base | Desktop | Status |
|---|---|---|---|
| Yellowfin | AlmaLinux Kitten 10 | GNOME | Stable |
| Albacore | AlmaLinux 10 | GNOME | Stable |
| Bonito | Fedora | GNOME | Beta |
| Skipjack | CentOS Stream 10 | KDE Plasma | Beta |
| Tromsø | BuildStream-based | KDE Plasma 6 | Stable |
| XFCE Linux | BuildStream-based | XFCE 4.20 | Stable |
| COSMIC | EL10 cell (Tideforge-built) | COSMIC | Beta |
| Niri | Fedora | Niri | Beta |
| Gurnard | Ubuntu 24.04 LTS | Pantheon | Experimental |
| Marlin | Arch | GNOME | Beta |

## Suggested pitch to DistroWatch Weekly editors

> "TunaOS brings the bootable-container model to the enterprise desktop:
> GNOME and KDE on 10-year Enterprise Linux lifecycles, updated atomically
> like a container fleet. New this quarter: an Ubuntu 24.04 + Pantheon
> variant (Gurnard) and Apple Silicon installer support."

## Submission checklist

- [ ] Maintainer review of description and variant matrix
- [ ] Confirm current download URLs + image tags before submission
- [ ] Submit via DistroWatch project submission form
- [ ] Add tunaos.org/download link to any public project listings
- [ ] Record submission date + referral traffic in ADOPTION-METRICS.md (funnel tier 1, #1311)
