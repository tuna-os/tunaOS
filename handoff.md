# Handoff — 2026-07-04

## Active goals

### 1. github-copr XFCE Wayland stack (28 packages)
**Status**: Tiers 0–3 fully confirmed passing (including garcon's split-off tier). Tier 4 (desktop-core) got its first real test in v18/v19 — diagnosed and fixed a large batch of bugs across all 6 packages; v19 (run 28689609213) is the check-next run.

- ✅ Tier 0 `xfce4-dev-tools`, Tier 1 `gtk-layer-shell` + `wlr-protocols` (new, see below), Tier 2 `libxfce4util`+`xfconf`, Tier 3 `libxfce4ui`+`libxfce4windowing`, Tier 3b `garcon` (own tier, see trap below) — all confirmed green as of v17/v18.
- 🔄 Tier 4 `xfce-desktop-core` (xfce4-panel, xfce4-session, xfce4-settings, thunar, tumbler) + Tier 4b `xfce-desktop-core-xfdesktop` (xfdesktop split out, same intra-tier-dependency trap as garcon — it links `thunarx-3` from sibling thunar).
  - **First-ever run of this tier (v17/v18) failed all 6** — same two bug classes as tier 3, at bigger scale: meson `--auto-features=enabled` forcing optional deps required, and specs whose `%files` was written from assumption rather than the real install manifest. Fixed in v18 (commit 46fe3df): missing BuildRequires per package (`libxslt`+`libgudev-devel`+`gobject-introspection-devel`+`libexif-devel`+`pcre2-devel` for thunar; `libxfce4util-devel`+`poppler-glib-devel` for tumbler; `libdbusmenu-gtk3-devel` for xfce4-panel; `libxfce4windowing-devel`+`gtk-layer-shell-devel` for xfce4-session; `garcon-devel`+`gtk-layer-shell-devel` for xfce4-settings; `libnotify-devel`+`libyaml-devel`+`gtk-layer-shell-devel` for xfdesktop). Also standardized `-Dx11=disabled` across the tier (this is a Wayland-only build) and disabled a few niche auto-enabled features that would've otherwise pulled in heavy/unwanted deps or created *more* intra-tier ordering problems: `thunar-tpa` (needs libxfce4panel from sibling xfce4-panel), tumbler's cover/ffmpeg/gepub/gst/raw thumbnailers, xfdesktop's `video-backdrop` (gstreamer).
  - v19 (commit 243a2be, run 28689609213) fixes what v18 surfaced next — now that `%build` succeeds for everyone, the specs' `%files` sections (never tested before) turned out wrong or incomplete in ways only visible once the mock build actually completed:
    - **thunar**: `msgfmt` failed translating `org.xfce.thunar.policy.in` — needs polkit's ITS rules file (`/usr/share/gettext/its/polkit.its`, shipped by the *base* `polkit` package, not `-devel`). Also filled in dbus service, polkit action, appdata metainfo, icons, locale.
    - **tumbler**: `%files` claimed `/usr/bin/tumblerd`, but meson actually installs it under `$libdir/tumbler-1/` (`helper_path_prefix` isn't `/usr/bin`) — already covered by the existing recursive glob, the explicit wrong path was the failure. Added systemd user service + default config.
    - **xfce4-session**: `%files` claimed `/usr/share/xsessions/*.desktop` and `/usr/libexec/xfce4/` — both wrong once X11 is disabled (xsessions install is `if enable_x11`-gated in meson.build) and the shutdown helper actually lives under `$libdir/xfce4/session/` (not libexecdir). Filled in the rest too (startxfce4/xflock4, labwc config, icons, xfconf config).
    - **xfce4-settings — real bug, not just %files**: meson.build wants the `protocols/wlr-protocols` git submodule, which isn't in the plain GitLab archive tarball (git submodules never are). Fix: packaged `wlr-protocols` as its own tiny noarch package (mirrors Fedora's approach — ships the protocol XML + a `.pc` file; meson already prefers pkg-config over the submodule-directory fallback, so this sidesteps needing the submodule at all), pinned to the exact commit xfce4-settings' submodule references (found via the GitLab tree API, since `.gitmodules` doesn't carry the pin). Added to the `xfce-layer-shell` tier (zero deps on our own stack). Also fixed xfsettingsd's actual location (spec had it at libexecdir; meson puts it at bindir) and filled in the rest of `%files` (icons, GTK module, xfconf config, autostart, menu file).
    - **xfwl4 (tier 5, still untested)**: fixed proactively — its Cargo.lock pulls in `xfconf-sys`/`libxfce4ui-sys`/`libxfce4kbd-private-sys`, needing `xfconf-devel`+`libxfce4ui-devel` via pkg-config. Found this by hitting the identical bug first in `tuna-os/debian-copr`'s parallel Rust build (see below) — worth checking proactively for any other spec whose upstream carries Rust/Cargo or other non-RPM build tooling.
  - **GitHub Actions trap, worth remembering for every future tier**: a job whose `needs:` failed gets marked `skipped`, not `failure` — invisible to `select(.conclusion=="failure")` queries. A tier that looks like it "passed" (absent from the failure list) may have never actually run. Always check `.conclusion=="skipped"` too. This is why garcon looked fine in v13/v14 but hadn't actually built yet.
