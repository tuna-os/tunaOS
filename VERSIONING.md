# Versioning Policy

## Scheme

tunaOS uses **date-based tags** with a flavor prefix:

```
<flavor>-<YYYYMMDD>
```

Examples: `gnome-20260606`, `kde-20260606`, `cosmic-20260606`

## Rationale

CI rebuilds the tunaOS images every day from upstream sources. There are no feature releases. Each build includes the newest upstream changes. Date tags give:

- **Freshness signal**: the date shows when an image became the `:testing` image of its flavor.
- **Traceability**: each date tag points to one image digest.
- **Simplicity**: there are no version numbers.

## Release rings

Each flavor of each variant has two rings ([RFC 018](docs/rfc/rfc018-testing-stable-rings.md)):

| Ring | Tag | What it gets |
|------|-----|--------------|
| **Stable** | `<flavor>`, for example `yellowfin:gnome` | A `:testing` image that has soaked for the variant's `soak_days` (3 days, 5 for yellowfin) with no open release blocker and no failed post-publish check. `promote-stable.yml` moves it daily at 06:00 UTC. This is the default. |
| **Testing** | `<flavor>-testing`, for example `yellowfin:gnome-testing` | Every image that passes the CI gates (build, signature, boot gate, desktop contract), on the day it passes. |

There is no LTS ring and no weekly ring. The `:latest` tag is not part of this scheme.

Other tags:

| Tag | Use |
|-----|-----|
| `<flavor>-<YYYYMMDD>` | The image that became the `:testing` image on that day. Use it to pin a host to one image, and as a rollback anchor. |
| `<flavor>-<arch>` | The stable image for one architecture, for example `gnome-amd64`. |
| `<flavor>-<arch>-<YYYYMMDD>` | The dated tag for one architecture. |
| `<flavor>-candidate` | Internal. CI pushes each build to this tag and runs the gates on it. Do not install it. |

A new flavor has no stable image before its first soak. The first image that passes CI for that flavor also becomes its first stable image.

## Choose a ring

Most users stay on the stable ring:

```bash
sudo bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/yellowfin:gnome
```

To get each image on the day it passes CI, switch to the `-testing` tag:

```bash
sudo bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/yellowfin:gnome-testing
```

To go back to the stable ring, switch to the bare tag again. If a `:testing` image is bad, `sudo bootc rollback` returns to the previous deployment.

## Variant Tags

| Tag | Description |
|-----|-------------|
| `gnome` | GNOME |
| `kde` | KDE Plasma |
| `cosmic` | COSMIC Desktop |
| `niri` | Niri (tiling Wayland) |
| `*-hwe` | Hardware Enablement kernel (suffix, for example `gnome-hwe`) |
| `*-nvidia` | NVIDIA drivers and CUDA (suffix, for example `gnome-nvidia`) |
| `*-nvidia-hwe` | NVIDIA drivers with the HWE kernel (suffix, for example `gnome-nvidia-hwe`) |

Hardware variants add a suffix to the desktop tag: `gnome-hwe-testing`, `gnome-nvidia-<YYYYMMDD>`.

## Breaking Changes

Release notes describe the changes that can break a system. Examples are a new kernel version, a major desktop update and a new file system layout. There is no major or minor version number. Date tags are in date order, not semantic.

## Docker/OCI Tags

Container images use the same scheme:

```
ghcr.io/tuna-os/yellowfin:gnome
ghcr.io/tuna-os/yellowfin:gnome-testing
ghcr.io/tuna-os/albacore:kde-hwe-20260606
```

## Migration

Users who migrate from Universal Blue or Fedora Silverblue/Kinoite rebase to the stable tag:

```bash
rpm-ostree rebase ostree-unverified-registry:ghcr.io/tuna-os/yellowfin:gnome
```

## References

- [RFC 018: the `:testing` and `:stable` rings](docs/rfc/rfc018-testing-stable-rings.md)
- [AlmaLinux lifecycle](https://almalinux.org/blog/2025-05-27-welcoming-almalinux-10/)
- [bootc documentation](https://containers.github.io/bootc/)
- [Universal Blue](https://universal-blue.org/)

---
*Adopted: 2026-06-06 | Proposed by: strategist agent | Issue: #274 | Rings: RFC 018, #4154*
