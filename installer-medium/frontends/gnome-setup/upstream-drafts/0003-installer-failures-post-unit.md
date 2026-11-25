# Draft MR: installer: Report failures, support a distro post-install unit, enroll the installed disk

Submit `patches/0003-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.

## Title

installer: Report failures, support a distro post-install unit, enroll the installed disk

## Description

Three linked fixes for real installs:

1. A failed `systemd-sysinstall` run now stops on the install page.
   The page shows "Installation Failed" and the error. Before, setup went
   on to the recovery key and done pages as if the run had worked.
2. `[page:installer] post-install-unit=` names a template unit.
   After sysinstall succeeds, setup starts it with the target disk as
   the instance (via `systemd-escape --path`) and waits for its job.
   A block copy cannot set new filesystem UUIDs, boot entries, or
   crypttab. The distro unit does that before the key page wipes the
   empty password.
3. Setup enrolls the recovery key on the LUKS2 partition of the disk
   that it installed to. It finds that partition in the udev database.
   It does not use a label, because a label can also name the root of
   the live medium.

Expect review to split this: (1) and (3) look safe alone, while (2)
adds a new `pages.conf` key that needs design sign-off.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0001-0002.
- Failure path shows the error page (code read; live test not yet done).
