# Local fork image qualification

This harness builds and tests real images. It does not publish them. Ordinary
`--identity-staging --build` remains blocked. It does not change production workflows or the platform catalog.

`Fork Image Qualification` runs on the `feat/fork-image-qualification` pull
request or by manual dispatch. It uses read-only permissions and no release
credentials. It tests yellowfin GNOME on amd64 first (AlmaLinux/EL10, the RPM
family), then grouper GNOME on amd64 (Ubuntu, the apt family). A failed first
cell stops the second. The job has a 180-minute limit; each VM has a 900-second
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
