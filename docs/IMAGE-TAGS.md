# Image tag reference

The build makes image tags as `<desktop>[-hardware]`, against the variant's
registry path (see the variant table in the [README](../README.md)).

## Rings

Each flavor has a `:stable` ring and a `:testing` ring
([RFC 018](rfc/rfc018-testing-stable-rings.md)):

| Tag | Ring | Moves when |
|-----|------|------------|
| `<flavor>` (for example `yellowfin:gnome`) | Stable, the default | `promote-stable.yml` copies a `:testing` image that soaked for `soak_days` and passed the promotion gates. It runs daily at 06:00 UTC. |
| `<flavor>-testing` | Testing | An image passes the CI gates (build, signature, boot gate, desktop contract). |
| `<flavor>-<arch>` | Stable, one architecture | With `<flavor>`. |
| `<flavor>-<YYYYMMDD>`, `<flavor>-<arch>-<YYYYMMDD>` | Pin and rollback anchor | Never. The date is the day that the image became `:testing`. |
| `<alias>:<flavor>`, `<alias>:<flavor>-<YYYYMMDD>` | Alias image name (for example `almalinux:gnome`) | With `<flavor>` and the dated tag. |
| `<flavor>-candidate` | Internal | Each build. CI runs the gates on it. Do not install it. |

To follow the `:testing` ring, switch to the `-testing` tag:

```bash
sudo bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/yellowfin:gnome-testing
```

To go back to the stable ring, switch to the bare tag.

## Desktop suffixes

* `gnome`: GNOME (stable)
* `kde`: KDE Plasma
* `cosmic`: COSMIC Desktop
* `niri`: Niri (tiling Wayland compositor)
* `xfce`: XFCE (Wayland experimental)
* `pantheon`: Pantheon desktop (elementary OS) — Gurnard variant, experimental
* `base`: Plain system image with no desktop environment pre-installed
  (available for most variants)

## Hardware suffixes

Append to any desktop suffix:

* *(none)*: Standard generic kernel build
* `-hwe`: Hardware Enablement (newer kernel stack)
* `-nvidia`: NVIDIA drivers + CUDA pre-configured
* `-nvidia-hwe`: NVIDIA drivers on HWE kernel stack

*Example tags:* `yellowfin:gnome-hwe`, `albacore:kde-nvidia`, `marlin:cosmic`

Some variants also publish stream-suffixed tags on a sibling variant's path:
`ghcr.io/tuna-os/bonito:*-rawhide` (Fedora Rawhide) and
`ghcr.io/tuna-os/flounder:*-sid` (Debian Sid). The full tag scheme and the
rings are in [`VERSIONING.md`](../VERSIONING.md).
