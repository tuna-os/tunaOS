# TunaOS Handoff Document

> **Generated:** 2026-07-02  
> **Branch / HEAD:** `main` @ `2acc89f`

---

## 1. Current State of `main`

The `feat/pipeline-gating-desktop-matrix` branch has been successfully **merged into `main`** and pushed.

### Recent commits (newest first)

| SHA | Description |
|-----|-------------|
| `2acc89f` | merge: resolve merge conflicts with origin/main |
| `6620f52` | feat(zirconium): expand configuration imports from Zirconium image stage |
| `c9d6176` | feat(zirconium): import Zirconium as builder stage and copy config dirs directly from target image |
| `022a5ae` | fix(ci): correct redirect syntax inside test workflow |
| `e81aef7` | feat(installer): update DMS config layout and add matugen generation support |
| `ecff66f` | feat(installer): implement feature-for-feature ports of projectbluefin/bootc-installer for KDE and COSMIC |

---

## 2. Work Accomplished This Session

### 2.1 Native Installer Ports
Created native-framework implementations under the new directory `conductor/` modeled on `projectbluefin/bootc-installer` layouts:
* **KDE Installer Wizard (`conductor/kde-wizard/main.py`)**: Qt-based wizard using PyQt6 implementing disk selection, root password configurations, and background daemon integrations for auto-pairing Bluetooth peripherals and discovering CUPS network printers.
* **COSMIC Desktop Installer (`conductor/cosmic-installer/src/main.rs`)**: Rust/Iced-based setup utility matching the official `libcosmic` desktop specifications.
* **DMS Native Configurator (`conductor/dms-native/shell.qml`)**: QML configurator with Matugen desktop theming integration to dynamically compile wallpaper palette configs directly into Niri colors (`~/.config/niri/colors.kdl`).

### 2.2 Zirconium Configuration Integration
Wired the core user preferences and desktop environment configurations from upstream Zirconium directly into the containerized build steps inside `Containerfile`:
* Added `ghcr.io/zirconium-dev/zirconium` as a build stage.
* Copies terminal overrides, Greetd managers, dms themes, PAM policies, and Chezmoi user initialization services directly from the Zirconium image layer at container-build time.

---

## 3. Build Commands Quick Reference

```bash
# Build a single variant base image (fastest test)
just yellowfin base
just skipjack base
just bonito base
just grouper base     # composefs; skips cache mounts automatically

# Build a desktop flavor (requires base image first)
just build yellowfin gnome

# Build an ISO (tacklebox, not bootc-image-builder)
just iso skipjack gnome

# Format + validate (MANDATORY before every commit)
just fix && just check

# Show all available commands
just --list
```
