---
tags: [flavors, build]
---

# flavor

The tag of a variant image: a desktop (`gnome`, `kde`, `cosmic`, `niri`, `xfce`, `pantheon`) or `base`, optionally suffixed by an overlay (`-hwe`, `-nvidia`, `-nvidia-hwe`, `-cachyos`, `-zfs`, `-t2`, `-asahi`). Routed to a Containerfile by `scripts/resolve-flavor.sh`; listed per variant in `.github/build-config.yml`. All flavors are equal tiers (ADR 0005).
