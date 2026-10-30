# TunaOS Build Pipeline Reference

How images and ISOs get built, verified, and published. If you change CI, read this first; if you change the pipeline's shape, update this file.

---

## The Build Matrix

`variant × desktop × hardware_layer`, defined in `tunaos.toml`.

Shell entrypoints resolve that contract through
`scripts/lib/build-config.sh`. For tests that use an alternate contract, set
`TUNAOS_BUILD_CONFIG`. Do not add new runtime dependencies on the current
`.github/` storage path.

| Variant | Base | Desktops | HWE/NVIDIA | Platforms |
|---------|------|----------|------------|-----------|
| yellowfin | AlmaLinux Kitten 10 | gnome, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 |
| albacore | AlmaLinux 10 | gnome, cosmic, kde, niri, xfce | yes | amd64, amd64/v2, arm64 |
| skipjack | CentOS Stream 10 | gnome, cosmic, kde, niri | gnome/cosmic families | amd64, arm64 |
| bonito | Fedora 44 | gnome, cosmic, kde, niri, xfce | nvidia only | amd64, arm64 |
| grouper | Ubuntu 26.04 | gnome, kde, niri, xfce | none | amd64 |

---

## Build Stages (DAG)

```
Stage 1:  base
             │
Stage 2:  ┌──┼──────────────────────────────────────┐
          │  base-hwe  base-nvidia                   │
          │  gnome  kde  niri  cosmic  xfce │  (all parallel)
          └──┬───────────────────────────────────────┘
             │
Stage 3:  gnome-hwe, kde-hwe, niri-hwe, cosmic-hwe     (layer on DE image)
          gnome-nvidia, kde-nvidia, niri-nvidia, cosmic-nvidia
             │
Stage 4:  gnome-nvidia-hwe                              (layer on gnome-hwe)
```

**Key insight**: the overlay stage applies HWE/nvidia layers ON TOP of DE images (not the other way around). `gnome-hwe` = `yellowfin:gnome` + HWE kernel. The DE is never duplicated.

---

## Workflow Files

