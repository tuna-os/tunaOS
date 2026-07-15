# CI Troubleshooting Playbook

Last updated: 2026-07-15 (by `fix/r2-cost-reduction` investigation)

Quick reference for diagnosing recurring CI failures. These were surfaced during a
branch-integration push that touched 36 files across `.github/`, `build_scripts/`,
`live-iso/`, `scripts/`, and `tests/`.

---

## Failure Catalog

### 1. `flatpak: command not found` in live ISO customization

**Affected workflows:** `LUKS E2E` (yellowfin:kde), any live ISO build for EL10
non-GNOME desktops.

**Symptom:**
```
./customize-live.sh: line 116: flatpak: command not found
```

**Root cause:** `build_scripts/10-base-packages.sh` installs `flatpak` in the Fedora
and apt (Debian/Ubuntu) package blocks but **not** in the EL10 (AlmaLinux/CentOS
Stream/RHEL) common-packages block (line ~214). `customize-live.sh` calls
`flatpak remote-add` unconditionally when `INSTALLER_APP` is set (i.e. any
non-GNOME desktop).

**Fix:**
1. **Primary:** Add `flatpak` to the EL10 `dnf_retry -y install` block in
   `10-base-packages.sh` (sorted alphabetically under `fastfetch`).
2. **Belt-and-suspenders:** `customize-live.sh` now checks `command -v flatpak`
   before attempting any flatpak operations and exits with a clear error
   instead of a confusing "command not found" at line 116.

**Files changed:**
- `build_scripts/10-base-packages.sh` — added `flatpak` to EL10 packages
- `live-iso/common/src/customize-live.sh` — added flatpak guard

**Verification:** After the fix, EL10 KDE/Niri/Cosmic/Xfce images will have
flatpak in the base layer. The guard in customize-live.sh provides defense in
depth — if flatpak is ever missing again, the error message identifies the
problem immediately.

---

### 2. Boot gate timeout — desktop experience contract never emitted

**Affected workflows:** `Build Yellowfin` (gnome gate), `Publish Grouped Dedup
ISOs` (boot gate), any workflow that runs `iso-e2e.sh --disk` or `iso-e2e.sh`
ready mode.

**Symptom (disk mode):**
```
ERROR: desktop experience contract marker was not emitted
==> Screenshot 10-ready stddev=0
==> Screenshot 10-ready looks blank (stddev=0 <= 0.02)
```

**Symptom (ISO ready mode):**
```
ERROR: readiness marker not seen within 900s
[serial output stops growing after ~2 min]
```

**Root cause chain:**
```
Server-oriented bootc bases (AlmaLinux) default to multi-user.target
  → display manager enabled but system never transitions to graphical.target
    → tunaos-desktop-contract.service (WantedBy=graphical.target) never runs
      → TUNAOS_DESKTOP_CONTRACT_OK / TUNAOS_LIVE_READY never emitted
        → boot gate times out
```

**Architecture context:**

The readiness markers live in two places depending on boot mode:

| Mode | Script | Waits for | Who emits it |
|------|--------|-----------|--------------|
| ISO boot (`ready`) | `iso-e2e.sh` ready mode | `TUNAOS_LIVE_READY` | `tunaos-live-ready.service` (set up by `customize-live.sh`) |
| Disk boot (`--disk`) | `iso-e2e.sh` disk mode | `TUNAOS_DESKTOP_CONTRACT_OK` | `tunaos-desktop-contract.service` (set up by `install-desktop.sh`) |

Both services are WantedBy/After `graphical.target` or `display-manager.service`,
so neither runs if the system stays at multi-user.target.

**PRIMARY FIX (applied):** `build_scripts/install-desktop.sh` now calls
`systemctl set-default graphical.target` after enabling the display manager.
Commit `0c36e46`.

**SECONDARY FIX (applied):** `bootc install to-disk` does not preserve the
`default.target` symlink through OSTree deployment — `graphical.target` is
never reached despite the build-time fix. The `just qcow2` recipe now passes
`--karg systemd.unit=graphical.target` to `bootc install to-disk`, forcing
the correct boot target via kernel command line. Commit `40c66b8`.

**Caveat for NVIDIA images:** The grouped ISO flagship group boots
`gnome-nvidia` by default. In QEMU with virtio-gpu (no NVIDIA hardware),
the NVIDIA kernel modules may interfere with DRM initialisation. This produces
a blank framebuffer even if graphical.target is reached. Two mitigations:
1. The `graphical.target` fix should at least let the contract service run
   (marker appears on serial even if screen is blank).
