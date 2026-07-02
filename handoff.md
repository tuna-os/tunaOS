# TunaOS Handoff Document

> **Generated:** 2026-07-02  
> **Branch / HEAD:** `main` @ `46fd181`

---

## 1. Current State of `main`

The `fix/daily-verify-yq-retry` feature branch has been **merged into `main`** and pushed. All work described here is on `main`.

### Recent commits (newest first)

| SHA | Description |
|-----|-------------|
| `46fd181` | merge: pull main into fix/daily-verify-yq-retry and resolve conflicts |
| `7fb60aa` | fix: tune DNF configuration on all RHEL-family OS variants for faster downloads |
| `e8ef8b5` | docs: add installer screenshot guides for GNOME and Cosmic |
| `87f09c8` | fix: disable cache mounts for grouper variant to avoid composefs bind-mount conflicts |
| `90d1213` | fix: disable SELinux in builder VM template |
| `7bfa40f` | fix: correct exit status capture in dnf_retry |
| `51a693a` | fix: mask systemd suspend/hibernate targets in walkthroughs |
| `ea4c446` | fix: include dmsquash-live in bootc initramfs so live ISO boots correctly |

---

## 2. Build VM Status

All four build VMs are running on the `karnataka` node (kubevirt/corral-vms namespace). Each has a completed `base` image.

| VM | Variant | Base OS | Image | Size | Status |
|----|---------|---------|-------|------|--------|
| `yellowfin-vm` | yellowfin | AlmaLinux Kitten 10 | `localhost/yellowfin:base` (`7dbdb1a`) | 4.99 GB | ✅ Built |
| `bonito-vm` | bonito | Fedora CoreOS (HWE kernel) | `localhost/bonito:base` (`dc7fa03`) | 5.78 GB | ✅ Built |
| `grouper-vm` | grouper | Ubuntu 26.04 (composefs) | `localhost/grouper:base` (`8b896f8`) | 2.73 GB | ✅ Built |
| `skipjack-vm` | skipjack | CentOS Stream 10 | `localhost/skipjack:base` (`5b270eb`) | 5.21 GB | ✅ Built |

### SSH access
```bash
corral ssh yellowfin-vm -u fedora
corral ssh bonito-vm    -u fedora
corral ssh grouper-vm   -u fedora
corral ssh skipjack-vm  -u fedora
```

Build logs on each VM: `/data/tunaos/build.log`

---

## 3. Key Fixes Landed This Session

### 3.1 DNF Performance on CentOS/RHEL/AlmaLinux (`build_scripts/00-workarounds.sh`)

CentOS Stream 10 package downloads on `skipjack-vm` were extremely slow (~8 kB/s) because DNF parallel downloads were only configured for Fedora. Extended the config to all RHEL-family variants:

```bash
max_parallel_downloads=10
fastestmirror=1
retries=5
timeout=30
```

### 3.2 Grouper Cache Mount Bypass (`scripts/setup-build-cache.sh`)

The `grouper` (Ubuntu/composefs) build fails when RPM/DNF cache directories are bind-mounted into `/var/cache/dnf` during the `mount-system.sh` composefs bootcification phase — that script wipes `/var` and errors out with "Device or resource busy". Added an early exit for `grouper` to skip all cache volume mounts.

### 3.3 Justfile Merge Conflict Resolution

The `build` and `_build` recipes had a 3-way conflict between our `enable_sshd` branch parameter and `main`'s `is_ci_build`/`enable_sshd_build` parameter names. **Resolved** by adopting the `main` naming convention (`is_ci_build`, `enable_sshd_build`) uniformly. The duplicate `ENABLE_SSHD` build-arg that was referencing the removed old parameter was also cleaned up.

---

## 4. Installer Screenshots (`docs/INSTALLER_SCREENSHOTS.md`)

Added installer screenshot documentation at [`docs/INSTALLER_SCREENSHOTS.md`](docs/INSTALLER_SCREENSHOTS.md) with carousels for both GNOME and Cosmic installer walkthroughs.

