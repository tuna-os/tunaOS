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
| `kde`, `cosmic`, `niri`, `xfce` | native ports | the native-frontend session |

`gnome/pages.conf` puts the live flow in gnome-setup: language, keyboard,
try or install, installer, disk passphrase, recovery key, done. The finish
step is `medium-install-post@.service`.

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
| `cosmic` | `files/bin/tuna-installer-cosmic` | `TUNA_USE_FISHERMAND` |
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