2. Consider changing the flagship group's default boot entry from
   `gnome-nvidia` to `gnome` for CI boot gates, or adding a
   `--boot-entry <name>` option to `iso-e2e.sh`.

**Timing note:** The fix commit was pushed 2026-07-15 ~12:00 UTC. Images built
before that do not have the fix. The scheduled `Build Yellowfin` and manual
workflow_dispatch runs must complete before the `gnome-testing` tag is updated.
Boot gates on old images will continue to fail until then.

---

### 3. Grouped ISO recipe build failure (schedule-only)

**Affected workflow:** `Publish Grouped Dedup ISOs to R2` (schedule trigger only)

**Symptom:**
```
Error: read recipe .build/iso-group/yellowfin/recipe.json:
  open .build/iso-group/yellowfin/recipe.json: no such file or directory
error: Recipe 'iso-group' failed on line 182 with exit code 1
```

**Observed:** All schedule runs (`0 23 * * 0`) from 2026-06-15 through
2026-07-13 failed this way. Manual `workflow_dispatch` runs (July 15) succeeded
at the build step (they fell through to the boot gate).

**Suspected cause:** Either:
- A now-removed `iso_groups` entry (e.g. an "nvidia" suffix group) was present
  during the schedule window and its intersection with variant flavors was
  empty, causing `build-iso-group.sh` to fail before creating the recipe.
- Or the schedule trigger's environment/defaults differ from workflow_dispatch
  in a way that breaks the matrix generation (`generate-matrix` step).

**Status:** Not yet root-caused. The schedule failures have stopped since the
config was simplified to two groups (flagship + community). Monitor the next
Sunday run (2026-07-20).

---

## Diagnostic Commands

```bash
# List recent failures for a workflow
gh run list --limit 10 --workflow "LUKS E2E"

# Get failure details
gh run view <run-id> --log 2>&1 | grep -E "error|ERROR|exit status|flatpak|readiness"

# Check which job failed
gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .name'

# Check all recent runs across workflows
gh run list --limit 20
```

## Key Files in the Boot Chain

```
Containerfile.el10
  └── build_scripts/10-base-packages.sh    # core packages (flatpak, etc.)
  └── build_scripts/install-desktop.sh     # DE install + graphical.target fix
        └── creates tunaos-desktop-contract.service
              └── calls build_scripts/verify-desktop-experience.sh --runtime
                    └── emits TUNAOS_DESKTOP_CONTRACT_OK on ttyS0

scripts/iso-e2e.sh                          # boot gate harness
  ├── ready mode: waits for TUNAOS_LIVE_READY
  └── disk mode:  waits for TUNAOS_DESKTOP_CONTRACT_OK

live-iso/common/src/customize-live.sh       # live ISO squashfs customization
  └── creates tunaos-live-ready.service
        └── emits TUNAOS_LIVE_READY on ttyS0

Containerfile.overlay (OVERLAY_TYPE=nvidia)
  └── build_scripts/nvidia.sh               # NVIDIA AKMOD RPM install
```

## Build Gate Workflow

```
gnome-testing tag published
  → Build Yellowfin workflow: bootc install to-disk → qcow2
    → Boot gate: iso-e2e.sh --disk qcow2
      → waits for TUNAOS_DESKTOP_CONTRACT_OK

Grouped ISO workflow:
  → just iso-group <variant> <group> ghcr
    → scripts/build-iso-group.sh → tacklebox → ISO
      → Boot gate: iso-e2e.sh ISO (ready mode)
        → waits for TUNAOS_LIVE_READY + screenshot sanity
```

## Confirmed Gate Failures (2026-07-15)

All failing gates share the same root cause — images built before the
`graphical.target` fix (commit `0c36e46`, pushed ~12:00 UTC):

| Workflow | Variant:Flavor | Mode | Error |
|----------|---------------|------|-------|
| Build Yellowfin | yellowfin:gnome | disk | `TUNAOS_DESKTOP_CONTRACT_OK` not emitted |
| Build Grouper | grouper:niri | disk | `TUNAOS_DESKTOP_CONTRACT_OK` not emitted |
| Publish Grouped ISOs | yellowfin (flagship) | ISO ready | `TUNAOS_LIVE_READY` not emitted + blank screen |
| LUKS E2E | yellowfin:kde | ISO → install | `flatpak: command not found` (separate root cause, see §1) |

Once new images are published with the `graphical.target` fix, all three boot-gate
timeouts should resolve (assuming no NVIDIA-driver interaction in §2 caveat).
