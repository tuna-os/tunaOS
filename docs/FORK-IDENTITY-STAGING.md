# Fork name/logo staging

This is an opt-in, **non-buildable** continuation of RFC 013, stacked on the
URL/package/wallpaper consumer preview. It tests identity formats and GNOME paths in a disposable root.
It does not enable a partially branded image. Stock builds keep their previous behavior.

## Prepare from the same fork file

Use the existing pinned config, with both `branding.name` and `branding.logo`.
`examples/fork/identity.template.yaml` is a template; supply a single-frame PNG
named `logo.png` beside the initialized file. Name is 1–64 ASCII letters,
digits, spaces, dots, underscores or hyphens. The first character must be a letter or digit. The name cannot end with a space. This restricted preview does not claim support
for arbitrary scripts or fonts.

```sh
# Copy your final PNG to /tmp/harbor/logo.png first.
cp examples/fork/identity.template.yaml /tmp/harbor/identity.template.yaml
python3 scripts/resolve-fork-config.py --init-template /tmp/harbor/identity.template.yaml > /tmp/harbor/fork.yaml
python3 scripts/prepare-fork-config.py /tmp/harbor/fork.yaml --identity-staging --output /tmp/harbor-staging
```

Preparation needs Pillow 10.1+ on the host. It decodes a PNG of at most 4 MiB,
2048 pixels per axis and one frame. It generates a normalized logo and a
lettermark using Pillow's bundled font, with no network or external font lookup.
SVG files contain raster pixels for the GNOME paths.
The original logo hash, exact output hashes and source receipt enter the
per-cell `manifests/fork-identity.json`. Generated files are internal adapters;
the fork author still owns only one config and its referenced assets.

The review plan retains the complete name/logo intent. The existing closed
package/URL adapter gets only its supported intent; the identity adapter gets
the remaining name/logo input and receipts. The compiler uses existing cells
and holds. Direct RPM, Ubuntu and Debian GNOME routes are understood; a held
Debian cell stays held and is never prepared. The adapter rejects other desktops.

`builds.json` explicitly lists `build_blocked` reasons. `--identity-staging
--build` fails before preparation. The ordinary build engine also refuses an identity context before it calls image tools. The identity
helper refuses `/` and symlink aliases of `/`. Do not remove these gates to
produce a release.

## Exercise implemented consumers

Use a disposable root with the selected cell's `usr/lib/os-release` and `usr/share/ublue-os/image-info.json`. It is not an image
build. The helper checks the cell before writes and rejects symlink escapes.

```sh
python3 build_scripts/lib/fork-identity.py /absolute/staging-root \
  --manifest /tmp/harbor-staging/yellowfin--gnome--linux-amd64/manifests/fork-identity.json
python3 build_scripts/lib/fork-identity.py /absolute/staging-root
```

The existing `fork-branding` adapter calls this helper after URL/art application;
its call sites already run after the stock writers in both desktop paths.
Without `fork-identity.json`, nothing new runs or changes.

Implemented consumers:

- `NAME`, `PRETTY_NAME`, `VARIANT`, `VERSION_CODENAME` in both os-release copies.
  The usual `/etc/os-release` symlink stays intact. Remove the stock CPE. Do not invent a fork CPE authority. Preserve base `ID`/`ID_LIKE`, route IDs, hostname and image references. A display name does not define package families or image names.
- The existing GNOME About icon and GDM lettermark paths, with exact hashes.
  GNOME's existing writer selects the lettermark; no runtime font is required.
- The console banner reads `PRETTY_NAME`. The fastfetch config displays the fork's pretty name. It omits the fish mark and the “part of TunaOS” label. This intentionally replaces the staged stock layout.
- An installed receipt and verification of applied bytes, source assets,
  image cell and display values. Repeated application is byte-stable.

The next slice generates a PNG lettermark and a one-frame version of the stock
Plymouth script. It keeps the password, question and normal-display callbacks.
The existing selector copies the theme before dracut runs. Tests use an explicit
`TUNAOS_SYSROOT`; live-root writes still fail. Ubuntu and Debian refuse a failed
fork selection. Stock behavior stays unchanged.