> **⚠️ Known Issue — Screenshots are not real**: The images in `docs/images/installer/` were **AI-generated placeholders**. They do not show the actual TunaOS installer. Real screenshots need to be captured by running the `scripts/run-walkthrough.sh` script against actual built ISOs.
>
> The walkthrough script (`scripts/run-walkthrough.sh`) boots each ISO under QEMU, drives the `bootc-install` GUI with keystrokes, and screendumps via the QEMU monitor socket. To regenerate real screenshots:
>
> ```bash
> # 1. Build the ISO first (requires a built desktop-flavor image on the VM)
> corral ssh skipjack-vm -u fedora -c 'cd /data/tunaos && just iso skipjack gnome'
>
> # 2. Copy the ISO to a host with QEMU/OVMF
> # 3. Run the walkthrough automation
> bash scripts/run-walkthrough.sh /path/to/skipjack-gnome.iso ./walkthrough-out
>
> # 4. Copy the PNG results to docs/images/installer/
> cp walkthrough-out/*.png docs/images/installer/
> ```
>
> Repeat for each desktop environment (gnome, kde, cosmic, niri).

---

## 5. Architecture Notes — Variant Overview

| Variant | Base OS | Backend | Target Audience | Status |
|---------|---------|---------|-----------------|--------|
| **yellowfin** | AlmaLinux Kitten 10 | ostree | Enterprise/stable desktop | ✅ Active |
| **albacore** | AlmaLinux 10 (stable) | ostree | Conservative enterprise | ✅ Active |
| **skipjack** | CentOS Stream 10 | ostree | Upstream EL preview | ✅ Active |
| **bonito** | Fedora CoreOS | ostree | HWE/gaming focus | ✅ Active |
| **grouper** | Ubuntu 26.04 Noble | **composefs** | Debian/Ubuntu ecosystem | 🔧 Re-enabled |

### Grouper (composefs) notes
- Uses `Containerfile.ubuntu` with a completely different package manager and base image
- `scripts/setup-build-cache.sh` skips bind-mount caches for grouper (see §3.2)
- `build_scripts/bootc/mount-system.sh` wipes `/var` during composefs bootcification — any bind-mounts under `/var` at build time will fail
- Reference for grouper's composefs setup: [projectbluefin/dakota-iso](https://github.com/projectbluefin/dakota-iso)

### Future variants (planned)
- **Arch-derived** image (no timeline yet)
- **Tromso / Dakota** (buildstream-derived, from hanthor project)
- **XFCE on Wayland** variant was started but not completed — `build_scripts/xfce.sh` exists but is not wired into the build matrix

---

## 6. Desktop Flavors

Each variant can be built as multiple desktop flavors. The ISO groups are:

| ISO Group suffix | Desktops included |
|------------------|-------------------|
| *(none)* — flagship | `gnome`, `gnome50`, `gnome-hwe`, `gnome50-hwe` |
| `-community` | `kde`, `kde-hwe`, `cosmic`, `cosmic-hwe`, `niri`, `niri-hwe` |
| `-nvidia` | `gnome-nvidia`, `gnome50-nvidia`, `gnome-nvidia-hwe` |

Live ISO sessions use autologin (`liveuser` account) configured per-desktop in `live-iso/common/src/desktop-{gnome,kde,cosmic,niri}.sh`.

---

## 7. Open Tasks / Known Issues

### High Priority

- [ ] **Real installer screenshots** — See §4. The current docs have AI-generated placeholders. Need to run `scripts/run-walkthrough.sh` per desktop and replace images in `docs/images/installer/`.
- [x] **Skipjack gnome/cosmic/kde flavor builds** — All three built on `skipjack-vm`. Note: `podman system prune -af` during chunkah aggressively prunes intermediate images; rebuild before ISO step.
- [x] **Skipjack ISOs (gnome, cosmic, kde)** — All three ISOs built and QEMU-verified:
  - `skipjack-gnome-10-x86_64.iso` (3.9 GB)
  - `skipjack-cosmic-10-x86_64.iso` (2.9 GB)
  - `skipjack-kde-10-x86_64.iso` (4.0 GB)
