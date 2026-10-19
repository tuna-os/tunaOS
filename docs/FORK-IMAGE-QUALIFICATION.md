# Local fork image qualification

This harness builds and tests real images. It does not publish them. Ordinary
`--identity-staging --build` remains blocked. It does not change production workflows or the platform catalog.

`Fork Image Qualification` runs on the `feat/fork-image-qualification` pull
request or by manual dispatch. It uses read-only permissions and no release
credentials. It tests yellowfin GNOME on amd64 first (AlmaLinux/EL10, the RPM
family), then grouper GNOME on amd64 (Ubuntu, the apt family). Both cells retain their results when one fails. The job has a 180-minute limit; each VM has a 900-second
boot limit. Images remain in the runner's local Podman storage.

The harness prepares the regular source-pinned context for identity. A
receipt binds the exact identity and paired configuration
bytes. The build entry checks the cell, platform, namespace and build switches.
The identity helper accepts writes at `/` only inside a Podman container with
that receipt. A normal host, stock context, different namespace or different
architecture remains blocked. The receipt is qualification authority, not a
production support claim or a credential.

Each cell writes `qualification.json`, a source receipt, inspection of the local image, serial output, Corral results and screenshots. The installed guest
runs the receipt verifier before its display manager starts. The desktop marker cannot replace the identity marker from the guest.

Read each result field separately. A passed boot does not prove login,
wallpaper display, graphical installer operation or installation through
that installer. These fields stay `not-run` until tests execute
them. The current disk test uses Corral's bootc installation path. It does not
exercise the graphical installer. Pin the installer artifacts
to the tested source commit before that additional qualification.

Use an isolated machine with Linux amd64.
Install Podman, QEMU/KVM, OVMF, Corral, Python, Pillow 10.1+, PyYAML, jq and the pinned yq:

```sh
sudo python3 scripts/qualify-fork-image.py --variant yellowfin --output /tmp/harbor-yellowfin
sudo python3 scripts/qualify-fork-image.py --variant grouper --output /tmp/harbor-grouper
```

Use a new output directory each time. No upload, registry login, push, R2
publication or production admission occurs in these commands.

## Evidence transport

The probe writes to `/dev/ttyS0` directly. In
[run 39187536308](https://github.com/tuna-os/tunaOS/actions/runs/39187536308),
the command line for composefs kept `console=tty0` last. Thus `journal+console`
did not put the identity result on the serial port. The desktop test used an
explicit serial path and did report its result.

Corral at the source pin in `image-versions.yaml` selects TCG when KVM is absent.
The workflow must not stop before that fallback can run. The receipt records
the selected accelerator. TCG uses the same assertions and timeout.

The harness also unpacks each actual initramfs. It compares the bytes of each theme
asset and checks the selected theme in its configuration.
This proves embedded assets, not the visible splash. The greeter diagnostic
records its profile and logo setting. A screenshot review must still confirm
that the greeter displays the intended logo and name.

The canary fails if an identity marker, base marker or installed-system TAP result is absent or fails.
The readiness marker from the desktop cannot replace these results.
The upload excludes Corral's ephemeral SSH keys.


## Optional native installer welcome proof

The typed-login helper can test the normal entrypoint of the GNOME installer in its
existing disposable guest. The workflow does not call this option yet.
Download the frozen artifact on the host first, in a separate token-scoped step:

```sh
python3 scripts/qualify-fork-installer.py --download-output /tmp/harbor-installer
sudo python3 scripts/qualify-fork-login.py \
  --image localhost/fork-qualification/yellowfin:gnome-linux-amd64 \
  --wallpaper /tmp/harbor-yellowfin/wallpaper.jpg \
  --output /tmp/harbor-yellowfin/login-installer \
  --installer-artifact /tmp/harbor-installer/installer-artifact.zip
```

The download helper accepts only bootc-installer artifact `12163907071` from
[run 39200715506](https://github.com/tuna-os/bootc-installer/actions/runs/39200715506).
It checks the successful completed run, source head and ZIP SHA-256. It records a second checksum for
the single Flatpak bundle. The login helper checks the ZIP again before extraction.

The API-verified source head is `4d0e653f9283debb57b460fe495f65184f9d2c6c`.
The recorded tested merge is `7b6cbf9c152147c031f9ba362ddf4e909f36f643`.
That merge comes from prior provenance; this helper does not recheck the checkout SHA. The helper does not substitute a source build or release.

`GITHUB_TOKEN`, when needed, is read only by the host download helper. The helper does not put its value
in command arguments, receipts, redirected downloads or the guest.
A cross-repository API denial stops the download. It does not trigger credential
creation, permission changes or a different artifact. Run the login command in a
separate step without that token.

The guest must reach Flathub. The helper installs `org.gnome.Platform//50` and the
verified bundle into the disposable guest's system Flatpak installation. It then
runs `flatpak run --system org.bootcinstaller.Installer` as the authenticated canary
user, with the display and session bus from that GNOME session. It does not create
a second desktop, override the app command or bypass hardware checks.

The welcome result needs all of these observations:

- The same active `gdm-password` desktop session remains present.
- The app belongs to that user and matches the installed commit.
- A new `gtk-map` stamp names `BootcWindow`, not a hardware warning window.
- The framebuffer contains both “Welcome to Harbor Canary” and “Install Harbor Canary”.
- The logo above that heading matches the deployed source image's 128-pixel canary
  fixture, including color, square geometry and position. Orange in other locations cannot pass.
- Cleanup removes the derived VM, image, temporary source tag and ephemeral keys.

The evidence includes the welcome screenshot, screenshot hash, source-logo hash,
reference PNG, artifact and bundle hashes, app/runtime commits, and window
observations. `installer_committed_install` and `installed_target_identity` remain
`not-run`. The helper does not activate Install or erase a disk. Unit tests for the helper
check these contracts; they are not evidence that the native wizard has passed.

## Local installer source export

After original-image checks pass, the canary exports that exact image to a local
OCI directory. It resolves the configured tag once, pins the image ID, and checks
the embedded fork manifest and measured installer recipe. Skopeo must preserve
the platform-manifest digest. A second check hashes every exported blob and checks
the config ID and platform. The source image ID must match the earlier image check.

The `source_export` result is separate from boot and installation. The workflow
uploads only the external source receipt and raw manifest. OCI layers stay on the
runner. This step does not launch the installer or write a target disk.
