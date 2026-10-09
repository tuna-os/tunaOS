# Experimental Tuna Desktop on Marlin

Tuna Desktop was called Roost until tuna-os/tuna-desktop#536 renamed it (naming table in tuna-os/tuna-desktop#505). This flavor was `roost` until then; the image keeps publishing the old `ghcr.io/tuna-os/marlin:roost` tag as an alias of `:tuna` (`tag_aliases` in `.github/build-config.yml`), so installs that track it keep updating.

Admission is tracked in tunaOS#2990 and tuna-os/tuna-desktop#69. On 2026-10-04, @hanthor confirmed existing CI capacity for one additional amd64 image and boot gate. The matrix admits one amd64 image. A signed package is available; image/runtime qualification is still in progress. This adds no ISO or LUKS matrix cells.

The key is byte-identical to tuna-os/tunaos-packages `public.gpg` at commit `f560ade103d6369794c177e50cfd0e77863dc0c7`, SHA256 `4de5dfede473d4d56d79719a23e7b0925336719adfc142ea638735118039a82e`, primary fingerprint `4E5CC9F8B3B521793D95266E629BE6EA45188366`. Package signatures are required. Tuna Desktop resolves explicitly from `tunaos/tuna-desktop`; other packages retain Arch repository precedence.

The existing gtkgreet/cage launcher supplies a graphical greetd session picker and software rendering fallback. The shipped `tuna.desktop` session launches its supervisor (`tuna-session`), and its `tuna-lock` PAM service handles unlock. `XDG_CURRENT_DESKTOP` is `Tuna:GNOME`, so xdg-desktop-portal reads `tuna-portals.conf`.

Upgrades from the `roost` flavor: the `tuna-desktop` package `provides` `roost` and ships, for one release, `roost-*` links to the `tuna-*` binaries, a hidden `roost.desktop` (`NoDisplay=true`, `Exec=tuna-session`) so a display manager that remembers the "roost" session still starts Tuna Desktop, and a `roost-lock` PAM service for a session started before the upgrade. Nothing in the image installs or requires a package named `roost`.

The desktop contract checks six executable versions, their `roost-*` compatibility links, both session entries, both PAM services, the user session target, the greetd session choice, calendar server, IBus, portal backends, keyring, WirePlumber and greeter. Image and runtime contract results are still required before publication; source checks do not establish boot readiness.
