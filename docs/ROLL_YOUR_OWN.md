# Roll Your Own TunaOS

TunaOS is not a distribution — it's a **build factory** that composes
bootable immutable Linux images from a matrix of choices:

```
base OS × desktop × kernel × drivers = image
```

The repo is designed to be forked. The intended workflow is: fork, turn
off the variants and desktops you don't want, edit the manifests in place,
and build your own images. Every shipped desktop manifest and Containerfile
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
gh repo fork tuna-os/tunaos --clone
cd tunaos
```

### 2. Prune: turn off what you don't want

Open `.github/build-config.yml`. This file defines every variant and every
flavor. Remove or comment out everything you don't need.

**Before** — full matrix, ~60 flavors:

```yaml
variants:
  - id: yellowfin
    ...
    flavors:
      - id: base
      - id: gnome
      - id: cosmic
      - id: kde
      - id: niri
      - id: gnome-hwe
      - id: gnome-nvidia
      - id: gnome-nvidia-hwe
      - id: cosmic-hwe
      - id: cosmic-nvidia
      - id: kde-hwe
      - id: kde-nvidia
      - id: niri-hwe
      - id: niri-nvidia
  - id: albacore
    ... (same shape)
  - id: skipjack
    ...
  - id: bonito
    ...
  # ... grouper, marlin, flounder, flounder-sid, sailfin, guppy, bonito-rawhide
```

**After** — one variant, one desktop, optional NVIDIA:

```yaml
variants:
  - id: yellowfin
    emoji: "🐠"
    description: "Based on AlmaLinux Kitten 10"
    base_image: "quay.io/almalinuxorg/almalinux-bootc:10-kitten"
    platforms: ["linux/amd64"]
    flavors:
      - id: base
        stage: 1
        build_image: true
      - id: gnome
        stage: 2
        build_image: true
        build_iso: true
      - id: gnome-nvidia
        stage: 3
        build_image: true
        build_iso: true
```

> **Tip:** Keep `base` — it's a shared stage that every desktop needs.
> Delete the rest. You can always add them back from git history.

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

### 3. Edit: customize the desktop manifests

Open `manifests/desktops/gnome.yaml` (or whichever desktop you kept). Add
and remove packages, change group installs, add COPR repos. See [Common
Customizations](#common-customizations-edit-in-place) below for recipes.

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

Push to your fork. The CI workflows in `.github/workflows/` are already
parameterized to push to `ghcr.io/<your-username>/...`. Commit, push, and
your images build automatically.

---

## Common Customizations (Edit in Place)

All of these are edits to existing files in the repo. No overlays, no
separate directories — you're changing the source of truth.

### Changing packages in a desktop

Edit `manifests/desktops/<de>.yaml`. Each desktop manifest has per-OS
package lists:

```yaml
# manifests/desktops/gnome.yaml — add what you want, remove what you don't
packages:
  fedora:
    packages:
      - gdm
      - gnome-shell
      - gnome-terminal     # ← added
      - nautilus
      - gnome-text-editor   # ← added
      # ... keep the rest ...

  el10:
    packages:
      - gdm
      - gnome-shell
      - gnome-terminal     # ← added
      - nautilus
      # ... keep the rest ...
```

To remove a package, delete its line or comment it out. The installer
reads the manifest as the canonical list — whatever's there gets
installed.

> **Which OS key do I edit?** The installer auto-detects:
> - `el10` — AlmaLinux, CentOS Stream, RHEL
> - `fedora` — Fedora, Rawhide
> - `apt` — Ubuntu, Debian
> - `pacman` — Arch Linux, CachyOS
> - `zypper` — openSUSE
> - `emerge` — Gentoo
>
> Edit the key for the variant you kept. Unused keys are skipped.

### System-wide packages and config

Desktop manifests only cover what goes into the DE layer. For packages
that should be in *every* image (base layer), edit
`build_scripts/20-packages.sh`.

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

These are copied into every image by `build_scripts/copy-files.sh` (step
1 of the build). To override a file that upstream already ships, use
`system_files_overrides/` — it's applied after `system_files/`.

### COPR repos, PPAs, and version locks

These go in the desktop manifest under the relevant OS key:

```yaml
# manifests/desktops/gnome.yaml
packages:
  el10:
    copr:
      - repo: someuser/someproject
        packages:
          - package-from-copr
          - another-package
      - repo: jonathanmetz/cosmic-epoch
        packages: []

    optional:
      - fish            # installed if available, skipped if not
      - neovim

    optional_group:     # install all or none (checks first item availability)
      - fcitx5
      - fcitx5-gtk
      - fcitx5-mozc

  apt:
    ppa:
      - repo: ppa:someuser/someproject
        condition: ubuntu        # only on Ubuntu, not Debian

