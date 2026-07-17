# build_scripts/ layout

The naming scheme is self-documenting along two axes:

- **Directories = code path.** Which Containerfile/stage runs a script is
  visible from its location.
- **Numeric prefixes = execution order.** Numbered scripts are the common
  base-image phases, run in ascending order by the base Containerfiles
  (`Containerfile.el10`, `Containerfile.ubuntu`, `Containerfile.debian`).

```
build_scripts/
├── lib.sh                     # shared library — sourced by everything as
│                              #   /run/context/build_scripts/lib.sh
│
│   # ── base-image phases (run in numeric order) ─────────────────────
├── 00-copy-files.sh           # overlay system_files into the image
├── 01-workarounds.sh          # temporary hacks (goal: empty)
├── 10-base-packages.sh        # core package set
├── 20-packages.sh             # main package set
├── 26-packages-post.sh        # post-package config (branding, plymouth…)
├── 40-services.sh             # systemd service enablement
├── 90-image-info.sh           # os-release / image metadata
├── 91-arch-customizations.sh  # arch-specific tweaks (after image-info)
├── 99-cleanup.sh              # final cleanup (always last)
│
├── desktop/                   # desktop stage (per-DE Containerfile targets)
│   ├── install-desktop.sh     #   manifest-driven installer (dnf/pacman/…)
│   │                          #   reads manifests/desktops/<de>.yaml
│   ├── configure-desktop-runtime.sh  # Ubuntu path: DM + contract wiring
│   ├── gnome.sh kde.sh cosmic.sh niri.sh xfce.sh  # Ubuntu per-DE installers
│   ├── zfs.sh                 #   grouper gnome-zfs flavor add-on
│   └── gnome-extensions.sh kcm-ublue.sh tuna-flatpak-remote.sh
│                              #   post-install helpers; manifests reference
│                              #   them by bare name (resolved to this dir)
│
├── overlay/                   # Containerfile.overlay, keyed by OVERLAY_TYPE
│   ├── hwe.sh                 #   OVERLAY_TYPE=hwe
│   ├── nvidia.sh              #   OVERLAY_TYPE=nvidia
│   └── cachyos.sh             #   OVERLAY_TYPE=cachyos (marlin)
│
├── checks/                    # build/runtime contracts (fail loudly)
│   ├── verify-desktop-experience.sh  # build: session/DM/launcher/unit
│   │                          #   validation; --runtime: serial markers
│   └── e2e-runtime-checks.sh  # snosi-derived installed-system TAP checks,
│                              #   baked to /usr/libexec/tunaos/ and
│                              #   harvested by scripts/iso-e2e.sh
│
├── bootc/                     # Ubuntu/Debian bootcification (finalize, …)
├── scripts/                   # in-image utilities (image-info-set)
└── apply-custom.sh            # Containerfile.custom entry point
```

Conventions:

- New base phase? Pick a free number that reflects its position; keep gaps
  so later insertions don't force renumbering.
- New desktop? Write `manifests/desktops/<name>.yaml` — no script needed
  (see `desktop/install-desktop.sh`). Ubuntu still needs a `desktop/<name>.sh`
  until it migrates to the manifest path.
- Scripts source the shared library via the absolute build-context path
  (`/run/context/build_scripts/lib.sh`), so scripts can move between
  subdirectories without breaking.
- Manifest `post_install` entries are bare filenames resolved against
  `build_scripts/desktop/`.
