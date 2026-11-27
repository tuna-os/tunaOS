# gnome-setup as an upstream patch series

tunaOS ships GNOME Setup from upstream, not from a fork. This directory
pins a single upstream commit (`PIN`) and carries every tunaOS change as a
patch with an upstream-ready message (`patches/`). `apply-and-build`
clones the pin, applies the series, and builds. The `Containerfile`
runs the same script for the medium.

## Patch list

| # | Change | tunaOS needs it | Upstream wants it |
|---|---|---|---|
| 0001 | Never force demo mode and debug overrides | Yes: without it the build never talks to sysinstall | Yes: upstream main must run on real hardware |
| 0002 | Return cryptenroll errors instead of panic | Yes: wrong password must not crash setup | Yes: strict bug fix |
| 0003 | Report install failure, support post-install unit, enroll key on installed disk | Yes: block copy needs fixups (UUIDs, boot entries, crypttab) before the key page wipes the empty password | Yes, split in review: failure report and installed-disk enroll look safe; the new `post-install-unit=` key needs upstream design sign-off |
| 0004 | polkit rule allows `ListSlots` on live media | Yes: the key page lists slots with no auth dialog | Yes: matches the rule style for the other actions |
| 0005 | Disk passphrase page when no TPM exists | Yes: without TPM the recovery key alone means typing 64 chars at each boot | Yes, needs review: page flow and the `Encrypt=` repart note |
| 0006 | `live-marker-path` meson option | Yes: tunaOS marks live media at its own path | Yes: one option, default keeps current path |
| 0007 | `post-wizard-command` meson option | Yes: tunaOS starts its own step after the wizard | Yes: one option, default keeps `gnome-initial-setup` |
| 0008 | `Run` treats `io.systemd.System` and other generic errors as failures | Yes: a failed install went on to the key page (tunaOS#5017) | Yes: strict bug fix |
| 0009 | Recovery key page stays and says so when the enroll fails | Yes: a failed enroll led to Done with a key that unlocks nothing | Yes: strict bug fix |

Patches 0001-0005 match the commits on the `utah` branch of the
hanthor/gnome-setup mirror, rebased onto the pin with README-only
commits dropped. Patch 0003 bundles three behaviors; upstream may ask
to split it. The series applies in order; later patches depend on
earlier ones, so check single patches only after the predecessors.

Patches 0006 and 0007 carry the placeholder author
`installer@tunaos.invalid`. Replace it with your own identity before
you submit (`git commit --amend --author` after `git am`).

## Compat exceptions

The rule for this directory is: only upstream-ready patches. `compat/`
holds the one exception that the owner approved on 2026-11-27. Each set
applies to the cells in its `cells` file only, after the whole series.

| Set | Cells | Why | Retire when |
|---|---|---|---|
| `gtk-4.14` | `gurnard:pantheon` | Ubuntu 24.04 has GTK 4.14. Upstream templates pass `_()` strings into closures, and GtkBuilder accepts a translatable `<constant>` only from GTK 4.16. gnome-setup aborted on its welcome page (run 45931354235). The patch passes plain strings and translates them in `apply_osinfo`. | Pantheon runs on GTK 4.16 or newer |

The gate is the cell, never the desktop name: `compat/for-cell` reads the
`cells` files, and `build-live-image.sh` passes the set to the medium build.
Two checks stop the build:

- `compat/check-ui`: a template of the build still holds a translatable
  `<constant>`.
- `compat/check-target-gtk` (Containerfile.live, on the cell image): a
  compat set on GTK 4.16 or newer. Also gnome-setup with no set on an
  older GTK.

The msgids stay as they are, so the translations still apply. The upstream
offer is in `wt-installer/upstream-drafts/` (not sent).

## Backend: no sysinstall patch needed

gnome-setup calls only `Run` and `ListCandidateDevices` on
`io.systemd.SysInstall`, and `Enroll`, `ListSlots`, `MakeRecoveryKey`
on `io.systemd.CryptEnroll`. The `fishermand` mock
(tuna-os/fisherman#513) covers all five calls. We wrote the IDL files there
from this client. No Utah patch exists only because
sysinstall lacks something, so no patch drops in favor of fishermand.

One exception stays: `src/interfaces/systemd_manager.rs` (new in
0003) drives the real systemd manager over D-Bus to start the
post-install unit. fishermand never proxies that; the medium provides
real systemd, and the unit runs there.

## Re-pin

Upstream moves. To move the pin: read the new upstream HEAD, check the
`utah` branch for new commits, rebase the series, run
`./apply-and-build --check-only`, and update `PIN`.

## Coordination

The medium build is `../gnome/build.sh`, which runs `apply-and-build`
with `-Dlive-marker-path=/run/tunaos/live -Dpost-wizard-command=`. The
`medium-live-setup` service creates that marker on each live boot. The
post-wizard step stays empty; `pages.conf` in `../gnome` names the
`medium-install-post@.service` unit instead. The `Containerfile` here
builds the same series for a quick check, without the pinned
blueprint-compiler that the medium build needs.
