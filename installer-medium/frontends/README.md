# Live-session frontends

Each desktop cell shows one installer in its live session. This directory
holds the dispatcher and the per-desktop installers. The medium runs them
at build time, inside the payload stage of `Containerfile.live`.

## Dispatcher

```bash
installer-medium/frontends/install-frontend.sh DESKTOP ROOT [--dry-run]
installer-medium/frontends/build-frontend.sh DESKTOP OUTDIR [--dry-run]
```

`DESKTOP` is `gnome`, `tuna`, `kde`, `cosmic`, `niri`, `xfce` or `pantheon`.
An unknown name fails; there is no default. `build-live-image.sh` takes the
name from `[installer_medium.frontends]` in `tunaos.toml`, which maps the
desktop of a flavor to one of these directories. A hardware flavor such as
`kde-nvidia` uses the directory of its desktop. A `base` flavor has no
graphical session and gets no medium.

`ROOT` is a scratch tree, never `/`.
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
the screen, so the launcher entries use the signal `bus-name`. The smoke test
of the old ISO rejects that value; the medium end-to-end harness reads only `app_id`.

## Desktops in this directory

| Desktop | Frontend | Owner |
|---|---|---|
| `gnome` | gnome-setup from `gnome-setup/` (pinned upstream plus patch series) | this directory |
| `pantheon` | the same gnome-setup build, plus LightDM autologin | this directory |
| `tuna` | the GNOME frontend under its own name: Tuna Desktop runs gnome-shell behind GDM | this directory |
| `kde`, `cosmic`, `niri`, `xfce` | native ports (Flatpak, pinned in `pin.env`) | `frontend-common.sh` and `live-session.sh` |

`gnome/pages.conf` puts the live flow in gnome-setup: language, keyboard,
try or install, installer, disk passphrase, recovery key, done. The finish
step is `medium-install-post@.service`.

## Native frontends: `kde`, `cosmic`, `niri`, `xfce`

These four do not source `lib.sh`. Each `install.sh` sources its own copy of
`frontend-common.sh`, which fetches and installs the pinned Flatpak. For the
live session it then calls `ls_autostart` from `live-session.sh`. That
function meets the same contract:

- It writes the autostart entry. The entry runs
  `/usr/libexec/medium-live-installer -- flatpak run APP_ID`.
- It declares the stamp as `native`.
- It writes the payload list. A directory line (`/var/lib/flatpak/app/APP_ID`)
  stands for the whole tree below it.
- When `DESKTOP/live-setup` exists, it installs that file as the boot hook
  `/usr/lib/medium-live/live-setup.d/50-DESKTOP-session`, and `live-greeter.sh`
  as `/usr/lib/medium-live/greeter.sh`.

The build writes no greeter config and no compositor config. The payload
stage is a scratch tree on a Fedora builder; the files of the cell are not
there. The boot hook writes them on a `tunaos.live` boot, when the root is a
RAM overlay. An installed system never runs the hook.

### Greeter autologin

The hook does not assume a display manager. It reads the unit that
`display-manager.service` points to. Without that alias it looks in `graphical.target.wants`. It continues
only when it finds one display manager there. Any other case stops
`medium-live-setup` with an error: there is no default.

| Desktop | Display manager the hook accepts | What the hook writes |
|---|---|---|
| `cosmic` | `greetd.service` or `cosmic-greeter.service` | the greetd config that the unit names in `ExecStart` (`--config`), else `/etc/greetd/config.toml`; the session command is `cosmic-session` |
| `niri` | `greetd.service` or `cosmic-greeter.service` | the same file; the session command is `niri-session`. It also adds the installer line to the niri config |
| `xfce` | `lightdm.service` | `/etc/lightdm/lightdm.conf.d/90-medium-live-autologin.conf` with the X11 session `xfce` or `xfce4` |
| `xfce` | `greetd.service` | the greetd config; the command is `dbus-run-session startxfce4 --wayland COMPOSITOR` for the first of `xfwl4`, `labwc`, `wayfire` |
| `kde` | no hook | `medium-live-setup` writes `/etc/sddm.conf.d/medium-live.conf` |

