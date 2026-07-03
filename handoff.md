# Handoff — 2026-07-03

## Active goals

### 1. github-copr XFCE Wayland stack (28 packages)
**Status**: Iterating through tiered build failures. 3 of 9 tiers confirmed passing; garcon tier-split confirmed working; v15 fix pushed and dispatched, not yet confirmed.

- ✅ Tier 0: `xfce4-dev-tools` (build tools)
- ✅ Tier 1: `gtk-layer-shell`
- ✅ Tier 2 (core-libs): `libxfce4util` + `xfconf`
- 🔄 Tier 3 (ui-libs): `libxfce4ui`, `garcon` (now its own tier `xfce-ui-libs-garcon`), `libxfce4windowing`.
  - v12 (run 28674958876) failed all three. Root causes: (a) meson's `--auto-features=enabled` promotes optional upstream deps to hard requirements — libxfce4ui was missing `startup-notification-devel`, `libgtop2-devel`, `libepoxy-devel`, `libgudev-devel`; libxfce4windowing was missing `gobject-introspection-devel`. (b) garcon's `configure.ac` hard-requires `libxfce4ui-2` (pkgconfig) + `gtk+-3.0` but was building *in parallel* with libxfce4ui in the same manifest tier — fixed by splitting it into a new tier `xfce-ui-libs-garcon` in `build-order-xfce.yml` that runs after `xfce-ui-libs` consolidates. **The workflow YAML is generated — never hand-edit `.github/workflows/build-xfce-distributed.yml`.** Regenerate with: `python3 scripts/generate-distributed-workflow.py build-order-xfce.yml .github/workflows/build-xfce-distributed.yml --name "XFCE Wayland Distributed Build and Publish" --secondary-r2-path ""`.
  - v13 (commit b4ca34c, run 28684335234): libxfce4ui and libxfce4windowing progressed to `%build` succeeding but `%files` failing (versioned header subdir; missing `vala`). Fixed. **garcon looked like it passed but didn't actually run** — see the GitHub Actions trap below.
  - v14 (commit 1f576a2, run 28685969914): both now fail with `error: Installed (but unpackaged) file(s) found` — `%build`/`%install` succeed, the specs just don't list everything meson actually installs. Two very minimal specs (`%files` was only ever written for the core `.so`/headers) meeting a package that also ships binaries, desktop files, icons, GIR/vapi bindings, and locale files.
    - `libxfce4ui`: missing `libxfce4kbd-private*.so.*` (runtime lib!), `xfce-open`/`xfce-desktop-item-edit`/`xfce4-about` binaries, `xfce4-about.desktop` + hicolor icons, the `xfce4-keyboard-shortcuts.xml` xfconf config, and locale `.mo` files (no `%find_lang`). Fixed by packaging all of it into the single `libxfce4ui` subpackage (no upstream reason found to split `xfce4-about` out — nothing downstream references it).
    - `libxfce4windowing`: missing GIR typelib (runtime) + `.gir`/vala vapi (devel) for *both* `libxfce4windowing` and `libxfce4windowingui`, and locale files. Fixed.
  - v15 (commit f481d0c, run 28687708505): libxfce4ui and libxfce4windowing **both finally passed**. But `garcon` — unchanged since v13 — failed for the first time, with the exact same class of bug (wrong header path: `xfce4/garcon-1/` instead of `garcon-1/`; also missing the `xfce-applications.menu`, `desktop-directories/*.directory` category files, hicolor icon, and locale files).
    - **GitHub Actions trap, worth remembering**: `build-xfce-ui-libs-garcon` `needs: consolidate-xfce-ui-libs`. When `consolidate-xfce-ui-libs` is skipped because its own `needs:` (`build-xfce-ui-libs`) failed, GitHub Actions marks *every* downstream job **`skipped`**, not `failure` — and `skipped` doesn't show up in `select(.conclusion=="failure")` job-listing queries. So garcon's tier silently never ran in v13 or v14; it only actually executed for the first time in v15, once libxfce4ui/libxfce4windowing (upstream of it) finally went green. A "passing" job in a downstream tier is not proof it was tested — check `.conclusion` isn't `skipped` too, not just that it's absent from the failure list.
    - Fixed (commit d9fc304) and dispatched as v16, run 28688126138 — **check this run next**.
  - If v16 is green, tier 3 is fully done — move on to auditing tiers 4-8 for the same three failure classes before dispatching them: (1) auto-features-enabled forcing optional meson deps required, (2) incomplete `%files` (specs written against assumption instead of the real install manifest), (3) the skipped-job trap above masking whether a downstream tier was ever actually exercised.
