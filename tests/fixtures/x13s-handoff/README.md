# X13s loader handoff fixture

This emulator-only fixture must boot the selected Fedora shim, GRUB and DTB-loader
bytes with an external sentinel initrd. It does not test X13s hardware, CHID
selection, USB-C safety, Secure Boot or the final TunaOS image.

The runner must be ARM64. Only official runner packages are installed; RPM payloads
are read without executing scriptlets. No image/kernel package transaction occurs.
The guest sees only its temporary fixture ESP and has no network or host disks.
