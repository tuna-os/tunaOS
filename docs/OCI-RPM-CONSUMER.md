# Build-only OCI RPM consumer

`scripts/install-oci-rpm-repository.py` is an opt-in path for a rehearsal.
Only the manual diagnostic calls it. Production workflows and Containerfiles do not call it.
It does not change `tunaos.toml`, feeds, image pins or production channels.
It does not retire standalone DNF support in tunaos-packages.

The consumer uses DNF to resolve native dependencies. It checks RPM signatures
and records the installed RPM inventory. It does not use `rpm --nodeps`, copy
package contents into an image, or replace the package database.

## Required inputs

- Supply a real GHCR reference that a reviewer has approved. The reference must
  be immutable and contain a complete snapshot of native RPMs. Supply its exact identity
  of the GitHub workflow, native target and architecture. The snapshot must
  have the new producer's scope labels and single `/repository` layer.
  Legacy Utah/GNOME50 image pins do not satisfy this format.
- Supply the local `scripts/oras_distribution.py` from tunaos-packages with
  `--transport`. Use merged revision `8f57b6376c0e7ec330a9bf1b08b5179c7288a299`.
  The consumer enforces SHA-256
  `7e37d1ff61153d5419cdfca54ea6f9a0256c65cb53972da9f6235c2081ccfb32`.
  It does not search sibling worktrees, infer download URLs or use a network fallback.
- Install ORAS **1.3.4**, cosign, Python 3.11+, **DNF4** and RPM in the build environment.
  The consumer refuses DNF5 before transport. This work does not qualify DNF5
  overrides or drop-in configuration. Do not use this helper for a Fedora/DNF5 migration.
  The transport has a pin and checks ORAS. It verifies the exact signer, issuer,
  digest, scope and layer bytes before it exposes the repository.
- Supply the local public key for RPM and its SHA-256. Review both inputs independently.
  Neither the consumer nor its repo file fetches the key over HTTP.
- Supply a package inventory file with one package name per line, without implicit selections.
  Empty lines, wildcards, URLs, flags and shell commands are invalid.
  Keep the intended inventory. Do not reduce it to make an incomplete provider pass.
- Supply a directory of signed upstream `.repo` files for the distribution.
  The consumer copies them into private temporary configuration.
  It rejects R2 references in base URLs and key URLs, even in disabled entries.
  It admits only static base URLs over HTTPS and local files for public keys.
  Before execution, it copies the key bytes and records their hashes.
  It rewrites the configuration to use private key paths.
  It rejects percent-encoded values and hosts that do not have a canonical form.
  Enable checks for RPM signatures and metadata signatures.
  It rejects variables, mirrorlists, alternate configuration sources, duplicate or reserved IDs,
  and unsupported options. This narrow contract can need snapshots from curated
  upstream sources with signatures instead of stock mirror configurations.
  The consumer disables plugins, so they cannot add unreviewed feeds.
  It does not load the host's DNF configuration.

Use only a disposable image-build `RUN` stage. Mount the inputs read-only.
The helper has no usable default references or fabricated example digests.

```bash
python3 scripts/install-oci-rpm-repository.py \
  --transport "$REVIEWED_TRANSPORT" \
  --reference "$VERIFIED_SNAPSHOT_REF" --identity "$VERIFIED_SIGNER" \
  --target "$NATIVE_TARGET" --architecture "$NATIVE_ARCH" \
  --key "$REVIEWED_PUBLIC_KEY" --key-sha256 "$REVIEWED_KEY_SHA256" \
  --packages "$PACKAGE_INVENTORY" --upstream-repos "$DISTRO_REPO_CONFIGS" \
  --priority "$REVIEWED_REPOSITORY_PRIORITY"
```

`--priority` defaults to DNF's 99. Supply the source policy explicitly;
the EL10 GNOME tier uses 1. The accepted range is 1–99.

## Trust, receipts and cleanup

Stdout contains a JSON receipt. It records the reference, signer, scope, requested
packages, installed RPM inventory and hashes of keys, tools and configurations.
Child processes send progress to stderr. Keep the receipt with external build evidence.

On success or exception, the consumer removes its repo, key file, caches, logs,
transport copy and temporary state. It retains the RPM database, including imported
public keys. Before DNF, it checks the detached repomd signature and every RPM
signature against the reviewed key. These checks use isolated GPG/RPM databases,
not ambient image trust. RPM `gpgcheck=1`, `repo_gpgcheck=1` and OCI signature
verification remain enabled. Before DNF runs, it refuses packages without signatures or with an incorrect architecture.

The script checks configuration for persistent RPM sources before and after the transaction:
`/etc/yum.repos.d`, `/etc/dnf/repos.d`, `/etc/dnf/dnf.conf` and `/etc/yum.conf`.
It fails on controlled R2 domains, even in disabled repos.
It also rejects indirect sources of variables or configuration.
Private DNF variables and a filtered environment prevent ambient `DNF_VAR_*`
values from any effect on the transaction.

It does **not** delete existing repo files. Remove old feeds only through a reviewed
migration of image stages. The CLI always checks the actual `/etc`.
Only the internal unit-test API can inject a fixture path.

This guard covers configuration for RPM, not the entire image filesystem or other build stages.
A static inspection does not prove where HTTPS redirects or third-party storage services send requests.
An actual build must deny egress to controlled R2 hosts. After every stage, including overlays,
a final audit of the built artifact must confirm R2 independence.

## Migration blockers and boundaries

`tunaos.toml` retains native feeds over HTTP for EL10, XFCE EL10/Fedora, Hummingbird,
rawhide, ELN, openSUSE and Tideforge Ubuntu/Debian. That configuration has no approved
replacement pins for immutable snapshots with scope labels.
**An absent verified snapshot is a blocker, not an empty repository.**
PR #3537 covers qualification of GNOME51 providers. Packages from Utah for Hummingbird cannot substitute for EL10 ABI compatibility. PRs #3700 and #3701 own brand/config work.
This helper does not change those schemas or adapters.

For future activation, complete snapshots must have signatures. Native solvers must pass
qualification for each architecture. Keep inventories unchanged and review key inputs.
Use explicit stage mounts and remove each replaced persistent feed.
Complete scans of final images and boot/login qualification.

DEB/Arch/Gentoo consumers and build caches remain separate work.
Core OS updates stay bootc/uupd through GHCR. Applications stay Flatpak, Homebrew
or containers. Standalone native clients can remain while the image factory stops R2 use.

## Verification

Use `python3 -m pytest -q tests/test_oci_rpm_consumer.py` for offline tests of process contracts.
It also tests strict inputs, trust flags, operation order, inventories, persistent URL rejection and cleanup.
The tests use fake DNF/RPM and a fake transport. They do not prove published
snapshots, native dependency closure or a built image.