versionlock:
  - gnome-shell
  - mutter
  - "qt6-*"
```

`versionlock` runs `dnf versionlock add` on each pattern. `optional`
packages are best-effort — they won't fail the build if unavailable.

### Changing branding, wallpapers, defaults

The image branding is set by environment variables in the Containerfile:

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

Also available: `custom/files/` (config file overlay), `custom/systemd/`
(units to enable), `custom/build.pre.sh` / `custom/build.post.sh` (hook
scripts), `custom/just/` (custom ujust recipes).

The overlay is good for personal machines and quick experiments. For a
project you intend to maintain and ship to others, the fork-edit-build
workflow is the right path.

---

## Going Deeper: Adding a Desktop

To add a desktop environment that isn't already in the repo:

### 1. Create the manifest

Create `manifests/desktops/<name>.yaml`:

```yaml
# manifests/desktops/myde.yaml
display_manager: lightdm

packages:
  fedora:
    packages:
      - lightdm
      - myde-session
      - myde-panel
      - myde-launcher
      - myde-terminal
      - xdg-desktop-portal-gtk

  el10:
    packages:
      - lightdm
      - myde-session
      - myde-panel

  apt:
    - lightdm
    - myde-session
    - myde-panel

  pacman:
    - lightdm
    - myde-session
    - myde-panel
```

Provide at least the package-manager keys your target variants use. Unused
keys are skipped.

### 2. Add a stage in each Containerfile you need

In `Containerfile.el10` (and others if supporting multiple distros):

```dockerfile
FROM base-no-de AS myde
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/install-desktop.sh myde
RUN rm -rf /opt && ln -s /var/opt /opt
```

### 3. Register in the build matrix

In `.github/build-config.yml`, under your variant:

```yaml
- id: myde
  stage: 2
  build_image: true
  build_iso: true
```

That's it — one YAML file, one Containerfile stage, one matrix entry. No
new shell scripts.

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
# In the OS detection section:
IS_MYOS=false
[[ "${BASE_IMAGE,,}" == *"myos"* ]] && IS_MYOS=true && IMAGE_NAME="myvariant" && IMAGE_PRETTY_NAME="MyVariant"

# In the package-manager section:
if [[ "$IS_MYOS" == true ]]; then
    PKG_MGR="my-pkg-mgr"
fi
```

### 3. Add the variant to the build matrix

```yaml
# .github/build-config.yml
- id: myvariant
  emoji: "🐟"
  description: "Based on MyOS"
  base_image: "ghcr.io/myorg/myos-bootc:latest"
  platforms: ["linux/amd64"]
  flavors:
    - id: base
      stage: 1
      build_image: true
    - id: gnome
      stage: 2
      build_image: true
      build_iso: true
```

### 4. Add package sections to desktop manifests

```yaml
# manifests/desktops/gnome.yaml — add at the bottom of packages:
  my-pkg-mgr:
    - gnome-shell
    - gnome-session
    - gdm
```

### 5. Add build commands to the Justfile

```just
build-myvariant flavor='gnome' *args: (build "myvariant" flavor +args)
```

---

## Running Your Own CI/CD

Once you've pruned the matrix and customized your manifests, push to your
fork. The existing workflows work out of the box:

### What's already wired up

| File | What it does |
|---|---|
| `.github/workflows/build-variant.yml` | Reads `.github/build-config.yml`, generates a matrix of builds, runs the 4-stage DAG |
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
├── manifests/desktops/              ← EDIT THESE — DESKTOP DEFINITIONS
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
├── build_scripts/                   ← EDIT THESE — BUILD ENGINE
│   ├── install-desktop.sh           #   generic manifest-driven DE installer
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
│   ├── gnome-extensions.sh          #   GNOME extensions compiler
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
├── custom/                          ← OVERLAY (lighter alternative)
│   ├── image.yaml                   #   base image + tag
│   ├── packages.yaml                #   add/remove packages
│   ├── files/                       #   config file overlay
│   └── systemd/                     #   systemd units
│
├── .github/build-config.yml         ← EDIT THIS — BUILD MATRIX
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
just verify-disk disk.qcow2          # QEMU boot check

# ── Pre-commit (mandatory) ─────────────────────────────────────
just fix && just check
```