- [x] **Debug kernel initramfs workaround** — CentOS Stream 10 ships a `+debug` kernel with no initramfs. Tacklebox picks the debug kernel first (alphabetically) and fails. Fixed by running `dracut --force --reproducible --no-hostonly` for the debug kernel inside the image before ISO build.

### Medium Priority

- [ ] **Grouper stage-2 builds** — grouper `base` is built, but no desktop flavors. The composefs pipeline is different — test gnome flavor carefully.
- [x] **XFCE variant** — wired into `build-config.yml` for all five variants (xfce stage added to `Containerfile`/`Containerfile.ubuntu`, apt branch implemented in `xfce.sh`, DM install added on EL10, flavor→desktop mapping in `scripts/lib/common.sh` + `build-iso-tacklebox.sh`).
- [ ] **Arch-derived variant** — No implementation yet. Discussed as a future direction.
- [ ] **Tromso / Dakota integration** — Reference: `hanthor/tromso` and `hanthor/dakota` projects.
- [ ] **Tacklebox container image rootless issue** — The containerized tacklebox fails on `podman unshare` when run as root, requiring `TACKLEBOX_FROM_SOURCE=1` to build from source on the host. Root cause: `podman unshare` only works in rootless mode, but tacklebox container runs privileged. Should be fixed in tacklebox or worked around in `scripts/lib/common.sh`.

### Low Priority / Informational

- [ ] **Ubuntu/Debian bootc reference** — See [bootc-shindig/ubuntu-bootc-remix](https://github.com/bootc-shindig/ubuntu-bootc-remix) and [bootc-shindig/bootc-deb](https://github.com/bootc-shindig/bootc-deb) for grouper reference implementation patterns.
- [ ] **Daily verify workflow** — The `fix/daily-verify-yq-retry` branch was addressing a yq retry issue in the CI verify workflow. Verify that the daily-verify workflow now passes cleanly on `main`.

---

## 8. Build Commands Quick Reference

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

### On a corral VM
```bash
corral ssh skipjack-vm -u fedora -c 'cd /data/tunaos && TMPDIR=/data/tmp just build skipjack base'
```

---

## 9. File Map for Key Changes

| File | What changed |
|------|-------------|
| [`Justfile`](Justfile) | Merged conflicts; unified `_build` / `build` recipe parameter names (`is_ci_build`, `enable_sshd_build`) |
| [`build_scripts/00-workarounds.sh`](build_scripts/00-workarounds.sh) | DNF perf tuning extended to all RHEL-family variants (CentOS/RHEL/AlmaLinux) |
| [`build_scripts/40-services.sh`](build_scripts/40-services.sh) | Merge conflict resolved; preserves liveuser and sshd config |
| [`scripts/setup-build-cache.sh`](scripts/setup-build-cache.sh) | Added bypass for grouper to skip cache bind-mounts |
| [`docs/INSTALLER_SCREENSHOTS.md`](docs/INSTALLER_SCREENSHOTS.md) | New — installer walkthrough guide (placeholder images, see §4) |
| [`docs/README.md`](docs/README.md) | Added link to INSTALLER_SCREENSHOTS.md |
| [`docs/images/installer/`](docs/images/installer/) | 13 installer screenshot images (currently AI-generated placeholders — replace with real ones) |

---

## 10. Useful References

| Resource | URL |
|----------|-----|
| bootc docs | https://containers.github.io/bootc/ |
| Ubuntu bootc reference | https://github.com/bootc-shindig/ubuntu-bootc-remix |
| bootc-deb (Debian/Ubuntu bootc) | https://github.com/bootc-shindig/bootc-deb |
| composefs ISO reference | https://github.com/projectbluefin/dakota-iso |
| tacklebox (ISO builder) | https://github.com/tuna-os/tacklebox |
| Agent guide | [`docs/AGENT_GUIDE.md`](docs/AGENT_GUIDE.md) |
