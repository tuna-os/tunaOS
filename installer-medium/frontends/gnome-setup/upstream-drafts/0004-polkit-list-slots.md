# Draft MR: polkit-rules: Allow listing cryptenroll keyslots

Submit `patches/0004-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.

## Title

polkit-rules: Allow listing cryptenroll keyslots

## Description

The recovery key page calls `io.systemd.CryptEnroll.ListSlots` to
find the password slots it must wipe. systemd guards that call with
`io.systemd.cryptenroll.list-slots` (`auth_admin_keep` by default),
so live users hit an auth dialog where the sibling actions
(`sysinstall.Run`, `cryptenroll.enroll`, ...) already pass. This adds
the missing action id to the same live-session rule.

Follows the rule style already in the file.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0001-0003.
- Rule file still parses as JS (`node --check` on the built output).
