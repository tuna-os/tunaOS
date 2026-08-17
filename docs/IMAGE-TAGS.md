# Image tag reference

Image tags are constructed as `<desktop>[-hardware]`, against the variant's
registry path (see the variant table in the [README](../README.md)).

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
`ghcr.io/tuna-os/flounder:*-sid` (Debian Sid). The full tag scheme and
stability tiers are in [VERSIONING.md](../VERSIONING.md).