The same fields generate `/etc/bootc-installer/branding.json`: `name`, `logo`,
and supplied `home_url`, `docs_url`, `support_url`. The adapter keeps other
existing fields. All frontends share this contract. The author does not maintain
another file. The logo is `/usr/share/pixmaps/tunaos.svg`. The installer must
translate host paths for Flatpak.

The adapter also updates display fields in an existing recipe. It updates a
catalog leaf only when its image reference is identical to the recipe value.
It preserves other entries, image references, install options, IDs and hostname.
It does not create a catalog when none exists. On standard live media, the
installer uses the common identity on its welcome and completion pages.
Explicit selection of another OS must still name that OS.

The adapter replaces stock tour names and the stock install illustration.
Custom illustrations stay intact. Tests of source code do not prove that the
pinned binary can render these files.

The receipt includes hashes of the theme and installer files. Runtime checks verify it
before they use fork expectations for names and the splash. Stock checks for
URLs, base identity, vendor, dconf and assets still apply. Corrupt receipts fail.
These checks do not remove the build gate or prove that dracut copied the theme.

The source-level test is not proof that GTK rendered the SVG,
that the GDM logo is visible, or that a boot/install completed.

## Installer artifact qualification remains blocked

Measured against bootc-installer dev commit
`981141d348b9207f9ef93bbdcec80d6b5f5611e0` (source, not a shipped artifact):

- GNOME [`apply_icon`](https://github.com/tuna-os/bootc-installer/blob/981141d348b9207f9ef93bbdcec80d6b5f5611e0/bootc_installer/views/done.py#L18-L27)
  handles `resource://` or theme icon names. It treats an absolute PNG/SVG filename as a theme name. The
  [welcome screen](https://github.com/tuna-os/bootc-installer/blob/981141d348b9207f9ef93bbdcec80d6b5f5611e0/bootc_installer/defaults/welcome.py#L93-L96)
  also prefers the selected catalog icon over the recipe logo.
- [Catalog rows](https://github.com/tuna-os/bootc-installer/blob/981141d348b9207f9ef93bbdcec80d6b5f5611e0/bootc_installer/defaults/image.py#L248-L270)
  accept an absolute filename but do not translate it to `/run/host`.
  A visible row icon would not prove the welcome/done header works.
- KDE and COSMIC use fixed drive icons on their welcome screens:
  [KDE](https://github.com/tuna-os/bootc-installer/blob/981141d348b9207f9ef93bbdcec80d6b5f5611e0/frontends/kde/modules/welcome/contents/ui/main.qml#L29-L35),
  [COSMIC](https://github.com/tuna-os/bootc-installer/blob/981141d348b9207f9ef93bbdcec80d6b5f5611e0/frontends/cosmic/src/ui.rs#L322-L332).
- [XFCE](https://github.com/tuna-os/bootc-installer/blob/981141d348b9207f9ef93bbdcec80d6b5f5611e0/frontends/xfce/tuna_installer_xfce/pages.py#L89-L113)
  has no product-logo widget in its welcome page.
- [Niri](https://github.com/tuna-os/bootc-installer/blob/981141d348b9207f9ef93bbdcec80d6b5f5611e0/frontends/niri/ui/installer.qml#L570-L589)
  renders an absolute `branding.logo` path, without host-path translation.

Each Flatpak grants access to host files. Flatpak exposes host `/usr` at
`/run/host/usr`, while sandbox `/usr` belongs to its runtime
([Flatpak filesystem contract](https://docs.flatpak.org/en/latest/sandbox-permissions.html#filesystem-access)).
A host hicolor icon does not prove that the sandbox can find that icon.
A resource URI cannot add a resource to an installed Flatpak.
The next consumer change needs a shared, Flatpak-aware file/logo contract and
renderer tests; then test the installer artifact at its pinned version.

## Remaining acceptance

Qualify the common installer contract in all frontend artifacts. Inspect the
actual generated initramfs for the selected theme, PNG and prompt callbacks.
Then test stock and fork canaries through build, boot, GDM/login and install. Record screenshots and immutable digests.

The identity helper verifies the receipt before it checks display values for the fork. Expand other desktops only
with their own consumers and evidence. No hold, source pin, release gate or
production workflow changes here.
