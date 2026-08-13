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

Variants cover the desktop spectrum on Enterprise Linux bases (AlmaLinux 10
and CentOS Stream 10): GNOME, KDE Plasma, the Rust-built COSMIC, the
scrollable-tiling Niri compositor, and XFCE. Additional published variants
track Fedora, openSUSE, Ubuntu, Debian, Gentoo, and Arch. Platform support is
variant-specific: the catalog currently includes x86_64 and selected arm64
images, while Apple Silicon (M1/M2) follows the Asahi installer path.

Under the hood, TunaOS is manifest-driven: a YAML file defines a variant,
the pipeline turns it into a published, signed image for each supported
architecture, and CI verifies every release. For teams already running Kubernetes, the Corral
project manages desktop and service VMs as declarative resources on the
same cluster estate, with snapshots and GPU passthrough as code.

TunaOS is free and open source under the Apache-2.0 license, with weekly
release cadence, verified boot reports, and an active community on Matrix.

## Metadata for the listing

| Field | Value |
|---|---|
| **Name** | TunaOS |
| **Homepage** | https://tunaos.org |
| **Source** | https://github.com/tuna-os/tunaOS |
| **Download** | https://tunaos.org/download (ISOs for all variants) |
| **Image registry** | https://github.com/orgs/tuna-os/packages (GHCR) |
| **Status** | Active (weekly releases) |
| **Origin** | USA / global maintainer community |
| **Desktop environments** | GNOME, KDE Plasma, COSMIC, Niri, XFCE, Pantheon (variant-dependent) |
| **Package management** | bootc image-based (rpm-ostree-style), atomic |
| **Architectures** | x86_64; arm64 for selected variants |
| **License** | Apache-2.0 |
| **First release** | 2026 |
| **Based on** | AlmaLinux Kitten 10, AlmaLinux 10, CentOS Stream 10, Fedora, openSUSE Tumbleweed, Ubuntu, Debian, Gentoo, Arch |
| **Related projects** | bootc (CNCF Sandbox), Bluefin/Universal Blue, Corral |

## Variant matrix (for the listing)

| Variant | Base | Desktop(s) | Status |
|---|---|---|---|
| Yellowfin | AlmaLinux Kitten 10 | GNOME, KDE, COSMIC, Niri, XFCE | Published |
| Albacore | AlmaLinux 10 | GNOME, KDE, COSMIC, Niri, XFCE | Published |
| Skipjack | CentOS Stream 10 | GNOME, KDE, COSMIC, Niri, XFCE | Published |
| Bonito | Fedora 44 | GNOME, KDE, COSMIC, Niri, XFCE | Published |
| Bonito Rawhide | Fedora Rawhide | GNOME, KDE, COSMIC, Niri, XFCE | Rolling |
| Hummingbird | Fedora Hummingbird | Base, GNOME | Experimental |
| Sailfin | openSUSE Tumbleweed | GNOME, KDE, Niri, XFCE | Published |
| Guppy | Gentoo | GNOME, KDE | Published |
| Gurnard | Ubuntu 24.04 LTS | Base, Pantheon | Experimental |
| Grouper | Ubuntu 26.04 | GNOME, KDE, Niri, XFCE | Experimental |
| Marlin | Arch Linux | GNOME, KDE, COSMIC, Niri, XFCE | Experimental |
| Flounder | Debian 13 | GNOME, KDE, COSMIC, Niri, XFCE | Experimental |
| Flounder Sid | Debian Sid | GNOME, KDE, COSMIC, Niri, XFCE | Rolling |

The matrix intentionally lists only variants in `.github/build-config.yml`
with a published registry path. Redfin (RHEL 10) is local-build-only and is
not a DistroWatch download target. Hardware-specific suffixes (such as
`-nvidia` and `-hwe`) are image flavors, not separate distributions.

## Suggested pitch to DistroWatch Weekly editors

> "TunaOS brings the bootable-container model to the enterprise desktop:
> GNOME and KDE on 10-year Enterprise Linux lifecycles, updated atomically
> like a container fleet. New this quarter: an Ubuntu 24.04 + Pantheon
> variant (Gurnard) and an Apple Silicon installer path."

## Submission checklist

- [ ] Maintainer review of description and variant matrix
- [ ] Confirm current download URLs + image tags before submission (the
      catalog and published release assets may change before Fedora 45)
- [ ] Submit via DistroWatch project submission form
- [ ] Add tunaos.org/download link to any public project listings
- [ ] Use `https://tunaos.org/download?utm_source=distrowatch&utm_medium=referral&utm_campaign=distrowatch-2026`
      as the download link where query parameters are accepted
- [ ] Record submission date, landing URL, and referral traffic in
      `ADOPTION-METRICS.md` (funnel tier 1, #1311)

### Maintainer verification before submission

Run these checks immediately before filing the external listing so the
submission does not promise an unavailable ISO:

```sh
grep -E '^  - id:|^    description:|^    platforms:' .github/build-config.yml
gh release list --repo tuna-os/tunaos --limit 1
```

Then confirm that the download page resolves and that each advertised
variant has a current release asset. Update the matrix above if either the
catalog or release policy has changed.