The hook replaces the whole greetd file. The image's file can already hold a
`[general]` table. A second table of that name is not valid TOML. The new file sets
`source_profile = false`, an `initial_session` and a `default_session` for
the live user. The session command runs through `systemd-cat -t
medium-live-session`, so `journalctl -t medium-live-session` shows why a
session stopped.

### Autostart in the session

COSMIC and XFCE run `/etc/xdg/autostart`. niri has two start paths:
`niri.service` wants `xdg-desktop-autostart.target`, and the hook adds a
`spawn-at-startup` line to the live user's `~/.config/niri/config.kdl`. When
that file is absent, the hook first copies the image default there, because
niri reads only one file. The hook does not write below `/usr`. Both paths run the
launcher with `--once`. The second launcher finds the lock in
`$XDG_RUNTIME_DIR` and starts nothing.

### Evidence of 2026-11-25

`podman run` on the published images of that date gave:

| Image | Display manager | Config | Sessions |
|---|---|---|---|
| `bonito:cosmic` `6793503c795a` | `cosmic-greeter.service` (`greetd.service` is disabled) | `/etc/greetd/cosmic-greeter.toml` | `wayland-sessions/cosmic.desktop` |
| `bonito:niri` `a2dcc3b1d7e3` | `greetd.service`, greeter `dms-greeter` | `/etc/greetd/config.toml` | `wayland-sessions/niri.desktop`; `/usr/share/niri/config.kdl` only |
| `bonito:xfce` `c94c945d8b4c` | `lightdm.service`; `gdm.service` is also in `graphical.target.wants` | `/etc/lightdm` | `xsessions/xfce.desktop`; no Wayland compositor |

Each hook ran inside its image (`podman run`, after `useradd liveuser`) and
wrote the file above. No medium has booted with these hooks. No person measured the other bases
(EL10, Arch, Debian, Ubuntu, openSUSE, Gentoo). There the hook fails when it
does not know the display manager. On `bonito:xfce` two display managers start.
The hook configures LightDM and prints a warning; `medium-live-setup` also
writes the GDM autologin because `/etc/gdm` exists.

## Bump the pin of a native frontend

`kde`, `cosmic`, `niri` and `xfce` each have a `pin.env`. The digests come from
`publish-flatpak.yml` in tuna-os/bootc-installer. Change the whole set together:

1. Take both manifest digests from one publish run. Check that the `index.json`
   of each run artifact (`oci-<frontend>-<arch>`) has the digest of the tag.
2. Set `SOURCE_COMMIT` to the commit of that run.
3. Unpack the layers of both architectures and search all files for the daemon
   client. Set `DAEMON_CLIENT_IN_DIGEST=yes` only when both hold it.
4. Read `runtime=` in the `metadata` file of the bundle. When it changed, update
   `RUNTIME_REF` and both `RUNTIME_COMMIT_*` values.

The client shows as the socket path `/run/fisherman/io.tunaos.Fisherman` and the
backend variable of the frontend:

| Frontend | File in the bundle | Backend variable |
|---|---|---|
| `kde` | `files/bin/tuna-installer-kde` | `TUNA_INSTALLER_BACKEND` |
| `cosmic` | `files/bin/tuna-installer-cosmic` | `TUNA_USE_FISHERMAND`, `TUNA_INSTALLER_BACKEND` |
| `niri` | `files/bin/tuna-installer-backend` | `TUNA_INSTALLER_BACKEND` |
| `xfce` | `files/lib/tuna-installer-xfce/tuna_installer_xfce/daemon.py` | `BOOTC_INSTALLER_BACKEND` |

The KDE binary stores the socket path as UTF-16 (`QStringLiteral`), so a plain
`grep` does not find it. Use `strings -e l`:

```bash
grep -rlaF /run/fisherman/io.tunaos.Fisherman TREE
strings -a -e l TREE/files/bin/tuna-installer-kde | grep -F /run/fisherman/io.tunaos.Fisherman
```

Run the same search on the old digest. It must find nothing there.

## Test without root

```bash
python3 -m pytest tests/test_installer_medium_daemon.py
bats tests/bats/test-installer-medium.bats
bats tests/bats/test-installer-medium-frontends.bats
```