- ⏳ Tiers 4–8: desktop-core, compositor (xfwl4), apps, panel-plugins, meta — unreached yet (or "unreached" in the sense of never actually building — double check with the skipped-job trap above rather than trusting `gh run view` failure-only queries).

**Key fixes applied per spec**:
| Package | Issues fixed |
|---|---|
| `xfconf` | meson migration (was autotools), header path `xfce4/xfconf-0/xfconf/`, `%find_lang`, GIO module, bash-completion |
| `libxfce4util` | autoreconf EL10 nm-parsing, removed phantom `%{version}` libdir, GI typelib/GIR are `Libxfce4util-1.0.*` (capital L), `%find_lang`, vala vapi, gtk-doc, kiosk-query binary |
| `xfce4-dev-tools` | `%files` verified against real tarball, added autoreconf + meson/ninja |
| `gtk-layer-shell` | devel subpackage, license file names, `%files` |
| Commit-pin Source0s | 5 specs had whitespace-sensitive gitlab-archive URL replacement failures |
| `libxfce4ui`, `libxfce4windowing`, `garcon` | see tier-3 root-cause notes above |

**Repo**: `tuna-os/github-copr` main branch (checked out at `/home/james/dev/tuna-os/github-copr`)
**Dispatch**: `gh workflow run build-xfce-distributed.yml`
**Debugging tip**: `gh run view <id> --json jobs -q '.jobs[] | select(.conclusion=="failure") | .name'` then `gh run view <id> --log --job=<databaseId>` — grep the saved log for `error:|ERROR:|Bad exit status`, the mock debug noise drowns everything else.

### 2. grouper (Ubuntu 26.04) full parity — ✅ DONE (pending final review)
**Status**: All 4 desktop builds AND all 4 boot gates pass (run 28685978251, confirmed). The composefs-backend fix works end-to-end. Nothing left to iterate on here unless a fresh regression shows up.

- Base `10-base-packages.sh` apt path: fdisk added (Debian splits it from util-linux), plasma-workspace-wayland removed (nonexistent), bootupd reverted (not an apt package).
- `build_scripts/kde.sh`: removed `plasma-workspace-wayland` from apt install.
- **Root cause**: `bootc install to-disk` defaults to the ostree backend, which always shells out to `bootupd` for bootloader management — but `bootupd` isn't packaged for Ubuntu apt.
- **Fix** (mirrors `bootc-shindig`/`bootcrew/mono`'s `ubuntu-bootc` reference, which also ships systemd-boot + no bootupd): per bootc docs (bootloaders.md, experimental-composefs.md), if `bootupd` is absent from the image, bootc falls back to systemd-boot — but only under the composefs-native storage backend (`--composefs-backend`), distinct from the `[composefs] enabled = yes` ostree-composefs mode our image already sets in `prepare-root.conf`.
  - `build_scripts/10-base-packages.sh`: added `systemd-boot` apt package (provides `bootctl` + EFI binaries).
  - `scripts/iso-e2e.sh`, `scripts/build-qcow2.sh`, `Justfile` (`qcow2` recipe): pass `--composefs-backend` conditionally, scoped to grouper. RPM variants untouched.
  - **First attempt (commit 0dc374e, run 28684055168) failed all 4 boot gates** with `error: Installing to disk: bootupd is required for ostree-based installs` — the flag never applied. Root cause: the boot gate calls `just qcow2` with a *full image ref* (`ghcr.io/tuna-os/grouper:gnome-testing`), not the bare variant name, so the Justfile's `{{ variant }} == grouper*` glob never matched. `OUTPUT_NAME` (already derived from the ref earlier in the recipe, same pattern `scripts/build-qcow2.sh` already used correctly) is the right thing to match against. Fixed in commit 1b1d7a7.
  - Re-dispatched as run 28685978251 — **check this run's boot gates next**.
- **Still-untested risk**: `--composefs-backend` is experimental/"not as heavily tested". If the boot gate now gets past the bootupd error but fails on something UKI/systemd-boot related, the next thing to check is whether bootc auto-generates an unsigned UKI at install time or needs a manual `ukify` step added to `build_scripts/bootc/finalize.sh` (see bootc's `experimental-composefs.md` "sealed images" build pattern).

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
