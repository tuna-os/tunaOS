# Tuna Desktop on TunaOS

Tuna Desktop was called Roost until tuna-os/tuna-desktop#536 renamed it (naming table in tuna-os/tuna-desktop#505). The supported image reference is `ghcr.io/tuna-os/marlin:tuna`. The owner decided to stop publishing the former `marlin:roost` tags immediately. Existing old tags remain at their last build; installs following them need the explicit switch below to receive updates.

Admission is tracked in tunaOS#2990 and tuna-os/tuna-desktop#69. On 2026-10-04, @hanthor confirmed existing CI capacity for one additional amd64 image and boot gate. The matrix admits one amd64 image. A signed package is available; image/runtime qualification is still in progress. This adds no ISO or LUKS matrix cells.

The key is byte-identical to tuna-os/tunaos-packages `public.gpg` at commit `f560ade103d6369794c177e50cfd0e77863dc0c7`, SHA256 `4de5dfede473d4d56d79719a23e7b0925336719adfc142ea638735118039a82e`, primary fingerprint `4E5CC9F8B3B521793D95266E629BE6EA45188366`. Package signatures are required. Tuna Desktop resolves explicitly from `tunaos/tuna-desktop`; other packages retain Arch repository precedence. The image installs exactly the published v1.0.0-beta.1 release (`tunaos/tuna-desktop=1.0.0beta.1-1` in `manifests/desktops/tuna.yaml`); a later release is an explicit bump of that pin.

GDM supplies the login experience and session picker. The shipped `tuna.desktop` session launches its supervisor (`tuna-session`), and its `tuna-lock` PAM service handles unlock. GDM starts the session directly as a regular user and sets the Wayland session type; `XDG_CURRENT_DESKTOP` is `Tuna:GNOME`, so xdg-desktop-portal reads `tuna-portals.conf`.

The Tuna overlay supplies GDM configuration in the native path for each base (`/etc/gdm/custom.conf` or `/etc/gdm3/daemon.conf`): Wayland is enabled, `tuna.desktop` is the default session, and automatic login is disabled. `tuna-gdm.sh` masks stale greetd state, points `display-manager.service` at GDM, and appends the Tuna theme overrides to GNOME Shell's theme resource.

Upgrades from the `roost` flavor: the `tuna-desktop` package `provides` `roost` and ships, for one release, `roost-*` links to the `tuna-*` binaries, a hidden `roost.desktop` (`NoDisplay=true`, `Exec=tuna-session`) so a display manager that remembers the "roost" session still starts Tuna Desktop, and a `roost-lock` PAM service for a session started before the upgrade. Nothing in the image installs or requires a package named `roost`.

The desktop contract checks six executable versions, their `roost-*` compatibility links, both session entries, both PAM services, the user session target, GDM's session/default/no-autologin configuration and compiled theme, calendar server, IBus, portal backends, keyring and WirePlumber. Image and runtime contract results are still required before publication; source checks do not establish boot readiness.

## Other variants

tuna-os/tuna-desktop ADR 0008 ships Tuna Desktop on every TunaOS variant, or records it as unsupported with a reason. `tuna_rollout` in `.github/build-config.yml` is that record; `tests/test_tuna_admission.py` keeps it complete and in step with the flavor cells.

- EL10 (`yellowfin:tuna`, `albacore:tuna`, `skipjack:tuna`) installs `tuna-desktop-1.0.0~beta.1-1.el10`, `gdm`, `gtk4-layer-shell` and `libseat` from the configured repositories.
- Fedora 44 (`bonito:tuna`) installs `tuna-desktop-1.0.0~beta.1-1.fc44` and `gdm`; the rest is Fedora's.
- Fedora ELN (`wahoo:tuna`) installs `tuna-desktop-1.0.0~beta.1-1.eln159` and `gdm`; the rest resolves from ELN.
- Fedora Rawhide (`bonito:tuna-rawhide`) installs `tuna-desktop-1.0.0~beta.1-1.fc46` and `gdm` through the manifest's `rawhide` section; the rest is as on Fedora 44.
- Ubuntu 26.04 (`grouper:tuna`), Debian 13 trixie (`flounder:tuna`) and Debian sid (`flounder:tuna-sid`) install `tuna-desktop=1.0.0~beta.1-1` and `gdm3` from the signed Tideforge apt index for their base (`repo.tunaos.org/tideforge/ubuntu/`, `repo.tunaos.org/tideforge/debian-trixie/` or `repo.tunaos.org/tideforge/debian-sid/`, `signed-by` its `tideforge.gpg`); the rest is the distribution's own. trixie's gtk4-layer-shell is 1.0, older than tuna-desktop needs, so the trixie build carries a private copy and Debian's `libgtk4-layer-shell0` is not installed.
- openSUSE Tumbleweed (`sailfin:tuna`) installs `tuna-desktop-1.0.0~beta.1-1` and `gdm` from the configured repositories (`repo.tunaos.org/rpm/opensuse-tumbleweed/x86_64`, `pkg_gpgcheck` against `https://repo.tunaos.org/public.gpg`); everything else is Tumbleweed's. `dbus-1-tools` supplies `dbus-update-activation-environment` and power profiles come from `power-profiles-daemon`, as on sailfin's GNOME flavor.

The dnf factory repositories keep `gpgcheck=1` against `https://repo.tunaos.org/public.gpg` and sit at priority 100, behind the distribution repositories, so they only supply what the base lacks. The openSUSE one has no priority, so where Tumbleweed ships the same package the newer build wins. These cells are amd64 only. They use the `tuna` stage of `Containerfile.el10`, `Containerfile.opensuse`, `Containerfile.ubuntu` or `Containerfile.debian` and the same GDM configuration, session choice, portal routing and contract as Marlin. The contract reads package ownership from the native pacman, RPM or dpkg database.

On the Fedora and EL bases, gdm is installed explicitly and `tuna-gdm.sh` unifies the service alias with GDM instead of masking it. Power profiles come from `tuned-ppd`, as on the GNOME flavors of those bases. `dbus-tools` supplies `dbus-update-activation-environment`, which beta.1 needs to start `graphical-session.target` and the portals (tuna-os/tuna-desktop#691 removes that need).

On the apt bases, the overlay supplies `/etc/gdm3/daemon.conf`; on Arch, Fedora, ELN, Rawhide and openSUSE it supplies `/etc/gdm/custom.conf`. In every case the hook masks greetd, selects the Tuna Wayland session and leaves keyring, IBus, calendar and portal routing on their existing packages.

## Switch an existing Roost install

After the Tuna image passes its published image qualification, save your work,
back up important data, and record the current deployment with `sudo bootc status`.
Then stage the new deployment and reboot:

```sh
sudo bootc switch --enforce-container-sigpolicy ghcr.io/tuna-os/marlin:tuna
sudo systemctl reboot
```

After reboot, `sudo bootc status` must show the Tuna image as booted. Select
`Tuna Desktop` at the greeter, verify login and lock/unlock, and check your home
files against the backup. A bootc switch replaces the image deployment; home
data remains in `/var/home`. Keep the previous deployment until these checks
pass. If the new deployment fails, select the previous deployment from the boot
menu or stage it with `sudo bootc rollback` and reboot.

This is the migration procedure to qualify; the source tests check its routing
and compatibility contracts. A published-image migration run must still prove
login and data preservation before v1 is declared.
