# Handoff — 2026-07-03

## Active goals

### 1. github-copr XFCE Wayland stack (28 packages)
**Status**: Iterating through tiered build failures. 3 of 9 tiers now pass.

- ✅ Tier 0: `xfce4-dev-tools` (build tools)
- ✅ Tier 1: `gtk-layer-shell`
- ✅ Tier 2 (core-libs): `libxfce4util` + `xfconf`
- 🔄 Tier 3 (ui-libs): `libxfce4ui`, `garcon`, `libxfce4windowing` — just pushed fixes for missing BuildRequires (`libSM-devel`, `gtk-doc`, X11/wnck/display-info deps). **v12 running now** (run 28674958876).
- ⏳ Tiers 4–8: desktop-core, compositor (xfwl4), apps, panel-plugins, meta — unreached yet.

**Key fixes applied per spec**:
| Package | Issues fixed |
|---|---|
| `xfconf` | meson migration (was autotools), header path `xfce4/xfconf-0/xfconf/`, `%find_lang`, GIO module, bash-completion |
| `libxfce4util` | autoreconf EL10 nm-parsing, removed phantom `%{version}` libdir, GI typelib/GIR are `Libxfce4util-1.0.*` (capital L), `%find_lang`, vala vapi, gtk-doc, kiosk-query binary |
| `xfce4-dev-tools` | `%files` verified against real tarball, added autoreconf + meson/ninja |
| `gtk-layer-shell` | devel subpackage, license file names, `%files` |
| Commit-pin Source0s | 5 specs had whitespace-sensitive gitlab-archive URL replacement failures |

**Repo**: `tuna-os/github-copr` main branch
**Dispatch**: `gh workflow run build-xfce-distributed.yml`

### 2. grouper (Ubuntu 26.04) full parity
**Status**: All 4 desktop builds pass (gnome, kde, niri, xfce ✅). Boot gate fix for the `bootupd` blocker just implemented, not yet CI-validated.

- Base `10-base-packages.sh` apt path: fdisk added (Debian splits it from util-linux), plasma-workspace-wayland removed (nonexistent), bootupd reverted (not an apt package).
- `build_scripts/kde.sh`: removed `plasma-workspace-wayland` from apt install.
- **Root cause**: `bootc install to-disk` defaults to the ostree backend, which always shells out to `bootupd` for bootloader management — but `bootupd` isn't packaged for Ubuntu apt.
- **Fix applied** (mirrors `bootc-shindig`/`bootcrew/mono`'s `ubuntu-bootc` reference, which also ships systemd-boot + no bootupd): per bootc docs (bootloaders.md, experimental-composefs.md), if `bootupd` is absent from the image, bootc falls back to systemd-boot — but only under the composefs-native storage backend (`--composefs-backend`), which is a different thing from the `[composefs] enabled = yes` ostree-composefs mode our image already sets in `prepare-root.conf`. Changes:
  - `build_scripts/10-base-packages.sh`: added `systemd-boot` apt package (provides `bootctl` + EFI binaries) to the apt base-packages list.
  - `scripts/iso-e2e.sh`, `scripts/build-qcow2.sh`, `Justfile` (`qcow2` recipe): all three `bootc install to-disk` call sites now pass `--composefs-backend` conditionally when the variant is `grouper`. RPM variants (bluefin/aurora-style, which do have bootupd) are untouched.
- **Untested risk**: `--composefs-backend` is explicitly documented as experimental/"not as heavily tested"; the "sealed image" docs mention UKI generation as part of the *build-time* pattern, but the plain `--composefs-backend` install flag is documented separately as usable "apart from sealed images" — unclear if bootc auto-generates an unsigned UKI at install time or if we'll need to add a UKI-build step (`ukify`) to `finalize.sh`. **Next step: dispatch a grouper build and watch the boot gate log for what it actually complains about.**

**Last grouper re-dispatch**: run 28674971576 (reverted bootupd, tracking S2 builds) — superseded by the composefs-backend fix above, not yet re-dispatched.

## Other repos

### tuna-os/corral
- PRs #74 (auto-backend QEMU/KubeVirt + boot gate), #76 (5 KubeVirt builder fixes), #78 (CI boot-gate docs) — all merged.
- Registry pull-through cache deployed on karnataka cluster.

### tuna-os/tacklebox
- PR #87 merged — single-context execution, kernel selection, serial kargs.
- TunaOS pin bumped to e3625d51 (PR #583 merged).

### tuna-os/docs
- Build Matrix page merged (#57).
- PipelineBand component in `src/pages/index.tsx` — uncommitted (+81 lines). Adds Tacklebox/Corral/github-copr/Zirconium section + Bluefin/Aurora foundation note. **Needs committing + CSS**.
- Installer walkthrough filmstrip + Grouper landing page merged (#56).
- Many open Hive-generated content PRs (#27–#54).

### tuna-os/debian-copr
- Remote exists at `tuna-os/debian-copr` — scaffolded with xfwl4 package + reprepro + CI workflows.
- **Not cloned locally**. Needs GPG_PRIVATE_KEY secret and build validation.

## CI pipeline improvements (all merged)
- Testing-tag → boot-gate → promotion model (Bluefin-style)
- Buildah native layer cache (`ghcr.io/tuna-os/tunaos-buildcache`)
- `BUILD_SCRIPTS_HASH` cache-invalidation fix (scripts edits now bust the cache)
- `SHA_HEAD_SHORT` late-bind (doesn't bust layer cache per-commit)
- QEMU boot gates for images + ISOs, screenshot-sanity fallback
- Installer captures published to R2 for website filmstrip
- SBOM OOM caps, rechunk verification, build telemetry

## Key files
- `build_scripts/10-base-packages.sh` — base packages per distro (apt/dnf paths)
- `build_scripts/xfce.sh`, `kde.sh` — desktop flavor install scripts
- `.github/build-config.yml` — variant × desktop matrix, xfce entries commented out for EL10
- `Containerfile`, `Containerfile.ubuntu` — build stages
- `Justfile` — `just boot-gate`, `just verify-disk`, `just qcow2`
- `docs/PIPELINE.md` — full pipeline reference
