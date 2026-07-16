# CI Troubleshooting Playbook

Last updated: 2026-07-16 (by `fix/r2-cost-reduction` investigation)

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

**Three fixes were needed (all applied):**

1. **Build-time: `systemctl set-default graphical.target`** in
   `install-desktop.sh` — sets the default target in the image layer.
   Commit `0c36e46`.

2. **Bootc install: `--karg systemd.unit=graphical.target`** in the `Justfile`
   `qcow2` recipe — `bootc install to-disk` creates a fresh OSTree deployment
   that does NOT preserve the default.target symlink from step 1. The kernel
   cmdline override is the only reliable way. Commit `40c66b8`.

3. **Service timeout: `TimeoutStartSec=30`** on `tunaos-desktop-contract.service`
   — prevents a hung `systemctl is-active` call from blocking boot indefinitely.
   Commit `ebdb0cd`.

**Additionally:** `verify-desktop-experience.sh --runtime` was hardened to use
individual gated checks with diagnostic `TUNAOS_DESKTOP_CONTRACT_FAIL` markers
instead of `set -e` killing the script silently. Commit `ebdb0cd`.

**Caveat for NVIDIA images:** The grouped ISO flagship group boots
`gnome-nvidia` by default. In QEMU with virtio-gpu (no NVIDIA hardware),
the NVIDIA kernel modules may interfere with DRM initialisation. This produces
a blank framebuffer even if graphical.target is reached. Two mitigations:
1. The `graphical.target` fix should at least let the contract service run
   (marker appears on serial even if screen is blank).
2. Consider changing the flagship group's default boot entry from
   `gnome-nvidia` to `gnome` for CI boot gates, or adding a
   `--boot-entry <name>` option to `iso-e2e.sh`.

**Timing note:** The fix commits were pushed 2026-07-15 ~14:00 UTC. A Build
Yellowfin dispatch from the branch is needed to test the full fix chain.

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

### 4. LUKS E2E fisherman rewrite — full bug chain (2026-07-16, `fix/r2-cost-reduction`)

Migrating `scripts/iso-e2e.sh --luks` from raw `sudo bootc install to-disk
--block-setup tpm2-luks` to `sudo fisherman recipe.json` (per the Key
Takeaway above) surfaced a chain of real, independent bugs, each only
visible once the previous one was fixed and the run got one step further.
Recorded here so the next similar migration doesn't have to re-discover
each one from scratch.

