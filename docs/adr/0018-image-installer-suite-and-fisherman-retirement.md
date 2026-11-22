# ADR 0018: Image-based installer suite, and conditional retirement of fisherman and bootc-installer

- Status: accepted (conditional). The retirement takes effect only after the
  suite meets every exit criterion below.
- Date: 2026-11-22
- Approval: the maintainer made the decisions in this ADR on 2026-11-22 and
  asked for this record. The epic records the decisions:
  [#4905](https://github.com/tuna-os/tunaOS/issues/4905).
- Issue: [#4905](https://github.com/tuna-os/tunaOS/issues/4905)
- Related: Utah ADR-0001 (image-based installer,
  [projectbluefin/utah#1403](https://github.com/projectbluefin/utah/issues/1403)),
  [projectbluefin/utah#1437](https://github.com/projectbluefin/utah/pull/1437),
  [projectbluefin/dakota#1920](https://github.com/projectbluefin/dakota/pull/1920)

## Context

Today a tunaOS install boots a live ISO and runs a frontend that writes a
`recipe.json`. Then fisherman runs `bootc install` from an OCI image that the
ISO carries. After the install, the machine must reboot.

- There are five frontends.
  - GNOME uses upstream bootc-installer.
  - KDE, COSMIC, Niri and XFCE use separate forks in
    [tuna-os/bootc-installer](https://github.com/tuna-os/bootc-installer),
    written in four languages.
  - [INSTALLER-FRONTENDS.md](../INSTALLER-FRONTENDS.md) calls feature drift
    "the default failure mode".
- fisherman is a backend that only tunaOS maintains. No upstream project
  shares it.
- Project Bluefin's Utah and Dakota now test a different design:
  - The medium is a raw disk image. The user writes it to a USB stick with
    `dd`.
  - [systemd-sysinstall](https://github.com/systemd/systemd) installs it over
    Varlink (`io.systemd.SysInstall`). systemd-repart and systemd-cryptenroll
    do the disk work.
  - GNOME's STF-funded [gnome-setup](https://gitlab.gnome.org/Teams/STF/setup)
    is the GNOME frontend.
  - On btrfs, a seed/migrate step moves the live root onto the target disk,
    and the live session becomes the installed system without a reboot.

## Decision

1. **Adopt the image-based installer suite** for every tunaOS desktop:
   - a hybrid ISO medium. The same file boots as a CD or ISO, and from a USB
     stick that the user writes with `dd`
     ([#4913](https://github.com/tuna-os/tunaOS/issues/4913));
   - a medium-only systemd-sysinstall backend;
   - a native frontend for each desktop;
   - an install that needs no reboot.

   Sub-issues of [#4905](https://github.com/tuna-os/tunaOS/issues/4905) track
   the work.
2. **Native frontend per desktop.**
   - GNOME and Pantheon use gnome-setup. We share the branch with Utah and
     send patches upstream.
   - KDE, COSMIC, Niri and XFCE keep their native frontends. We port them from
     `recipe.json` to the Varlink backend.
   - All frontends use one backend contract, one mock server and one screen
     contract.
3. **btrfs root on every non-EL base.** EL10 has no btrfs, so it stays on xfs.
   - btrfs bases: the seed/migrate install. The session survives the install.
   - EL10: a block copy, then `systemctl soft-reboot` into the copy. A spike
     must prove this path
     ([#4909](https://github.com/tuna-os/tunaOS/issues/4909)).
4. **Retire fisherman and bootc-installer when the suite succeeds.** Until
   then, the ISO, fisherman and bootc-installer path stays the default. It
   also stays the only path that a required check gates.

## Exit criteria

The suite succeeds when all of these are true at the same time:

- **CI.** The parallel image-installer track
  ([#4910](https://github.com/tuna-os/tunaOS/issues/4910)) passes all seven
  stages for every promoted cell, on 14 consecutive nightly runs:
  1. live boot;
  2. installer pages;
  3. install;
  4. TPM unlock or recovery key;
  5. first-boot setup;
  6. desktop and `bootc status`;
  7. `bootc switch` and rollback.
- **ISO.** Each promoted cell's medium boots as a CD-ROM and as a USB disk.
  All seven stages pass from both.
- **Frontends.** gnome-setup and each native frontend pass the shared screen
  contract. The contract includes the recovery-key and no-reboot screens.
- **No reboot.**
  - btrfs cells: a file that the user writes in the live session is still
    there after the install.
  - EL10 cells: the soft reboot reaches the installed login screen, SELinux
    is Enforcing, and no units fail.

  If the soft-reboot spike fails, EL10 keeps a normal reboot. That result
  does not block retirement.
- **Security.**
  - Secure Boot works.
  - The TPM2 PCR 7 unlock needs no prompt.
  - The recovery key unlocks the disk without the TPM.
  - After the install, fs-verity is on for the objects of each composefs cell.
- **No regression against the ISO path** for the same digest:
  - the medium download is not larger;
  - the install is not slower;
  - each stage that passes on the ISO path also passes on the new path.
- **Hardware.** One EL10 cell and one btrfs cell install on real machines.
  The evidence goes on #4905.
- **Upstream.** systemd merges the sysinstall toggles
  ([systemd/systemd#44968](https://github.com/systemd/systemd/pull/44968)),
  or we record that we carry the patch.

## Retirement sequence

1. The new suite becomes the default medium. The ISO and fisherman path stays
   available as a fallback for two `:stable` promotions
   ([ADR 0016](0016-testing-and-stable-image-rings.md)).
2. We remove the fisherman path from CI, the release workflows, the docs and
   the image pins. That includes `live-iso/`, the fisherman bats and
   regression tests, `scripts/iso-e2e.sh`, `scripts/check-installer-fisherman-pins.py`,
   and the `image-versions.yaml` and Renovate entries.
3. We move the four native frontends out of tuna-os/bootc-installer into an
   installer repository that we name at that time. Then we archive
   tuna-os/bootc-installer and tuna-os/fisherman.

## If the suite does not succeed

The suite stays an experimental track. fisherman and bootc-installer stay the
default. We do not retire anything. We record the failed criteria on #4905 and
update this ADR.

## Alternatives considered

- **gnome-setup on every desktop.** One codebase and no drift. The
  maintainer rejected it, because each desktop must keep its native look.
- **xfs or ext4 on non-EL bases.** This keeps one filesystem everywhere, but
  it removes the seed/migrate install. The maintainer rejected it.
- **Keep fisherman as the backend for the new frontends.** fisherman would
  duplicate systemd-sysinstall, and only tunaOS would maintain it.

## Consequences

- Three ISO parts keep an `.iso` file:
  - the live ISO pipeline;
  - the browser ISO builder ([ADR 0002](0002-browser-iso-builder.md));
  - the provenance contract for ISO media
    ([ADR 0014](0014-iso-media-provenance-contract.md)).

  Their input changes from the fisherman ISO to the hybrid medium.
- The medium needs systemd v262 or later for the Varlink sysinstall. The
  medium ships its own build, because the bases ship systemd 257 and later.
- The medium's ESP must hold the live kernel, because a CD boot cannot read
  a separate `/boot`.