- ⏳ Tiers 5–8 (compositor/xfwl4, apps, panel-plugins, meta) — still genuinely unreached. Expect the same two bug classes (missing auto-enabled BuildRequires, incomplete `%files`) at whatever scale each tier turns out to be — budget for it rather than assuming any spec is closer to correct than it's been proven to be by an actual green CI run.

**Debugging workflow that's worked well this session**: dispatch → `gh run view <id> --json jobs -q '.jobs[] | select(.conclusion=="failure" or .conclusion=="skipped") | .name'` → pull full job logs (`gh run view <id> --log --job=<databaseId>`, note the databaseId lookup can match multiple jobs if the package name is a substring of another job name — grab the exact `databaseId` not just a name-contains filter) → grep for `error:|ERROR:|ninja: build stopped|ERROR: Installed \(but unpackaged\)|Directory not found|File not found` → when a dep is missing, check the *actual* upstream `meson.build`/`meson_options.txt` (or `configure.ac`) at the exact pinned commit rather than guessing, since `--auto-features=enabled` (baked into the `%meson` RPM macro) silently promotes every `type: 'feature', value: 'auto'` option to required — one missing pkgconfig lib can hide several more behind it.

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
Now cloned locally at `/home/james/dev/tuna-os/debian-copr`. Actively debugged this session (3 real bugs fixed, still blocked on a structural issue — see below).

- **GPG signing — resolved**: generated a fresh dedicated GPG key ("TunaOS Debian Repo Signing Key", no passphrase) rather than reusing github-copr's RPM key (James's call — GitHub secrets are write-only so the existing key couldn't be copied anyway). Private key set as the `GPG_PRIVATE_KEY` repo secret; public key committed as `public.gpg` at repo root and wired into the `publish` job's R2 upload (`deb/public.gpg`), mirroring github-copr's convention. R2/Cloudflare secrets are org-level (`ALL` repos) so those needed no setup.
- **Real bugs fixed** (commits 4cea4dc, 577206d, 5bb8e9f):
  1. `scripts/build-chain.sh` didn't initialize an empty reprepro repo before the very first package build — `apt-get update` inside the build container failed outright (not just warned) against a nonexistent `dists/<dist>/Release`/`Packages`, unlike RPM/createrepo_c which is fine with valid-but-empty metadata. Fixed by exporting an empty repo up front if `Release` doesn't exist yet.
  2. That fix then hit `gpgme gave error GPGME:54: Unusable secret key` — `conf/distributions` has `SignWith: default`, but no GPG key exists yet in the intermediate build/import job's keyring (only the final `publish` job imports one). Split into `conf-unsigned/` (no SignWith, used by every intermediate `build-chain.sh` step) and `conf/` (SignWith: default, used only by `publish` after the real key is imported).
  3. `xfwl4`'s `debian/compat` file conflicted with `debian/control`'s `debhelper-compat (= 13)` — modern debhelper refuses both being set. Removed the redundant `debian/compat`.
- **Current blocker — structural, not a bug**: `xfwl4` needs `libxfce4ui-2`/`xfconf`/`libxfce4util` via pkg-config (same Cargo.lock-driven discovery that led to the proactive `xfwl4.spec` fix in github-copr above), but **none of those exist as Debian/Ubuntu apt packages** — they're the same custom XFCE-Wayland stack github-copr builds for RPM, which is the whole reason debian-copr exists. `xfwl4` was picked as "provable first" package, but it structurally can't build standalone — github-copr's own tier order already reflects this (`xfce-compositor` runs *after* `xfce-ui-libs`/`xfce-desktop-core`, for exactly this reason). **To unblock xfwl4, `libxfce4util`, `xfconf`, and `libxfce4ui` need Debian packaging ported first** (`debian/control`+`rules`+`changelog` per package, following the same tier-manifest pattern). The already-fixed RPM specs in github-copr are a working recipe for what each package needs — this is bounded porting work, not exploration, but it's a few packages' worth, not a one-line fix. **Told James this; he redirected focus to github-copr's RPM side for now — debian-copr is paused, not abandoned.**

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
