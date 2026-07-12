# Roll Your Own TunaOS

TunaOS is not a distribution — it's a **build factory** that composes
bootable immutable Linux images from a matrix of choices:

```
base OS × desktop × kernel × drivers = image
```

The same factory that produces the official `yellowfin:gnome-nvidia` image
can produce *your* image — with your package selection, your config files,
your wallpaper, your CI pipeline. This guide walks through every
customization level, from a 5-minute overlay to a full fork with your own
desktop environments and distro variants.

---

## Table of Contents

1. [Quickest Path: the `custom/` Overlay](#quickest-path-the-custom-overlay)
2. [Customization Recipes](#customization-recipes)
   - [Adding and removing packages](#adding-and-removing-packages)
   - [Overlaying custom config files](#overlaying-custom-config-files)
   - [Running scripts at build time](#running-scripts-at-build-time)
   - [Adding systemd services](#adding-systemd-services)
   - [Switching the base image](#switching-the-base-image)
   - [Changing branding and wallpapers](#changing-branding-and-wallpapers)
3. [Going Deeper: Patching a Desktop Manifest](#going-deeper-patching-a-desktop-manifest)
4. [Going Deeper: Adding a New Desktop Environment](#going-deeper-adding-a-new-desktop-environment)
5. [Going Deeper: Adding a New Distro Variant](#going-deeper-adding-a-new-distro-variant)
6. [Setting Up Your Own CI/CD](#setting-up-your-own-cicd)
7. [Reference: Directory Map](#reference-directory-map)

---

## Quickest Path: the `custom/` Overlay

You can build a fully personalized immutable OS in under five minutes
**without touching a single line of TunaOS source**. The `custom/`
directory is a self-contained overlay system that layers your changes on
top of any published TunaOS image.

### What you get

- Add/remove packages (any package manager: dnf, apt, pacman, zypper, emerge)
- Override any config file in `/etc`, `/usr`, etc.
- Add systemd services
- Run arbitrary shell scripts at build time
- Switch the base image (e.g. build on Fedora instead of AlmaLinux)
- All in one directory — `custom/`

### Step 1: Fork and clone

```bash
gh repo fork tuna-os/tunaos --clone
cd tunaos
```

### Step 2: Edit your config

Open `custom/image.yaml`:

```yaml
# custom/image.yaml
base: ghcr.io/tuna-os/yellowfin:gnome   # the image you're layering on
tag: my-custom-os                        # what to name your image
publish: false                           # set to true when you set up CI
```

Choose your base from any published flavor:

| If you want... | Use |
|---|---|
| Latest GNOME on AlmaLinux | `ghcr.io/tuna-os/yellowfin:gnome` |
| KDE Plasma on Fedora | `ghcr.io/tuna-os/bonito:kde` |
| Arch Linux with GNOME | `ghcr.io/tuna-os/marlin:gnome` |
| Rolling GNOME on Debian Sid | `ghcr.io/tuna-os/flounder-sid:gnome` |
| NVIDIA drivers on AlmaLinux | `ghcr.io/tuna-os/yellowfin:gnome-nvidia` |

> See [ghcr.io/tuna-os](https://github.com/orgs/tuna-os/packages) for the
> full list of published images.

### Step 3: Add your packages

Edit `custom/packages.yaml`:

```yaml
# custom/packages.yaml — add packages for your chosen base OS's package manager
dnf:
  - neovim
  - btop
  - syncthing
  # remove packages by prefixing with a minus
  - "-gnome-tour"          # remove the welcome tour
  - "-firefox"             # remove the default browser
```

The `apt` / `pacman` / `zypper` / `emerge` keys work the same way — the
build system auto-detects the base image's package manager.

### Step 4: Add your config files

Drop files into `custom/files/` mirroring the target filesystem:

```
custom/files/
└── etc/
    └── dconf/
        └── profile/
            └── user          # your dconf defaults
```

Anything you place here overwrites the corresponding file in the image.

### Step 5: Build

```bash
just build-custom
```

This builds a local container image tagged `localhost/my-custom-os`. To
test it as a VM:

```bash
just run-custom-vm
```

That's it. You have your own immutable OS, built from a published TunaOS
image plus your overlay.

---

## Customization Recipes

### Adding and removing packages

Edit `custom/packages.yaml`. The key names (`dnf`, `apt`, `pacman`,
`zypper`, `emerge`) match `PKG_MGR` in the build library. The build
auto-detects which key to use from the base image.

```yaml
# custom/packages.yaml

dnf:
  - neovim
  - btop
  - syncthing

# Enable COPR repos (dnf only)
copr:
  - yselkowitz/wlroots-epel
  - jonathanmetz/cosmic-epoch
```

Package removal (prefix with `-`) runs `dnf remove` / `apt purge` etc.
before installing the new packages, so a package you remove cannot pull
itself back in as a dependency later.

### Overlaying custom config files

The `custom/files/` directory is copied over the image root:

```
custom/files/
├── etc/
│   ├── dconf/
│   │   └── profile/
│   │       └── user
│   └── environment              # set global env vars
└── usr/
    └── share/
        └── backgrounds/
            └── my-wallpaper.png
```

Existing files with the same path are overwritten. Directories are merged
(cp `-aT`).

### Running scripts at build time

Two hook scripts run at build time:

| Script | When it runs |
|---|---|
| `custom/build.pre.sh` | Before any packages are installed or files copied |
| `custom/build.post.sh` | After all packages, files, and systemd units are applied |

```bash
#!/usr/bin/env bash
# custom/build.pre.sh — runs inside the container before anything else
set -euo pipefail
source /run/context/build_scripts/lib.sh

# Install a COPR repo the long way
dnf copr enable -y someuser/someproject

# Fetch a binary from the internet
curl -fsSL https://example.com/tool -o /usr/local/bin/tool
chmod +x /usr/local/bin/tool
```

The TunaOS build library (`lib.sh`) is available — `pkg_install`,
`install_available`, `dnf_retry`, and all `IS_*` flags work.

### Adding systemd services

Drop units into `custom/systemd/`. They're copied to
`/etc/systemd/system/` and enabled:

```
custom/systemd/
└── myservice.service
```

```ini
# custom/systemd/myservice.service
[Unit]
Description=My Custom Service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/my-script.sh

[Install]
WantedBy=multi-user.target
```

### Switching the base image

Change one line in `custom/image.yaml` to rebase on a different variant:

```yaml
# Build on Fedora 44 instead of Almalinux
base: ghcr.io/tuna-os/bonito:gnome
```

You can also rebase on a non-TunaOS bootc image — any OCI image with
`bootc` installed works as a base.

### Changing branding and wallpapers

Place files in `custom/files/` and set your preferred defaults:

```
custom/files/
└── usr/
    └── share/
        ├── backgrounds/
        │   └── my-wallpaper.png
        └── glib-2.0/
            └── schemas/
                └── 99_my_custom_defaults.gschema.override
```

Then in `custom/build.post.sh`, compile the schemas:

```bash
#!/usr/bin/env bash
glib-compile-schemas /usr/share/glib-2.0/schemas
```

---

## Going Deeper: Patching a Desktop Manifest

Sometimes you want to change what goes into the desktop itself — not just
layer on top. Desktop manifests live at `manifests/desktops/<name>.yaml`.

For example, to swap GNOME's default terminal from Ptyxis to GNOME
Terminal, edit `manifests/desktops/gnome.yaml`:

```yaml
# find the packages section for your target OS...
  el10:
    packages:
      - gnome-terminal    # add this
      # - ptyxis          # remove this (comment out, don't delete —
      #                     you might want it back)
```

Then build locally:

```bash
just build yellowfin gnome
```

Manifest fields:

| Field | Purpose |
|---|---|
| `display_manager` | gdm, sddm, greetd, etc. |
| `packages.<os>.packages` | packages to install |
| `packages.<os>.groups` | dnf group install list |
| `packages.<os>.exclude` | packages excluded from groups |
| `packages.<os>.optional` | best-effort (installed if available) |
| `packages.<os>.copr` | COPR repos to enable (EL10/Fedora) |
| `packages.<os>.ppa` | PPAs to add (Ubuntu) |
| `versionlock` | dnf versionlock patterns |
| `disable_desktop_files` | .desktop files to hide |
| `post_install` | scripts to source after install |
| `post_install_inline` | shell commands to eval |

The generic installer `build_scripts/install-desktop.sh` reads all of
these — no new shell script needed.

---

## Going Deeper: Adding a New Desktop Environment

To add a desktop environment that isn't already shipped:

### 1. Create the manifest

Create `manifests/desktops/<name>.yaml`:

```yaml
# manifests/desktops/myde.yaml
display_manager: lightdm

packages:
  dnf:
    packages:
      - lightdm
      - myde-session
      - myde-panel
      - myde-launcher
      - myde-terminal
      - xdg-desktop-portal-gtk

  apt:
    - lightdm
    - myde-session
    - myde-panel

  pacman:
    - lightdm
    - myde-session
    - myde-panel
```

Provide at least the package-manager keys your target variants use (dnf,
apt, pacman, zypper, emerge). Unused keys are harmlessly skipped.

### 2. Add a stage in the Containerfile

In `Containerfile.el10` (and `Containerfile.ubuntu`,
`Containerfile.debian`, etc. if supporting those):

```dockerfile
FROM base-no-de AS myde
RUN --mount=type=tmpfs,dst=/opt --mount=type=tmpfs,dst=/tmp \
  --mount=type=tmpfs,dst=/boot \
  --mount=type=bind,from=context,source=/,target=/run/context \
  /run/context/build_scripts/install-desktop.sh myde
RUN rm -rf /opt && ln -s /var/opt /opt
```

### 3. Register it in the build matrix

In `.github/build-config.yml`, under each variant you want to support:

```yaml
- id: myde
  stage: 2
  build_image: true
  build_iso: true
```

That's it. One YAML file, one Containerfile stage, one matrix entry. No
new shell scripts.

---

## Going Deeper: Adding a New Distro Variant

To build on an entirely new base OS (e.g. NixOS, Void, Chimera Linux):

### 1. Find or build a bootc-compatible base image

The base image must have `bootc` installed and working. For existing
distributions, check if a bootc image exists. For new ones, you'll need
to build one.

### 2. Add detection to the build library

In `build_scripts/lib.sh`, add detection for your OS:

```bash
IS_MYOS=false
[[ "${BASE_IMAGE,,}" == *"myos"* ]] && IS_MYOS=true && IMAGE_NAME="myvariant" && IMAGE_PRETTY_NAME="MyVariant"
```

And wire up the package manager:

```bash
if [[ "$IS_MYOS" == true ]]; then
    PKG_MGR="my-pkg-mgr"
fi
```

### 3. Add the variant to the build matrix

In `.github/build-config.yml`:

```yaml
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

In each desktop manifest you want to support, add your pkg-mgr key:

```yaml
# manifests/desktops/gnome.yaml (add at the bottom of packages:)
  my-pkg-mgr:
    - gnome-shell
    - gnome-session
    - gdm
```

### 5. (Optional) Create a Containerfile

If your base image isn't already bootc-compatible, create
`Containerfile.myvariant` to bootcify it — follow the pattern in
`Containerfile.ubuntu` or `Containerfile.debian`.

Add build recipes to the Justfile:

```just
build-myvariant flavor='gnome' *args: (build "myvariant" flavor +args)
```

---

## Setting Up Your Own CI/CD

The TunaOS CI pipeline is public and reusable. To run your own automated
builds that push to your registry:

### 1. Set up GitHub Container Registry

No setup needed — GHCR is available to every repo.

### 2. Copy the workflow files

The critical files:

| File | Role |
|---|---|
| `.github/workflows/build-variant.yml` | Orchestrator — reads build-config, generates matrix, runs DAG |
| `.github/workflows/reusable-build-image.yml` | Per-image build + push + sign + boot-gate |
| `.github/workflows/reusable-build-artifacts.yml` | ISO/QCOW2 generation |
| `.github/build-config.yml` | Your build matrix |

The workflows are already parameterized — they reference
`${{ github.repository_owner }}` for the registry. Fork and they work.

### 3. Prune the matrix to what you care about

Edit `.github/build-config.yml` — remove variants and flavors you don't
want, add the ones you do. CI only builds what's listed.

### 4. Set repository secrets

For signing (cosign) and optional features:

- `COSIGN_PRIVATE_KEY` / `COSIGN_PUBLIC_KEY` — for image signing
- RHSM credentials if you need RHEL repos

### 5. Trigger your first build

Push to main, or dispatch manually:

```
Actions → Build Yellowfin → Run workflow
```

### Build costs

A full build of one variant (all desktops) takes ~45 minutes on GitHub's
free runners. With a warm container registry cache, individual builds drop
to ~15 minutes. Most customization work should be done locally with
`just build` — only push to CI when you're ready to publish.

---

## Reference: Directory Map

```
tunaos/
├── custom/                          ← YOUR OVERLAY (the quickest path)
│   ├── image.yaml                   #   base image + tag + publish flag
│   ├── packages.yaml                #   add/remove packages
│   ├── build.pre.sh                 #   pre-build hook script
│   ├── build.post.sh                #   post-build hook script
│   ├── files/                       #   config file overlay (mirrors /)
│   └── systemd/                     #   systemd units
│
├── manifests/desktops/              ← DESKTOP DEFINITIONS
│   ├── gnome.yaml                   #   package lists, DM, version locks
│   ├── gnome-debian.yaml            #   Debian-specific overrides
│   ├── gnome-arch.yaml              #   Arch-specific overrides
│   ├── kde.yaml
│   ├── cosmic.yaml
│   ├── niri.yaml
│   └── xfce.yaml
│
├── build_scripts/                   ← BUILD ENGINE (shell)
│   ├── install-desktop.sh           #   generic manifest-driven DE installer
│   ├── apply-custom.sh              #   custom/ overlay runner
│   ├── lib.sh                       #   shared library (OS detect, pkg wrappers)
│   ├── HWE.sh                       #   HWE kernel installer
│   ├── nvidia.sh                    #   NVIDIA driver installer
│   ├── cachyos.sh                   #   CachyOS kernel overlay
│   ├── gnome-extensions.sh          #   GNOME extensions compiler
│   └── ...                          #   base packages, cleanup, etc.
│
├── Containerfile.el10               ← MAIN CONTAINERFILE (EL10/Fedora)
├── Containerfile.overlay            ← HWE/NVIDIA/CachyOS parameterized overlay
├── Containerfile.ubuntu             ← Ubuntu bootcification
├── Containerfile.debian             ← Debian bootcification
├── Containerfile.arch               ← Arch Linux bootcification
├── Containerfile.gentoo             ← Gentoo bootcification
├── Containerfile.opensuse           ← openSUSE bootcification
├── Containerfile.custom             ← YOUR custom overlay build
│
├── .github/build-config.yml         ← BUILD MATRIX (variants × flavors × platforms)
├── .github/workflows/               ← CI PIPELINE
│   ├── build-variant.yml            #   orchestrator
│   ├── reusable-build-image.yml     #   per-image build+push+sign
│   └── reusable-build-artifacts.yml #   ISO/QCOW2 generation
│
├── scripts/                         ← TOOL SCRIPTS
│   ├── resolve-flavor.sh            #   flavor → Containerfile, target, flags
│   ├── resolve-image.sh             #   image ref resolver
│   ├── build-image-inner.sh         #   build engine (env-var driven)
│   └── build-qcow2.sh               #   convert container → VM disk
│
└── Justfile                         ← TASK RUNNER
    just build yellowfin gnome       #   build one flavor locally
    just build-custom                #   build your overlay
    just run-custom-vm               #   boot your overlay as a VM
    just qcow2 yellowfin gnome       #   build QCOW2 disk
    just iso yellowfin gnome         #   build ISO
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

# ── Custom overlay ────────────────────────────────────────────
just build-custom                    # build your custom/ overlay
just run-custom-vm                   # boot it as a VM

# ── Testing ────────────────────────────────────────────────────
just test                            # bats + pytest
just qcow2 yellowfin gnome           # produce VM disk
just verify-disk disk.qcow2          # QEMU boot check

# ── Pre-commit (mandatory) ─────────────────────────────────────
just fix && just check
```