| # | Symptom | Root cause | Fix |
|---|---|---|---|
| 1 | `scp: stat local "2222": No such file or directory` | Reused ssh's `-p 2222` port flag for scp too — scp's port flag is `-P` (capital); `-p` means "preserve attributes" and consumed the port number as a filename | Separate `-P` for scp, `-p` for ssh |
| 2 | `sudo: fisherman: command not found` | `command -v fisherman` (the gate check) ran as liveuser, whose PATH includes `/usr/local/bin`; `sudo fisherman` uses sudo's `secure_path`, which doesn't | Invoke `/usr/local/bin/fisherman` by full path under sudo |
| 3 | gnome live ISOs had **no** installer Flatpak at all | `customize-live.sh` set `INSTALLER_APP=""` for gnome — only kde/niri/cosmic/xfce get a TunaOS-branded fork | Ship upstream `org.bootcinstaller.Installer` for gnome, fetched as a release bundle + imported into a throwaway local ostree repo (mirrors `projectbluefin/dakota-iso`'s `install-flatpaks.sh`) |
| 4 | `dbus-uuidgen: command not found` (niri/cosmic) | Some flavors don't transitively pull in the package providing `dbus-uuidgen` | Swapped to `systemd-machine-id-setup` (core systemd, always present) |
| 5 | `dbus-run-session: command not found` (niri/cosmic) | Same package gap, different binary | Spin up `dbus-daemon --session` directly instead of the wrapper |
| 6 | `dbus-daemon: command not found` (niri/cosmic) | The gap was the whole `dbus` package, not just specific binaries | Added `dbus-daemon` to `10-base-packages.sh` (both apt and dnf) |
| 7 | grouper: `ERROR: dev ISO requested but no SSH service is installed` | `Justfile`'s `iso` recipe only rebuilt with `ENABLE_SSHD=1` when `repo == "local"`; the workflow calls `... ghcr "" 1`, so the SSH-enabling rebuild never ran for `repo=ghcr` | `dev=1` now always triggers the local SSH-enabled rebuild, regardless of `repo` |
| 8 | grouper: still no SSH after #7 | `Containerfile.ubuntu` never declared `ARG ENABLE_SSHD` — podman silently drops undeclared build-args, so it never reached `40-services.sh`'s apt branch | Added the same `ARG`/`ENV ENABLE_SSHD` pair its sibling Containerfiles (debian, el10, arch, overlay) already have |
| 9 | grouper: `Refusing to operate on linked unit file sshd.service` | Debian/Ubuntu's `openssh-server` ships `sshd.service` as a compat **symlink** to the real `ssh.service` unit; `systemctl enable` refuses to target a linked unit directly | Require `sshd.service` to be a real (non-symlink) file before preferring it, else fall through to `ssh.service` |
| 10 | `'overlay' is not supported over overlayfs, a mount_program is required` | The live squash's own rootfs is overlayfs (squashfs+tmpfs); containers/storage's default `overlay` driver can't nest a second overlay mount on that without a userspace mount_program | Added `fuse-overlayfs` package + `mount_program = "/usr/bin/fuse-overlayfs"` in `/etc/containers/storage.conf`, written by `customize-live.sh` into the live squash (mirrors `projectbluefin/dakota-iso`'s non-composefs storage.conf, `projectbluefin/iso` commit `34fe6659`) |
| 11 | `requires the runtime org.gnome.Platform/x86_64/49 which was not found` | `customize-live.sh` only added the `tuna-os` Flatpak remote (hosts our apps), never `flathub` (hosts the runtimes those apps depend on) | Added `flatpak remote-add ... flathub` — flatpak resolves missing runtime refs from any configured remote |
| 12 | `Pathname can't be converted from UTF-8 to current locale` | Minimal containers (grouper/apt) have no locale beyond POSIX/C (strictly ASCII); glib's path handling requires a UTF-8-capable locale even for ASCII paths | `export LANG=LC_ALL=C.UTF-8` before any flatpak/glib calls in `customize-live.sh` |
| 13 | `ghcr.io/tuna-os/tunaos:yellowfin does not resolve to an image ID` (yellowfin only) | `sudo ./scripts/iso-e2e.sh` in the workflow resets the environment, dropping the `VARIANT`/`FLAVOR` env vars the recipe-building code needs; it fell back to parsing them from the ISO filename, which (for `build-iso-tacklebox.sh`'s raw output `tunaos-<variant>-<flavor>.iso`) has a `tunaos-` project prefix the fallback parser didn't strip, producing `VARIANT=tunaos FLAVOR=yellowfin` | `sudo -E` in the workflow step; also hardened the fallback parser to strip a leading `tunaos-` so a future caller that forgets `-E` degrades correctly instead of building a bogus ref |
| 14 | `ghcr.io/tuna-os/<variant>:<flavor> does not resolve to an image ID` (yellowfin, even with the right ref this time) | Fix #7's Justfile change makes `dev=1` always rebuild **locally**, so the embedded image is actually tagged `localhost/<variant>:<flavor>` in containers-storage — but the recipe still hardcoded the `ghcr.io/tuna-os/` prefix | Changed the recipe's image ref to `localhost/<variant>:<flavor>`, matching what dev/E2E builds are now actually tagged as |
| 15 | grouper:xfce — SSH times out even though `ssh.service` starts fine | Not a fisherman/install bug at all: `lightdm.service` fails to start repeatedly in the live session (pre-existing xfce/lightdm packaging gap on grouper, exposed for the first time now that fix #7/#8 make grouper's dev/E2E ISOs actually build and boot with SSH); the VM shuts itself down from the crash loop before the install step is ever reached | Not fixed — out of scope for the fisherman migration. Use a grouper flavor whose desktop actually boots (kde/niri) to verify the composefs install path instead |
| 16 | `localhost/<variant>:<flavor>` (or `ghcr.io/...`) — `does not resolve to an image ID` | Neither ref is a queryable tag in the live squash's actual containers-storage, even though `localhost/<variant>:<flavor>` is literally what tacklebox's own `recipe.json` embeds — it isn't preserved as a lookup-able tag once squashed | For non-composefs (default): leave `image` and `targetImgref` **empty**, so fisherman adds no `--source-imgref` at all and bootc auto-detects the running container natively — the documented behavior for exactly this case (see fisherman's `recipe.Validate()` comment). Composefs (grouper) still needs a real ref (skopeo has to copy from containers-storage by name before bootc runs), so it's unresolved there — moot for now since bug #17 blocks grouper before install is ever reached |
| 17 | grouper (any flavor) — `sddm`/`ssh.service` both start successfully, but SSH never connects; VM eventually shuts itself down | Serial log never reaches `network.target`/`network-online.target` — no DHCP/network-configuration service (systemd-networkd, NetworkManager) ever runs in grouper's live squash, so `eth0` never gets an IP and QEMU's `hostfwd` can't reach it at the TCP/IP level even though sshd is listening | Not fixed — a foundational live-ISO networking gap for the Ubuntu variant, affects every grouper flavor uniformly regardless of desktop, unrelated to fisherman/install logic. Needs its own investigation into what network service grouper's live squash should enable |
| 18 | `Either --source-imgref must be defined or this command must be executed inside a podman container` | Bug #16's fix (leave image/targetImgref empty for auto-detect) was based on a wrong reading of fisherman's docs — that auto-detect only works when bootc itself runs **inside a `podman run` container** (fisherman's `bootcViaContainer` path). Our live squash isn't a podman container at runtime, and fisherman's `bootcDirect` mode (what always runs here) calls `bootc install to-filesystem` completely natively — no container context exists to introspect at all | Stopped guessing/theorizing about the ref entirely: SSH into the live VM and ask it directly — `sudo podman images --format '{{.Repository}}:{{.Tag}}'`, filtered to skip untagged entries — then use whatever it actually reports as both `image`/`targetImgref` |
| 19 | `podman images -a` returns nothing at all — bug #18's query came back empty | **Root cause of the entire bugs #13-18 saga**: TunaOS's tacklebox pipeline doesn't embed a local OCI image store into the live squash at all — no `podman images` entries, no `/usr/share/tuna-installer/oci-store`, no `/var/lib/superiso-store` (both nonexistent). The live system boots as a deployed ostree/bootc filesystem directly, never "as a container" with a local copy anywhere. Confirmed by reading `projectbluefin/dakota-iso`'s own git history (commit `57c9672`): they hit the identical bug class and fixed it by *actually embedding* an OCI layout at `/var/lib/containers/oci-store` and pointing `image`/`local_imgref` at `oci:<path>` — infrastructure TunaOS's tacklebox doesn't build (a separate, out-of-scope feature) | Set the recipe's `image` field (not just `targetImgref`) to the real `ghcr.io/tuna-os/<variant>:<flavor>` ref. This routes through fisherman's `bootcViaContainer` instead of `bootcDirect` — `CheckImage()` correctly sees nothing local, actually `podman pull`s over the network, then runs bootc inside that freshly pulled container. This is fisherman's normal designed path for a machine with no embedded local store (i.e. a real production install target) |

**Pattern to notice (bugs #1-14):** almost every bug here was a live-squash-specific
environment gap (missing package, missing locale, missing remote, wrong
storage driver) that a *normal* container build never hits — the live ISO's
minimal customize-time container and its overlayfs-on-overlayfs runtime
environment are much less forgiving than either a regular build or an
already-installed system. When adding new live-squash logic, assume nothing
beyond what `10-base-packages.sh` explicitly installs, and test the actual
QEMU boot — a build-time success proves nothing about the live-boot
environment.

---

## Glossary of Components

| Tool | Role | Source |
|------|------|--------|
| **tacklebox** | ISO builder — takes a recipe.json with bootable environments and produces a combined ISO with dedup squashfs | `github.com/tuna-os/tacklebox` |
| **fisherman** | Disk installer — takes a recipe.json with disk/image/encryption params and runs the full install (partition, format, bootc install, flatpaks, hostname) | `github.com/projectbluefin/fisherman` (cloned at `_upstream-snapshots/fisherman/`) |
| **bootc-installer** | GTK/libadwaita installer frontend — wraps fisherman for GUI installs | `github.com/projectbluefin/bootc-installer` (cloned at `_upstream-snapshots/bootc-installer/`) |
| **remora (n)** | Package layering CLI — installs additional RPMs/packages on top of a bootc base image | `github.com/tuna-os/remora` |
| **dakota** | Bluefin buildstream — defines the Bluefin CI pipeline for building bootc images | `github.com/projectbluefin/dakota` (cloned at `_upstream-snapshots/dakota/`) |
| **dakota-iso** | Bluefin ISO build pipeline — the full live ISO / installer / E2E test setup (luks-install-qemu.sh, fisherman-install.sh, etc.) | `github.com/projectbluefin/dakota-iso` (cloned at `_upstream-snapshots/dakota-iso/`) |

### What goes where

- **tacklebox** runs on the **host** (or in CI) — builds ISO from published images
- **fisherman** runs **inside the live VM** (or container) — installs to disk
- **bootc-installer** runs **inside the live session** as a Flatpak — shows the GUI
- **remora** runs **inside the installed system** — layers packages
- **dakota-iso** is the **reference pattern** for how all these fit together

### Key takeaway

Every place in our code that calls `bootc install to-disk` directly should be
replaced with `fisherman recipe.json`. This is how dakota-iso does it. The
fisherman tool:
- Handles ostree vs composefs backend selection
- Preserves graphical.target on EL10 (ostree) via proper kernel kargs
- Handles LUKS/TPM encryption
- Installs flatpaks post-install
- Sets hostname
- Creates user accounts

See `_upstream-snapshots/dakota-iso/scripts/luks-install-qemu.sh` for end-to-end
example including recipe generation, fisherman building, SCP upload, and SSH invocation.

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

## Serial Log Deep Diagnosis

For boot-gate timeouts, download the gate artifact and inspect the raw serial log:

```bash
# Download the artifact (name from the workflow log — e.g. "boot-gate-yellowfin-gnome")
gh run download <run-id> -n boot-gate-yellowfin-gnome -D /tmp/gate-artifact

# Follow the boot timeline — this tells you EXACTLY where it failed
cat /tmp/gate-artifact/serial.log | grep -oP '\[.*?\]|TUNAOS_|gdm|display-manager|graphical|poweroff|shutdown|contract|error|fail' | uniq

# Check the full timeline at key transition points:
grep -n "Stopped\|Started\|gdm\|contract\|poweroff\\|shutdown\|TUNAOS" /tmp/gate-artifact/serial.log

# See what the VM looked like at timeout:
eog /tmp/gate-artifact/10-ready.ppm  # or similar viewer
```

### What to look for in serial.log

| Pattern | Means | Action |
|---------|-------|--------|
| `Started gdm.service` then `localhost login:` | Display server crashed, fell back to text getty | Check GDM journal, check NVIDIA/virtio-gpu driver |
| `Starting tunaos-desktop-contract.service` with no `Started`/`Finished` | Service hung — likely `systemctl is-active` blocking on dbus | Add `TimeoutStartSec=30` |
| `TUNAOS_DESKTOP_CONTRACT_FAIL reason=*` | Individual check failed | Use the reason field to identify which check |
| `Reached target initrd-switch-root.target` then `Powering off` | System booted initrd but the cleanup sent `system_powerdown` after timeout | Graphical.target was never reached |
| `Started plymouth-poweroff.service` | System is shutting down (cleanup via monitor socket) | Timeout expired first |

## Key Files in the Boot Chain

```
Containerfile.el10
  └── build_scripts/10-base-packages.sh    # core packages (flatpak, etc.)
  └── build_scripts/install-desktop.sh     # DE install + graphical.target fix (BUILD LAYER ONLY!)
        └── creates tunaos-desktop-contract.service (TimeoutStartSec=30)
              └── calls build_scripts/verify-desktop-experience.sh --runtime
                    └── emits TUNAOS_DESKTOP_CONTRACT_OK or FAIL on ttyS0

Justfile (qcow2 recipe)
  └── bootc install to-disk --karg systemd.unit=graphical.target  # CRITICAL — overrides OSTree default

scripts/iso-e2e.sh                          # boot gate harness
  ├── ready mode: waits for TUNAOS_LIVE_READY
  ├── disk mode:  waits for TUNAOS_DESKTOP_CONTRACT_OK
  └── cleanup: sends system_powerdown → serial log shows shutdown sequence

live-iso/common/src/customize-live.sh       # live ISO squashfs customization
  └── creates tunaos-live-ready.service
        └── emits TUNAOS_LIVE_READY on ttyS0

build_scripts/verify-desktop-experience.sh  # contract check (build + runtime)
  ├── build mode: creates /usr/share/tunaos/experience-contracts/<desktop>
  └── runtime mode: gated checks with diagnostic FAIL markers on ttyS0

Containerfile.overlay (OVERLAY_TYPE=nvidia)
  └── build_scripts/nvidia.sh               # NVIDIA AKMOD RPM install
```

## Critical architectural insight: IMAGE vs OSTREE DEPLOYMENT

A common source of confusion: `systemctl set-default graphical.target` in
`install-desktop.sh` works during the Containerfile build, but `bootc install
to-disk` creates a **fresh OSTree deployment** that does NOT preserve the
default.target symlink **on ostree-backend variants only**.

### Backend distinction

| Backend | Variants | Bootloader | Loses graphical.target? |
|---------|----------|------------|------------------------|
| **ostree** | EL10 (yellowfin, albacore, skipjack) | grub2 (bootupd) | ✅ YES |
| **composefs** | Fedora, Ubuntu, Arch, Debian, openSUSE, Gentoo | systemd-boot | ❌ NO |

The kernel cmdline override `systemd.unit=graphical.target` is the only reliable
way to ensure EL10 installed systems reach graphical.target.

### Fisherman recipe approach (replaces raw `bootc install to-disk`)

The proper fix is to use `fisherman` (from `projectbluefin/fisherman`, cloned at
`_upstream-snapshots/fisherman/`) with a recipe.json. The recipe selects the backend:

```json
{
  "disk": "/dev/vda",
  "filesystem": "xfs",
  "image": "containers-storage:localhost/yellowfin:gnome",
  "composeFsBackend": false,     ← false for EL10 (ostree), true for others (composefs)
  "bootloader": "systemd",
  "hostname": "tunaos-test",
  "encryption": {"type": "tpm2-luks"},
  "flatpaks": []
}
```

See `_upstream-snapshots/fisherman/fisherman/internal/recipe/recipe.go` for the full
Recipe struct with all fields.

This means:
- **For boot gates (disk mode):** the `--karg systemd.unit=graphical.target` in
  the `Justfile` `qcow2` recipe is a short-term workaround for EL10 only. The
  proper fix is to switch to `fisherman recipe.json` everywhere
- **For live ISO (ready mode):** the live squashfs uses the image's default target
  directly (no OSTree deployment), so the `set-default` in install-desktop.sh works
- **For real installed systems:** users never hit this because they bootc install
  and their system already runs graphical=true before install... but VERIFY this

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
