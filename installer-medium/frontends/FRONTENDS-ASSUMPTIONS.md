# Frontend install assumptions

Each `installer-medium/frontends/<desktop>/install.sh ROOT [--dry-run]` reads the
contract below this way. Correct any line that is wrong.

- ROOT is the root partition that `mount-medium.sh` mounts. `bootc install
  to-disk` leaves the deployment below it, so the script looks for
  `ostree/deploy/*/deploy/*/etc` and `ostree/deploy/*/var` (ostree), then
  `state/deploy/*/{etc,var}` (composefs). If neither exists it uses `ROOT/etc`
  and `ROOT/var`. Two matches fail. `TUNA_FRONTEND_{VAR,ETC,USR}` override. The
  composefs layout is unverified.
- The Flatpak store is `<var>/lib/flatpak`, set through `FLATPAK_SYSTEM_DIR`.
  Run as root, since flatpak needs it for a system installation.
- The artifact is the Flatpak OCI bundle at
  `ghcr.io/tuna-os/bootc-installer`, pinned by manifest digest in `pin.env`. The
  OLD path installed from a floating `tuna-os` remote. The release assets hold
  GNOME only.
- The runtime (`RUNTIME_REF`) comes from Flathub at a pinned ostree commit. The
  GL and Locale extensions are not installed (`--no-related`); the baked set
  may already cover them.
- "Readiness stamp" is read as: the frontend writes
  `$XDG_RUNTIME_DIR/tuna-installer-ready` itself at runtime (docs/INSTALLER-FRONTENDS.md
  section 1). Baking one would turn check 2b green forever, so the script writes
  none. It writes `/etc/tuna-installer/frontend-receipt` (app id, digest, source
  commit) instead.
- The autostart runs only when `tunaos.live` is on the kernel command line. The
  installed copy keeps the Flatpak and override until the post-install hook
  removes them; that hook is not part of these scripts.
- Backend switch: `TUNA_INSTALLER_BACKEND=daemon` for all four, plus the variable
  each frontend reads at bootc-installer f9d3b25: `TUNA_USE_FISHERMAND=1`
  (cosmic) and `BOOTC_INSTALLER_BACKEND=daemon` (xfce).
- `kde/frontend-common.sh` is copied byte for byte into each directory. A bats
  test fails on drift.
