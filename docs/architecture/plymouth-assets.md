# Architectural Standards: Plymouth Asset Management, Storage, & Optimization Policy

**Status**: APPROVED (Active Architectural Policy)  
**Tracks**: [#1650](https://github.com/tuna-os/tunaOS/issues/1650) (plymouth PNG frames loader asset cleanup & optimization policy)  
**Owner**: Architecture / Scanner  
**Applies to**: `system_files/usr/share/plymouth/themes/`, CI image build workflows, and branding packages  

---

## 1. Executive Summary

Boot-splash graphics in TunaOS provide visual feedback during early boot via the Plymouth framework. Over successive development cycles, multiple animated Plymouth themes were added to the core repository under `system_files/usr/share/plymouth/themes/`.

### Current Inventory & Problem Statement
- **Repo Bloat**: The themes directory grew to **486 PNG frames totalling ~6.8 MB** across 10 themes (`pufferfish`, `tunaos`, `dragon`, `radioactive`, `shark`, `fishing-pole`, `rainbow`, `rocket`, `sushi`, `tropical-fish`).
- **Clone Penalty**: Plymouth animation frame sequences accounted for roughly **31% of non-git repository content**, forcing every developer and CI job cloning the repository to download multi-megabyte binary blobs for 10 animated themes even though each OS variant only boots with one default theme.
- **Git History Inefficiency**: Multi-frame sequences (e.g., 72 frames in `fishing-pole`, 84 frames in `pufferfish`) cannot be meaningfully reviewed via git diffs. Any revision to an animation curve permanently commits dozens of replacement PNG binary blobs into git history.

This document establishes architectural standards, distribution boundaries, build-time generation rules, and size gates for Plymouth assets in TunaOS.

---

## 2. Core Architectural Principles

1. **Separation of Shipped Default vs. Optional Branding**: The core OS image repository must only vendor the default boot theme required for active OS builds. Secondary or alternative cosmetic themes belong in external release artifacts or the `branding` repository.
2. **Source-First Authoring**: Visual assets must be authored and stored as vector source formats (SVG, procedural animation scripts, or high-level sprite definitions) rather than committed collections of discrete PNG frames.
3. **Build-Time Frame Generation or Artifact Pull**: Where frame sequences are necessary for Plymouth rendering, frames must either be generated deterministically at image build time or pulled from pinned release tarballs.
4. **Strict Size & Resolution Budgets**: Every splash asset included in a build must conform to lossless compression standards, resolution limits, and byte budgets enforced by CI gates.

---

## 3. Repository Boundary & Theme Distribution Policy

### 3.1 Shipped Default vs. Optional Themes

| Theme Category | Location / Distribution Mechanism | Criteria / Rules |
|---|---|---|
| **Default Theme** (`tunaos`) | `system_files/usr/share/plymouth/themes/tunaos/` | Shipped with base OS image; strictly bounded size budget; optimized assets. |
| **Minimal Fallback** (`default.plymouth`) | Symlink to active default theme | Guarantees bootloader and Plymouth fallback integrity. |
| **Optional / Themed Variants** (`dragon`, `shark`, `pufferfish`, `rainbow`, etc.) | `branding` repository / OCI release tarballs / extra packages | Decoupled from core git history; installed on-demand or during tailored flavor builds. |

### 3.2 In-Tree File Contract

For any theme residing in `system_files/usr/share/plymouth/themes/<theme-name>/`, the directory must strictly contain:
1. `<theme-name>.plymouth`: The Plymouth theme descriptor file.
2. `<theme-name>.script` (or `.so` plugin configuration): Plymouth rendering script.
3. Vector source files (`*.svg`) or minimal optimized background assets.
4. Generator scripts (`generate-frames.sh` or build integration) if frames are procedurally derived.

Committed collections of raw `frame-001.png` ... `frame-080.png` git blobs are **prohibited** from the core repository working tree.

---

## 4. Asset Generation & Build Pipeline Integration

### 4.1 Procedural Frame Generation (Preferred)
When animation frames are required by a Plymouth script plugin:
- Source vectors (`animation.svg` or layered SVG components) must be committed to the repository.
- During container image construction (or via a dedicated `just generate-plymouth-frames` recipe), build tooling (`rsvg-convert`, `inkscape`, or ImageMagick) rasterizes the frames into the build target:
  ```bash
  # Example build-time rasterization pattern
  rsvg-convert -w 1920 -h 1080 animation-frame.svg -o /usr/share/plymouth/themes/tunaos/frame-001.png
  ```
- Output frame directories must be listed in `.gitignore`.

### 4.2 Release Artifact Fetching (Alternative)
For complex pre-rendered animations where procedural build-time rasterization is too resource-intensive:
- Pre-baked frame archives must be published as versioned release assets in the `branding` repository or GHCR package registry.
- Image build recipes fetch and extract the pinned tarball at build time:
  ```bash
  curl -fsSL "https://github.com/tuna-os/branding/releases/download/v1.0.0/plymouth-theme-tunaos.tar.gz" \
    | tar -xz -C /usr/share/plymouth/themes/
  ```

---

## 5. Optimization Standards & Size Budgets

### 5.1 Static Image Optimization
All static splash images (e.g. watermark logos, single-frame backgrounds like `sushi` and `tropical-fish`) must undergo lossless PNG optimization prior to merging:
- **Optimization Tools**: Run `oxipng -o max --strip all` or `pngquant` + `optipng -o7`.
- **Color Depth**: Use 8-bit indexed PNG where full 24/32-bit RGBA is visually indistinguishable.
- **Resolution**: Static splash background images must not exceed 1920×1080 (1080p) or 2560×1440 for HiDPI targets.

### 5.2 Size Budgets

| Asset Scope | Maximum Allowed Size Budget | Enforcement Gate |
|---|---|---|
| Single Static Splash Image | ≤ 80 KB | PR Quality Gate |
| Default Theme Total Footprint | ≤ 500 KB | CI Build Check |
| Entire Themes Directory in Core Repo | ≤ 1.5 MB | Repository Size Gate |

---

## 6. Verification and CI Enforcement

1. **Size Ceiling Assertion**: A CI check verifies that `system_files/usr/share/plymouth/themes/` does not exceed the 1.5 MB repository ceiling and flags any committed PNG frame sequences > 10 frames.
2. **Format Inspection**: Pre-commit / CI verification ensures all committed PNGs are optimized and stripped of non-essential metadata chunks (`eXIf`, `tIME`, `tEXt`).
3. **Boot Gate Testing**: The QEMU / `corral` / `iso-e2e.sh` boot verification pipeline validates that the active theme initializes correctly without missing asset warnings in `/var/log/boot.log`.
