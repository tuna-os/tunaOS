# Draft MR: crypt-enroll: Return errors instead of panicking

Submit `patches/0002-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.

## Title

crypt-enroll: Return errors instead of panicking

## Description

`MakeRecoveryKey` and `Enroll` unwrap the reply from
systemd-cryptenroll. A wrong unlock password or an unsupported volume
then crashes gnome-setup on the recovery key page. This returns the
error to the caller so the page can report it.

No behavior change on success.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0001.
- Wrong-password path returns `Err` instead of panic (code read).
