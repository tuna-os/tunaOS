# Roll Your Own TunaOS

TunaOS is not a distribution — it's a **build factory** that composes
bootable immutable Linux images from a matrix of choices:

```
base OS × desktop × kernel × drivers = image
```

The repo is designed to be forked. The intended workflow is: fork, turn
off the variants and desktops you do not need, edit `tunaos.toml`, and build
your images. Desktop manifests are generated adapters, not editable inputs.
Read [configuration wiring](CONFIG-WIRING.md) before changing package policy.

The complete config-and-assets-only branded journey is still being integrated
under [#3668](https://github.com/tuna-os/tunaOS/issues/3668). This guide does
not claim that pending identity, artwork or image-wide package fields work on
main. Framework changes below are advanced development, not that promised
config-only interface.

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

Use Python 3.10+ for config reads; the parser is vendored. For builds, set up
the container tools and permissions in [CONTRIBUTING.md](../CONTRIBUTING.md)
and [the Agent Guide](AGENT_GUIDE.md#setup). Package-editor dependencies are
separate; see [PACKAGE-AUTHORING.md](PACKAGE-AUTHORING.md). Local media generation
needs root privileges and VM verification needs the documented QEMU setup.

```bash
gh repo fork tuna-os/tunaos --clone
cd tunaos
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
until tests support a change. If you remove a whole variant, also remove its
`tuna_rollout` entry. Run `python3 scripts/config.py validate` after edits.
Use `python3 scripts/config.py show` to inspect the effective matrix.

Desktop package profiles and Flatpak declarations also live in `tunaos.toml`.
Installed identity, artwork and image-wide package deltas are not yet part of
the main schema. The [migration plan](PRIMARY-CONFIG-MIGRATION.md) is a design
reference, not a copyable configuration. `show` prints the matrix; it is not
a full field-provenance or installed-package explanation.

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

Edit existing `[desktops.<profile>.packages.<family>]` tables in `tunaos.toml`.
Do not edit `manifests/desktops/*.yaml`; generation overwrites those adapters.
Use [the package editor](PACKAGE-AUTHORING.md) for index-backed search and a
reviewable add preview, or edit the existing lists manually. The editor targets
an existing desktop/family, not all variants automatically.

```bash
python3 scripts/config.py validate
python3 scripts/config.py generate
python3 scripts/config.py show
```

These commands check and project source intent. They do not install packages
or prove that a package transaction will succeed.

### 4. Edit: customize the Containerfile

Skip this step for changes already supported by TOML. It is an advanced
framework modification, outside the config-and-assets-only contract.

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
system-wide packages, `01-workarounds.sh` applies early patches,
`40-services.sh` enables services.

### 5. Build locally

```bash
just build yellowfin gnome
```

This builds your customized image. Test it:

```bash
just qcow2 yellowfin gnome
just verify-disk ./yellowfin.qcow2
```

A QCOW2 boot test is not an ISO GUI installation test. For ISO commands and
checksum/signature verification, use [INSTALL.md](INSTALL.md). For installed
updates and rollback commands, use [USER-GUIDE.md](USER-GUIDE.md). The branded
Yellowfin/Grouper journey still needs matching build, login, visible branding,
plain/LUKS install, media-detached boot, update and recovery receipts under
[#3474](https://github.com/tuna-os/tunaOS/issues/3474). Do not infer these from
`validate`, generated files or a successful image build.

### 6. Publish only to an authorized destination

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

CI signs in with the repository's own `GITHUB_TOKEN`. That token can push only
to `ghcr.io` under the repository owner. CI cannot yet push to another
registry or namespace; issue #3668 tracks the credentials for that case.

---

## Common Customizations (Edit in Place)

All of these are edits to existing files in the repo. No overlays, no
separate directories — you're changing the source of truth.

### Changing packages in a desktop

Edit the existing family table in `tunaos.toml`. For example, Ubuntu GNOME
uses `[desktops.gnome.packages.apt]` and its `required` list. Debian GNOME
uses `gnome-debian`; Arch GNOME uses `gnome-arch`. Family-specific profiles
replace the generic profile; they are not extra layers on top of it.

For RPM families, inspect `include` groups as well as local `required`,
`optional` and `exclude` fields. The schema differs by native family; use the
existing section and [wiring reference](CONFIG-WIRING.md#package-fields-and-limits)
instead of copying an RPM table into APT. Included groups expand before local
entries, without deduplication. A shared policy can affect multiple variants.

Removing a name from an authored desktop list changes requested policy. It
does not prove removal from an inherited base image or a dependency closure.
Image-wide removal is deliberately unsupported by the primary interface.

### System-wide packages and config

Desktop manifests only cover what goes into the DE layer. For packages
that should be in *every* image (base layer), edit
`build_scripts/20-packages.sh`. That is a framework change. Open PR
[#3739](https://github.com/tuna-os/tunaOS/pull/3739) adds image-wide package
additions to TOML; `main` does not have them yet.

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

Edit the corresponding existing TOML family section. Repository, COPR and
PPA shapes differ; see [package fields and limits](CONFIG-WIRING.md#package-fields-and-limits).
The generated YAML carries them to the existing installer. Do not put tokens
in repository URLs. Optional packages are best-effort, not installed-inventory
proof. DNF version locks remain profile policy; they are not portable to APT.

### Changing branding, wallpapers, defaults

Main still uses framework identity and artwork writers. The pending primary
identity stack is not enabled by adding `[project]` to current main. If you
change framework branding below, inspect the final image: later writers can
overwrite environment values. These are not config-only instructions.

Existing Containerfile inputs include:

```dockerfile
ENV IMAGE_NAME="myproject"
ENV IMAGE_VENDOR="mycompany"
ENV IMAGE_NAME_VARIANT="myvariant"
```

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

Optional extras, created only if you need them: `custom/files/` (config file
overlay), `custom/systemd/` (units to copy and enable), `custom/flatpaks.list`,
`custom/build.pre.sh` / `custom/build.post.sh` (hook scripts) and
`custom/just/` (custom ujust recipes). `build_scripts/apply-custom.sh` applies them.

The overlay is good for personal machines and quick experiments. For a
project you intend to maintain and ship to others, the fork-edit-build
workflow is the right path.

---

## Going Deeper: Adding a Desktop

To add a desktop environment that isn't already in the repo:

### 1. Define and generate the desktop policy

Add a `[desktops.<name>]` profile to `tunaos.toml`, following an existing
profile's validated family schema. Run `python3 scripts/config.py validate`
and `python3 scripts/config.py generate`. The latter creates the desktop
manifest. Adding a profile does not implement a Containerfile route or qualify
the new desktop; the next steps are framework development.

### 2. Add a stage in each Containerfile you need

In `Containerfile.el10` (and others if supporting multiple distros):

```dockerfile
FROM base-no-de AS myde
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/desktop/install-desktop.sh myde
RUN rm -rf /opt && ln -s /var/opt /opt
```

### 3. Register in the build matrix

In `tunaos.toml`, append a flavor table under your variant:

```toml
[[variants.yellowfin.flavors]]
id = "myde"
stage = 2
build_image = true
build_iso = true
```

Also update flavor routing and tests where required. A declared name is not
a supported route until the build and runtime contracts accept it.

---

## Going Deeper: Adding a Distro Variant

To build on a new base OS:

### 1. Find or build a bootc-compatible base image

The base image must have `bootc` installed. For existing distros, check if
a bootc image exists. For new ones, you'll need to build one (follow the
pattern in `Containerfile.ubuntu` or `Containerfile.debian`).

### 2. Add detection to the build library

In `build_scripts/lib.sh`, add OS detection and package-manager wiring:

```bash
# In the OS detection section, next to the existing BASE_IMAGE checks:
[[ "${BASE_IMAGE,,}" == *"myos"* ]] && IS_MYOS=true && _derive_name "myvariant" "MyVariant"

# In the package-manager section:
if [[ "$IS_MYOS" == true ]]; then
    PKG_MGR="my-pkg-mgr"
fi
```

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

### 4. Extend the native package contract

A new package-manager key is not accepted automatically. Extend the schema,
generator and installer contract with tests, then add the matching primary
TOML policy. Reuse a supported family when its actual behavior matches.

### 5. Add build commands to the Justfile

```just
build-myvariant flavor='gnome' *args: (build "myvariant" flavor +args)
```

---

## Running Your Own CI/CD

Once you have validated the primary config and tested the affected images,
review the publication workflow and permissions before pushing to your fork:

### What's already wired up

| File | What it does |
|---|---|
| `.github/workflows/build-variant.yml` | Reads `.github/build-config.yml`, generates a matrix of builds, runs the 4-stage DAG |
| `.github/workflows/reusable-build-image.yml` | Per-image build → push to the resolved destination → cosign sign → QEMU boot gate |
| `.github/workflows/reusable-build-artifacts.yml` | ISO and QCOW2 generation |

Destination fields resolve independently: `IMAGE_REGISTRY` /
`REPO_ORGANIZATION` environment overrides, then `[build.publish]`, then the
GitHub repository owner for namespace, then `ghcr.io` / `tuna-os` defaults.
Use `scripts/publish-destination.sh` to inspect the result. Resolution is not
authorization to push; see the credential boundary in step 6.

### What you may need to set up

- **CI permissions:** the publishing workflow signs keylessly with GitHub
  Actions OIDC (`id-token: write`); it does not need a project signing key.
  Registry write access and workflow permissions must also be enabled. A fork
  has its own signing identity; do not verify it with the upstream identity.
  See [artifact verification](VERIFY-ARTIFACTS.md).
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
├── manifests/desktops/              ← GENERATED FROM tunaos.toml; DO NOT EDIT
│   ├── gnome.yaml                   #   packages, DM, copr repos, version locks
│   ├── gnome-debian.yaml            #   Debian-specific overrides (apt package names)
│   ├── gnome-arch.yaml              #   Arch-specific overrides (pacman package names)
│   ├── kde.yaml
│   ├── kde-debian.yaml
│   ├── kde-arch.yaml
│   ├── cosmic.yaml
│   ├── niri.yaml
│   └── xfce.yaml
│
├── build_scripts/                   ← FRAMEWORK CODE, NOT CONFIGURATION
│   ├── desktop/install-desktop.sh   #   generic manifest-driven DE installer
│   ├── lib.sh                       #   shared library (OS detect, pkg wrappers)
│   ├── 00-copy-files.sh             #   system_files → image
│   ├── 01-workarounds.sh            #   early patches and workarounds
│   ├── 10-base-packages.sh          #   base OS packages (no DE)
│   ├── 20-packages.sh               #   system-wide packages
│   ├── 26-packages-post.sh          #   post-package cleanup
│   ├── 40-services.sh               #   systemd service enablement
│   ├── 90-image-info.sh             #   image metadata stamping
│   ├── 99-cleanup.sh                #   final cleanup
│   ├── overlay/                     #   HWE, NVIDIA, CachyOS, Asahi, T2 overlays
│   └── ...
│
├── system_files/                    ← EDIT THESE — SYSTEM CONFIG
│   ├── etc/                         #   /etc config files
│   └── usr/                         #   /usr config files
│
├── system_files_overrides/          ← OVERRIDES (applied after system_files)
│   └── ...
│
├── Containerfile.el10               ← FRAMEWORK: MAIN BUILD (EL10/Fedora)
├── Containerfile.overlay            ← HWE/NVIDIA/CachyOS parameterized overlay
├── Containerfile.ubuntu             ← Ubuntu bootcification
├── Containerfile.debian             ← Debian bootcification
├── Containerfile.arch               ← Arch bootcification
├── Containerfile.gentoo             ← Gentoo bootcification
├── Containerfile.opensuse           ← openSUSE bootcification
│
├── custom/                          ← OVERLAY (lighter alternative)
│   ├── image.yaml                   #   base image + tag
│   ├── packages.yaml                #   add/remove packages
│   └── build.pre.sh, build.post.sh  #   hooks; files/, systemd/ etc. are optional
│
├── tunaos.toml                     ← EDIT THIS — PRIMARY BUILD/PACKAGE POLICY
├── .github/workflows/               ← CI PIPELINE
│   ├── build-variant.yml            #   orchestrator (works as-is on forks)
│   ├── reusable-build-image.yml     #   per-image build+push+sign
│   └── reusable-build-artifacts.yml #   ISO/QCOW2 generation
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
brew install just podman shellcheck shfmt yq
gh repo fork tuna-os/tunaos --clone && cd tunaos

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
just verify-disk ./yellowfin.qcow2   # QEMU boot check

# ── Pre-commit (mandatory) ─────────────────────────────────────
just fix && just check
```
