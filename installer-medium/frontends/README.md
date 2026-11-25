# Live-session frontends

Each desktop cell shows one installer in its live session. This directory
holds the dispatcher and the per-desktop installers. The medium runs them
at build time, inside the payload stage of `Containerfile.live`.

## Dispatcher

```bash
installer-medium/frontends/install-frontend.sh DESKTOP ROOT [--dry-run]
installer-medium/frontends/build-frontend.sh DESKTOP OUTDIR [--dry-run]
```

`DESKTOP` is `gnome`, `kde`, `cosmic`, `niri`, `xfce` or `pantheon`. An
unknown name fails; there is no default. `ROOT` is a staging tree, never `/`.
`Containerfile.live` copies it over the live image. `build-frontend.sh` runs
`DESKTOP/build.sh OUTDIR` when that file exists. `install-frontend.sh` then
installs the shared launcher and runs `DESKTOP/install.sh ROOT`.

## Contract for `DESKTOP/install.sh`

The dispatcher sets `MEDIUM_FRONTENDS` (this directory) and, when `build.sh`
ran, `MEDIUM_PAYLOAD` (its output). The script gets `ROOT` as `$1`. It
sources `lib.sh` and must:

1. Call `fe_init "$1" DESKTOP`.
2. Install the frontend below `ROOT` with `fe_install`, `fe_write` or
   `fe_install_tree`. Each call records its paths for the post-install hook.
3. Write one autostart entry with `fe_autostart`. The entry runs
   `/usr/libexec/medium-live-installer`. The launcher does nothing without
   `tunaos.live` on the kernel command line and sets
   `TUNA_INSTALLER_BACKEND=daemon`. Never write `OnlyShowIn=`.
4. Declare the readiness stamp with `fe_stamp native` or `fe_stamp launcher`.
5. Put anything that only a live boot may change (autologin, for example) in
   a hook with `fe_live_setup_hook`. `medium-live-setup` runs it as root.

The dispatcher checks the autostart entry, the payload list and the stamp
declaration, and fails the build when one is missing. Only coreutils, bash
and `install` are safe to call in `install.sh`; build tools belong in
`build.sh`. Write nothing outside `ROOT`.

### Readiness stamp

The frontend writes `$XDG_RUNTIME_DIR/tuna-installer-ready` itself
(`native`), as `docs/INSTALLER-FRONTENDS.md` section 1 describes. When it
cannot, `fe_stamp launcher` makes the launcher write it once the frontend owns
a session bus name. That proves the process started, not that a frame reached
the screen, so the launcher entries use the signal `bus-name`. The old ISO smoke
test rejects that value; the medium end-to-end harness reads only `app_id`.

## Desktops in this directory

| Desktop | Frontend | Owner |
|---|---|---|
| `gnome` | gnome-setup from `gnome-setup/` (pinned upstream plus patch series) | this directory |
| `pantheon` | the same gnome-setup build, plus LightDM autologin | this directory |
| `kde`, `cosmic`, `niri`, `xfce` | native ports | the native-frontend session |

`gnome/pages.conf` puts the live flow in gnome-setup: language, keyboard,
try or install, installer, disk passphrase, recovery key, done. The finish
step is `medium-install-post@.service`.

## Test without root

```bash
python3 -m pytest tests/test_installer_medium_daemon.py
bats tests/bats/test-installer-medium.bats
```
