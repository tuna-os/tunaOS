# Opt-in fork brand consumers

This preview applies a deliberately small part of [RFC 013](rfc/rfc013-single-fork-config.md).
It does not qualify a new brand, desktop, boot splash or installer. Stock builds
never create or read a fork configuration unless the prepared context explicitly
contains `manifests/fork-config.json`.

## Supported values

- `homepage` sets `HOME_URL` and KDE's `[General] Website` when that file exists.
- `documentation` sets `DOCUMENTATION_URL`.
- `support` sets both `SUPPORT_URL` and `BUG_REPORT_URL`.
- `wallpaper` replaces the shared active wallpaper with a host-validated JPEG.
  Prepare the final JPEG before materialization. The image build does not convert PNG to JPEG.
  The preview rejects wallpaper changes for `tuna` until we measure the setting
  its desktop reads. URL/package-only previews remain possible for that desktop.
  The compiler limits each file to 16 MiB and 8192 pixels per axis.
  It accepts only a single-frame JPEG.

The adapter updates both os-release files when a base carries independent copies.
It preserves the normal `/etc/os-release -> ../usr/lib/os-release` symlink.
Values are literal data: URL query ampersands, quotes, dollars and backticks do
not become shell or sed expressions. An unspecified URL keeps its stock value.

The preview rejects `name` and `logo`, including apparently harmless partial
changes. Fish names/codenames, CPE, hostname, lettermarks, fastfetch,
Plymouth and logos in the installer need a coordinated adapter and artifact evidence.
A local SVG cannot replace a resource URI in the installer. These surfaces remain stock; a URL/wallpaper preview is not a
fully renamed distribution. The stock installer text and imagery remain in use.

The local preview's canonical variant names remain separate, including
`bonito-rawhide` and `flounder-sid`. Its image reference uses the configured
registry and namespace plus that canonical variant. It does not use the aliases
for stock releases. Preparation does not publish the image or authorize a push.

## Internal input and application order

The generated JSON has only these top-level keys:

- `schema_version: 1`
- `image: {registry, namespace}`
- `variant`, `flavor`, `platform`, `package_manager`
- `intent: {branding, packages}`
- `sources: {sha256}`
- `assets`, empty or `{wallpaper: {path, sha256}}`

A wallpaper asset is beside the manifest at
`fork-assets/<sha256>.jpg`. The adapter rejects duplicate/unknown JSON keys,
missing/symlinked assets and hash changes. It also rejects unsupported fields
and mismatches in cell identity or architecture before any writes. It needs the existing
`IMAGE_NAME_VARIANT` and `TUNAOS_IMAGE_FLAVOR` build identity. The wrapper passes
the exact platform to the build engine; `uname` can distinguish amd64 from arm64
but cannot establish amd64/v2 ISA qualification.

`build_scripts/lib/fork-branding.sh` provides these functions:

- `tunaos_validate_fork_branding <context>` validates before package deltas.
- `tunaos_apply_fork_branding <context> [root=/]` applies and persists inputs.
- `tunaos_verify_fork_branding [root=/]` compares installed state to that input.

The root argument is a test seam. Missing generated input is a quiet no-op,
without new files or rewritten stock files. If input exists but is invalid, the adapter fails.

The final hook in `90-image-info.sh` reapplies the overrides after all stock
identity and wallpaper writes, including when that script runs again in a later
stage. Both desktop paths apply after curated files and again after
`select-wallpaper.sh`, so per-variant/per-desktop artwork cannot overwrite the
requested wallpaper. They reapply after the desktop scripts too because
KDE's About writer restores its stock website.

The GNOME, KDE, COSMIC, Niri, XFCE and Pantheon desktop consumers use
`/usr/share/backgrounds/tunaos/tunaos-default.jpg`. KDE's wallpaper-package image
is a symlink to it; GNOME/COSMIC settings and Niri/XFCE helpers use
the same path. The Pantheon schema names that path too. User-selected wallpapers are still
user preferences. This does not replace them after first login.

## Verification boundary

The adapter persists the validated JSON and original asset bytes under
`/usr/share/tunaos/fork`, installs its verifier, and adds a `fork-config` source
receipt to `image-info.json`. Verification checks variant/flavor, configured
image reference/vendor, both os-release copies, KDE's About website when
present, the copied asset hash and the active wallpaper hash.

`verify-branding.sh` changes URL/vendor expectations only after that check
passes. It retains the stock fish codename, name denylist, logo, image identity,
Plymouth, dconf and asset checks. Existing per-desktop contracts still run.
Nothing turns a failed fork validation into a stock pass.

Run focused source-level checks:

```sh
python3 -m pytest tests/test_fork_branding.py -q
bats tests/bats/test_gnome_branding.bats tests/bats/test_wallpaper_contract.bats tests/bats/test_installer_branding.bats
```

The Python tests execute the helper under a temporary root. They check that
stock bytes do not change without input. Repeated application must also be safe.
They test invalid input, literal URLs and changes to source or applied files.

They also check hook order in both desktop paths and execute the existing GNOME
and KDE writers. The tests use placeholders for dconf files. They do not prove that GLib
compiled a database. No test here is evidence of a produced image, boot, visible greeter,
Plymouth, login or installer. Those remain the required canary boundaries before
wider consumer rollout.

### Late-copy canary gap

`Containerfile.opensuse` copies the pinned common image's
`/system_files/bluefin` into `sailfin:gnome` **after** `install-desktop.sh`, then
recompiles schemas/dconf. The repository does not contain the exact contents of
that OCI layer. This source-only run therefore cannot exclude a later override
of the active wallpaper or settings.

Runtime checks of hashes and GNOME settings
remain enabled. Build and inspect an image after the final COPY. Then boot it
and check the visible wallpaper. A successful helper call before the COPY does
not prove the state of the final artifact.
