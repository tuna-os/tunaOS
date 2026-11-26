# Draft MR: sysinstall: Treat generic error replies of Run as failures

Submit `patches/0008-*.patch` to https://gitlab.gnome.org/Teams/STF/setup.
Do NOT post from an agent account; a human submits this file's content.

## Title

<!-- ste-disable: upstream commit subject, must match the patch -->
sysinstall: Treat generic error replies of Run as failures
<!-- ste-enable -->

## Description

systemd-sysinstall stops a failed installation with a generic error,
for example `io.systemd.System` with an errno. For `Run`, the proxy
reads an error reply only as a `SysInstallError`. That type lists the errors of
the interface itself.

zlink first tries the reply as an error and then as a plain reply. So
`io.systemd.System` becomes a plain reply, its parameters become an
empty `RunOutput`, and the stream ends. Setup then shows the passphrase
and recovery key pages for a disk that holds no system.

The patch adds `RunError`. It takes a `SysInstallError` or any other
error name with its errno. `Run` uses it. A failed installation now
reaches the error state of the install page.

No change for a successful installation.

## Checklist

- Patch applies on the pinned commit in `PIN` after 0007.
- The `systemd_sysinstall.rs` module compiles against zlink 0.5.0. A
  decode test with zlink's reply shape passes (tunaOS issue #5017).
  Before the patch, the `io.systemd.System` frame decodes as a reply.
  After it, the frame decodes as an error shown as
  `io.systemd.System (EIO)`. `DiskTooSmall`, `NoCandidateDevices`,
  progress frames and the empty last frame decode as before.
- Not run against real systemd-sysinstall.