| File | Role |
|------|------|
| `build-yellowfin.yml` / `build-albacore.yml` / etc. | Top-level per-variant entry points (trigger: schedule + manual) |
| `build-variant.yml` | Unified orchestrator — generates matrix, runs 4-stage DAG |
| `reusable-build-image.yml` | Per-platform build + push + sign + boot-gate (Decomposition Plan: [docs/architecture/reusable-build-image-decomposition.md](architecture/reusable-build-image-decomposition.md)) |
| `reusable-build-artifacts.yml` | ISO/QCOW2 generation |
| `promote-stable.yml` | RFC 018 `:testing` → `:stable` promotion. Phase 2: a daily dry run that only reports (see [Stable promotion dry run](#stable-promotion-dry-run)) |

---

## How a Build Works

1. **Matrix generation** — `build-variant.yml` reads `build-config.yml`, emits per-stage matrices
2. **Stage 1** — builds `base` (Containerfile `base-no-de` target)
3. **Stage 2** — builds DE images via `install-desktop.sh <de>` (reads YAML manifests)
4. **Stage 3-4** — layers HWE/nvidia via `Containerfile.overlay`
5. **Rechunk** — chunkah makes ostree-optimized layers for delta updates
6. **Boot gate** — Corral boots the `-candidate` image under QEMU, and Promote waits for the result (see [Boot gates](#boot-gates))
7. **Publish** — multi-arch manifest pushed to the resolved registry, signed with cosign.
   - `ghcr.io/<owner>` uses `GITHUB_TOKEN`.
   - Any other destination needs the `TUNAOS_PUBLISH_*` credential. [RFC 016](rfc/rfc016-publish-credentials.md) lists the jobs that choose and use it.
8. **Live overlay** — Promote writes the bare tag of a desktop cell on `main`. Then the `Live overlay` job starts `live-overlay.yml` for that cell. It passes the digest of the index that Promote wrote.
   - `scripts/dispatch-live-overlay.sh` sends the dispatch. `scripts/live-overlay-matrix.sh` selects the cells.
   - When the tag has moved past that index, the overlay run writes a notice and builds from the current base. It binds only a base that the tag still names.
   - Thus the `org.tunaos.live-overlay.base-digest` annotation follows the image that tacklebox selects.
   - `live-overlay.yml` must be enabled. When it is disabled, the dispatch step fails and prints `gh workflow enable live-overlay.yml`. The step continues on error, so the variant run stays green.

---

## Stable promotion dry run

[RFC 018](rfc/rfc018-testing-stable-rings.md) splits each cell into two rings. The `:<flavor>-testing` ring gets every image that passes CI. The bare `:<flavor>` tag is the `:stable` ring, and it gets a `:testing` image only after a soak. `promote-stable.yml` runs `scripts/promote-stable.py` daily at 06:00 UTC. It can also run manually for one or more cells (`cell` input, for example `albacore:gnome,yellowfin:*`).

**Phase 2 is a dry run.** The workflow has no `packages: write` permission and runs no copy. Promote in `reusable-build-image.yml` continues to write the bare tags. A `mode` other than `dry-run` fails with `RFC 018 phase 3 not enabled`. The `rollback_to` and `reason` inputs also only report the refs that a repoint would write.

For each cell, the script reads the dated tags `<tag>-YYYYMMDD` for the last 30 days, newest first. A dated tag records the day that its digest became the cell's `:testing` image. The script selects the newest digest that has soaked for `soak_days`. The default is 3 days in `[defaults]` of `tunaos.toml`, and a variant can set its own value (yellowfin: 5).

The soak starts at the end of the dated day. Thus a digest dated D with a 3-day soak is eligible from D+4 at 00:00 UTC. Then the script checks these gates:

| Gate | Holds the cell when |
|---|---|
| release-blocker | An open issue with the `release-blocker` label names the cell in its title (`albacore:gnome` or `bonito:kde-rawhide`), or has the label `variant/<variant>`. |
| desktop contract | The newest `desktop-contract-sweep.yml` result for the cell (artifact `desktop-contract-baseline`, `all.json`) is not `pass`, is missing, or is older than the candidate. A `-hwe`, `-nvidia` or other derived flavor uses its desktop's result. A flavor without a swept desktop (`base`, `tuna`) is `n/a`. |
| Soak-After | A commit between the stable revision and the candidate revision has a `Soak-After: <N>d` trailer, and the candidate is younger than the largest N. |

The revision is `org.opencontainers.image.revision`. If that label is missing, the script uses `org.opencontainers.image.version`, which `Containerfile.final` sets to the short build commit. The workflow reads the commit range from a full-history checkout. A cell is held if the script cannot read a fact. The run stays green when it holds cells.

**How to read the output.** The log and the job summary have one row for each cell:

- `PROMOTE` — all gates passed. Phase 3 would copy the candidate digest to the bare tag, the arch tags and the alias images.
- `HOLD` — the reason names each gate that held the cell, for example `soak: ... eligible 2026-11-02T00:00Z` or `release-blocker: #1234 (title)`.
- `NOOP` — the stable tag points at the selected digest, or at a newer digest. While Promote writes the bare tag (phases 1 and 2), `stable is ahead` is the usual result. Then the **Phase-3 verdict** column shows the decision of the phase 3 rules for the soaked digest. Read this column during the phase 2 week.

Run it locally (read-only; needs `skopeo`, `gh` and a full-history clone):

```bash
python3 scripts/config.py generate
python3 scripts/promote-stable.py evaluate --cell 'albacore:gnome,yellowfin:gnome' --summary ''
```

---

## Flavor Resolution

`scripts/resolve-flavor.sh` maps any flavor to its build parameters:

```bash
$ ./scripts/resolve-flavor.sh yellowfin gnome-nvidia
CONTAINERFILE="Containerfile.overlay"
DESKTOP_FLAVOR="desktop"
ENABLE_HWE="0"
ENABLE_NVIDIA="1"
OVERLAY_TYPE="nvidia"
PARENT_FLAVOR="gnome"
```

---

## The Manifest Installer

DE packages are installed by `build_scripts/desktop/install-desktop.sh`, which reads `manifests/desktops/<de>.yaml`:

```yaml
# manifests/desktops/kde.yaml
display_manager: sddm
packages:
  fedora:
    groups: [kde-desktop]
    packages: [sddm, dolphin, konsole, ...]
  el10:
    groups: ["KDE Plasma Workspaces", ...]
    optional: [kdeconnect, nvtop, ...]
  apt:
    - kde-plasma-desktop
    - sddm
versionlock: [plasma-desktop, "qt6-*"]
```

Supports: dnf (Fedora/EL10), apt (Ubuntu/Debian), pacman (Arch/CachyOS).

---

## Image Refs and Pinning

Three sources of image metadata, consolidated via `scripts/resolve-image.sh`:

| Source | Contains |
|--------|----------|
| `tunaos.toml` | `base_image` per variant |
| `image-versions.yaml` | Digest pins for common/brew/zirconium + download versions |
| `registry-map.yaml` | Mirror overrides |

Usage: `./scripts/resolve-image.sh yellowfin common` → full `image@sha256:...` ref.

---

## Local Development

```bash
just build yellowfin gnome             # build locally
just qcow2 yellowfin gnome             # generate VM disk
just verify-disk ./yellowfin-gnome.qcow2  # QEMU boot check
just iso yellowfin gnome               # build ISO via tacklebox
```

---

## Tooling

### Boot gates

Corral runs the boot gate. `scripts/corral-boot-gate.sh` gives the image to `corral vmtest`. Corral installs the image to a disk and boots the disk under QEMU with UEFI. The script then reads the contract markers on the serial console. The Gate job in `reusable-build-image.yml` and the PR gate step use this script. The CI contract declares the PR gate in `.github/green-criteria.yml`.

The verdict is the same as the verdict of `scripts/iso-e2e.sh --disk`:

- **Pass:** `TUNAOS_DESKTOP_CONTRACT_OK` is on the console. Also, `TUNAOS_BASE_CONTRACT_FAIL` does not occur in the next 120 seconds.
- **Fail:** a contract `FAIL` marker, an emergency shell, or a kernel panic is on the console. Corral stops the wait when one of these occurs.
- **Fail:** no marker occurs before the timeout.

The disk agrees with `just qcow2`. A sealed image gets ext4, and other images get xfs. `TUNAOS_QCOW2_FILESYSTEM` overrides this choice. The kernel arguments are the same, and the boot entry also gets `tunaos.countme=0`. Thus a gate guest never sends an adoption report, from the first boot.

`image-versions.yaml` pins the Corral commit in `downloads.corral`, and `scripts/install-corral.sh` builds that commit. The workflow `corral-boot-gate.yml` boots one ostree image and one composefs image through the script when a pull request changes the script.

The GPU-routed compositors (cosmic, niri, xfwl4) use `just qcow2` and `scripts/iso-e2e.sh --disk`, because Corral has no virgl display. The Gate does not schedule these flavors at this time. For the same reason, the boot step of a pull request build skips them.

For a KubeVirt cluster, `scripts/boot-gate.sh` checks for `--karg` support in both fresh and resumed guests. It passes `tunaos.countme=0` before boot, or exits 77 before it creates a guest. See the [measured cause and test](ci-troubleshooting.md#automated-corral-guests-could-enter-adoption-counts).

### PR canary cells (TUNA-2)

`tuna-pr-images.yml` builds four canary cells from the checkout: albacore:gnome, bonito:kde, marlin:cosmic and flounder:xfce, one per package family. The cells build only when a pull request changes a top-level `Containerfile*`, a file under `build_scripts/`, or `tunaos.toml` (`.github/scripts/canary-cell-inputs.sh`). Each cell builds for amd64, does not publish, and runs `verify-desktop-experience.sh` on the built image (`Desktop contract (PR gate)`). Then the PR gate step boots the image, except for cosmic. The check is not required.

`just test-canary-cells` runs the same contract on the published images after a merge.

---

## Renovate (Automated Updates)

`renovate.json` extends the shared `tuna-os/.github` policy and tracks:

- image digest pins (`image-versions.yaml`)
- SHA pins of GitHub Actions
- Git submodules
- pinned download versions

Routine minor, patch, pin, and digest updates may automerge only after required
CI and branch protection pass. Major updates and repository-specific holds
need human review. The config gate runs both Renovate's schema validator
and `scripts/check-renovate-automerge-policy.py`, because schema-valid rules
can still violate the org automerge boundary. See
[DEPENDENCY-FRESHNESS.md](DEPENDENCY-FRESHNESS.md) for the org policy,
Dependabot coordination, and monthly health check.
