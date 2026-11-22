# Draft MR: installer: Ask for a disk passphrase when there is no TPM

Submit `patches/0005-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.

## Title

installer: Ask for a disk passphrase when there is no TPM

## Description

Without TPM 2.0 the installed root cannot bind to one, and the
recovery key alone means typing a 64-character key at each boot. This
adds a `disk-passphrase` page between the installer and the recovery
key pages. It builds only when no TPM 2.0 is present. The user picks a
passphrase (entered twice); setup enrolls it through
`io.systemd.CryptEnroll` next to the empty password sysinstall
enrolled. The recovery key page then keeps that slot when it wipes the
others, so the recovery key is a second key, not the only one.

Note for distributions: repart definitions must not ask for `tpm2` on
such machines; write `Encrypt=` per boot (for example `key-file`
there).

Expect review on the page flow and on TPM detection.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0001-0004.
- TPM-less path shows the extra page; TPM path skips it (code read).
