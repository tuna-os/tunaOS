# Tuna Desktop on TunaOS

Tuna Desktop was called Roost until tuna-os/tuna-desktop#536 renamed it (naming table in tuna-os/tuna-desktop#505). The supported image reference is `ghcr.io/tuna-os/marlin:tuna`. The owner decided to stop publishing the former `marlin:roost` tags immediately. Existing old tags remain at their last build; installs following them need the explicit switch below to receive updates.

Admission is tracked in tunaOS#2990 and tuna-os/tuna-desktop#69. On 2026-10-04, @hanthor confirmed existing CI capacity for one additional amd64 image and boot gate. The matrix admits one amd64 image. A signed package is available; image/runtime qualification is still in progress. This adds no ISO or LUKS matrix cells.

The key is byte-identical to tuna-os/tunaos-packages `public.gpg` at commit `f560ade103d6369794c177e50cfd0e77863dc0c7`, SHA256 `4de5dfede473d4d56d79719a23e7b0925336719adfc142ea638735118039a82e`, primary fingerprint `4E5CC9F8B3B521793D95266E629BE6EA45188366`. Package signatures are required. Tuna Desktop resolves explicitly from `tunaos/tuna-desktop`; other packages retain Arch repository precedence. The image installs exactly the published v1.0.0-beta.1 release (`tunaos/tuna-desktop=1.0.0beta.1-1` in `manifests/desktops/tuna.yaml`); a later release is an explicit bump of that pin.

The existing gtkgreet/cage launcher supplies a graphical greetd session picker and software rendering fallback. The shipped `tuna.desktop` session launches its supervisor (`tuna-session`), and its `tuna-lock` PAM service handles unlock. `XDG_CURRENT_DESKTOP` is `Tuna:GNOME`, so xdg-desktop-portal reads `tuna-portals.conf`.

gtkgreet has no display-name field: it lists `/etc/greetd/environments` verbatim, and greetd runs the chosen line as `exec <line>`. The picker therefore lists the session by its name, `Tuna Desktop`, and that line runs the `Tuna` launcher in this overlay (`/usr/bin/Tuna`), which accepts only the argument `Desktop`, sets `XDG_SESSION_TYPE=wayland` (greetd, unlike GDM, leaves the tty session type), and starts `tuna-session` (tunaOS#3110).

Upgrades from the `roost` flavor: the `tuna-desktop` package `provides` `roost` and ships, for one release, `roost-*` links to the `tuna-*` binaries, a hidden `roost.desktop` (`NoDisplay=true`, `Exec=tuna-session`) so a display manager that remembers the "roost" session still starts Tuna Desktop, and a `roost-lock` PAM service for a session started before the upgrade. Nothing in the image installs or requires a package named `roost`.

The desktop contract checks six executable versions, their `roost-*` compatibility links, both session entries, both PAM services, the user session target, the greetd session choice, calendar server, IBus, portal backends, keyring, WirePlumber and greeter. Image and runtime contract results are still required before publication; source checks do not establish boot readiness.

## Other variants

tuna-os/tuna-desktop ADR 0008 ships Tuna Desktop on every TunaOS variant, or records it as unsupported with a reason. `tuna_rollout` in `.github/build-config.yml` is that record; `tests/test_tuna_admission.py` keeps it complete and in step with the flavor cells.

- EL10 (`yellowfin:tuna`, `albacore:tuna`, `skipjack:tuna`) installs `tuna-desktop-1.0.0~beta.1-1.el10`, `gtk4-layer-shell`, `libseat` and `greetd` from the factory's el10 index (`repo.tunaos.org/repo/10/x86_64`), `gtkgreet` from its xfce tier and `cage` from EPEL.
- Fedora 44 (`bonito:tuna`) installs `tuna-desktop-1.0.0~beta.1-1.fc44` from the factory's fedora index (`repo.tunaos.org/xfce/44-x86_64`); everything else is Fedora's.

The factory repositories keep `gpgcheck=1` against `https://repo.tunaos.org/public.gpg` and sit at priority 100, behind the distribution repositories, so they only supply what the base lacks. These cells are amd64 only. They use the `tuna` stage of `Containerfile.el10` and the same greetd/gtkgreet launcher, session choice, portal routing and contract as Marlin. The contract reads package ownership from the native pacman or RPM database.

On the RPM bases, gnome-shell requires `gdm-libs`, so gdm is installed; `greetd-system-integration.sh` masks `gdm.service` and points `display-manager.service` at greetd. Power profiles come from `tuned-ppd`, as on the GNOME flavors of those bases. `dbus-tools` supplies `dbus-update-activation-environment`, which beta.1 needs to start `graphical-session.target` and the portals (tuna-os/tuna-desktop#691 removes that need).

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
