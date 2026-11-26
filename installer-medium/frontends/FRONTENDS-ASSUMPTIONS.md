# Frontend install assumptions

Each `installer-medium/frontends/<desktop>/install.sh ROOT [--dry-run]` reads the
contract below this way. Correct any line that is wrong.

- ROOT is the root partition that `mount-medium.sh` mounts. `bootc install
  to-disk` leaves the deployment below it, so the script looks for
  `ostree/deploy/*/deploy/*/etc` and `ostree/deploy/*/var` (ostree), then
  `state/deploy/*/{etc,var}` (composefs). If neither exists it uses `ROOT/etc`
  and `ROOT/var`. Two matches fail. `TUNA_FRONTEND_{VAR,ETC,USR}` override. The
  No test has measured the composefs layout.
- The Flatpak store is `<var>/lib/flatpak`, set through `FLATPAK_SYSTEM_DIR`.
  Run as root, since flatpak needs it for a system installation.
- The artifact is the Flatpak OCI bundle at
  `ghcr.io/tuna-os/bootc-installer`, pinned by manifest digest in `pin.env`. The
  OLD path installed from a `tuna-os` remote that had no pin. The release assets hold
  GNOME only.
- The runtime (`RUNTIME_REF`) comes from Flathub at a pinned ostree commit. The
  GL and Locale extensions are not installed (`--no-related`); the baked set
  may already cover them.
- "Readiness stamp" is read as: the frontend writes
  `$XDG_RUNTIME_DIR/tuna-installer-ready` itself at runtime (docs/INSTALLER-FRONTENDS.md
  section 1). A stamp in the image would make check 2b pass always, so the script
  writes none. It writes `/etc/tuna-installer/frontend-receipt` (app id, digest, source
  commit) instead.
- The autostart entry runs `/usr/libexec/medium-live-installer`. The launcher
  starts nothing unless `tunaos.live` is on the kernel command line. The
  installed copy keeps the Flatpak and override until the post-install hook
  removes them. That hook is not part of these scripts; the payload list
  names what it must remove.
- `install-frontend.sh` gives a plain scratch tree as ROOT. The files of the
  cell (greeter config, niri config) are not in it. The scripts write no such
  file. A boot hook writes them on a `tunaos.live` boot (`README.md`,
  "Greeter autologin").
- The display manager is read from the image at boot. It is never assumed
  from the name of the desktop. `bonito:cosmic` starts `cosmic-greeter.service`,
  which is greetd with its own config file; `bonito:xfce` starts LightDM. The
  adapter of the old ISO (`desktop-xfce.sh`) records greetd for the EL10 XFCE cells. An unknown display manager stops the hook.
- niri: the session can start the installer from the XDG autostart entry and
  from `spawn-at-startup`. No boot has shown which one runs, so both exist.
  With `--once` the launcher starts only one installer.
- KDE: `medium-live-setup` writes SDDM autologin with `Session=plasma`. It has
  no rule for `plasmalogin.service` and none for a session named
  `plasmawayland`. This change measured no KDE image.
- Backend switch: `TUNA_INSTALLER_BACKEND=daemon` for all four, plus the variable
  each frontend reads at bootc-installer 25452dd: `TUNA_USE_FISHERMAND=1`
  (cosmic) and `BOOTC_INSTALLER_BACKEND=daemon` (xfce).
- Each directory has a byte-for-byte copy of `kde/frontend-common.sh`. A bats
  test fails on drift.
