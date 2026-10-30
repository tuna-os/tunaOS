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
| `promote-stable.yml` | RFC 018 `:testing` → `:stable` promotion. Daily at 06:00 UTC, it moves the bare tags of each cell to a soaked `:testing` image (see [Stable promotion](#stable-promotion)) |

---

## How a Build Works

1. **Matrix generation** — `build-variant.yml` reads `build-config.yml`, emits per-stage matrices
2. **Stage 1** — builds `base` (Containerfile `base-no-de` target)
3. **Stage 2** — builds DE images via `install-desktop.sh <de>` (reads YAML manifests)
4. **Stage 3-4** — layers HWE/nvidia via `Containerfile.overlay`
5. **Rechunk** — chunkah makes ostree-optimized layers for delta updates
6. **Boot gate** — Corral boots the `-candidate` image under QEMU, and Promote waits for the result (see [Boot gates](#boot-gates)). Promote writes `:<flavor>-testing` and the dated tags. The bare `:<flavor>` tags move later, in `promote-stable.yml`.
7. **Publish** — multi-arch manifest pushed to the resolved registry, signed with cosign.
   - `ghcr.io/<owner>` uses `GITHUB_TOKEN`.
   - Any other destination needs the `TUNAOS_PUBLISH_*` credential. [RFC 016](rfc/rfc016-publish-credentials.md) lists the jobs that choose and use it.

---

## Stable promotion

[RFC 018](rfc/rfc018-testing-stable-rings.md) splits each cell into two rings. The `:<flavor>-testing` ring gets every image that passes CI. The bare `:<flavor>` tag is the `:stable` ring, and it gets a `:testing` image only after a soak. `promote-stable.yml` runs `scripts/promote-stable.py` daily at 06:00 UTC. It can also run manually for one or more cells (`cell` input, for example `albacore:gnome,yellowfin:*`).

**Modes.** A scheduled run uses `promote`. A manual run uses the `mode` input, `dry-run` by default:

- `dry-run` writes only the log and the summary.
- `promote` moves the stable tags of each `PROMOTE` cell.
- `rollback` repoints the stable tags of one `cell` to the dated tag `rollback_to`. It needs a non-empty `reason`. A `dry-run` with `rollback_to` shows the tags that the rollback writes. See [the rollback runbook](../runbooks/rollback-a-bad-image-promotion.md).

**Jobs.** The `Evaluate` job is read-only. In `promote` and `rollback` mode, it writes a plan (artifact `promote-stable-plan`) with the tags to write, each source digest, and the stable digest that it evaluated. The `Write stable tags` job is the only job with `packages: write`. For each cell in the plan it:

1. Reads the bare tag and each source again. If one of them moved after the evaluation, it skips the cell (`SKIPPED`) and writes nothing.
2. Copies by digest (`skopeo copy --all --preserve-digests`), with retries: `<tag>-YYYYMMDD` to `<tag>`, `<tag>-<arch>-YYYYMMDD` to `<tag>-<arch>` for each platform, and `<tag>-YYYYMMDD` to `<alias>:<tag>` for each `aliases:` entry in `build-config.yml`. It writes the bare tag last, so a failed copy leaves `:stable` where it was.
3. Reads each written tag. A digest that is not the source digest, or a failed copy, fails the run (`FAILED`).

The job summary has one row for each cell with the result and the tags written. The workflow runs one at a time and never cancels a run in progress.

**Bootstrap.** A new cell has no bare tag. Promote in `reusable-build-image.yml` writes the bare, arch and alias tags of a cell only when the bare `:<tag>` does not exist yet. Thus users can install a new cell before its first soak. If Promote cannot read the bare tag, it does not write it. An alias added to a cell that has a bare tag gets `<alias>:<tag>` at the next promotion of the cell.

For each cell, the script reads the dated tags `<tag>-YYYYMMDD` for the last 30 days, newest first. A dated tag records the day that its digest became the cell's `:testing` image. The script selects the newest digest that has soaked for `soak_days`. The default is 3 days in `[defaults]` of `tunaos.toml`, and a variant can set its own value (yellowfin: 5).

The soak starts at the end of the dated day. Thus a digest dated D with a 3-day soak is eligible from D+4 at 00:00 UTC. Then the script checks these gates:

| Gate | Holds the cell when |
|---|---|
| release-blocker | An open issue with the `release-blocker` label names the cell in its title (`albacore:gnome` or `bonito:kde-rawhide`), or has the label `variant/<variant>`. |
| desktop contract | The newest `desktop-contract-sweep.yml` result for the cell (artifact `desktop-contract-baseline`, `all.json`) is not `pass`, is missing, or is older than the candidate. A `-hwe`, `-nvidia` or other derived flavor uses its desktop's result. A flavor without a swept desktop (`base`, `tuna`) is `n/a`. |
| lifecycle | A job for the cell (`variant:flavor (arch)`) failed or timed out in the newest completed scheduled `bootc-lifecycle.yml` run. That workflow checks the published bare tag, which is the current `:stable` image, not the candidate. A cell that the run did not check (the beta lane) is `n/a`. |
| Soak-After | A commit between the stable revision and the candidate revision has a `Soak-After: <N>d` trailer, and the candidate is younger than the largest N. |

The revision is `org.opencontainers.image.revision`. If that label is missing, the script uses `org.opencontainers.image.version`, which `Containerfile.final` sets to the short build commit. The workflow reads the commit range from a full-history checkout. A cell is held if the script cannot read a fact. The run stays green when it holds cells.

**How to read the output.** The log and the job summary have one row for each cell:

- `PROMOTE` — all gates passed. In `promote` mode, the `Write stable tags` job moves the stable tags of the cell to the candidate digest.
- `HOLD` — the reason names each gate that held the cell, for example `soak: ... eligible 2026-11-02T00:00Z` or `release-blocker: #1234 (title)`.
- `NOOP` — the stable tag points at the selected digest, or at a newer digest (`stable is ahead`). Stable is ahead after a manual repoint or a bootstrap. It is also ahead in the first days of RFC 018 phase 3. Until then, Promote wrote the bare tags. Stable does not move back. The **Gate verdict** column shows the decision of the gates for the soaked digest.

Run it locally (read-only; needs `skopeo`, `gh` and a full-history clone):

```bash
python3 scripts/config.py generate
python3 scripts/promote-stable.py evaluate --cell 'albacore:gnome,yellowfin:gnome' --summary ''
```

`--mode promote --plan plan.json` also writes the plan. `apply --plan plan.json` writes the tags; it needs a registry login that can write packages.

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
