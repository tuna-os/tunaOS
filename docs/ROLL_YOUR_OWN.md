# Roll Your Own TunaOS

TunaOS is not a distribution — it's a **build factory** that composes
bootable immutable Linux images from a matrix of choices:

```
base OS × desktop × kernel × drivers = image
```

The repo is designed to be forked. The intended workflow is: fork, turn
off the variants and desktops you don't want, edit `tunaos.toml`,
and build your own images. Every shipped desktop profile and Containerfile
is a starting point — not a locked artifact.

This guide walks through that workflow, from a minimal single-desktop fork
to a full custom CI pipeline.

---

## Table of Contents

1. [The Fork-Edit-Build Workflow](#the-fork-edit-build-workflow)
2. [Common Customizations (Edit in Place)](#common-customizations-edit-in-place)
   - [Changing packages in a desktop](#changing-packages-in-a-desktop)
   - [System-wide packages and config](#system-wide-packages-and-config)
   - [COPR repos, PPAs, and version locks](#copr-repos-ppas-and-version-locks)
   - [Changing branding, wallpapers, defaults](#changing-branding-wallpapers-defaults)
   - [Adding systemd services](#adding-systemd-services)
   - [Running custom build scripts](#running-custom-build-scripts)
3. [The custom/ Overlay (Lighter Alternative)](#the-custom-overlay-lighter-alternative)
4. [Going Deeper: Adding a Desktop](#going-deeper-adding-a-desktop)
5. [Going Deeper: Adding a Distro Variant](#going-deeper-adding-a-distro-variant)
6. [Running Your Own CI/CD](#running-your-own-cicd)
7. [Reference: Directory Map](#reference-directory-map)

---

## The Fork-Edit-Build Workflow

This is the primary path. Fork, prune, edit, build.

### 1. Fork and clone

```bash
gh repo fork tuna-os/tunaOS --clone
cd tunaOS
```

### 2. Prune: turn off what you don't want

Open `tunaos.toml`. TunaOS itself uses this file for the matrix. Edit the
existing variant and flavor tables; do not edit `.github/build-config.yml`.
Build setup creates that ignored compatibility file from TOML.

For example, find this flavor under Yellowfin and change its build flags:

```toml
[[variants.yellowfin.flavors]]
id = "cosmic"
stage = 2
build_image = false
build_iso = false
build_qcow2 = false
```

This is an excerpt, not a whole config file. Keep the shared `base` stage and
all parent stages that the desktops you keep need. Keep existing safety holds
until tests support a change. Run `python3 scripts/config.py validate` after
edits. Use `python3 scripts/config.py show` to inspect the effective matrix.

To drop a whole variant, delete its `[variants.<id>]` and
`[[variants.<id>.flavors]]` tables and run `validate`. Each error names the
next leftover; clear them in this order (measured on a fork that kept only
`yellowfin` and `grouper`):

| Delete or edit | Why `validate` asks |
|---|---|
| `[tuna_rollout.<id>]` | every rollout record needs its variant |
| `[flavor_metadata.<flavor>]` for each flavor no remaining variant has | the table must cover exactly the flavor ids that remain |
| The variant under `[[iso_builder.selection.facets.values]]` of the `base` facet, and each `desktop` or `edition` value that no remaining flavor uses | the ISO Builder cannot offer what the matrix lacks |
| `[package_catalogs.<id>]` whose `variant` is the one you removed (`debian-trixie` names `flounder`) | a catalog needs its variant |
| `iso_builder.default_selection` and `[[iso_builder.selection.recommendations]]`, if they name it | the default must be a cell that builds |

Two leftovers are not `validate` errors. `[[sibling_images]]` lists TunaOS's own
sibling projects, so delete it. `.github/workflows/build-<id>.yml` stays behind
because `just generate-workflows` writes wrappers and never removes one, and
that file keeps its nightly cron; `just check` fails and names each wrapper
whose variant is gone. Delete those files.

A variant's nightly cron and its place in the manual `build-flavor.yml` sweep are
keys on the variant, not code. `schedule = "20 3 * * *"` sets the cron of
`build-<id>.yml` (omit it for a dispatch-only variant; stagger it, because the org
runs 20 jobs at once and `build-variant.yml` records the slots).
`flavor_dispatch = false` keeps a variant out of the sweep, which otherwise lists
every non-experimental variant.

`asahi_verify = true` adds a variant to the daily
sweep of `verify-asahi.yml`. `asahi_hardware = true` adds it to the sweep of
`asahi-hw-nightly.yml`. Both default to false. `just generate-workflows` writes
all of them.

`tunaos-builder.yaml` is a static VM file. Lima and corral do not expand
environment variables in it. A fork that uses lima alone edits the `tunaos`
clone URL. Corral builds set `origin` to `GITHUB_REPOSITORY` first. The sample
arguments in the `Justfile` name TunaOS variants. Pass your own.

Workflows and scripts that read or write published images (`bootc-lifecycle`,
`catalog-facts`, `live-overlay`, `live-initramfs`, `publish-isos`,
`publish-iso-groups`, `verify-asahi`, `asahi-hw-nightly`, the buildcache name,
`package-parity.sh`, `build-custom`) take the destination from `[build.publish]`,
else `ghcr.io/<repository owner>`, through `scripts/publish-destination.sh`.

Packages, identity and brand settings live in the same file; the sections below
show each. [Still hardcoded in code](#what-a-fork-still-edits-in-code) lists the
few values a fork has to change outside `tunaos.toml` today.

What to turn off and why:

| Remove this | If... |
|---|---|
| Variants you don't use | You don't need 11 distros |
| Desktops you don't ship | You only care about GNOME |
| `*-hwe` flavors | Your hardware runs fine on the stock kernel |
| `*-nvidia` flavors | You don't have NVIDIA GPUs |
| `build_iso: true` on flavors you test as containers | ISOs take extra CI time |
| `linux/arm64` / `linux/amd64/v2` platforms | You only run amd64 |

The smaller your matrix, the faster your CI. A single-desktop build takes
~15 minutes cold, ~5 minutes warm.

### 3. Edit: customize the desktop policies

Edit the `[desktops.<profile>.packages.<family>]` tables in `tunaos.toml` for
the desktop you kept. Do not edit `manifests/desktops/*.yaml`. Generation
writes those files and overwrites your edits. Use the
[package editor](PACKAGE-AUTHORING.md) to search an index and preview an add.
See [Common Customizations](#common-customizations-edit-in-place) below.

### 4. Edit: customize the Containerfile

The Containerfile runs numbered build scripts in order. To add your own
script, insert it into the pipeline:

```dockerfile
# Containerfile.el10 — add your own script between existing ones
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/20-packages.sh

# Your custom script — runs after base packages, before desktop install
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
   /run/context/build_scripts/25-my-custom-stuff.sh
```

Or edit an existing script directly — `20-packages.sh` installs
system-wide packages, `00-workarounds.sh` applies early patches,
`40-services.sh` enables services.

### 5. Build locally

```bash
just build yellowfin gnome
```

This builds your customized image. Test it:

```bash
just qcow2 yellowfin gnome
just verify-disk ./yellowfin-gnome.qcow2
```

### 6. That's your distro now

Push to your fork. With no other change, CI publishes to
`ghcr.io/<your-username>/...`, and each image records that location as its
vendor and update source. Commit, push, and your images build automatically.

To publish somewhere else, for example another registry or an organization,
set the destination in `tunaos.toml`:

```toml
[build.publish]
registry = "quay.io"
namespace = "acme"
```

Local builds, CI, ISOs and the boot gate all use this destination, and each
image records it. The repository variable `IMAGE_REGISTRY` (for example
`quay.io/acme`) still overrides it for one repository.

CI signs in to `ghcr.io/<repository owner>` with the repository `GITHUB_TOKEN`.
That token cannot write anywhere else. For any other destination, CI uses the
credential that [RFC 016](rfc/rfc016-publish-credentials.md) defines. It never
falls back to `ghcr.io/<repository owner>`.

| What | Name | Where |
|---|---|---|
| Registry user or robot account | `TUNAOS_PUBLISH_USERNAME` | secret in the `publish` environment |
| Registry token for that account | `TUNAOS_PUBLISH_PASSWORD` | secret in the `publish` environment |
| The one approved destination, for example `quay.io/acme` | `TUNAOS_PUBLISH_SCOPE` | repository variable |

Set it up once:

1. Create the environment `publish`. Restrict its deployment branches to
   `main`. Put both secrets in the environment, not in the repository.
2. Set the variable `TUNAOS_PUBLISH_SCOPE` to the exact destination.
3. Use a robot or deploy token that can write that one namespace. Do not use an
   account or organization admin token.
4. Make the published packages public. Users run `bootc upgrade` with no
   registry login, and the boot, ISO and lifecycle jobs pull with none.

`tunaos.toml` never holds a credential or a scope. A job refuses to start when:

- the run is not a `push`, `schedule` or `workflow_dispatch` run;
- one secret is set and the other is not;
- the variable is not set, or is not equal to the destination. A prefix does
  not match: `quay.io/acme` does not allow `quay.io/acme-evil`.

The error names the missing input. `scripts/publish-credential.py` makes this
choice and sees only whether each secret is set, never its value. The password
goes to each tool on standard input. The build steps never have it: login runs
after **Build Image**, so the layer cache in a non-owner registry is read-only.
A fork with a second destination must wait for a later extension: one
repository has one scope. For `ghcr.io/<other-org>`, docker and cosign keep one
`ghcr.io` entry, so they hold this token for all of `ghcr.io` in those jobs.

---

## Common Customizations (Edit in Place)

All of these are edits to existing files in the repo. No overlays, no
separate directories — you're changing the source of truth.

### Changing packages in a desktop

Edit the existing family table in `tunaos.toml`. For example, Ubuntu GNOME
uses `[desktops.gnome.packages.apt]` and its `required` list. Debian GNOME
uses the `gnome-debian` profile, and Arch GNOME uses `gnome-arch`. A
family-specific profile replaces the generic profile. It is not a layer on top.

RPM families also have `include` groups, which expand before the local
`required`, `optional` and `exclude` lists. A shared policy can affect several
variants. Use the existing table and the
[field reference](CONFIG-WIRING.md#package-fields-and-limits). Do not copy an
RPM table into an APT profile.

```bash
python3 scripts/config.py validate
python3 scripts/config.py generate
```

These commands check and write the adapters. They do not install packages or
show that a package transaction works.

### System-wide packages and config

Desktop manifests only cover what goes into the DE layer. To add packages to
*every* image of a variant, base flavors included, use `tunaos.toml`:

```toml
[defaults.packages]            # every variant
add = ["htop"]

[variants.yellowfin.packages]  # one variant, after the defaults
add = ["tree"]
optional = ["btop"]            # installed when available
repositories = [{ id = "acme", url = "https://repo.acme.example/el10", key_url = "https://repo.acme.example/key.asc" }]
```

Use the native package name of each variant's package manager. Gentoo needs
`category/name`, so put names that differ by distribution under the variant.
Repositories work on dnf and zypper only, and each needs a GPG key. Removals
are not supported yet. Run `python3 scripts/config.py generate-image-packages`;
`just check` fails if a name does not suit a variant's package manager. The
list of base packages stays in `build_scripts/20-packages.sh`.

For system-wide config files, add them to `system_files/`:

```
system_files/
├── etc/
│   ├── environment           # global env vars
│   └── dconf/
│       └── profile/
│           └── user          # dconf defaults for all users
└── usr/
    └── share/
        └── backgrounds/
            └── my-wallpaper.png
```

These are copied into every image by `build_scripts/00-copy-files.sh` (step
1 of the build). To override a file that upstream already ships, use
`system_files_overrides/` — it's applied after `system_files/`.

### COPR repos, PPAs, and version locks

Put COPR and PPA records in the desktop profile of `tunaos.toml`. Add each
record as a new array-of-tables entry under the family table. Do not edit the
generated `manifests/desktops/*.yaml` files. For the record shapes, see the
[repository records](CONFIG-WIRING.md#package-fields-and-limits).

```toml
# Append to tunaos.toml: a COPR for GNOME on el10, a PPA for GNOME on Ubuntu.
[[desktops.gnome.packages.el10.copr]]
repo = "someuser/someproject"
packages = ["package-from-copr", "another-package"]

[[desktops.gnome.packages.apt.ppa]]
repo = "ppa:someuser/someproject"
condition = "ubuntu"
```

A COPR record enables the source only for the listed `packages`. A PPA record
must use `condition = "ubuntu"`. Debian cannot use PPAs.

To add packages to one variant for every desktop, use
`[variants.<variant>.packages]`. `add` packages are required. `optional`
packages are best effort: the build continues if they are not available. On
dnf and zypper variants, `repositories` adds a signed RPM repository:

```toml
# Append to tunaos.toml: extra packages and one RPM repository for yellowfin.
[variants.yellowfin.packages]
add = ["htop"]
optional = ["fish", "neovim"]

[[variants.yellowfin.packages.repositories]]
id = "myproject"
url = "https://example.com/myproject/el10/"
key_url = "https://example.com/myproject/RPM-GPG-KEY-myproject"
```

Version locks are the `versionlock` list of a desktop profile, for example
`versionlock` in `[desktops.gnome]`. Edit the list that is already there. The
build runs `dnf versionlock add` for each pattern.

Run `python3 scripts/config.py generate` after each edit. The command
validates the file and writes the adapters.

### Changing branding, wallpapers, defaults

Your project's name, links and codenames live in `tunaos.toml`:

```toml
[project]
name = "Acme OS"          # fastfetch and the KDE About page: "part of Acme OS"
id = "acmeos"             # lowercase; project-id suffix in the CPE product
cpe_vendor = "acme"       # the vendor part of CPE_NAME
website = "https://acme.example"       # OCI `url` label, SBOM namespace (<website>/spdxdocs/)
docs_url = "https://acme.example/docs" # release notes; OCI `documentation` label is <docs_url>/intro
# Weekly adoption reports. Empty sends none. Validation rejects TunaOS's own
# endpoint once name or id differ from TunaOS, so a fork cannot report as a
# TunaOS cell by leaving it in place. Leave both out to send nothing.
countme_endpoint = ""
# countme_metrics_url = "https://acme.example/metrics"   # only with an endpoint

[defaults.branding]       # os-release HOME_URL, DOCUMENTATION_URL, SUPPORT_URL, BUG_REPORT_URL
homepage = "https://acme.example/os"
documentation = "https://acme.example/os/docs"
support = "https://acme.example/os/support"
bug_report = "https://acme.example/os/issues"
plymouth = "acmeos"        # boot splash for an image name that is no known variant

[variants.yellowfin]
codename = "Wile E"       # os-release VERSION_CODENAME
# Accent colour (ANSI_COLOR, /etc/issue, fastfetch, KDE, wallpapers), the
# nearest GNOME accent name, the base label, a short colour note and the
# boot splash theme.
branding = { accent = "#E87D0D", gnome_accent = "orange", base = "AlmaLinux Kitten", homage = "Acme orange", plymouth = "acmeos" }
```

Edit every variant you keep, not only one. A variant that you do not edit keeps
its TunaOS accent, codename and boot splash. For example, `albacore` keeps
the `tunaos` splash when you change only `[defaults.branding]`.

Then regenerate the files every image build reads, and commit them with
`tunaos.toml`:

```bash
python3 scripts/config.py generate-all
```

`generate-all` writes the matrix adapter, `build_scripts/lib/identity.env`,
`variant-identity.tsv`, `variant-aliases.tsv`, `image-packages.tsv`, the
Flatpak policy and the two files for the ISO Builder under `docs/`. `just check` runs
a `check-*` for each of them and fails, naming `generate-all`, when one
disagrees with `tunaos.toml`. If you change the matrix (variants, flavors or
platforms), also run `python3 scripts/generate-countme-allowlist.py`; only
`just test` checks that file. Each variant's name (Yellowfin, Marlin) comes
from its id, or its `publish_name`.

The variant's mark, lettermark and fastfetch letters follow its `emoji`, name
and `branding.accent`. After you change those, regenerate the artwork:

```bash
python3 -m pip install -r requirements-branding.txt
python3 scripts/branding/check-artwork.py --write
```

A new emoji needs an image: copy its file from Noto Emoji's `svg/` folder to
`scripts/branding/emoji/`. CI fails if the committed artwork does not match
`tunaos.toml`.

You supply the drawn art. Each variant needs a wallpaper at
`system_files/usr/share/backgrounds/tunaos/<variant>.jpg`, and
`tunaos-default.jpg` beside it, which must be JPEG files. TunaOS ships one
anime image for each variant and a copy of one of them as
`tunaos-default.jpg`. The build copies the
variant's file over `tunaos-default.jpg`, and fails if the file is missing.
Add each wallpaper to
`system_files/usr/share/gnome-background-properties/tunaos.xml`, the list in
GNOME Settings. `just test` fails when a variant has no entry.

Each variant's `branding.plymouth` names its boot splash, a theme folder under
`system_files/usr/share/plymouth/themes/`. An image name that is not a known
variant gets the theme in `[defaults.branding] plymouth`. `just check` fails
and names the file when a wallpaper or a splash file is missing. It also fails
when a wallpaper is not a JPEG.

To start from an existing splash, copy the folder, rename its two files
and edit the descriptor. The descriptor still names the folder you copied:

```bash
cd system_files/usr/share/plymouth/themes
cp -r tunaos acmeos && mv acmeos/tunaos.plymouth acmeos/acmeos.plymouth && mv acmeos/tunaos.script acmeos/acmeos.script
# In acmeos.plymouth set Name, Description, ImageDir=/usr/share/plymouth/themes/acmeos
# and ScriptFile=/usr/share/plymouth/themes/acmeos/acmeos.script
```

`check-drawn-artwork` fails when `ImageDir` or `ScriptFile` points at another
theme. Before this check, a copied theme passed and the image booted the splash
of the original theme.

The installer's slides come from `system_files/etc/bootc-installer/recipe.json`,
and the build puts the variant name where they name the project. The installer
logo is the variant's mark, made from its `emoji`. The build sets `imgref` and
`local_imgref` to `<registry>/<namespace>/<project id>:latest`, from the
destination this build publishes to and `[project] id`. For TunaOS that is
`ghcr.io/tuna-os/tunaos:latest`; for the Acme tree it is
`quay.io/acme/acmeos:latest`. Publish an image under that name, or the
installer has nothing to install.

`[flatpak_preinstall] remote_url` sets the Flatpak remote of Tuna Desktop and
of the live ISO. It is the URL of a `.flatpakrepo` file. The image registers
the remote as `tuna-os`, and the installer apps of the live ISO come from it.
An empty value registers no remote.

The ISO Builder page and the ISO file names have their own brand keys, in
`[iso_builder.brand]`, `[iso_builder.presentation]` and `[iso_builder.output]`
(`name`, `homepage_url`, `headline`, `volume_label`, `filename_prefix`).
`[project]` does not set them. Set them too, then run `generate-all`.

For GNOME defaults, create a gschema override:

```
system_files_overrides/usr/share/glib-2.0/schemas/99_my_defaults.gschema.override
```

```ini
[org.gnome.desktop.background]
picture-uri='file:///usr/share/backgrounds/my-wallpaper.png'

[org.gnome.desktop.interface]
gtk-theme='Adwaita-dark'
```

The build system already runs `glib-compile-schemas`.

### What a fork still edits in code

These values name TunaOS but are not read from `tunaos.toml` yet. A fork that
publishes under its own name changes them in the file shown. These items are
not in this list now. They come from `[project]`, `[defaults.branding]` and
`[flatpak_preinstall]` (above). These are the installer image, the
usage-report endpoint, image labels and release notes. They are also the SBOM
identity, live-ISO launchers, ISO media names, KDE theme names and Flatpak
remote.

| Value | Where | Effect if you leave it |
|---|---|---|
| Builder VM clone URL | `tunaos-builder.yaml` | the VM template clones `tuna-os/tunaos`; `scripts/corral-build.sh` re-points it to `CORRAL_REPO` or `GITHUB_REPOSITORY`, `limactl start` alone does not |
| Nightly schedule per variant | `scripts/generate-workflows.py` (`SCHEDULES`) | a variant you add has no cron |
| Variant list for manual builds | `.github/workflows/build-flavor.yml` (`matrix.variant`) | dispatches variants you may not have |
| Plasma theme and wallpaper package ids and paths | `system_files/usr/share/plasma/look-and-feel/org.tunaos*.desktop/` (`Id`), `system_files/usr/share/wallpapers/TunaOS/` (the folder), `system_files/etc/xdg/kscreenlockerrc` | internal identifiers, not shown: KDE lists the variant's name, the project name and your URLs come from `tunaos.toml`, but the package ids and the folder keep their TunaOS spelling |
| Installer Flatpak ids (`org.tunaos.Installer*`) and the `tuna-os` remote name | `live-iso/common/src/customize-live.sh`, `live-iso/common/src/desktop-*.sh` | the live ISO installs these apps from the remote `[flatpak_preinstall] remote_url` names; your remote must carry them under these ids |
| Package repository host | `build_scripts/desktop/install-desktop.sh`, `build_scripts/10-base-packages.sh`, `Containerfile.arch` (`repo.tunaos.org`) | the image keeps pulling TunaOS's packages; this is a dependency, not branding |

### Adding systemd services

Two approaches:

**A) Via system_files (recommended):** Place units in
`system_files/etc/systemd/system/` and they're copied in. Then edit
`build_scripts/40-services.sh` to enable them:

```bash
# build_scripts/40-services.sh — add:
safe_enable "myservice.service"
```

**B) Via build script:** Create `build_scripts/25-my-services.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/lib.sh"

cat > /etc/systemd/system/myservice.service <<'EOF'
[Unit]
Description=My Custom Service
[Service]
Type=oneshot
ExecStart=/usr/local/bin/my-script.sh
[Install]
WantedBy=multi-user.target
EOF

safe_enable "myservice.service"
```

Then add a `RUN` step to the Containerfile (see [step 4
above](#4-edit-customize-the-containerfile)).

### Running custom build scripts

Create a script in `build_scripts/` (follow the numbered naming
convention — scripts run in order) and add a `RUN` line in the
Containerfile:

```bash
#!/usr/bin/env bash
# build_scripts/25-my-stuff.sh
set -euo pipefail
source "$(dirname "$0")/lib.sh"

echo "installing my custom things"
pkg_install my-package another-package
```

The build library (`lib.sh`) gives you `pkg_install`,
`install_available`, `dnf_retry`, `safe_enable`, and all `IS_*` flags.

---

## The custom/ Overlay (Lighter Alternative)

`custom/packages.yaml` remains an authored input for this separate overlay,
consumed by `build_scripts/apply-custom.sh`. It is not a generated desktop
manifest. The TOML generation commands do not replace it.

If you'd rather not edit source files at all, the `custom/` directory is a
self-contained overlay that layers on top of a published TunaOS image.
It's simpler but less powerful — you can't change the desktop manifest or
build stages.

```bash
# Edit these two files:
#   custom/image.yaml    — base image + tag
#   custom/packages.yaml — add/remove packages

just build-custom        # build your overlay
just run-custom-vm       # boot it as a VM
```

```yaml
# custom/image.yaml
base: ghcr.io/tuna-os/yellowfin:gnome
tag: my-custom-os
```

```yaml
# custom/packages.yaml
dnf:
  - neovim
  - btop
  - syncthing
  - "-gnome-tour"     # remove packages with a minus prefix
```

Also available: `custom/files/` (config file overlay), `custom/systemd/`
(units to enable), `custom/build.pre.sh` / `custom/build.post.sh` (hook
scripts), `custom/just/` (custom ujust recipes).

The overlay is good for personal machines and quick experiments. For a
project you intend to maintain and ship to others, the fork-edit-build
workflow is the right path.

---

## Going Deeper: Adding a Desktop

A fork changes desktops in `tunaos.toml` only. You can:

- add packages, COPRs or PPAs to a desktop that the repo has (see
  [COPR repos, PPAs, and version locks](#copr-repos-ppas-and-version-locks));
- select which existing desktops each variant builds, with the
  `[[variants.<variant>.flavors]]` tables.

```toml
# Append to tunaos.toml: an extra COPR package for XFCE on el10.
[[desktops.xfce.packages.el10.copr]]
repo = "someuser/xfce-extras"
packages = ["xfce4-extra-plugin"]
```

Each desktop flavor builds from a Containerfile stage of the same name. A
desktop that has no stage, for example a new `myde`, is not a fork change. It
needs a new `[desktops.myde]` profile, a Containerfile stage and a flavor.
Open an issue or a pull request for it in tuna-os/tunaOS.

---

## Going Deeper: Adding a Distro Variant

To build on a new base OS:

### 1. Find or build a bootc-compatible base image

The base image must have `bootc` installed. For existing distros, check if
a bootc image exists. For new ones, you'll need to build one (follow the
pattern in `Containerfile.ubuntu` or `Containerfile.debian`).

### 2. Confirm package-manager support

If this base uses a manager TunaOS already supports, continue with the TOML
tables below. If it needs a new manager, stop. The build framework needs code
and tests for package detection, installation, and family validation. This work
is separate from a config-only fork.

### 3. Add the variant to the build matrix

```toml
# tunaos.toml: add these tables to the existing file.
[variants.myvariant]
emoji = "🐟"
description = "Based on MyOS"
base_image = "ghcr.io/myorg/myos-bootc:latest"
platforms = ["linux/amd64"]

[[variants.myvariant.flavors]]
id = "base"
stage = 1
build_image = true

[[variants.myvariant.flavors]]
id = "gnome"
stage = 2
build_image = true
build_iso = true

[tuna_rollout.myvariant]
status = "unsupported"
package_target = "myos"
reason = "Tuna Desktop packages for this base need tests."
```

### 4. Declare desktop packages in the primary config

Edit the existing `[desktops.<profile>.packages.<family>]` table in
`tunaos.toml`; generated YAML is not the source of truth. For an apt-based
variant using the generic GNOME profile, the table has this shape:

```toml
# tunaos.toml — edit the existing table, do not append a duplicate.
[desktops.gnome.packages.apt]
required = ["gnome-shell", "gnome-session", "gdm3"]
```

Preserve the other required packages when you edit the list. Select the profile
and native family using the [package field reference](CONFIG-WIRING.md#package-fields-and-limits);
Debian and Arch may use replacement profiles. An invented `my-pkg-mgr` key is
not supported: a new package manager needs schema and consumer implementation.

Run `python3 scripts/config.py validate` and `python3 scripts/config.py generate`.
Generation writes `.github/build-config.yml` for matrix consumers and
`manifests/desktops/<profile>.yaml` for `build_scripts/desktop/install-desktop.sh`.
These source checks do not establish package installability or image/installer
acceptance.

### 5. Add build commands to the Justfile

```just
build-myvariant flavor='gnome' *args: (build "myvariant" flavor +args)
```

---

## Running Your Own CI/CD

Once you've pruned the matrix and customized `tunaos.toml`, push to your
fork. The existing workflows work out of the box:

### What's already wired up

| File | What it does |
|---|---|
| `.github/workflows/build-variant.yml` | Reads generated `.github/build-config.yml`, builds a matrix, and runs the 4-stage DAG |
| `.github/workflows/reusable-build-image.yml` | Per-image build → push to GHCR → cosign sign → QEMU boot gate |
| `.github/workflows/reusable-build-artifacts.yml` | ISO and QCOW2 generation |

The workflows use `${{ github.repository_owner }}` as the registry
namespace — forked, they automatically push to `ghcr.io/<your-username>/...`.

### What you may need to set up

- **Secrets** (optional): `COSIGN_PRIVATE_KEY` / `COSIGN_PUBLIC_KEY` for
  image signing. Builds work without these — images are unsigned but still
  functional.
- **RHSM credentials**: Only needed if you added a RHEL variant.

### Triggering builds

Push to main, or manually:

```
Actions → Build Yellowfin → Run workflow
```

### Build costs

A single-desktop build on GitHub's free runners takes ~15 minutes cold,
~5 minutes with a warm cache. Most customization work should happen
locally with `just build` — only push when you're ready to publish.

---

## Reference: Directory Map

```
tunaos/
├── tunaos.toml                     ← EDIT THIS — MATRIX AND DESKTOP POLICY
│   # variants.*, desktops.<profile>.packages.<family>, package_groups.*
├── .github/build-config.yml        ← GENERATED by config.py generate
├── manifests/desktops/             ← GENERATED by config.py generate
│   └── <profile>.yaml              # consumed by desktop/install-desktop.sh
│
├── build_scripts/                   ← EDIT THESE — BUILD ENGINE
│   ├── desktop/install-desktop.sh   #   generic manifest-driven DE installer
│   ├── lib.sh                       #   shared library (OS detect, pkg wrappers)
│   ├── 00-workarounds.sh            #   early patches and workarounds
│   ├── 10-base-packages.sh          #   base OS packages (no DE)
│   ├── 20-packages.sh               #   system-wide packages
│   ├── 26-packages-post.sh          #   post-package cleanup
│   ├── 40-services.sh               #   systemd service enablement
│   ├── 90-image-info.sh             #   image metadata stamping
│   ├── HWE.sh                       #   HWE kernel installer
│   ├── nvidia.sh                    #   NVIDIA driver installer
│   ├── cachyos.sh                   #   CachyOS kernel overlay
│   ├── copy-files.sh                #   system_files → image
│   ├── cleanup.sh                   #   final cleanup
│   └── ...
│
├── system_files/                    ← EDIT THESE — SYSTEM CONFIG
│   ├── etc/                         #   /etc config files
│   └── usr/                         #   /usr config files
│
├── system_files_overrides/          ← OVERRIDES (applied after system_files)
│   └── ...
│
├── Containerfile.el10               ← EDIT THIS — MAIN BUILD (EL10/Fedora)
├── Containerfile.overlay            ← HWE/NVIDIA/CachyOS parameterized overlay
├── Containerfile.ubuntu             ← Ubuntu bootcification
├── Containerfile.debian             ← Debian bootcification
├── Containerfile.arch               ← Arch bootcification
├── Containerfile.gentoo             ← Gentoo bootcification
├── Containerfile.opensuse           ← openSUSE bootcification
│
├── custom/                          ← OPTIONAL PACKAGE/FILE OVERLAY, separate from TOML
│   ├── image.yaml                   #   base image + tag
│   ├── packages.yaml                #   supported package overlay input
│   ├── files/                       #   config file overlay
│   └── systemd/                     #   systemd units
│
├── scripts/                         ← TOOL SCRIPTS (usually don't need editing)
│   ├── resolve-flavor.sh            #   flavor → Containerfile, target, flags
│   ├── resolve-image.sh             #   image ref resolver
│   └── build-image-inner.sh         #   build engine (env-var driven)
│
└── Justfile                         ← TASK RUNNER
    just build yellowfin gnome       #   build one image locally
    just build yellowfin all         #   build all desktops for a variant
```

---

## Cheat Sheet

```bash
# ── Setup ──────────────────────────────────────────────────────
brew install podman
gh repo fork tuna-os/tunaOS --clone && cd tunaOS
python3 scripts/lint_tools.py install --bin-dir "$HOME/.local/bin"
export PATH="$HOME/.local/bin:$PATH"
just setup

# ── Local builds ───────────────────────────────────────────────
just build yellowfin gnome           # build one image
just build yellowfin all             # build all desktops for a variant
just build yellowfin kde linux/amd64 # specific platform

# ── Custom overlay (lighter alternative) ───────────────────────
just build-custom                    # build your custom/ overlay
just run-custom-vm                   # boot it as a VM

# ── Testing ────────────────────────────────────────────────────
just test                            # bats + pytest
just qcow2 yellowfin gnome           # produce VM disk
just verify-disk disk.qcow2          # QEMU boot check

# ── Pre-commit (mandatory) ─────────────────────────────────────
just fix && just check
```
