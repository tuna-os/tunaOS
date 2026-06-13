# RFC 010 — Ubuntu 26.04 as a TunaOS variant

**Status:** Draft / spec
**Tracking issue:** [#339](https://github.com/tuna-os/tunaOS/issues/339) (closed — deferred behind CI stabilization)
**Author:** drafted 2026-06-13
**Supersedes/builds on:** the architect assessment in #339

> This is a **spec**, written while reconnoitring the codebase. It records what
> actually exists today, the concrete integration surface, and a phased plan —
> so the work can be picked up in safe, reviewable slices rather than one risky
> mega-PR.

---

## 1. Goal

Make **Ubuntu 26.04 "Resolute Raccoon"** a first-class (if experimental) TunaOS
variant — built and published through the same pipeline as the RPM variants —
rather than the standalone project it is today.

Proposed variant id: **`grouper`** 🐟 (fish-themed, matching yellowfin /
albacore / skipjack / bonito). The RFC's working name was "raccoon" 🦝; the
architect flagged that it breaks the fish theme. **Open question** — see §8.

---

## 2. Current state (verified)

### 2.1 What already exists

- **`tuna-os/ubuntu-26.04-iso`** is a *self-contained* build. Tree:
  ```
  ubuntu-26.04/Containerfile          # deb-based bootc image
  ubuntu-26.04/Containerfile.builder
  ubuntu-26.04/payload_ref
  ubuntu-26.04/src/build-iso.sh       # dakota-iso ISO build
  ubuntu-26.04/src/configure-live.sh
  ubuntu-26.04/src/zfs-install.sh
  ubuntu-26.04/src/install-flatpaks.sh
  ubuntu-26.04/src/etc/bootc-installer/{images,recipe}.json
  ```
  It publishes the bootc base image **`ghcr.io/hanthor/ubuntu-26.04-desktop-bootc`**
  and a working Live ISO with an online `bootc install to-disk` installer.
- It does **not** share this repo's `build_scripts/` or `Containerfile*`.

### 2.2 Why it isn't a drop-in variant

TunaOS's build layer is deeply **dnf/RPM-coupled**:

- **`build_scripts/lib.sh`** derives OS identity from the `BASE_IMAGE` string into
  RPM-only flags — `IS_FEDORA`, `IS_RHEL`, `IS_ALMALINUX`, `IS_ALMALINUXKITTEN`,
  `IS_CENTOS` (lib.sh:34-44). There is **no `IS_UBUNTU`/`IS_DEBIAN` and no
  `PKG_MGR`**.
- lib.sh's package helpers are dnf-specific: `dnf_retry()` (209),
  `install_available()` (252), `install_from_copr()` (364), plus
  `safe_enable/safe_disable` for systemd.
- **11 build scripts call `dnf` directly:** `00-workarounds.sh`,
  `10-base-packages.sh`, `20-packages.sh`, `arch-customizations.sh`,
  `cleanup.sh`, `cosmic.sh`, `gnome.sh`, `kcm-ublue.sh`, `kde.sh`, `niri.sh`,
  and `lib.sh` itself.
- `10-base-packages.sh` also does RHSM/`subscription-manager` registration —
  irrelevant for Ubuntu and already guarded by `IS_RHEL`/`IS_CENTOS`.

### 2.3 The Containerfile chain

`Containerfile` (+ `.hwe`, `.nvidia`, `.dx`, `.final`) is a multi-stage build:
`COMMON_IMAGE_REF` + `BREW_IMAGE_REF` → `context` (copies `system_files`,
`build_scripts`, `image-versions.yaml`) → `FROM ${BASE_IMAGE} AS base-no-de` →
runs `build_scripts` via `run_buildscripts_for()`. Containerfile selection (not
an env gate) drives HWE/NVIDIA. The base packages run `dnf` inside the
`${BASE_IMAGE}` stage.

### 2.4 Variant config

`.github/build-config.yml` defines variants declaratively: `id`, `emoji`,
`description`, `base_image`, `platforms`, and a `flavors` list with `stage` +
`build_image`/`build_iso` flags. Adding a variant *entry* is trivial; making its
`flavors` actually build is the work.

---

## 3. Scope (v1)

Per the RFC, intentionally minimal:

| Dimension | v1 |
|-----------|----|
| Desktop | **GNOME only** (no KDE/COSMIC/Niri) |
| Arch | **x86_64 only** (`linux/amd64`; no arm64, no v2) |
| Flavors | `base` (stage 1), `gnome` (stage 2, ISO) |
| Install | online `bootc install to-disk` |
| Secure Boot | not supported |
| Matrix | **manual dispatch only** — not in the daily build |

---

## 4. Design

Two integration strategies; this spec recommends **B → A** in phases.

### Strategy A — full pipeline integration (the deep path)
Teach TunaOS's own `build_scripts` to build on a deb base. Highest fidelity
(Ubuntu gets brew/common/system_files the same way), highest cost/risk.

### Strategy B — consume the prebuilt base (the thin path)
Treat `ghcr.io/…/ubuntu-26.04-desktop-bootc` as the `base_image` and run only a
**minimal, apt-aware** subset of build scripts (or none), reusing the existing
ubuntu-26.04-iso build logic. Lowest risk; ships something real fast.

### 4.1 `PKG_MGR` abstraction (foundation for A — additive, safe)

Add to `lib.sh`, after the existing flags (no change to RPM behaviour):

```sh
IS_UBUNTU=false
IS_DEBIAN=false
[[ "${BASE_IMAGE,,}" == *"ubuntu"* ]] && IS_UBUNTU=true && IMAGE_NAME="grouper" && IMAGE_PRETTY_NAME="Grouper"
[[ "${BASE_IMAGE,,}" == *"debian"* ]] && IS_DEBIAN=true

# Package manager dimension
if [[ "$IS_UBUNTU" == true || "$IS_DEBIAN" == true ]]; then
  PKG_MGR="apt"
else
  PKG_MGR="dnf"
fi
export IS_UBUNTU IS_DEBIAN PKG_MGR
```

Then introduce thin wrappers so scripts stop calling `dnf` directly:

| New helper | dnf | apt |
|------------|-----|-----|
| `pkg_install PKGS…` | `dnf_retry install -y` | `apt-get install -y --no-install-recommends` |
| `pkg_remove PKGS…` | `dnf remove -y` | `apt-get purge -y` |
| `pkg_refresh` | `dnf makecache` | `apt-get update` |
| `pkg_clean` | `dnf clean all` | `apt-get clean && rm -rf /var/lib/apt/lists/*` |

`install_from_copr()` stays dnf-only and is simply not called on the apt path
(guard with `[[ $PKG_MGR == dnf ]]`).

### 4.2 Containerfile

Add **`Containerfile.ubuntu`** (or `Containerfile.grouper`) mirroring the base
`Containerfile` stages but: skip RHSM, skip COPR, use the apt path. Wire its
selection into the Justfile `_build` helper / `scripts/build-image.sh` keyed on
the variant (same mechanism that selects `.hwe`/`.nvidia`).

### 4.3 build-config.yml entry

```yaml
  - id: grouper            # 🐟 fish-themed; "raccoon" is the upstream codename
    emoji: "🐟"
    description: "Based on Ubuntu 26.04 Resolute Raccoon"
    base_image: "ghcr.io/hanthor/ubuntu-26.04-desktop-bootc:latest"  # pin to digest before merge
    platforms: ["linux/amd64"]
    experimental: true     # manual dispatch only — exclude from daily matrix
    flavors:
      - id: base
        stage: 1
        build_image: true
      - id: gnome
        stage: 2
        build_image: true
        build_iso: true
```

Requires `generate_matrix`/`generate-workflows.py` to honour an
`experimental: true` flag (exclude from the scheduled cron, keep on
`workflow_dispatch`). **Verify** the schema supports this; if not, that's a
prerequisite sub-task.

### 4.4 lib.sh `detected_os()` / IMAGE_NAME

`detected_os()` (lib.sh:60) and the per-variant `IMAGE_NAME` mapping must learn
`grouper`. Covered by the §4.1 snippet.

---

## 5. Files to change (Strategy A, exhaustive)

| File | Change |
|------|--------|
| `build_scripts/lib.sh` | `IS_UBUNTU`/`IS_DEBIAN`/`PKG_MGR` + `pkg_*` wrappers + `grouper` IMAGE_NAME |
| `build_scripts/10-base-packages.sh` | apt branch for base packages; RHSM already guarded |
| `build_scripts/20-packages.sh` | route through `pkg_install`; deb package-name map |
| `build_scripts/gnome.sh` | apt GNOME package set |
| `build_scripts/40-services.sh` | systemd unit names parity (likely fine) |
| `build_scripts/cleanup.sh` | apt clean branch |
| `build_scripts/00-workarounds.sh` | guard dnf-only workarounds behind `$PKG_MGR` |
| `Containerfile.ubuntu` | **new** — apt-aware multi-stage |
| `.github/build-config.yml` | `grouper` variant entry |
| `scripts/generate-workflows.py` / matrix | honour `experimental: true` |
| `scripts/build-image.sh` / `Justfile` | select `Containerfile.ubuntu` for grouper |
| `image-versions.yaml` | pin the Ubuntu base image digest |
| `docs/` + `ROADMAP.md` + tunaos.org | document the variant |

KDE/COSMIC/Niri scripts are **out of scope** for v1 (GNOME-only).

---

## 6. Phased plan (safe slices)

1. **Foundation PR** *(low risk, additive)* — `lib.sh`: `IS_UBUNTU`/`IS_DEBIAN`/
   `PKG_MGR` detection + `pkg_*` wrappers. No RPM behaviour change; dnf scripts
   can migrate to `pkg_*` incrementally. Ships green, unblocks everything else.
2. **Containerfile + base flavor** — `Containerfile.ubuntu`, base-packages apt
   branch; build the `grouper:base` image locally / on manual dispatch.
3. **GNOME flavor + ISO** — `gnome.sh` apt set; `grouper:gnome` + ISO via the
   existing ubuntu-26.04-iso dakota path.
4. **Matrix wiring** — `experimental: true`, manual-dispatch workflow.
5. **Docs + ROADMAP** — variant page, download entry, system-requirements note.
6. **Tier-1 eval** *(later)* — arm64, Secure Boot, daily matrix, adoption.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|------|-----------|
| Doubles CI surface; apt failure modes | Manual dispatch only; not in daily cron |
| `dnf`→`pkg_*` migration regresses RPM builds | Wrappers are additive; migrate script-by-script with the existing variant builds as the regression test |
| Can't build/verify deb image in this env | Each slice validated in CI on a branch before merge |
| Base image is under `hanthor/`, mutable `:latest` | Pin to digest in `image-versions.yaml` (same concern as #462) |
| Architect's CI-stability gate (#226–#314) | Confirm current pass rate ≥ target before enabling any scheduled build; v1 stays manual |

---

## 8. Open questions

1. **Name** — `grouper` (fish theme, recommended) vs `raccoon` (upstream
   codename). Affects `IMAGE_NAME`, image tags, docs, ISO filenames. **Needs a
   call before Phase 2.**
2. **Strategy A vs B** — build through TunaOS `build_scripts` (fidelity) or
   consume the prebuilt `ubuntu-26.04-desktop-bootc` base (speed)? Recommend B
   for v1 to ship, migrate toward A as `pkg_*` matures.
3. **CI gate** — is the daily build pass-rate now healthy enough to lift the
   architect's deferral? (Was the explicit blocker in #339.)

---

## 9. Recommendation

Proceed **incrementally**, starting with the **Phase 1 foundation PR**
(`lib.sh` `PKG_MGR` abstraction) — it's safe, additive, independently useful,
and the prerequisite for everything else. Hold the scheduled/daily build behind
the CI-stability gate; keep v1 GNOME-only, x86_64-only, manual-dispatch. Resolve
the **name** (§8.1) before tagging any images.
