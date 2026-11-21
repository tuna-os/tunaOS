# X13s loader handoff fixture

This emulator-only fixture must boot the selected Fedora shim, GRUB and DTB-loader
bytes with an external sentinel initrd. It does not test X13s hardware, CHID
selection, USB-C safety, Secure Boot or the final TunaOS image.

The runner must be ARM64. Only official runner packages are installed; RPM payloads
are read without executing scriptlets. No image/kernel package transaction occurs.
The guest sees only its temporary fixture ESP and has no network or host disks.

## RPM key import failure

Symptom: the Ubuntu runner reports `key 1 not an armored public key` before
signature verification. Cause: GnuPG exports binary OpenPGP packets by default,
while the selected RPM 4.x importer expects ASCII armor. Fix: export only the
approved full-fingerprint key with `--armor`, reject an unarmored export, and keep
the explicit signature receipt and unsigned-RPM negative control unchanged.
