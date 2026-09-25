# CI Troubleshooting Playbook

Last updated: 2026-07-16 (by `fix/r2-cost-reduction` investigation)

Quick reference to diagnose CI failures that recur. A branch-integration push
that touched 36 files across `.github/`, `build_scripts/`, `live-iso/`,
`scripts/`, and `tests/` surfaced them.

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
   before it runs any flatpak operation. It exits with a clear error instead of
   the unclear "command not found" at line 116.

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

The readiness markers live in two places, one for each boot mode:

| Mode | Script | Waits for | Who emits it |
|------|--------|-----------|--------------|
| ISO boot (`ready`) | `iso-e2e.sh` ready mode | `TUNAOS_LIVE_READY` | `tunaos-live-ready.service` (set up by `customize-live.sh`) |
| Disk boot (`--disk`) | `iso-e2e.sh` disk mode | `TUNAOS_DESKTOP_CONTRACT_OK` | `tunaos-desktop-contract.service` (set up by `install-desktop.sh`) |

Both services are WantedBy/After `graphical.target` or `display-manager.service`,
so neither runs if the system stays at multi-user.target.

**Three fixes, all applied:**

1. **Build-time: `systemctl set-default graphical.target`** in
   `install-desktop.sh` — sets the default target in the image layer.
   Commit `0c36e46`.

2. **Bootc install: `--karg systemd.unit=graphical.target`** in the `Justfile`
   `qcow2` recipe. `bootc install to-disk` creates a fresh OSTree deployment.
   That deployment does NOT preserve the default.target symlink from step 1.
   The kernel cmdline override is the only reliable way. Commit `40c66b8`.

3. **Service timeout: `TimeoutStartSec=30`** on `tunaos-desktop-contract.service`
   — a hung `systemctl is-active` call then cannot block the boot indefinitely.
   Commit `ebdb0cd`.

**Also:** we hardened `verify-desktop-experience.sh --runtime` to use
individual gated checks with diagnostic `TUNAOS_DESKTOP_CONTRACT_FAIL` markers,
instead of `set -e`, which killed the script silently. Commit `ebdb0cd`.

**Caveat for NVIDIA images:** The flagship group of the grouped ISO boots
`gnome-nvidia` by default. In QEMU with virtio-gpu (no NVIDIA hardware),
the NVIDIA kernel modules may interfere with DRM initialisation. This produces
a blank framebuffer even if the system reaches graphical.target. Two mitigations:
1. The `graphical.target` fix should at least let the contract service run
   (marker appears on serial even if screen is blank).
2. For CI boot gates, consider a change of the flagship group's default boot
   entry from `gnome-nvidia` to `gnome`. A new `--boot-entry <name>` option
   for `iso-e2e.sh` is an alternative.

**Timing note:** We pushed the fix commits 2026-07-15 ~14:00 UTC. To test the
full fix chain, dispatch Build Yellowfin from the branch.

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
- A now-removed `iso_groups` entry (e.g. an "nvidia" suffix group) existed
  during the schedule window. Its intersection with variant flavors was empty,
  so `build-iso-group.sh` failed before it created the recipe.
- Or the schedule trigger's environment/defaults differ from workflow_dispatch
  in a way that breaks the matrix generation (`generate-matrix` step).

**Status:** Not yet root-caused. The schedule failures have stopped since we
simplified the config to two groups (flagship + community). Monitor the next
Sunday run (2026-07-20).

---

### 4. LUKS E2E fisherman rewrite — full bug chain (2026-07-16, `fix/r2-cost-reduction`)

The move of `scripts/iso-e2e.sh --luks` from raw `sudo bootc install to-disk
--block-setup tpm2-luks` to `sudo fisherman recipe.json` (per the Key
Takeaway above) surfaced a chain of real, independent bugs. Each bug became
visible only after a fix for the previous one let the run go one step further.
This record exists so the next similar migration doesn't have to re-discover
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
| 20 | Network pull stalls indefinitely mid-blob — zero output for 2+ hours before a hard `timeout 1800` (added defensively once #19 made the pull real) started firing instead | Serial log showed 41 layers pulling cleanly in under a minute (~1/sec), then complete silence starting the blob copy for layer 42/65 — no error, no further progress, ever. First theory: QEMU SLIRP Path-MTU-Discovery blackhole, fixed by clamping the guest's own interface MTU to 1400. **Disproven by a second run**: with the MTU clamp applied, the pull stalled on the exact same blob (`sha256:a525a8e1...`) for the same ~29 minutes. Checked whether that blob was anomalously large via GHCR's manifest API directly (`skopeo` isn't installed on this box; used `curl`+the registry's token endpoint instead) — it's 77MB, unremarkable next to several 200-400MB layers earlier in the same manifest that pulled fine. So this isn't a size- or MTU-triggered fragmentation issue; root cause is unresolved (plausibly SLIRP NAT connection-tracking flakiness under the GitHub Actions runner's own nested virtualization) | Stopped trying to prevent the stall and instead made it recoverable: pre-pull the image with `podman pull` in a retry loop (4 attempts, 600s each) before invoking fisherman. `podman pull` skips layers already present in local storage, so a retry after a stall only has to re-fetch the blob that didn't finish, not the whole image; once the image is local, fisherman's `bootcViaContainer` `CheckImage()` finds it and skips its own pull entirely. The guest-side MTU clamp (bug #20 v1) is left in place since it's harmless, but is not the operative fix. **Superseded by bug #21** — the real fix eliminates the network pull entirely. |
| 21 | Network pull stall (bug #20) is a symptom: the ISO already embeds an offline payload store (`LiveOS/store.squashfs.img`, built by tacklebox's `BuildOfflineStore()`) but the live system never mounts it, so fisherman's only option was the network path | tacklebox correctly builds an overlay-driver containers-storage of the payload image and places it at `LiveOS/store.squashfs.img` on the ISO (confirmed by reading tacklebox's `offline_store.go` and `build.go`). However: (1) the live system had no systemd mount unit to loop-mount it, (2) `/etc/containers/storage.conf` had no `additionalimagestores` entry pointing at the mount point, so podman/buildah/bootc could never find images inside the additional store even if it were mounted. Pattern: projectbluefin/dakota-iso's approach (their `configure-live.sh` mounts/registers the store), adapted for tacklebox's separate-store format (dakota-iso has since moved to embedding the store directly in the main squashfs as VFS at `/var/lib/containers/storage`, but the mount-based approach is correct for tacklebox's current output). | **Part 1 — `customize-live.sh`**: Added `var-lib-superiso\x2dstore.mount` systemd unit (loop-mounts `LiveOS/store.squashfs.img` → `/var/lib/superiso-store`), enabled via `local-fs.target.wants`. Added `/etc/containers/storage.conf.d/99-tunaos-offline-store.conf` with `additionalimagestores = ["/var/lib/superiso-store"]`. The existing `fuse-overlayfs` mount_program config (bug #10) is still required — the live rootfs is overlayfs and the additional store is overlay-driver. **Part 2 — `scripts/iso-e2e.sh`**: Probes the guest for `podman image exists localhost/<v>:<f>` (dev ISOs) and `ghcr.io/tuna-os/<v>:<f>` (production ISOs); if found, sets recipe `image` to `containers-storage:<ref>` — no network pull needed. Falls back to the bug #20 retry loop only when the offline store is absent (older ISOs). `targetImgref` always names the GHCR production ref so the installed system tracks the right image for updates. |
| 22 | The 2026-09-01 monthly sweep failed at **Build dev ISO in every cell of all 15 variants** (run 33506738063) — no cell ever reached QEMU, so no LUKS behaviour was tested at all | `luks-e2e.yml` hardcoded `TACKLEBOX_SHA: fd95174` (2026-07-31). `image-versions.yaml` records that commit as a **floor, not a ceiling** — it is the one that replaced tacklebox's baked-in `--omit "tpm2-tss pcsc"` with a per-image probe — and the tracked pin moved to `f3dd168` on 2026-08-20 for tacklebox#235 ("iso-smoke on RunsOn + k8s-file logging"), because the runner images have no journald for the container and every tacklebox podman run otherwise dies in conmon. Pinned at July, this workflow could not build an ISO on those runners at all. Cross-check: `installer-smoke.yml` takes the tracked pin and built the same `marlin:kde` dev ISO successfully on 2026-09-02 (run 33634610625) — same runners, same ISO, newer tacklebox | Deleted the hardcoded `TACKLEBOX_SHA` from `luks-e2e.yml` so `scripts/lib/common.sh` falls back to the reviewed, Renovate-watched pin in `image-versions.yaml`. `publish-iso-groups.yml` had the same defect one month deeper (`a105d6d`, 2026-07-18, five red runs) and was unpinned with it. **Rule:** a workflow that pins tacklebox by SHA silently stops tracking the floor the moment it is written — pin in `image-versions.yaml` or not at all |
| 23 | Local `just build <variant> <flavor>` dies at Pass 3 with `writing blob to file "/tmp/container_images_storage.../35": no space left on device`, after the image itself built fine | Not a repo bug — a workstation one. `scripts/build-image-inner.sh` honours `TMPDIR` for both the chunkah scratch dir and `podman load`, and on an atomic desktop (Bluefin here) `/tmp` is a 7.7 GB RAM-backed tmpfs, which a ~4 GB rechunked OCI archive plus podman's staging copy overruns. CI runners have a disk-backed `/tmp`, which is why this never appears there | Build with a disk-backed scratch: `TMPDIR=/var/tmp/tunaos-build just build ...`. Note the failing step runs `podman system prune -af` just before it, so a failure here costs the whole build cache — set `TMPDIR` on the first attempt, not the second |
| 24 | `marlin:kde`'s live session started only intermittently — sometimes the installer, sometimes a black screen with **stddev exactly 0** and no `TUNAOS_LIVE_READY` marker — and SSH into the live env was ALWAYS refused (`kex_exchange_identification: Connection reset by peer`, TCP and vsock alike). LUKS E2E stayed green throughout, because `--luks` drives fisherman over SSH and never looks at the screen | **Two independent causes, both named by the guest's own diagnostics dump** (`tunaos-live-debug`, captured on a boot with `ready=0`). (1) `flatpak-preinstall.service` is `Type=oneshot` + `WantedBy=multi-user.target`, so the target waits for a flatpak download and `graphical.target` waits on the target — at 40s the dump showed it `start running` with `multi-user.target`, `graphical.target` and `tunaos-live-ready.service` all `start waiting`. One blocker, three symptoms, and intermittent purely because it tracked the download (markers observed at 9s, 98s, and never). (2) The Justfile runs the ISO build under `sudo -E`, which preserves `HOME`, and podman picks its store from `HOME` — so the build read images from the invoking user's *rootless* store while `mksquashfs` ran as real root outside that namespace, recording uid 1000 for every file in the live root (`/usr`, `/usr/bin/sshd`, `/usr/share/empty.sshd` all `755 james:james`). sshd refuses its privsep directory outright (`must be owned by root`), exits 255 and restart-loops. It also silently defeated `tunaos_import_to_root_storage`, whose `podman image exists` probe found the image in the user's store and returned early | **Fixed and verified.** `customize-live.sh` masks `flatpak-preinstall.service` in the live squash (installed systems keep the curated app set); `build-iso-tacklebox.sh` pins `HOME=/root` and clears `XDG_DATA_HOME`/`XDG_CONFIG_HOME` in the root context. Rebuilt ISO measures `755 root:root` on `/usr/share/empty.sshd` and `flatpak-preinstall.service -> /dev/null`; the boot then reached `TUNAOS_LIVE_READY uptime=6.97` (was 98s or never), `ok - ssh daemon is active`, and the harness completed its in-guest smoke suite over SSH for the first time. Both pinned by bats tests. Remaining nit, not a product fault: KDE composites through llvmpipe, so the installer lands on screen well after the Plasma splash — the checkpoint runner re-captures for `TBOX_E2E_CHECKPOINT_SETTLE` (240s) rather than judging the splash frame |
| 25 | `marlin:cosmic`'s live ISO shows no desktop and no installer, while looking healthy by every usual check: greetd active, autologin succeeded (`pam_unix(greetd:session): session opened for user liveuser`), `graphical.target` active, **zero failed units**, `cosmic-greeter` inactive (correct — the live adapter masks it deliberately) | greetd's `source_profile` defaults to true, so it does not exec the session command — it wraps it in `/bin/sh -c '[ -f /etc/profile ] && . /etc/profile; ...; exec cosmic-session'`. MEASURED inside the guest over SSH: `859 S+ do_wait /bin/sh -c ... exec cosmic-session` with child `882 Sl+ wait_woken umotd`. `umotd` (from `/etc/profile.d/umotd.sh`, shipped by the ublue common payload) blocks in a non-interactive session, so the shell waits forever and `exec` is never reached. Nothing logs an error | `source_profile = false` in the `[general]` section of every live greetd config — cosmic, niri **and xfce**, all three of which autologin through greetd (a bats test pins it, and is what caught xfce missing it). Verified on a rebuilt ISO: `cosmic-session`, `cosmic-comp`, `cosmic-panel` and `bwrap ... tuna-installer-cosmic` all running, framebuffer stddev 0.13, and the calibrated cosmic checkpoint passes 4/4. Two corrections worth keeping: cosmic does NOT need virgl to start OR to render (it drew fine on a host with no `virtio-vga-gl`), and the blank frames seen before this fix were the hang, not the GPU |
| 26 | The fixes for rows 24 and 25 each landed in ONE place, but neither defect lives in one place. Asked directly: *do these propagate to the other variants?* | `source_profile = false` reached live cosmic/niri/xfce only. gnome and kde do not use greetd. The **installed-system** greetd configs (`build_scripts/desktop/greetd-gtkgreet.sh`, `xfce-greeter.sh`) run their greeter through the same shell that sources the profile, with no such setting. An installed niri/xfce box therefore risks the identical hang. Separately, `build-iso-tacklebox.sh` pins `HOME`. But `.github/workflows/live-overlay.yml` invokes the tacklebox **binary** directly under `sudo -E` and never sources that script, so it continued to publish overlays built against the runner's rootless store. | Fixed one level up instead: `build_scripts/40-services.sh` rewrites `/etc/profile.d/umotd.sh` with an interactive guard (`case $- in *i*`). It is one of only three build scripts that **all six** Containerfiles invoke. So it covers every variant, every desktop, live media **and** installed systems. `01-workarounds.sh`, the obvious home, runs for el10 and ubuntu only and would have missed Arch, the variant we measured this on. The guard is POSIX shell because dash sources `/etc/profile.d` on the Debian and Ubuntu variants. Measured cost of the guard: a login shell adds only `LANG`, `DEBUGINFOD_URLS`, perl paths, and `XDG_DATA_DIRS`. `/usr/local/bin` (fisherman) is on PATH either way, and the flatpak exports come back via the `60-flatpak` user-environment-generator, so a session loses nothing. `live-overlay.yml` now pins `HOME=/root` itself, and a bats test fails any *direct* root tacklebox call that does not | 
| 27 | `installer GUI checks reported 127 failure(s)` on marlin:kde and marlin:cosmic alike — on healthy images and broken ones, before and after the row 25 fix | Not a count. `scripts/e2e-installer-gui-checks.sh` resolved its helper as `${TEST_LIB_DIR}/lib/e2e-assert.sh` while `iso-e2e.sh` uploads it to `${TEST_LIB_DIR}/e2e-assert.sh` (`e2e-smoke-checks.sh` has the `/lib` *inside* the default and was always right). `source` failed, `check` was undefined, every assertion was a no-op, and 127 was bash's command-not-found status. A gate that can neither pass nor fail — and therefore could not report the bug in itself | Path corrected; a bats test now pins all three check scripts against the upload destination. **Consequence worth stating:** this gate has never asserted anything, so no historical run of it is evidence of anything. With `check()` restored it immediately failed on `installer readiness stamp present` — see row 28 |
| 28 | With the row 27 fix in place, `not ok - installer readiness stamp present` on a marlin:cosmic ISO whose compositor and installer were both confirmed running | A false negative this repo had already diagnosed once. installer-smoke runs 63-68 failed identically until run 32445454947 found the stamp at `/run/user/<uid>/.flatpak/<app-id>/xdg-run/tuna-installer-ready`: inside the sandbox `$XDG_RUNTIME_DIR` reads as `/run/user/<uid>`, but it is a bind mount and the host path differs. `installer-smoke.yml` was fixed and pinned by `tests/test_readiness_stamp_lookup.py`; `e2e-installer-gui-checks.sh` is the second copy of that lookup and kept the two-path version, invisibly, because its assertions had never executed. What makes it durable: flatpak still *creates* the empty `app/<app-id>/` directory, so listing it reads as confirmation that nothing was written rather than as a wrong path | Sandbox host path added first, and the failure branch now `find`s the stamp rather than re-listing the directories it already assumes are right. The pytest pins **both** copies together. Gate now 4/4 on marlin:cosmic: compositor `cosmic-comp`, frontend `org.tunaos.InstallerCosmic`, stamp present, app_id matches, `signal: first-frame` |
| 29 | `not ok - hostname is set` on every marlin ISO e2e run | A check bug, never an image defect — and the evidence was in the same serial log twice. `scripts/e2e-smoke-checks.sh` asserted `test -n "$(hostname)"` over SSH; `build_scripts/checks/e2e-runtime-checks.sh` asserted the same thing **with** a `/proc/sys/kernel/hostname` fallback on the console of the SAME boot and passed at 6.77s. `hostname` is a net-tools/inetutils binary the Arch-based variants do not ship, so only the copy without the fallback saw an empty string. Measured: hostname `archlinux`, `DEFAULT_HOSTNAME=marlin` | Smoke copy brought in line, and a bats test pins the two byte-identical — two copies of one assertion returning different verdicts on one boot is what kept this unexplained rather than obvious. Benign artifact noticed while tracing it: the live squashfs carries an empty `/etc/hostname` the OS image does not have (podman's bind-mount placeholder, captured when the live rootfs is squashed); systemd falls back correctly |
| 30 | `marlin:cosmic` **installs** fail at step 9 of 10, 98% complete: `fisherman: fatal: writing hostname: finding deployment dir: ostree admin --print-current-dir: exit status 1`. LUKS, TPM enrolment, the bootc deploy and 2.3 GB of Flatpak copying all succeeded first. `marlin:kde` installs fine (CI run 34062061739, 2026-09-06) | **Not a cosmic defect and not an ISO defect — a stale `fisherman` bundled in the cosmic installer Flatpak.** Each desktop ships its own `org.tunaos.Installer*`, each bundling its own fisherman build, and they are pinned independently. Read out of the built ISOs with `go version -m` on `*/files/bin/fisherman`: **kde `027fa25c` (2026-08-29)**, but **cosmic, niri and xfce all `35c8f6f1` (2026-07-31)** — 123 commits behind. All five Flatpaks were *published* 2026-09-06/07, so this is a stale **pin**, not an unbuilt package. Upstream fisherman `36902966` names this exact failure: `bootc install to-filesystem --composefs-backend` lays the deployment under `<sysroot>/state/deploy/<hash>/` but ALSO creates `/ostree`, and `isComposeFsNative` keyed off "/ostree absent" — so a composefs-native install is mis-classified as ostree, `WriteHostname` takes the ostree path, and `ostree admin --print-current-dir` exits 1 on a freshly-installed `--skip-finalize` target. Confirmed in our log: `ls /mnt/fisherman-target/ostree` → `bootc deploy`, i.e. exactly the mis-classification condition | **The pins point at the WRONG REPOSITORY.** fisherman moved from `projectbluefin/fisherman` to `tuna-os/fisherman`, and only the kde manifest followed: `tuna-installer-kde/flatpak/org.tunaos.InstallerKde.json` sources `github.com/tuna-os/fisherman.git` @ `027fa25c`, while **cosmic** sources `github.com/projectbluefin/fisherman.git` @ **branch `dev`** and **niri**/**xfce** pin `projectbluefin/fisherman` @ `35c8f6f1`. That branch head IS `35c8f6f1` (2026-07-31) and has not moved since — so cosmic's *unpinned* branch source produces the same frozen binary as the two explicit pins, and Renovate cannot help because a git source aimed at a dead repo's branch has nothing to bump. **Fix: repoint all three manifests at `tuna-os/fisherman` — a one-line change per repo, not a change in tunaOS.** **gnome is affected too, and worse:** `tuna-os/bootc-installer` carries fisherman as a git *submodule* on `projectbluefin/fisherman` branch `dev`, pinned at `6092be78` (**2026-06-23**) — which is why its binary has no VCS stamp (flatpak builds it from a `dir` source, not a git one) and why the binary-inspection method could not date it; the manifest method can. Full picture, all five desktops: **kde `tuna-os/fisherman` @ `027fa25c` (2026-08-29) — the only current one**; cosmic/niri/xfce `projectbluefin/fisherman` @ `35c8f6f1` (2026-07-31); gnome `projectbluefin/fisherman` @ `6092be78` (2026-06-23). Four of five desktops build their installer from the abandoned upstream repo. Two lessons worth keeping: (1) per-desktop installer Flatpaks are a propagation boundary the same way the greetd configs were — a fisherman fix reaches only the desktops whose manifest was bumped, and nothing here notices; (2) the older fisherman reports a bare `exit status 1`, while `aeeb2bb9` (also missing from the stale build) makes failed bootc/ostree steps carry their last output — so the stale installer is also the one that tells you least about why it failed. `bootc-installer` (gnome) carries no VCS stamp, so its fisherman age is undetermined by this method |
| 31 | After debugging an image with `sudo podman image mount`, ROOTLESS `podman` on the workstation dies with `open /run/user/1000/containers/overlay-layers/mountpoints.json: permission denied` — and earlier, `open .../storage/overlay-images/images.json: permission denied` | The same HOME/XDG leak as rows 24 and 26, one level down. `sudo` here resets `HOME` to `/root` (so root podman does use root's *storage*), but it still passes `XDG_RUNTIME_DIR` through — so root podman writes its runtime state into the invoking user's `/run/user/1000/containers`, leaving one root-owned file that locks the user out of their own store. `sudo -E` is worse: it preserves `HOME` too, and then root podman writes into `~/.local/share/containers` as well | Repair with a targeted `find … ! -user <you> -exec chown <you>:<you> {} +` over BOTH `~/.local/share/containers/storage` and `/run/user/<uid>/containers` — not a blanket recursive chown, which flattens the subuid-mapped ownership a rootless store depends on. Note the count of "foreign-owned" files *rises* after the repair: chowning the directories makes previously untraversable subuid-mapped files visible, which is normal and not damage. Avoid it in the first place with `sudo env -u XDG_RUNTIME_DIR podman …` (options before assignments — see row 26) |
| 32 | **Preventing rows 30–31 from recurring.** The fisherman drift lasted ~2 months and nothing reported it | Nothing that existed could have. The Flatpaks were *rebuilt daily*, so publish dates looked healthy — the package was fresh and the SOURCE was stale. Renovate has nothing to bump when a git source points at a repository that no longer moves. Binary inspection could date four of five but not gnome, whose Flatpak builds fisherman from a `type: dir` source with no VCS stamp. And the source of truth lives in five OTHER repositories, so no check inside tunaOS was looking at it | `scripts/check-installer-fisherman-pins.py` reads the fisherman source out of all five installers — the four Flatpak manifests and gnome's `.gitmodules` — and fails any that is not `tuna-os/fisherman`. Run daily by `installer-fisherman-pins.yml` (drift here happens over months, so per-PR would be noise), plus on any PR touching the check itself, so a PR that breaks the guard is caught by the guard. Three deliberate design calls: (1) it asserts the **repository, not the revision** — pinning an older revision of a live repo is a visible, reviewable choice, while sourcing a dead repo is the silent one, and a noisy check gets switched off; (2) revision *divergence* across desktops is a warning, because that is the exact shape the drift took — kde moved, nobody else did; (3) a missing/unparseable source is a hard **failure**, not a skip — the gate in row 27 could neither pass nor fail for months, so "found nothing" must never read as "nothing wrong". Ten unit tests exercise the pure audit with no network, including the literal broken configurations that shipped. A network error warns rather than reddening the build: this guards against drift over months, not a flaky minute |
| 33 | `not ok - graphical.target is active` and `not ok - systemd unit graph verifies (graphical.target)` on **every** installed-system run, on **every** desktop — including LUKS installs that pass end-to-end (measured: marlin:cosmic at 11.7s under greetd, marlin:kde at 12.4s under sddm, both `TUNAOS_LUKS_E2E_PASS`) | Two different causes, same shape — an assertion that could never pass. (1) `e2e-runtime-checks.sh` runs from `tunaos-desktop-contract.service`, which is `WantedBy=graphical.target`, so it executes **inside that target's own startup transaction**; a target is not `active` until every unit wanting it has finished, so `is-active` reports `activating` there and structurally always will. **The obvious fix is a trap**: polling until `active` deadlocks — the target waits on this unit, the unit waits on the target — until `TimeoutStartSec=90` fires, adding a 90s stall to every boot. (2) `systemd-analyze verify --recursive-errors=yes` returns non-zero when **any transitively reachable** unit warns, including upstream units we neither ship nor can fix; measured on a dev host, `flatpak-appstream-refresh.service:7: Unknown key 'ExecCondition'` alone is enough | (1) Assert `ActiveState` is one of `active`/`activating`/`reloading` — healthy *including* the in-transaction case — and add `systemctl get-default == graphical.target`, which is the stable half of the original intent because unlike `ActiveState` it does not depend on when in the boot you ask. Verified the predicate still fails `inactive`, `failed`, `deactivating` and empty, so it was not merely softened into always passing. (2) Gate on `--recursive-errors=no` (our unit, which is what the assertion claims) and keep the transitive sweep as **information**, printed rather than discarded into `/dev/null`. **The rule this shares with rows 27 and 29:** an assertion that always says the same thing cannot report a regression, so a permanently-red check is not a known-issue — it is a dead gate |
| 34 | **Build Marlin red on every run for 18+ consecutive days**, both arches, and `just build marlin <flavor>` fails identically locally: `error: failed to run custom build command for 'selinux-sys v0.6.15'` → `selinux-sys: Failed to find 'selinux/selinux.h'` | Renovate bumped `downloads.bootc` to **v1.16.11** on 2026-09-03. That release added `selinux = { workspace = true }` to `crates/lib/Cargo.toml` as a **hard, non-optional** dependency — no feature flag to turn it off. Confirmed against the tags: `selinux-sys` is absent from v1.16.8/9/10's `Cargo.lock` and present in v1.16.11's. `selinux-sys`'s build script needs `selinux/selinux.h`. **Arch does not ship it: `libselinux` is not in the official repos at all** (`pacman -Si libselinux` → "package not found"). So there is nothing to add to `Containerfile.arch`'s bootc-builder stage. Not a tunaOS regression: an upstream dependency change that is unbuildable on a non-SELinux distro. Note also that the failures predate 09-03, so at least one *earlier* cause is still unidentified. This row explains the current one, not the whole 18-day streak. | Pinned back to **v1.16.10** as a **CEILING**. It is the opposite of the FLOOR pin for tacklebox directly below it in the same file, and the comment says so. A reader who takes one for the other reintroduces this with a well-meant bump. We verified this: `Containerfile.arch`'s bootc-builder stage builds on a clean `archlinux:latest` at **both** versions — v1.16.11 fails as above, v1.16.10 completes. A full `just build marlin niri` then reached `BUILD_EXIT=0`. **A pin alone would not have held** — Renovate would re-bump it next run, which is how it arrived. So `renovate.json` carries a matching `allowedVersions: "<=1.16.10"`, and `tests/test_bootc_version_ceiling.py` pins both files and requires them to agree. The rule's description must name the exit condition (bootc makes selinux optional, or Arch ships libselinux), because a ceiling with no stated way out becomes permanent by accident |
| 35 | `not ok - SSH host keys were generated` on **every** installed system, on **every** flavor — measured on all five marlin flavors at ~11s, each on a LUKS install that otherwise passed end to end | Not a timing artifact, unlike rows 33's pair. The guard was `systemctl list-unit-files sshd.service ssh.service`, which matches a unit that is **present but DISABLED**. Production images ship openssh and then deliberately turn it off (the `safe_disable sshd.service`/`ssh.service`/`.socket` calls in `40-services.sh`), so `sshd-keygen` never runs and `/etc/ssh/ssh_host_*_key` legitimately does not exist. The assertion was asserting against the image's own design | Gate on whether sshd actually **runs** — `is-enabled` or `is-active` on any of the four unit spellings — rather than on whether it is installed. That keeps the check meaningful exactly where it matters: the dev ISOs, where `ENABLE_SSHD=1` and that daemon is the harness's only way into the guest, so a missing host key is fatal. A skipped check now **says so** in the serial log, because a production image with sshd off and a dev ISO whose sshd failed to enable both end up with no host keys and only that line separates them. **Third assertion in this one file found permanently red for a reason unrelated to what it claims to test** (see rows 33 and 29): a check that always says the same thing cannot report a regression, so a permanently-red check is not a known issue — it is a dead gate, and the file now has tests pinning all three against returning to that state |
| 36 | `systemd-analyze verify graphical.target` reports an ordering cycle through `rechunker-group-fix.service` on every variant (surfaced by the informational sweep added in row 33) | The ublue common payload ships `rechunker-group-fix.service`, which is `After=local-fs.target` **and** `Before=systemd-sysusers.service` — a genuine cycle in the unit graph, back through `systemd-tmpfiles-setup-dev` → `local-fs-pre.target`. Upstream `projectbluefin/common:latest` still ships it that way; our own `_upstream-snapshots/aurora` copy has that `Before=` commented out, so someone upstream already hit it. **But the unit is irrelevant to tunaOS regardless:** its header says it exists for images built with `ublue-os/legacy-rechunk`, which prunes `/usr/lib/group` and `/usr/lib/gshadow`. tunaOS rechunks with **chunkah** (`coreos-chunkah`), and a built `marlin:niri` confirms it — neither file exists, so the damage the unit repairs was never done | Masked in `40-services.sh` (above the package-manager branching, so every family reaches it). **State the evidence precisely:** the cycle is a **STATIC** `systemd-analyze` finding — PID 1 logged no cycle and no deleted job on either a pre-mask or post-mask boot, and masking does **not** silence `systemd-analyze`, which reads unit files rather than enablement state. So the sweep still reports it after this change, and that is not a regression. The justification for masking is that we should not ship repairs for tools we do not use — it runs `systemd-sysusers`, `rechunker-group-fix` and `systemd-tmpfiles` on every boot of every variant for a problem we do not have — **not** an observed runtime failure. Masked rather than deleted so it survives a re-copy of the common payload; do not unmask without first checking the image is still chunkah-built |
| 37 | Thirteen bats tests fail on a developer workstation and pass in CI — the whole `OS detection` / `detected_os` / `print_debug_info` / `warn_on_fail` cluster in `test_lib.bats`, reporting e.g. `ALMALINUX: true` for a **fedora** `BASE_IMAGE` | Two faults, and the suite was not hermetic. (1) `test_lib.bats`'s `setup()` stubbed `jq` to print `almalinuxorg/almalinux-bootc` **unconditionally** — meant for one image-info.json test, but applied to every test in the file. (2) `lib.sh` read that answer straight into `BASE_IMAGE`. On any **ublue-derived workstation** `/usr/share/ublue-os/image-info.json` exists, so `lib.sh` consulted it, the stub answered "almalinux" regardless of the file, and each test's own `BASE_IMAGE` was overridden. In CI the file is absent, `jq` is never called, and everything passed — so the failures looked like developer-environment noise and were dismissed as such (by me, repeatedly, as "pre-existing on main") | Both fixed. The jq shim now delegates to the real `jq` — the one test that needed a canned answer writes a real JSON with a `base-image` key and never needed one — and `setup()` defaults `_IMAGE_INFO` to a path that does not exist, so host state cannot leak in. **And a genuine library bug behind it:** `lib.sh` assigned the lookup straight into `BASE_IMAGE`, so an `image-info.json` that exists but carries **no** `base-image` key set it to the empty string, destroying a caller-provided value — `// empty` returns "" and the fallback below then cannot tell "nobody told us" from "we just threw it away". Our own `90-image-info.sh` writes the key, but it runs late, so any stage sourcing `lib.sh` on a base that already ships a partial file loses what the Containerfile passed in. Now read into a scratch var and applied only when non-empty, with a regression test confirmed to fail without the fix. **Lesson:** a test that fails only on developer machines is not automatically environment noise — here it was the suite reading the developer's own OS, and a real library defect underneath |
| 38 | Fedora **43** still referenced after bonito moved to **44** — and one reference is functional, not commentary | `FEDORA-BASE-POLICY.md` commits the project to one Fedora stable at a time and bonito tracks **44**; `build-config.yml` and `registry-map.yaml` both say 44, and `test_fedora_base_currency.bats` already guards that pair. What nothing guarded: `build_scripts/overlay/overrides/nvidia/20-nvidia.sh` hardcoded `NVIDIA_RELEASEVER="${FEDORA_AKMODS_VERSION:-43}"` — the fallback used when the akmods bundle carries no readable dist tag. On a Fedora 44 image that pointed negativo17's `fedora-nvidia` repo at **releasever 43**: kmod and userspace from different Fedora releases, the exact mismatch the dist-tag derivation directly above it exists to prevent. (The `:43` in `get-base-image.sh`'s header is historical commentary about a drift already fixed, not a live pin) | Bumped to 44, verified upstream first rather than assumed: negativo17 `fedora-43` and `fedora-44` both return HTTP 200 and `fedora-45` returns 404, so this is a currency bump, not a reachability fix, and it does not get ahead of the policy's N+1 sequencing. The new `test_fedora_base_currency.bats` case derives the expected value from **bonito's `build-config` base** instead of hardcoding 44, so the next transition fails loudly here — confirmed to fail when reverted to 43. Stale `fedora-bootc:43` fixtures in `test_lib.bats` refreshed too. **The pattern this file keeps re-learning:** a version pin living in more than one place needs something that compares the copies, or the copy nobody looks at goes stale silently |
| 39 | **`rawhide_rpmdb_probe` can delete the working directory.** A full `bats tests/bats/` run destroyed a checkout of this repo — every user-owned file including `.git`, leaving only a root-owned `.build`. In the same run every test after `test_rawhide_rpmdb_probe.bats` failed with `shell-init: error retrieving current directory: getcwd: cannot access parent directories` (75 failures instead of 11) | `lib.sh`'s copy-up did `_rpmdb_dir="$(readlink -f "$_rpmdb_path")"` — and **`readlink -f ""` does not fail, it returns `$PWD`**. So when `rpm --eval '%_dbpath'` yields nothing (rpm absent, erroring, or stubbed), `_rpmdb_dir` became the working directory, the `-d` guard passed, and the round trip ran `cp -a "$PWD" "$PWD.tbox-copyup"` → `rm -rf "$PWD"` → `mv` back. **The `rm -rf` was not conditional on the `cp -a` succeeding**, so with the disk nearly full the copy failed and the delete ran anyway, with nothing to restore from. Six of the eight tests in `test_rawhide_rpmdb_probe.bats` left `RPM_DBPATH_OUT` unset, so the stub printed an empty string and the suite steered the real function at bats's own cwd — the repo root | Library: refuse a `%_dbpath` that is empty or not absolute **before** resolving it; also require the resolved dir not be `/` or `$PWD`; and make `rm -rf` conditional on the `cp -a` returning success, warning and leaving the directory alone otherwise. The parent-glob cleanup one line down had the same hazard (empty `_rpmdb_dir` → globs against `/`) and is guarded too. Tests: `setup()` now defaults `RPM_DBPATH_OUT` to a real scratch dir so no test can steer the probe at a live cwd, the "nothing to salvage" case is expressed by a new `NO_SALVAGE` stub knob instead of by an empty path, and two new tests run the probe from a scratch cwd with an empty and a relative `%_dbpath` and assert the directory survives. **This also explains 64 of the 75 failures** — they were cascade, not defects |
| 40 | The published **gurnard-pantheon** ISO boots to a **black screen** — `stddev=0` on every captured frame across three `--published` harness runs, including one with a 420s boot settle. No sshd on production media to diagnose from inside | `live-iso/common/src/customize-live.sh`'s desktop detection has branches for plasma, niri, cosmic and xfce, and `DESKTOP` **defaults to `gnome`** — there was no pantheon branch. So a Pantheon image ran `desktop-gnome.sh`, which writes **GDM** autologin. Verified by mounting the published ISO: `/etc/gdm/custom.conf` is present carrying `AutomaticLoginEnable=True` / `AutomaticLogin=liveuser`; **no gdm, gdm3, sddm or greetd is shipped at all**; `lightdm` is the only display manager and `/etc/systemd/system/display-manager.service` → `lightdm.service`; `/etc/lightdm/` has **no autologin** anywhere; and `liveuser` **does** exist. The account was fine — nothing logged it in, so no session ever started | Added a `pantheon` detection branch (matches `wayland-sessions/pantheon-wayland.desktop` or `xsessions/pantheon.desktop`) and a `desktop-pantheon.sh` adapter that writes **LightDM** autologin to `/etc/lightdm/lightdm.conf.d/`, picks `autologin-session` from a session file that actually exists (pointing it at a missing session reproduces the same black screen by another route), and installs the standard installer autostart entry. Nine tests drive the **real** detection block against fake session roots and were confirmed to fail when the branch is reverted; one asserts the adapter's *code* never writes gdm config while its header may still explain the mistake. **The shape to remember:** a detection default is a silent fallback — an unrecognised desktop does not fail, it becomes gnome, and every downstream assumption follows from that wrong answer |
| 41 | `just fix` reformats the whole tree again, on a repo where `.editorconfig` and the code already agree | **shfmt itself was unpinned.** `just/utilities.just` and `lint.yml` both did `brew install shfmt`, which installs whatever is current. shfmt is a **formatter**, so its version *is* the formatting: two contributors on different versions produce different trees, each sees the other's as unformatted, and `AGENTS.md` makes `just fix && just check` mandatory before every commit — so everyone hits it at once, on a release nobody in the repo made. This is the same failure as row 40's `.editorconfig` mismatch, waiting on an upstream release instead of a config edit | Pinned `shfmt: "v3.14.1"` in `image-versions.yaml` beside the other tool pins, with a Renovate `depName=mvdan/sh` comment so it is tracked rather than frozen. `_check_shfmt_version` in `just/utilities.just` compares the running shfmt against that pin and **both `just fix` and `just check` depend on it** — guarding only `check` would let a wrong-version `fix` rewrite the tree and then report the result as drift. On mismatch it names both versions and the exact `go install` line, and `TUNAOS_ALLOW_SHFMT_DRIFT=1` exists because a hard stop with no way past it gets deleted by the next person. CI installs the pinned version over brew's. **The rule:** a formatter you do not pin is a formatter that will reformat the tree on somebody else's release schedule |
| 42 | `just check` exits 1 on a clean `main` from the `actionlint` step, with `SC2193` ("The arguments to this comparison can never be equal") in `desktop-contract-sweep.yml` and `SC2094` ("Make sure not to read and write the same file in the same pipeline") in `installer-smoke.yml` (actionlint 1.7.12; shellcheck 0.9.0 and 0.11.0) | Two real script defects, not lint noise. **SC2193:** `[[ "${{ matrix.variant }}" == hummingbird* ]]` puts a template expansion in a shell test; actionlint substitutes a placeholder, so shellcheck sees a constant. **SC2094:** the "no tunaos-live-session journal" check was inside the command group that redirects to `"$out"`, so its `grep` read the log while the group was still writing it, and its `::notice::` went into the log file, not to the annotations. The bare-tag match also matched the section header that the capture writes into `"$out"` on every run, so the notice could never fire | Use the step's `$VARIANT` env var in the tests. Move the check after the group closes, and match the journal's `tunaos-live-session[pid]:` form. Do not add either code to the `-ignore` list in `just/utilities.just`: that hides a real finding. `tests/regressions/test_issue_2668_*.py` runs the real notice block against a header-only log. **The rule:** before you ignore a new shellcheck code, read the script it points at |
| 43 | `dbus-broker-launch`: `Access denied in /etc/selinux/targeted/contexts/dbus_contexts`, followed by a dead system bus, logind and PAM SELinux failures on **yellowfin and skipjack**; eight GNOME cells red and KDE could promote without a bus (tunaOS#2485) | The rolling bases carried **libselinux 3.11-1.el10** while healthy albacore carried 3.10. Runtime probes showed the same enforcing mode, policy 43.1-1.el10, file label, expected label and readability on all three. The controlled skipjack build then changed only libselinux to 3.10 and went from a dead bus (run 35185567440) to a passing Gate and `TUNAOS_DESKTOP_CONTRACT_OK` (run 35191766126). The file contents, DAC mode and computed SELinux label were not the differentiator | Declare a **3.10-2.el10 ceiling** in `image-versions.yaml`, downgrade and versionlock `libselinux`, `libselinux-utils` and `python3-libselinux` only on yellowfin/skipjack, and fail the image build if any installed EVR differs. 3.10-2 adds only RHEL-110181's restorecon ENOENT fix over the measured-good 3.10-1 and is retained by both rolling repositories. Remove the ceiling only after a 3.11+ build passes the same enforcing boot and desktop contracts; `tests/regressions/test_issue_2485_rolling_el10_libselinux_ceiling.py` prevents the pin or either affected variant from disappearing silently |
| 44 | A cell whose boot Gate fails every night shows as **untested** (⬜) in `docs/MATRIX-STATUS.md`, with `builds`/`boots` `untested` and an empty `run` in `docs/matrix-provenance.json`. The README lists it under "never reached". Measured on `hummingbird:gnome`: the Gate failed in run 35938968035 and every nightly before it, and the matrix recorded no run | `build_stage_results()` in `scripts/gen-matrix-status.py` (and the matching loop in `.github/scripts/update-build-status.sh`) fixed a cell only on a **conclusive Promote**. A failed Gate is exactly what *skips* Promote. The walk stepped past every red run, so the cell was never scored. An older green Promote inside the 10-run window would have been read in place of the newer red Gate | A failed Gate now scores the cell from its run: `boots=fail`, the run linked, and `builds` left untested because Promote never ran. The README counts the cell as failing. A skipped Promote behind a passing or skipped Gate is still not a verdict, and the walk continues. Tests: `tests/regressions/test_issue_2513_a_failed_gate_scores_the_cell.py` and two cases in `tests/bats/test_build_status_classification.bats` |
| 45 | A GPU-routed desktop Gate fails before producing a serial log, or reports the same blank screen as an image defect when the runner silently lacks virgl | The Gate previously selected `virtio-vga-gl` only opportunistically. It recorded neither KVM/render-node availability nor the QEMU/Mesa/DRM versions, and could fall back to plain virtio on a mis-provisioned GPU runner. Separately, RunsOn fleet failures such as `VcpuLimitExceeded` happen before any repository step can execute; run 33041330231 measured the account's `g4dn` vCPU quota at **0** | `scripts/gpu-drm-preflight.sh` now runs before the candidate image is built or booted. It writes the KVM, render-node/driver, QEMU, Mesa, GL-device and `egl-headless` fingerprint to both the Gate summary and `runner-capability.txt`. GPU-routed cells require `virgl` and exit 78 with `GPU/DRM infrastructure unavailable` rather than booting the image on a fallback; the boot step is pinned to `TBOX_E2E_GPU=virgl` after that proof. A failure in GitHub's **Set up runner** phase still means no script could run: inspect that phase for the AWS quota/capacity error and do not classify it as a desktop failure |
| 46 | A desktop Gate passes, and the image promotes, while `dbus-broker.service` and `dbus.socket` are failed on the same boot. yellowfin:kde (run 35957716969) and skipjack:kde (run 34705564876) did this; #2664 found the same on an installed yellowfin:niri | The image runs two contracts on one boot: `tunaos-base-contract.service` at multi-user, which checks the system bus, and the desktop contract at graphical. `scripts/iso-e2e.sh --disk` waited for the desktop marker only. SDDM starts without the bus, so the desktop contract printed OK, and the `TUNAOS_BASE_CONTRACT_FAIL` line above it went unread | In desktop mode, after the desktop marker, the disk arm waits up to `BASE_CONTRACT_GRACE` (120 s) for the base verdict and fails on `TUNAOS_BASE_CONTRACT_FAIL`. No base marker gives a warning only, so an older image does not fail. `tests/regressions/test_issue_2664_*.py` runs the real helper against the serial log of the false pass. **The rule:** when a boot writes two verdicts, the Gate reads both |
| 47 | Every cell of one variant (bonito, 2026-09-24) flips to builds ⬜ "untested" in `docs/matrix-provenance.json` with an empty `run` and `date`, while its sibling (bonito-rawhide) stays green and `Build Bonito` shows green Promote jobs | **A failed `gh` call was scored as "no runs".** `build_stage_results()` read `gh_json(... run list ...) or []` and `gh_json(... run view ...) or {}`; `gh_json` returns `None` after three failed attempts and discarded gh's stderr. So a transient API failure during the refresh (run 35990117734) produced exactly the shape of a variant that has never built, and the log said nothing. Measured: run 35881676275 (2026-09-23) promoted 16/16 bonito cells, and re-running the same code against it today scores 16/16. A failed `Attest SBOM` (Rekor 502) does not cause this — only `Promote`/`Gate` jobs are read. | `gh_json_required()` raises on a failed query in `build_stage_results()`, so the refresh job fails loudly instead of opening a PR that blanks a row; `gh_json` now logs the failing command and gh's stderr. A workflow with genuinely no runs still returns `[]` and stays ⬜. Test: `tests/test_a_failed_run_query_is_not_an_untested_cell.py`. If a whole row goes ⬜ with no run named, re-derive it before believing it: `gh run view RUN_ID --json jobs` on the newest `build-VARIANT.yml` run and look for `/ Promote` conclusions. |
| 48 | ISO builds finish live-customize, then fail in `podman commit` at exactly 600.0 seconds with exit 124: skipjack:xfce on both rootless and root paths, and marlin:gnome/kde with native `overlay` storage | The limit was in Tacklebox, not in the runner or the storage driver. Its post-customize commit ran under a literal `timeout --foreground 600`, so a slow commit of a multi-gigabyte desktop layer and a real wedge gave the same exit 124. Root and faster storage helped some cells, but 600 seconds was not a valid limit for all of them (tunaOS#1893). Tacklebox also ignores a `TBOX_CUSTOMIZE_COMMIT_TIMEOUT` it cannot parse and uses 600, so a typo gives the same failure | Pinned Tacklebox `ae93e9b` (tuna-os/tacklebox#300), which reads `TBOX_CUSTOMIZE_COMMIT_TIMEOUT`. `scripts/lib/tacklebox.sh` sets it to 1800 when the caller does not, stops with exit 2 on a value that is not a whole number, and forwards exported `TBOX_*` settings into the Tacklebox container. The 4800-second `TUNAOS_TACKLEBOX_TIMEOUT_SECONDS` stays the outer limit, so `0` cannot make a build run without end. `tests/regressions/test_issue_1893_customize_commit_deadline.py` runs the real adapter and proves that the value gets to Tacklebox |
| 49 | `hummingbird:cosmic` is red in `docs/MATRIX-STATUS.md` with `missing required command: cosmic-comp` (Desktop Contract Sweep run 36069044544). The build log annotates `cosmic-comp ... is not in the active repos`, but `cosmic-comp-1.4.0-1.fc43` **is** in the `repo.tunaos.org/hummingbird/20251124-x86_64` index | Two causes. **(1) One night's upstream packaging defect.** `cosmic-comp` pulls `xml-common`, which requires `/usr/bin/xmlcatalog`, so dnf adds `libxml2`. `public-hummingbird` build `libxml2-2.15.4-1.hum1` (built 2026-09-23 10:11Z) also shipped and provided `libxml2.so.16`, and the base image already has that file from `libxml2-16-2.15.3-0.1.2.hum1`. dnf resolved the transaction, rpm refused it: `file /usr/lib64/libxml2.so.16 from install of libxml2-2.15.4-1.hum1 conflicts with file from package libxml2-16-2.15.3-0.1.2.hum1` (Build Hummingbird run 35938968035, job 107462242332). The per-package fallback in `install_available` discarded dnf's stderr, so that line was lost, and `record_package_wishlist` reported the package as absent. The Desktop contract waived it (7 unmet; the night before had 6, with cosmic-comp present) and Promote published the image, revision `c46f3fc`, created 2026-09-24T00:51Z. That is before #2670, which removed the COSMIC waiver. Upstream fixed the build in `libxml2-2.15.4-1.1.hum1` (2026-09-24 11:06Z), which no longer provides `libxml2.so.16`. **(2) The standing gap, #2513.** `cosmic-session`, `cosmic-greeter`, `greetd`, `cosmic-settings(-daemon)`, `cosmic-osd`, `cosmic-files` and `xdg-desktop-portal-cosmic` do not resolve on any night, because `fprintd-pam`, `libvorbis`, `python3-setools`, `python3-distro` and `libreport-filesystem` are in neither repository index (measured 2026-09-24) | `install_available`'s per-package fallback keeps dnf's output. If a package that the repoquery found is still not installed, it now emits a `Package in repos but not installed` warning that names the package and quotes the dnf error line. `tests/regressions/test_issue_2513_install_available_names_why_a_present_package_failed.py` drives the real function with the measured conflict line. No pin or swap was needed for libxml2: the upstream fix is live. After #2670 the Desktop contract fails COSMIC on a missing session, so a new build does not promote, and the cell stays red on the old image until the package factory builds the #2513 set. **Before you diagnose a missing package, confirm it is absent from the index.** A package that is present but not installed is a dependency or rpm problem, not a packaging request |
| 50 | A `Manifest` job fails at "Install dependencies" in the `cgr.dev/chainguard/wolfi-base` container with `ERROR: libgpg-error-1.61-r3: Permission denied`, then `N errors; ... MiB in M packages` and exit N. The packages differ on every run: `linux-pam` and `libgpg-error` (bonito-rawhide base, run 36046888245), `bash`, `libkrun`, `libstdc++`, `netavark` and `gpg-agent` (flounder-sid kde, run 36083457907). When it hits `base`, stage 2 is skipped and every stage-2 ISO stops at the provenance gate | **No file permission is involved.** apk-tools 2.14.10 reports an HTTP 401/403 on a package download as `EACCES`, so the log says `Permission denied`. Each refused package errors 50-90 ms after its `Installing` line, and a real download takes 300-400 ms. Every package fetch from `apk.cgr.dev` is a 303 redirect to a presigned Cloudflare R2 URL, and sometimes one request is refused. Measured with the pinned image digest against a local repository: a 403 or 401 prints `Permission denied`, a 404 prints `package mentioned in index not found`, and a 502 prints `remote server returned error`. The step ran one bare `apk add`, so one refusal failed the job | The step retries `apk update && apk add` up to 4 times, with 5, 10 and 15 s pauses. A second `apk add` fetches only the packages that the first one did not install: against a repository that refused 25% of package fetches once each, the first attempt ended `19 errors` and the second ended `OK: 267 MiB in 90 packages`. `tests/regressions/test_issue_2693_manifest_apk_install_retries_a_refused_download.py` runs the step's own shell against a stub apk (#2693). **Read an apk `Permission denied` as an HTTP refusal first**, especially when it names a different package on each run |
| 51 | Every `Attest SBOM` job fails after 10 minutes with `Post "https://rekor.sigstore.dev/api/v1/log/entries": giving up after 2 attempt(s): status 502` and `SIGSTORE_OUTAGE`, on every variant and on the automatic re-run. It looks like a Rekor outage (#2671), but `Sign` passes against the same log in the same minutes: Build Albacore 35970880514 had 17/17 Sign passed and 17/17 Attest SBOM failed | **The request is too large, and Rekor is not down.** rekor.sigstore.dev refuses a request body over 24 MiB with a bare 502 page. Measured 2026-09-25: a 24117352-byte POST to `/api/v1/log/entries` got a 400 from Rekor, and a 25165928-byte POST got the 502. Syft's SPDX output has one `files` entry and one `CONTAINS` relationship for each file that a package owns. The bonito base-rawhide SBOM was 37.9 MB, and kde-nvidia-rawhide was 122.7 MB, and `cosign attest` sends the predicate base64-encoded. No SBOM attestation passed in any scheduled Build Yellowfin run from 2026-08-14 to 2026-09-18. `cosign-retry.sh` reads a 502 from a Sigstore host as an outage, so each image used the 10m budget, and `rerun-infra-failures.yml` re-ran a job that cannot pass. In the same runs, an `Upload SBOM` DNS failure (job 107608521404) failed build_push, and niri-hwe's Sign, Gate and Promote were skipped | `attest-sbom.yml` attests a package-level SBOM, made by `.github/scripts/sbom-for-rekor.sh`. The script removes the per-file entries and their relationships, sets `filesAnalyzed` to false and removes `packageVerificationCode`: 37.9 MB becomes 3.5 MB, and 122.7 MB becomes 7.5 MB, with all packages kept. An SBOM that is still over `REKOR_PREDICATE_MAX_BYTES` (10 MiB) fails with its size and without `SIGSTORE_OUTAGE`. `Upload SBOM` is `continue-on-error`, like `Generate SBOM` (#1796). `tests/regressions/test_issue_2697_sbom_attestation_fits_the_transparency_log.py` (#2697). **Before you call a Sigstore 502 an outage, check if `Sign` passed in the same run.** If it did, the log is up, and the request is the problem |
| 52 | All three flounder-sid `*-nvidia` builds fail at `Setting up nvidia-kernel-dkms (550.163.01-5.1)` with `Building module(s)...(bad exit status: 2)` for `7.2.7+deb14-amd64`, then `dpkg: error processing package nvidia-kernel-dkms` and exit 100 (run 36083457907) | **sid's kernel outran the only Debian nvidia driver.** `make.log`: `nvidia/os-interface.c:753:5: error: implicit declaration of function 'strncpy'`, since Linux 7.2 dropped it. Measured in debian:sid on 2026-09-25: 550.163.01 builds on 7.1.13 but fails on 7.2.7. The open 550 module (`__vm_flags`, `in_irq`) and experimental 555.58.02 (`VMA_LOCK_OFFSET`) also fail on 7.2.7, and no Debian suite has anything newer. The published parent `flounder:kde-sid` already shipped 7.2.7 | `build_scripts/overlay/debian-nvidia-kernel-hold.sh`, called from `nvidia-debian/20-nvidia.sh`, swaps the nvidia overlay's kernel to the newest archive kernel at or below the driver's measured ceiling (550.x: 7.1). The swap follows the RPM path's `10-kernel-swap.sh`. When the archive has no such kernel, the build exits 1 and names the reason. Add a ceiling row only from a measured dkms build. Regression test: `tests/regressions/test_issue_2696_*` (tunaOS#2696) |
| 53 | The **marlin arm64** ISO fails `Boot gate: verify ISO readiness` with `readiness marker not seen within 900s` and a blank screen, every night; amd64 marlin and every other arm64 ISO pass (run 36075112992) | **Arch Linux ARM's `linux-aarch64` cannot mount zstd squashfs, and tacklebox writes only zstd.** `serial.log`: `mount: /run/rootfsbase: fsconfig() failed: Filesystem uses "zstd" compression. This is not supported.` 165 times, then `A start job is running for dracut initqueue hook (20min …)`. The ALARM kernel config has `# CONFIG_SQUASHFS_ZSTD is not set` (XZ is `=y`). tacklebox's `live.go` hard-codes `-comp zstd`, and a `return` at the top level of `tbox-live-root.sh` turns the mount failure into an endless retry instead of a fast failure | `scripts/build-iso-tacklebox.sh` reads the image's kernel (`/usr/lib/modules/*/pkgbase` or a `*-aarch64-ARCH` module directory). For a kernel listed in `scripts/lib/squashfs-compat.sh`, it installs a `mksquashfs` wrapper in `/usr/local/bin` for the build, which rewrites `-comp zstd` to `xz`. `/usr/local/bin` is used because tacklebox calls mksquashfs through `sudo -u … podman unshare`, and sudo's secure_path drops a PATH prepend. It then reads each `/LiveOS` superblock out of the ISO and fails the build on zstd. Retire the wrapper when tacklebox takes a compressor in the recipe. Regression test: `tests/regressions/test_issue_2705_*` (tunaOS#2705) |

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

### 5. COSMIC cells pass the LUKS gate while shipping a greeter that never starts (2026-08-07)

**Affected:** every cosmic cell where both `greetd` and `cosmic-greeter` are
installed. Measured on `skipjack:cosmic` (run 31136849989) and
`albacore:cosmic` (run 31100129320). **Both are ticked green on
`docs/MATRIX-STATUS.md`.**

**Symptom.** The gate passes outright —

```
TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1 installed_boot=1
```

— and the desktop contract fails beside it, non-fatally, so nothing goes red:

```
TUNAOS_LUKS_E2E_DESKTOP_CONTRACT desktop_contract=fail fatal=0
```

The `dm_diag` block `verify-desktop-experience.sh` ships with `dm_inactive`
(added exactly because the DM logs to the journal while the gate can only read
the serial console) gives the mechanism:

```
greetd: unable to start greeter: terminal: unable to take controlling
        terminal: EPERM: Operation not permitted
cosmic-greeter.service: Main process exited, code=exited, status=1/FAILURE
cosmic-greeter.service: Scheduled restart job, restart counter is at 1.
Id=cosmic-greeter.service  SubState=auto-restart  NRestarts=1
```

**Root cause chain.**

```
cosmic-greeter (COPR on EL10, deb on Ubuntu) claims display-manager.service
  → the manifest also declares display_manager: greetd, which
    install-desktop.sh force-links into graphical.target.wants
      → two units, both running `greetd` on vt = 1, both Restart=always
        → greetd takes the controlling terminal first
          → cosmic-greeter gets EPERM and crash-loops forever
```

Ubuntu FAILED THE BUILD on this (greetd.service there carries
`[Install] Alias=display-manager.service` and no `WantedBy=`, so
`systemctl enable greetd` collides with the existing alias). Fedora/EL ship
`WantedBy=` and no `Alias=`, so there is no collision, the build SUCCEEDS, and
the race ships. Succeeding is the worse outcome.

**Controls** — same EL10 base, same headless QEMU, same harness:

| cell | display-manager.service | contract |
|---|---|---|
| skipjack:cosmic | cosmic-greeter.service | **fail** |
| albacore:cosmic | cosmic-greeter.service | **fail** |
| skipjack:niri | greetd.service | ok |
| skipjack:xfce | greetd.service | ok |
| bonito-rawhide:kde | plasmalogin.service | ok |

So the contract is a working check that a desktop can pass, and cosmic is the
outlier. Two hypotheses were killed getting here and are recorded so nobody
re-runs them: it is **not** the contract racing its own `graphical.target`
(the unit reaches `auto-restart` with `ExecMainStatus=1` — it starts and
dies), and `rendered=absent` is **not** a signal of a broken desktop — it
appears on niri and xfce cells whose contract passes, because the harness runs
headless with no render node (`GPU: -vga virtio headless (no
render node/virgl)`). Only Plasma draws in this environment.

**Fix.** Both halves key off the symlink, never off whether cosmic-greeter is
installed: `configure-desktop-runtime.sh` picks whichever greeter already owns
the alias, and `install-desktop.sh` stops force-linking greetd beside it.

**Why it stayed invisible.** `desktop_contract` is `fatal=0`. The LUKS gate
asserts encryption, passphrase unlock and installed boot — all genuinely true
here — and `docs/MATRIX-STATUS.md` §1 already states that LUKS "does not
prove ... that a desktop session starts". Nothing was lying; there was simply
no axis reporting the contract, so a dead greeter and a working one look
identical from the board.

### 6. `FISHERMAN_OVERRIDE` never installed on images that ship no fisherman (2026-08-07)

**Affected:** all three `guppy` cells (Gentoo). Measured on `guppy:xfce`,
run 31131624108.

**Symptom:**

```
ERROR: fisherman not found on live image (VARIANT=guppy FLAVOR=xfce)
ERROR: and TBOX_E2E_IMAGE is unset, so the generic bootc path cannot name
       an image ref
exit code 3
```

**The misleading part.** The run spans 23:34 to 01:44, which reads exactly
like a 65-minute Gentoo build plus the 3600s `TUNAOS_E2E_INSTALL_TIMEOUT`. It
is not: the LUKS step ran for **55 seconds**. Everything before it was the
build. Check the step's own start/end times before concluding a timeout.

**Root cause.** `run_install()` in `scripts/iso-e2e.sh` had two statements
~260 lines apart: a hard `return 3` if `/usr/local/bin/fisherman` is absent,
and — far below it — the `scp` + `install` that puts `FISHERMAN_OVERRIDE`
at exactly that path. The check ran first, so an image shipping no fisherman
died without ever installing the binary the workflow had just built for it,
with "Build fisherman in a golang container" green immediately above.

**Fix.** Install the override before the check. That is also what the flag
means: *use this fisherman*, not *use this fisherman provided the image
already had one*. The error path now also distinguishes "the override path
does not exist on the runner" from "the file exists, so the scp/install
failed".

**What the reorder took with it.** The generic (non-tunaOS) bootc path keyed
off that same check — *no fisherman on the image* **and** `TBOX_E2E_IMAGE` set.
Once the override lands first, the first half is never true again, so a caller
naming a generic image would have taken the fisherman path and installed a
tunaOS ref resolved from `VARIANT`/`FLAVOR` instead. The image is therefore
probed **once, before** the override, and that probe is what the diversion
reads; the check after the override is only there to prove the override landed.

**Two more consequences of an image that ships nothing.** `install -D` cannot
create `/usr/local/bin` on the ostree layout: `-D` uses `mkdir -p`, `/usr/local`
is a symlink to a `../var/usrlocal` the image does not contain, and `mkdir -p`
refuses to create *through* a dangling symlink (`cannot create directory
'/usr/local': File exists` — the same failure `customize-live.sh` documents at
the symlink it makes at build time). Canonicalise with `readlink -m` first.

And the missing fisherman is itself a defect worth naming: the flatpak carrying
it carries the installer GUI, so that ISO has no installer a human could use —
`customize-live.sh` only downgrades the failed install to a warning because the
media is dev/E2E. The cell continues on the caller's binary and emits a
`::warning::` saying it did **not** cover that ISO's own installer.

---

### 7. A guest that overstays its poweroff makes the next boot impossible (2026-08-07)

**Affected:** any LUKS cell whose guest is slow to shut down. Measured on
`albacore:cosmic`, run 31140233496 — where `yellowfin:cosmic` passed on the
same commit, so this presents as one flaky cell.

**Symptom:**

```
==> fisherman install complete. Shutting down...
==> Waiting for VM to shut down...
==> LUKS passphrase gate: booting installed disk, injecting passphrase, expecting login...
qemu-system-x86_64: cannot create PID file: Cannot lock pid file: Resource temporarily unavailable
##[error]Process completed with exit code 1
```

**The misleading part.** The install had already logged `Installation
complete!` and the encrypted-disk evidence had already passed. The cell died
70 seconds later with no `ERROR:` line of its own — just qemu's one-liner and
a bare `exit 1` — which reads like a harness bug in whatever ran last (here,
the timelapse, which was merely the next thing to print).

**Root cause.** `poweroff_and_wait_vm` waited 30 × 2s and then returned
regardless. Its callers immediately launch the installed-disk boot on the
**same** `-pidfile`, and QEMU holds an exclusive lock on that file for its
entire life, so a guest still running at the end of the window does not delay
the gate, it forbids it. Two lines earlier in that run fisherman had reported
`cryptsetup luksClose: Device fisherman-root is still in use`, and a busy dm
device is exactly what `systemd-shutdown` spends its shutdown retrying — on
top of systemd's own 90s `DefaultTimeoutStopSec`, which 70s cannot outlast.
The generic path has a second stake in this: `swtpm` only exits when its QEMU
disconnects, and the TPM gate restarts it.

**Fix.** Wait long enough for a slow-but-healthy shutdown
(`TUNAOS_E2E_POWEROFF_WAIT`, default 180s), then stop asking: ACPI
`system_powerdown` over the monitor, then `SIGTERM`, then `SIGKILL`, and do
not return until the process is actually gone. The install is finished and its
target filesystem is already unmounted, frozen and flushed by then, so ending
the guest ourselves costs the following boot nothing. If it survives `SIGKILL`
the function now fails with that as the reason, and the passphrase gate's own
launch names a QEMU it could not start instead of exiting silently.

### 8. `guppy` shipped skopeo instead of podman, so its offline store read as empty (2026-08-07)

**Affected:** both `guppy` cells (Gentoo). Measured on `guppy:gnome`, run
31134373523 — 2h30m in, after a complete and correct image build, a green live
squash and 13 passing live-ISO checks.

**Symptom:**

```
--- names recorded in the offline store ---
[{... "names":["ghcr.io/tuna-os/guppy:gnome"] ...}]
==> Probing for ghcr.io/tuna-os/guppy:gnome...
==> Probing for localhost/guppy:gnome...
==> No local image in offline store — transferring from host via SSH
...
scp: write remote "/home/liveuser/luks-image-guppy-gnome.tar": Failure
ERROR: image transfer to guest timed out or failed
```

**The contradiction is the whole clue.** The dump prints the store's own index,
recording the exact ref the very next line fails to find. Fifteen lines above
it, twice: `sudo: podman: command not found`.

**Root cause, two layers.**

*The image.* `Containerfile.gentoo` emerged `app-containers/skopeo` and never
`app-containers/podman`. Skopeo looks like coverage — it is what bootc's
containers-image-proxy shells out to — but it cannot *start* a container, and
`guppy` probes `BACKEND=composefs-native`, whose install path cannot take
fisherman's `bootcDirect` shortcut: bootc runs inside a container podman
starts. Every other base has podman (the rpm and apt ones via
`build_scripts/10-base-packages.sh`, `Containerfile.arch` and `.debian` by
name) and Gentoo runs none of those scripts. Third time Gentoo was the last
base without something — see `sudo` (§ `test_live_sudo_every_base.bats`) and
flatpak before it.

*The harness.* Both offline-store probes were answered **inside** the guest:
`sudo podman image exists <ref>`, then `sudo jq -e ... images.json` as the
fallback. guppy has neither binary, so both exited 127 and the harness
concluded "image absent". It then fell through to the SSH image transfer.
`scripts/iso-e2e.sh` documents that transfer at length as physically impossible:
a ~4.9G tar into a tmpfs upperdir on a 4096M guest, #941. A missing tool read as
a missing image.

**Fix, matching the two layers.**

- `Containerfile.gentoo` emerges `app-containers/podman`.
- `customize-live.sh` asserts `command -v podman` next to its `sudo`
  assertion. The next base to omit it then fails the ISO build in seconds. It does
  not die in hour three of a matrix cell.
- `cat` reads the store index out of the guest once, and the **host** parses
  it (`store_records_image`). The probe then needs nothing from the guest
  that the diagnostic dump has not already proven it can do. The match is on
  `names` only, never `names-history`, because containers-storage will not
  resolve a ref that someone retagged away. A yes for one is the same dead end
  by another road.
- Podman-shaped diagnostics run only when the guest has podman. A skopeo-only
  base then says so once. It does not print `command not found` a dozen times
  and leave the reader to infer the cause from an absent `Found` line.

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

Every place in our code that calls `bootc install to-disk` directly must use
`fisherman recipe.json` instead. This is how dakota-iso does it. The
fisherman tool:
- Handles the choice between the ostree and composefs backends
- Preserves graphical.target on EL10 (ostree) via proper kernel kargs
- Handles LUKS/TPM encryption
- Installs flatpaks post-install
- Sets hostname
- Creates user accounts

See `_upstream-snapshots/dakota-iso/scripts/luks-install-qemu.sh` for an end-to-end
example that includes recipe generation, the fisherman build, SCP upload, and SSH invocation.

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

## Reading a published image without a container runtime

`podman run` is not always available. tunaOS#2485 sat for a day on "the next
step is a `podman run`". That environment had no podman, and no skopeo either.
It did not need one. Ask a red cell what mode a file has, or what it
holds, or whether the package landed. Plain HTTPS to the registry answers.

```bash
# Metadata for one path, per layer that carries it
scripts/inspect-published-image.py stat tuna-os/skipjack:gnome \
    etc/selinux/targeted/contexts/dbus_contexts

# Everything under a prefix
scripts/inspect-published-image.py ls tuna-os/skipjack:gnome \
    etc/selinux/targeted/contexts

# The bytes
scripts/inspect-published-image.py cat tuna-os/albacore:gnome \
    etc/selinux/config
```

Two paths, picked per layer. A `zstd:chunked` layer embeds a table of contents,
named by its `io.github.containers.zstd-chunked.manifest-position` annotation. A
range request fetches it, and it lists every path with mode, uid, gid, size,
xattrs and byte offsets. A 320 MB layer costs a 584 KB read. For any other layer the script
streams the blob through zstd or gzip into `tarfile`. That is slower, and it
writes nothing to disk.

**A large file is more than its table-of-contents entry.** It is one `reg` entry
plus trailing `chunk` entries, each with its own range. Read the `reg` range
alone and the request succeeds, zstd decompresses, and you hold a plausible file
with its tail missing. A 374,034-byte `file_contexts` measured 49,094 bytes that
way, ending mid-record, and looked exactly like a truncated write inside the
image. The script reads every chunk and checks the total against the declared
size. A short read then raises, and never answers.

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

### serial.log carries the journal, not only the console

`iso-e2e.sh` boots the installed system with
`systemd.journald.forward_to_console=1`, so `serial.log` holds each unit's own
stderr as well as systemd's status lines. Read it first for any unit that
failed: the reason is usually there in full.

This exists because `boot-diagnostics.txt` fails you on the worst boots. The
gate collects that file over SSH. The failures you most want to read are the
ones that break SSH: `dbus-broker` fails, so `systemd-logind` fails, so sshd
cannot open a PAM session. `NetworkManager` is a dbus dependent, so it takes
the TCP transport too. The file then holds one line:

```
WARNING: guest SSH unavailable; could not collect boot diagnostics
```

The serial console needs no service inside the guest, so it survives that.
When SSH *does* work, `boot-diagnostics.txt` is still richer — read both.

### What to look for in serial.log

| Pattern | Means | Action |
|---------|-------|--------|
| `Failed to start dbus-broker.service` | Everything that needs the bus fails after it: logind, NetworkManager, upower, the display manager. Nothing downstream is a separate bug | Find dbus-broker's own journal lines in `serial.log`; the cascade below it is noise |
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

build_scripts/checks/verify-desktop-experience.sh  # contract check (build + runtime)
  ├── build mode: creates /usr/share/tunaos/experience-contracts/<desktop>
  └── runtime mode: gated checks with diagnostic FAIL markers on ttyS0

Containerfile.overlay (OVERLAY_TYPE=nvidia)
  └── build_scripts/overlay/nvidia.sh               # NVIDIA AKMOD RPM install
```

## Critical architectural insight: IMAGE vs OSTREE DEPLOYMENT

A common source of confusion: `systemctl set-default graphical.target` in
`install-desktop.sh` works during the Containerfile build. But `bootc install
to-disk` creates a **fresh OSTree deployment** that does NOT preserve the
default.target symlink **on ostree-backend variants only**.

### Backend distinction

| Backend | Variants | Bootloader | Loses graphical.target? |
|---------|----------|------------|------------------------|
| **ostree** | EL10 (yellowfin, albacore, skipjack) | grub2 (bootupd) | ✅ YES |
| **composefs** | Fedora, Ubuntu, Arch, Debian, openSUSE, Gentoo | systemd-boot | ❌ NO |

The kernel cmdline override `systemd.unit=graphical.target` is the only reliable
way to make sure that EL10 systems, once installed, reach graphical.target.

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
  directly, with no OSTree deployment. The `set-default` in install-desktop.sh
  therefore works
- **For real installed systems:** users never hit this. They bootc install, and
  their system already runs graphical=true before install... but VERIFY this

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

All gates that fail share the same root cause — images built before the
`graphical.target` fix (commit `0c36e46`, pushed ~12:00 UTC):

| Workflow | Variant:Flavor | Mode | Error |
|----------|---------------|------|-------|
| Build Yellowfin | yellowfin:gnome | disk | `TUNAOS_DESKTOP_CONTRACT_OK` not emitted |
| Build Grouper | grouper:niri | disk | `TUNAOS_DESKTOP_CONTRACT_OK` not emitted |
| Publish Grouped ISOs | yellowfin (flagship) | ISO ready | `TUNAOS_LIVE_READY` not emitted + blank screen |
| LUKS E2E | yellowfin:kde | ISO → install | `flatpak: command not found` (separate root cause, see §1) |

Once we publish new images with the `graphical.target` fix, all three boot-gate
timeouts should resolve, if no NVIDIA-driver interaction from the §2 caveat occurs.

---

### 9. GHCR `permission_denied: write_package` on experimental variants

**Affected workflows:** `Build Flounder-sid` (`flounder-sid`), `Build Guppy` (`guppy`), `Build Sailfin` (`sailfin`), `Build Marlin` (`marlin`), `Build Flounder` (`flounder`), `Build Grouper` (`grouper`).

**Symptom:**
```
Error: writing blob: initiating layer upload to /v2/tuna-os/flounder-sid/blobs/uploads/ in ghcr.io: denied: permission_denied: write_package
```

**Root cause:**
A workflow pushes new container images for an experimental variant to GitHub Container Registry (`ghcr.io/tuna-os/<variant>`) for the first time. GitHub then automatically creates the package under the organization namespace. By default, a GHCR package that GitHub creates does NOT inherit write permissions for the repository's `GITHUB_TOKEN` from GitHub Actions workflows.

Even though `reusable-build-image.yml` declares `permissions: packages: write`, GitHub Container Registry applies its own access controls for each package. If the `tuna-os/<variant>` package settings do not explicitly grant access for Actions to `tuna-os/tunaOS`, `podman push` fails with `permission_denied: write_package`.

**Resolution (GitHub Org Admin / Package Owner Settings):**
For each variant package published to `ghcr.io/tuna-os/<package>`:
1. Navigate to **GitHub Org (`tuna-os`) → Packages → `<variant>`** (or `https://github.com/orgs/tuna-os/packages/container/<variant>/settings`).
2. Scroll to **Manage Actions access**.
3. Click **Add repository**, search for `tuna-os/tunaOS`, and set role to **Write**.
4. Save changes.

Applies to all experimental variant packages: `flounder-sid`, `flounder`, `guppy`, `sailfin`, `marlin`, `grouper`.

---

### 10. `bonito-rawhide` build failures (Quay CDN flakes & desktop contract gate failures)

**Affected workflows:** `Build Bonito Rawhide` (`bonito-rawhide`).

**Symptom 1 (EOF during the base image pull):**
```
Error: pulling image quay.io/fedora/fedora-bootc:rawhide: unexpected EOF / CDN blob transfer dropped mid-pull
```
**Symptom 2 (failure of the desktop contract gate):**
```
ERROR: desktop experience contract marker was not emitted
==> Screenshot 10-ready stddev=0
```

**Root cause & Mitigations:**
1. **Blob drop at the Quay CDN:** `reusable-build-image.yml` includes an explicit retry loop of 4 tries with exponential backoff (`sudo podman pull --platform "${PLATFORM}" "$BASE"`) before it calls `just build`. If `quay.io` drops a blob transfer, local podman retries the pull, and the job does not fail.
2. **Desktop contract gate / Rawhide desktop breakage:** Rawhide packages the development builds of Fedora as they roll. Desktop packages in Rawhide break temporarily, the defaults of the display manager change, or systemd target initialization changes. The boot gate in `reusable-build-image.yml` then times out as it waits for `TUNAOS_DESKTOP_CONTRACT_OK`.
   - Gate artifacts (`serial.log`, `10-ready.png`) go to the Actions run. They provide the evidence to identify the cause: display manager startup (`gdm`, `greetd`, `sddm`), missing systemd units (`graphical.target`), or package breakage.
   - The published ISO matrix (`publish-iso-groups.yml`) automatically skips `bonito-rawhide` tags that fail or never publish, via `#674`. A broken Rawhide build therefore does not block the release of stable ISOs.

---

### 11. Podman/crun cache mount options rejected (`rw + bind conflict`)

**Affected workflows:** `LUKS E2E`, Containerfile builds that use `--mount=type=cache,rw,...` options.

**Symptom:**
```
resolving mountpoints: invalid options "rw, shared, rw, bind", can only specify 1 'rw' or 'ro' option
```

**Root cause:**
Older versions of `crun` / `podman` on certain runner environments (e.g. Blacksmith or legacy GitHub runners) have a bug in how they parse mounts. The bug appears when a build passes explicit `rw` options to `--mount=type=cache,rw,...`. Because `type=cache` mounts default to read-write (`rw`) mode automatically, an explicit `rw` flag makes `crun` concatenate duplicate `rw` flags (`rw, shared, rw, bind`), and `crun` then rejects the mount initialization.

**Fix & Prevention:**
1. **Omit explicit `rw` in cache mounts**: In Containerfiles or build scripts, omit the redundant `rw` modifier from buildah/podman cache mounts. For example, use `--mount=type=cache,id=...` instead of `--mount=type=cache,rw,id=...`.
2. **Runner `crun` version alignment**: Make sure that the runner environments for GitHub Actions update `crun` to `v1.14.1+`. In that version, the parser for mount options removes duplicates from the default access modes.

---

### 12. Installer Walkthrough Automation & Frontend Drivers (#577)

**Affected workflows:** `Installer Walkthrough / Screenshots` (`installer-screenshots.yml`), `Installer Smoke` (`installer-smoke.yml`).

**Symptom:**
```
Drift in fixed-sleep sendkey choreography (ret/tab/tab/ret) causing screenshot capture drift or installer navigation failure across different desktop frontends.
```

**Root cause & Modernized Driver Design:**
1. **Drift in the blind sendkey choreography**: GUI installers change screen layouts or load times. Fixed sleeps (`sleep 45/60/60`s) and a fixed count of keys then break. The installers here are `bootc-installer` and the per-desktop `org.tunaos.Installer*` forks.
2. **State-aware step driver**: Replaced blind choreography in `scripts/run-walkthrough.sh` with the state-aware driver in `scripts/installer-walkthrough.py`. It polls QEMU screendumps, detects framebuffer stabilization (hash/stddev delta), does OCR matching against `tests/installer-screens.yaml`, and advances screens dynamically (`welcome -> disk -> encryption -> summary -> install -> done`).
3. **Per-desktop frontend keymaps & assertions**: Frontends (`org.bootcinstaller.Installer`, `org.tunaos.InstallerKde`, etc.) declare per-desktop keymaps and screen contracts. The driver enforces assertions on framebuffer stddev for compositors that render with GL (GNOME, KDE, COSMIC). For virgl-dependent compositors (Niri, XFCE) it only records them.
4. **Hardened installed-disk gate**: After UI installation completes, `iso-e2e.sh --disk` boots `install-disk.qcow2` and injects the test passphrase. It then verifies both LUKS encryption and the desktop experience contract (`TUNAOS_DESKTOP_CONTRACT_OK`), and a failure stops the job.

---

### 13. Debian COSMIC Desktop Package Gap (`flounder:cosmic` & `flounder-sid:cosmic`) (#924)

**Affected variants:** `flounder:cosmic`, `flounder-sid:cosmic`.

**Symptom:**
```
flounder:cosmic exit=1 missing required command: cosmic-comp
flounder-sid:cosmic exit=1 missing required command: cosmic-comp
```

**Root cause:**
Debian 13 (Trixie), Sid (unstable), and experimental repos do not ship COSMIC desktop packages (`cosmic-comp`, `cosmic-session`, etc.) natively in Debian archives. The `manifests/desktops/cosmic.yaml` PPA declaration `ppa:hepp3n/cosmic-epoch` specifies `condition: ubuntu`, so Debian builds skip it and do not install Ubuntu binary packages with a skewed ABI. As a result, apt soft-fails missing package names, and the published container images have no compositor.

**Resolution Strategy & Upstream Packages:**
1. **Track for upstream DEB packages**: `tuna-os/tunaos-packages#152` is the original Debian-specific ask. `tuna-os/tunaos#964` tracks the comprehensive plan: widen every COSMIC recipe to Debian *and* Ubuntu, then publish them to our own apt repo. The plan then retires `ppa:hepp3n/cosmic-epoch` entirely, the same third-party dependency that also causes grouper:cosmic's failures.
2. **Concrete progress, verified 2026-08-09**: of the 14 COSMIC recipes, 5 are gate-proven for both the `ubuntu` and `debian` Tideforge targets. They are `pop-icon-theme`, `cosmic-icon-theme`, `cosmic-randr`, `cosmic-panel` and `cosmic-comp` (`tunaos-packages` issues #204, #210, #214, #216). 4 of those 5 already reach `repo.tunaos.org/tideforge/<distro>/` through `.github/workflows/publish-tideforge-debs.yml`, a matrix that we dispatch by hand and widen step by step. `cosmic-comp`'s publish entry hasn't landed yet, even though its gate has. The other 9 have no widened gate yet. They include `cosmic-session`, which must land last because it `Requires` the other ten. `manifests/desktops/cosmic.yaml`'s `apt:` block still points at the PPA and must stay that way until all 14 reach the repo. `cosmic-session`'s own recipe now ships with an intentionally empty `ubuntu`/`debian` runtime-`Depends` list for exactly this reason. To point `flounder`/`grouper` at that repo today would trade a PPA build that works for an apt failure on unsatisfiable `Depends`.
3. **Matrix Visibility**: The flavor remains declared in `.github/build-config.yml`, and post-publish contract sweeps (`desktop-contract-sweep.yml` / #921) report it as red. That keeps the state visible, instead of a silent reduction of matrix coverage. A rebuild after package updates will replace existing tags cleanly, with no destructive registry actions.

---

### 14. Promotion Criteria for Experimental Variants to Nightly Build Schedule (#641)

**Affected variants:** `grouper`, `marlin`, `flounder-sid`, `guppy`, `sailfin`, `flounder`.

**Policy & Criteria:**
An experimental variant (`experimental: true`) is eligible for promotion to the nightly build schedule (`schedule: cron: "0 1 * * *"`) once it meets the following criteria:
1. **Clean Image Build**: All declared DE/flavor stages build green without failures.
2. **ISO & Disk Boot Gate**: Some variants have `build_iso: true` (e.g. `grouper`, `marlin`). For those, the ISO build and QEMU disk boot gate (`iso-e2e.sh --disk`) complete cleanly and emit `TUNAOS_DESKTOP_CONTRACT_OK`.
3. **No Soft Failures / Missing Compositors**: The post-publish sweep of the desktop contract looks for essential commands (e.g. `niri`, `cosmic-comp`, `nautilus`, `sddm`). They must be present and functional.

**Variant Status & Promotion Record:**
- `grouper` (Ubuntu 26.04): Promoted once image and ISO e2e boot gates pass cleanly.
- `marlin` (Arch): Promoted once it passes image and ISO e2e gates.
- `flounder-sid` (Debian Sid): Promoted upon green image builds (no ISOs).
- `guppy` (Gentoo) & `sailfin` (openSUSE TW): Promoted upon green image builds following target-stage fixes.
- `flounder` (Debian Trixie): Stays experimental until ostree base requirements (`≥ 2025.3`) land.

---

### 15. Post-Publish Desktop Contract Sweep & Published Artifact Verification (#925)

**Affected workflows:** `Post-Publish Desktop Contract Sweep` (`desktop-contract-sweep.yml` / #921).

**Symptom & Defect Class:**
Published container images built green in CI but shipped missing essential desktop components:
- `flounder:niri`: Missing `niri` compositor (no apt branch).
- `sailfin:gnome`: Missing `nautilus`, file manager, keyring (minimal pattern skeleton).
- `flounder:cosmic` & `flounder-sid:cosmic`: Missing `cosmic-comp` (Debian skips the Ubuntu PPA condition).
- `grouper:gnome`: Missing `gnome-keyring` (absent from apt list).
- `KDE on PlasmaLogin`: The build skipped enablement of the display manager unit, because of a hardcoded DM name or base-stage timing.

**Root cause:**
1. **Gating of build-time checks against published artifacts**: Build-time checks run only during initial image assembly. They do not run against published registry tags on GHCR (`ghcr.io/tuna-os/*`). We could publish stale tags or un-gated apt builds despite missing binaries.
2. **Apt Soft Failures**: Package managers on apt paths didn't hard-fail on missing optional packages. They soft-skipped missing compositors or desktop utilities.

**Solution Architecture:**
1. **Scheduled Post-Publish Sweep (`desktop-contract-sweep.yml`)**: Executes `build_scripts/checks/verify-desktop-experience.sh` nightly against all 47 published matrix cells.
2. **Four explicit verdicts per cell**:
   - `pass`: Image pulled, verified, and satisfies the full desktop contract.
   - `fail`: Image pulled but fails required binary or unit assertions.
   - `missing`: No published image tag in registry.
   - `error`: Network or registry pull failure.
3. **Assertion on display manager enablement**: Verifies that the display manager units (`gdm`, `sddm`, `plasmalogin`, `greetd`) are actively enabled in the image layer. Presence as installed unit files is not enough.

---

### 16. A red LUKS E2E cell can be stale evidence, not a live bug (#979, 2026-08-09)

**Affected cells (as measured):** `yellowfin:gnome/kde/niri/cosmic`, `albacore:gnome/kde/cosmic` — all four/three shown red in `docs/MATRIX-STATUS.md` as of its 2026-08-08 snapshot.

**Symptom (identical across all six jobs checked):**
```
TUNAOS_LUKS_E2E_PASS encrypted=1 passphrase_unlock=1 installed_boot=1
TUNAOS_LUKS_E2E_DESKTOP_CONTRACT desktop_contract=ok fatal=0
TUNAOS_LUKS_E2E_PIXEL_GATE result=absent frames=<200-400> stddev=na fatal=1
ERROR: pixel gate FAILED — the encrypted install unlocked and reached
       login, but nothing provably rendered (...).
##[error]Process completed with exit code 6.
```
Encryption, unlock, boot and the in-guest desktop contract all genuinely passed — the *only* signal that fails is `scripts/lib/pixel-gate.sh`'s pixel gate, and specifically its `shot=absent` path.

**Root cause — not a new defect, a timing gap:** `scripts/lib/pixel-gate.sh` commit `e20fd037` (#1102, merged 2026-08-08T02:42 UTC) added exactly this case — `shot=absent` *and* `contract=ok` — as an advisory `absent_contract_ok` verdict (`fatal=0`). The evidence was `gurnard:pantheon` and `grouper:xfce`, which hit the identical pattern. Every one of the six job logs that fail here (`yellowfin:gnome` run 31226672079, `yellowfin:kde`/`niri`/`cosmic` same run, `albacore:gnome`/`kde`/`cosmic` runs 31224487929/31224494825) carries a timestamp **before** `e20fd037` landed. They ran the *old* pixel-gate logic, which had no `contract=ok` carve-out and fell through to the fatal `absent` branch instead. Nobody has re-dispatched these cells since the fix merged. So `MATRIX-STATUS.md`'s "35/52 green" — sourced from the newest available run per cell — reports genuinely stale verdicts for these six, not current ones.

**Lesson:** before you treat a red cell of LUKS E2E as an open bug to diagnose, check the evidence lines of the job that failed. Compare them against `git log` for `scripts/lib/pixel-gate.sh`, or for whatever check failed. `fatal=1` on an old run doesn't mean the current tree would still produce it. A cell only needs new investigation once it fails again on a run that started *after* the relevant fix.

**Action taken:** re-dispatched `LUKS E2E` (`workflow_dispatch`) for `variant=yellowfin,flavor=all` (run [31286843546](https://github.com/tuna-os/tunaOS/actions/runs/31286843546)) and `variant=albacore,flavor=all` (run [31286849405](https://github.com/tuna-os/tunaOS/actions/runs/31286849405)) to get fresh, post-fix verdicts. Not yet observed to completion — a multi-cell LUKS sweep runs well past a single investigation session. Check those runs' own conclusions before you decide that the cells are already green.

**Separate, still-open, NOT covered by the above:** `yellowfin:xfce` (same run, job 93022287474) fails during the **image build** itself — `dracut-install: ERROR: installing '/root'` plus `error: Linting: Checks failed: 2`, retried 3 times. It never reached the LUKS/pixel-gate stage at all. `albacore:gnome/kde/cosmic` log the identical `dracut-install`/lint messages during their own builds, but the build still *succeeds* there. Those messages are non-fatal, and they match the warn-only default that `bootc container lint` documents — see #10 above. So this is not "the same bug, sometimes fatal": `yellowfin:xfce`'s build genuinely dies and needs its own root-cause pass, not a re-dispatch.

---

### 17. A failing gate took its own evidence with it (`no_silent_omissions`, 2026-09-13)

**Affected workflow:** `Desktop Contract Sweep` (`desktop-contract-sweep.yml`), and every desktop cell in `docs/MATRIX-STATUS.md`.

**Symptom:** the silent-omissions section read `**0 of 51** cells clean (0 read, 51 never read)`. `.github/green-criteria.yml` marks `no_silent_omissions` as a blocker. A cell it cannot score never reaches green. So the composite table rendered every desktop cell ⬜, and the header undercounted by up to 51 cells.

**What made it hard to see:** the sweep measured everything. In run [34692178123](https://github.com/tuna-os/tunaOS/actions/runs/34692178123), 52 of 53 jobs succeeded. All 51 cell jobs pulled their published image, ran `verify-package-wishlist.sh`, and wrote a verdict. The status page said "never read" about images it had already read.

**Root cause — two couplings, and either one alone does it:**

1. The `Baseline` job ended with a completeness gate. That gate fails on any cell short of a pass. `upload-artifact` sat after it with no `if:`. When the gate went red, it skipped that upload, and `all.json` never reached the artifact.
2. `scripts/gen-matrix-status.py` accepted artifacts only from runs whose conclusion was `success`.

The gate trips whenever a cell goes red. That is the ordinary state of a matrix under repair. It had tripped nightly since 2026-09-09, on 28 desktop-contract cells that fail. Between the two couplings, the axis went dark for exactly the period that most deserved a reader.

**Fix (#2495):** the verdict and the evidence are separate things.

- The completeness gate is its own step, after the upload. It still fails on `fail + miss + err + lost > 0`, so the sweep goes red as often as before.
- The upload runs `if: always()`.
- The reader accepts `failure` beside `success`. It still refuses cancelled, skipped, timed-out and in-flight runs.

Trust is per artifact, not per conclusion. The table is built as `reconciled.json`. It becomes `all.json` only once the sweep's reconciliation accounts for every dispatched cell. So the file's presence in the artifact asserts that the totals add up. An unreconciled run publishes `baseline.md` alone, and the reader's existing `exists()` check skips it. The fix leaves the classification of each cell alone: missing, error and lost still score untested, never clean (#1730).

**Lesson:** when a status page says an axis has no measurement, ask whether the measurement ran and then went in the bin. A gate that publishes nothing on failure hides its own inputs. Keep the artifact upload ahead of the gate that judges it, and let the run's conclusion carry the verdict on its own.

---

### 18. A self-check that balances on both sides cannot see a doubling (2026-09-13)

**Affected workflow:** `Desktop Contract Sweep` (`desktop-contract-sweep.yml`), the `Baseline` job.

**Symptom:** the baseline printed totals for twice as many cells as the sweep has.

```
DESKTOP CONTRACT BASELINE: 80/102 pass, 20 fail, 2 no image, 0 error, 0 lost
```

The sweep dispatches 51 cells. Every count in that line, and every row count in `baseline.md`, was twice its true value for as long as the job has existed.

**Root cause:** each cell artifact carries `result.json` twice. One copy sits at the artifact root; `scripts/evidence-bundle.sh` writes the second into `evidence/<variant>/<flavor>/amd64/`. The collate step ran `find results -name result.json`, which matched both, so every cell entered the table twice.

**Why the job's own guard missed it.** That job already asserts its arithmetic:

```
if (( pass + fail + miss + err + lost != total )); then
  echo "::error::baseline does not reconcile: ..."
```

Double both sides and they still balance. `102 == 102` held on every run, and the check reported a healthy table while every number in it was wrong. The guard targets a real defect — cells that went missing, per the reconciliation comment in that step — and it catches that one. It cannot catch a cell counted twice, because two of a cell is not a shortfall.

**Fix (#2497):** exclude the evidence copy from the tally, and assert what the arithmetic structurally cannot.

```
find results -name result.json -not -path '*/evidence/*'
dupes=$(jq -r 'group_by(.cell)[] | select(length > 1) | .[0].cell' found.json)
```

A cell reported twice now fails the step by name. The evidence bundle still uploads: this changes what the tally reads, not what the artifact carries.

**How it surfaced.** Only #2495 made it visible. The baseline artifact had never reached a red run, so nobody could compare the published table against the 51 cell artifacts beside it. The first fix exposed the second defect.

**Lesson:** a check for internal consistency proves the parts agree with each other. It does not prove they agree with the world. So pin at least one number to something outside the computation — here, that a cell appears once. Otherwise a proportional error stays invisible for as long as it stays proportional.

---

### 19. versionlock hides a package, and no exclude probe will show it (`bonito:gnome-t2`, 2026-09-13)

**Affected script:** `build_scripts/overlay/t2.sh`, and any future kernel swap that installs packages under their stock names.

**Symptom:** four builds of `bonito:gnome-t2` died on the same line, with a message that names the wrong thing.

```
Failed to resolve the transaction:
No match for argument 'kernel' in repositories 'copr:…:sharpenedblade:t2linux'
```

**Root cause:** `build_scripts/10-base-packages.sh` runs `dnf versionlock add kernel kernel-core …` against the **installed** Fedora kernel. That pins `7.2.4-200.fc44` and excludes every other version, the COPR's `7.1.9-200.t2.fc44` among them. dnf says so plainly, but only once the transaction stops naming a repo:

```
Argument 'kernel-7.1.9-200.t2.fc44' matches only packages excluded by versionlock.
```

**Three traps, and each one cost a build.**

1. **A repo-scoped install reports the lock as an empty repo.** Under `--from-repo`, the only candidates come from that one repo. The lock excludes all of them, so dnf words the emptiness in terms of the pin. The pin is not the problem, and neither is the repo.
2. **`repoquery` and `install` disagree, honestly.** `repoquery --repo=<id> 'kernel*'` lists all 18 packages while `install --from-repo=<id> kernel` finds none — same id, same options, seconds apart in one job. `repoquery` does not apply versionlock's excludes. That gap reads like a broken flag and is not one.
3. **An exclude probe answers "(none)" and is right.** `grep -E '^(exclude|excludepkgs)=' /etc/dnf/dnf.conf /etc/yum.repos.d/` finds nothing, because versionlock keeps a list of its own. Run `dnf versionlock list` too, or the probe misses the filter in force.

**Why no earlier swap hit it.** This repo holds two other kernel swaps, and each one evades the lock by accident. `overrides/nvidia/10-kernel-swap.sh` bypasses dnf entirely with `rpm -ivh`. `overlay/asahi.sh` installs `kernel-16k`, a name the lock list does not carry. `t2` installs packages named exactly `kernel`, so it is the first swap the lock bites.

**Fix (#2498):** release the lock, swap, then re-apply it to the kernel that was installed. Release every name `10-base-packages.sh` locks, or a straggler holds one package and the transaction fails on that alone. Re-application matters as much as release. `10-kernel-swap.sh` gives the reason after its own swap: a later transaction that pulls a different kernel would undo the whole point of the script.

**Lesson:** "no match for argument" means the solver had no candidate. It does not mean the repo lacks the package. So before you doubt the repo, the id, or the flag, ask what filters the candidate set — `dnf.conf`, the `.repo` files, **and** `dnf versionlock list`. Two dnf subcommands can also disagree about the contents of a repo. When they do, suspect a difference in the filters that each of them applies. Call either of them broken only after that.

---

### 20. A scriptlet can fail without failing the transaction (`bonito:gnome-t2`, 2026-09-13)

**Affected script:** `build_scripts/overlay/t2.sh`, and any overlay that installs a kernel with dnf.

**Symptom:** the image built, signed, and passed the desktop contract. Two jobs later the boot gate panicked.

```
Kernel panic - not syncing: VFS: Unable to mount root fs on unknown-block(0,0)
CPU: 2 UID: 0 PID: 1 Comm: swapper/0 Not tainted 7.1.9-200.t2.fc44.x86_64
```

**Root cause:** the image carried no initramfs. `kernel-core`'s `%posttrans` runs `rpm-ostree kernel-install`, which calls dracut. `/boot` is a tmpfs mount in `Containerfile.overlay`, dracut stages its output in the default tmpdir, and the rename into `/boot` crosses a filesystem boundary:

```
>>> Generating initramfs
>>> error: rpm-ostree kernel-install: Adding kernel: Running dracut:
    Invalid cross-device link (os error 18)
```

**The part that cost the cycle:** dnf called that transaction a success. The scriptlet failed, the message went to the log, and the exit status stayed 0. So the build went green with a kernel and no way to mount root. The first sign of trouble arrived at the boot gate: a different job, a different log, and a symptom that points at the kernel. The install that produced it looks innocent.

**Fix (#2500):** `TMPDIR=/boot` on the install, so dracut's rename stays on one filesystem. Then build the initramfs again, explicitly, into `/lib/modules/<kver>/`, which is part of the image; `/boot` is a tmpfs and does not survive the build. `overrides/nvidia/10-kernel-swap.sh` met the identical EXDEV and its comment is where both halves come from.

Then assert the result. A missing initramfs, or one too small to hold the root storage drivers, now fails the build at the step that creates it:

```
ERROR: no initramfs at /lib/modules/<kver>/initramfs.img after the swap
```

**Lesson:** a green dnf transaction means dnf resolved and installed. It does not mean every scriptlet succeeded. When a package's `%post` or `%posttrans` builds something the image needs, check for that artefact yourself. Otherwise the first report you get is the symptom, in a later job, and it points somewhere else.

---

### 21. An unbounded wait makes every check below it unreachable (2026-09-13)

**Affected script:** `build_scripts/checks/verify-base-contract.sh`, and any gate that waits on a machine before it judges the machine.

**Symptom:** the boot gate reports a timeout and the serial log carries no verdict at all.

```
Starting tunaos-base-contract.service - Verify TunaOS base boot contract...
[ 314.604325] tunaos-base-contract.service: start operation timed out. Terminating.
[ 314.635751] Failed to start tunaos-base-contract.service
```

Between those two lines the contract printed nothing. It had run for the unit's whole `TimeoutStartSec` and died mid-call.

**Root cause:** the contract opened with `systemctl is-system-running --wait`. That call returns when startup reaches a terminal state, and a machine whose startup never settles never reaches one. The wait had no bound, so the unit's timeout became the bound.

**The expensive part:** every check after that line was unreachable on exactly the images those checks exist to judge. The contract asserts `bootc status`. It also asserts that the system message bus is alive. #2484 added that check for `skipjack`, whose dbus-broker dies on an SELinux denial and takes the bus down with it. That is the same class of machine whose startup never settles, so the assertion written for the failure could never run on it. The gate said `timeout`; the defect had a name, and nobody heard it.

**First fix (#2501, #2506), now withdrawn:** bound the wait at 120s, then at 240s, and ask again without `--wait` when the bound expires. That turned a silent kill into a named verdict. It did not make the checks below reachable.

**The real cause (#2514):** the wait was on the unit's own job, so no bound can be correct. Three facts close the loop:

- `systemctl is-system-running --wait` returns when the manager leaves `starting`.
- The manager leaves `starting` when the initial boot transaction completes.
- `tunaos-base-contract.service` is `Type=oneshot` and `WantedBy=multi-user.target`, so its job is in that transaction until the script exits.

The contract waited for a state that the contract itself held back. The serial log shows it. On `hummingbird:gnome`, `Startup finished` came 10-14 ms after the wait gave up, at both bounds:

| bound | wait gave up | `Startup finished` | userspace |
|---|---|---|---|
| 120s | `133.320660` | `133.334844` | 2min 7.074s |
| 240s | `252.338862` | `252.351227` | 4min 7.191s |

The userspace time tracked the bound, not the image. The value "2min 7s" looked like a slow image, and it caused the move to 240s. That move doubled the value.

Desktop cells lost the verdict in a different way. `scripts/iso-e2e.sh` sees `TUNAOS_DESKTOP_CONTRACT_OK` and stops the VM while the base contract is still in the wait:

```
[ 30.170663] systemd[1]: tunaos-base-contract.service: Main process exited, code=killed, status=15/TERM
```

That is `bonito:gnome-t2`, run 34768771243. So no cell ran `bootc status` or the system-bus check.

**Fix (#2514):** take one sample of the state and do not wait. `checks/e2e-runtime-checks.sh` already samples this way.

| state | verdict |
|---|---|
| `maintenance`, `stopping`, `offline`, no answer | fail |
| `initializing`, `starting` | pass; the unit starts after `multi-user.target`, so multi-user was reached |
| `running`, `degraded` | pass |

The contract also prints the names of the failed units in a `TUNAOS_BASE_CONTRACT_NOTE` line. That line is evidence, not a verdict. `TUNAOS_SETTLE_WAIT_SECONDS` and its bound tests are gone. `tests/bats/test_no_settle_wait_inside_boot_transaction.bats` finds each script that a boot unit starts, and fails if one of them waits on `is-system-running`.

**Lesson:** a gate that waits must bound the wait, and #2501 was correct about that. But first make sure that the wait can end. A check that runs as a job in the boot transaction cannot wait for that transaction to complete. If a measured duration moves when you change the bound, the bound is the thing you measure.

### 22. Two reports that both mistook silence for a verdict (2026-09-13)

**Affected scripts:** `.github/scripts/update-build-status.sh`, `scripts/gen-matrix-status.py`.

**Symptom:** the README snapshot gave `bonito` **1/16**. All sixteen bonito cells had promoted that day. All sixteen tags were live.

```
| 🎣 `bonito` | **1/16** | [✅ 2026-09-13](.../34768771243) | — | base,base-hwe,base-nvidia,
  gnome,cosmic,kde,niri,xfce,gnome-hwe,gnome-asahi,gnome-nvidia,cosmic-nvidia,
  kde-nvidia,niri-nvidia,xfce-nvidia |
```

**Root cause:** both scorers read one run per variant. Then they scored every cell from that run. `gen-matrix-status.py` stated the premise outright:

> a build run asserts its whole matrix at once, so the newest conclusive run IS the current state of every cell it scheduled

`build-<variant>.yml` accepts a flavor-filtered `workflow_dispatch`. One rebuild of one flavor breaks that premise. Run 34768771243 built `gnome-t2` alone. It then became the newest conclusive run. The fifteen cells it never scheduled scored "not reached".

The `Failing` column stayed empty. That was the tell. Nothing had failed. The table never mentioned those cells, and it read the silence as doubt.

**Fix:** score each cell from the newest conclusive run that asserted *that cell*. Walk runs newest first. Let the first conclusive Promote win, so a fresh failure beats an older success. Only a cell that no run asserted reaches further back. Read the Gate from the same run as the Promote, so one cell's `builds` and `boots` describe one image.

The walk stops once every flavor has a verdict. The ordinary case still costs one fetch.

Measured: `bonito` 1/16 → 16/16, `skipjack` 12/17 → 13/17, totals 112/139 → 128/138. No row lost a cell.

**That same day the drift gate on the same document failed from the other end.** `--check-structure` masks live content. It then compares a committed `MATRIX-STATUS.md` against a fresh one. CI churn must never fail a pull request. The gate failed #2512 on this line:

```
+N cell(s) in the most recent sweep are missing (no published image), errored
+(registry/runner trouble), or lost (job produced no result)...
```

A sweep finished between the commit and the check. It returned one `missing` cell. The generator then emitted a caveat paragraph that no committed copy could hold.

**The mask works line by line. A rewrite of a line cannot hide a line that one side lacks.** Every other live readout there is a line that always exists. Only its numbers move, so the mask covers it. Name a conditional paragraph in `VOLATILE_LINE` instead.

**Lesson:** a report claims what someone measured, and silence measures nothing. Ask two questions of every line you print. Did a run look at this cell? Might this line not print at all? A comparison that normalises what both sides hold will still fail on what one side alone holds.

### 23. A gate broke on prose that no diff ever showed (2026-09-14)

**Affected files:** `.github/scripts/update-build-status.sh`, `scripts/gen-matrix-status.py`, and the two documents they write.

**Symptom:** the STE ratchet failed on `main`, and on every pull request that touched a `.md` file. It stayed red for three days. The change behind it had passed that same gate.

```
2026-09-14T18:54 push         main                        failure
2026-09-15T11:08 pull_request automation/matrix-status    failure
2026-09-16T10:57 pull_request automation/matrix-status    failure
2026-09-17T01:58 pull_request strategy/q3-close-q4-...    failure
```

**Root cause:** STE lints `README.md` and `docs/MATRIX-STATUS.md`. Nobody writes either by hand. tunaOS#2512 edited the README paragraph inside `update-build-status.sh`, and the local STE run read 3048 — correctly, because the committed README still held the old sentence. Automation regenerated it two days later. The fresh sentence carried a filler word and a passive clause, so the total reached 3052 against a budget of 3050.

So the prose that STE reads had moved, and the diff behind it showed nothing. The gate had nothing to catch. The author had nothing to see.

The second cause needs no author at all. `gen-matrix-status.py` prints a caveat paragraph only while the newest sweep holds a cell with no clean verdict. One sweep result makes that paragraph appear, and the repo total moves on its own. That same paragraph had already broken the drift gate in §22, for the same reason from the other side.

**Fix.** Edit the generator and the committed file in one commit, so the linted bytes land in the diff. Keep a conditional paragraph short and active, because its cost falls on whoever opens the next pull request. `tests/test_generated_prose_is_visible_in_the_diff.py` holds the two in step.

**Never raise the budget to clear this.** It looks like a fix and it discards the ratchet. The prose was wrong. The number was right.

**Lesson:** ask what reads a file, not who writes it. A generator's output is source for every gate that measures it, and a generator's prose is prose. When a gate reads something your diff never showed, your green describes the old bytes.

### 24. Our own fix ran after the thing that needed it (`flounder:kde`, 2026-09-17)

`flounder:kde` and `flounder:kde-nvidia` produced no ISO on any run for two
weeks. The job died in tacklebox's embedded live baseline:

```
>>> [customize] (1/2) baseline.sh
useradd: cannot create directory /home
Error: live customize for flounder-kde: ... exit status 12
```

**Root cause.** Two scripts in this repo disagree, and neither is wrong alone.
`ostree-layout.sh` makes `/home` a symlink to `var/home`, then creates
`/var/home`, and says why: the targets must exist at build time, because later
layers probe the aliases. `99-cleanup.sh` then runs `find /var -mindepth 1
-maxdepth 1 -delete`, which removes it. It restores the dpkg and apt paths and
nothing else. So `/home` in the published image points at nothing.

**Who it hits.** Only the bases where cleanup runs after layout:
`Containerfile.arch`, `.debian` and `.gentoo`. The bases with no layout step
take their layout from the parent and never show it. That list names the
failing cells exactly, which is what confirmed the mechanism.

**Why nothing caught it.** tunaOS already carries this fix. `customize-live.sh`
holds `mkdir -p "$(readlink -f /home)"`, under a comment that describes this
exact failure. It is script 2/2. The baseline that needs it is script 1/2, and
tacklebox puts every `--script` after its embedded baseline. So the fix sat in
this repo and never ran before the code it protects.

**Fix.** Restore the `/var` alias targets in `99-cleanup.sh`, beside the dpkg
restore and for the same stated reason. The wipe stays. The `tmpfiles.d` entries
still own the runtime side.

**Lesson:** a fix has a position, not only a body. When a script fixes something
for its own callers, ask what runs before it. Ours was correct, tested and
inert, and the symptom pointed at another repository the whole time.

### 25. The same fix, written once, for one base out of two (`marlin:gnome` arm64, 2026-09-17)

`marlin:gnome` built an ISO on amd64 and died on arm64, in the same tacklebox
baseline as §24 but for a different reason:

```
>>> [customize] (1/2) baseline.sh
useradd: UID 1000 is not unique
Error: live customize for marlin-gnome: ... exit status 4
```

**Root cause.** tacklebox's baseline asks for `--uid 1000` and does not check.
marlin's arm64 legs build from `ghcr.io/tuna-os/archlinuxarm`, because
`docker.io/archlinux` is x86_64 only, and Arch Linux ARM ships its own account
there. Read from the published layer, not assumed:

```
alarm:x:1000:1000::/home/alarm:/bin/bash
```

`build-archlinuxarm-base.yml` keeps it on purpose, which suits a base image and
not an ISO built from one. The x86_64 Arch base has no such account, so one
architecture failed and the other did not.

**Why nothing caught it.** This repo had already solved it. A block in
`01-workarounds.sh` removes the cloud account that `docker.io/library/ubuntu`
ships at the same UID, and its comment states the reason: the real error lands
"an hour downstream, in another repo's code, with no mention of this image".
The guard was `IS_UBUNTU`. The diagnostic that block prints for this failure
sat inside the same branch, so Arch ARM hit the identical bug in silence.

**Fix.** Remove the `alarm` account on the same terms as the Ubuntu one: only
when it is still named `alarm` and still at exactly 1000. Move the warning out
of the per-base branch, so the next base to ship an account at 1000 reports
itself in the build that causes it.

**Lesson:** when a workaround names one base, ask which other bases have the
same shape. A guard is a claim about who is affected, and this one was a guess
that nobody revisited when a second base arrived.

### 26. The fix the build never ran (`marlin:gnome` arm64, 2026-09-17)

The next `marlin` run failed on the same line as §25, with the same message:

```
>>> [customize] (1/2) baseline.sh
useradd: UID 1000 is not unique
Error: live customize for marlin-gnome: ... exit status 4
```

**Root cause.** `Containerfile.arch` does not run `01-workarounds.sh`. Only
`Containerfile.el10` and `Containerfile.ubuntu` run that script. The §25 fix
went into it, so the Arch branch could never execute. The Containerfile even
says so, ten lines above the spot where the call belongs: this base leaves out
the numbered base scripts. That comment was already correct and nobody read
it.

**Why nothing caught it.** The test asserted that the removal existed in
`01-workarounds.sh`, and it did, so the test passed. Presence in a file is not
reach from a build. No test checked the call in `Containerfile.arch`, and the
run conclusion for §25 looked like a fix that worked.

**Fix.** The removal now lives in `build_scripts/free-uid-1000.sh`. That script
reads no distro flags and needs no build context, so any Containerfile calls it
in one line. `Containerfile.arch` calls it directly. `01-workarounds.sh` calls
the same script, so one copy serves every base. The test now asserts that each
Containerfile which builds ISOs reaches the script, on a line that is not a
comment.

**Lesson:** prove that the build reaches the fix. A test that finds code in a
file proves only that the file holds the code. This is the fourth entry in this
document where the repository already held the correct fix and the fix did not
reach the failure.

### 27. A volume label two characters too long (`bonito-rawhide` nvidia ISOs, 2026-09-17)

bonito-rawhide built one nvidia ISO and failed the other four:

```
xorriso : FAILURE : -volid: Text too long (34 > 32)
Error: xorriso: ... -commit: exit status 5
```

**Root cause.** ISO 9660 caps the volume ID at 32 characters. xorriso rejects
the whole build instead of a quiet truncation. The media name was
`tunaos-<variant>-<flavor>`, and `bonito-rawhide` is a long variant name:

| media name | length | result |
| --- | --- | --- |
| `tunaos-bonito-rawhide-cosmic-nvidia` | 35 | failed |
| `tunaos-bonito-rawhide-gnome-nvidia` | 34 | failed |
| `tunaos-bonito-rawhide-niri-nvidia` | 33 | failed |
| `tunaos-bonito-rawhide-xfce-nvidia` | 33 | failed |
| `tunaos-bonito-rawhide-kde-nvidia` | 32 | built |

**Why the pattern misleads.** Every cell that died was an nvidia cell, so the
column reads as an NVIDIA fault. It is not. `kde-nvidia` sits exactly on the
limit and built. The nvidia flavors carry the longest names in the
group. The same overflow reaches `flounder-sid-cosmic-nvidia` at 33
characters. Nothing is wrong with those images.

**Fix.** `tunaos_iso_media_name` in `scripts/lib/common.sh` caps the name, and
both ISO builders call it. A name that already fits stays exactly as it was,
because the boot path depends on the label. tacklebox puts the same string on the
kernel cmdline as `root=tbox:CDLABEL=...`. Both sides read `media_name`, so a
shorter name moves them together. The cap drops the `tunaos-` prefix first:
every ISO in the matrix carries that prefix, and `<variant>-<flavor>` is what
identifies the media.

**Lesson:** when a tool enforces a limit, put the real names in a test. This
one held for years, because no variant name was long enough. One new variant
with a longer name then broke four cells at once. Test the boundary: the
`kde-nvidia` row at exactly 32 is what proves the rule. An off-by-one there
would rename the one label that the kernel cmdline depends on.

### 28. The kernel was there; the index was not (`marlin:gnome` arm64, 2026-09-17)

§26 cleared the UID 1000 failure on this cell. The next build reached much
further and stopped here:

```
no kernel found under /usr/lib/modules (looked for modules.dep):
7.2.6-1-aarch64-ARCH
```

**Root cause.** tacklebox selects the kernel by the index, not the kernel:
`[ -f "$d/modules.dep" ] || continue`. The image had the directory and
`initramfs.img`, and only `modules.dep` was absent from it.

This entry first said the image also had `vmlinuz` and booted. It had neither.
§30 has the correction and the second fault behind the same message.

`depmod` lives in `build_scripts/26-packages-post.sh`, which
`Containerfile.arch` does not run. On x86_64 that cost nothing: the base is
`docker.io/archlinux`, `pacman -S linux` installs a kernel, and pacman's
depmod hook writes the index. On aarch64 the base is
`ghcr.io/tuna-os/archlinuxarm`, whose rootfs already carries
`linux-aarch64`, so `pacman -S --needed` does nothing, the hook never fires,
and nothing indexes the tree.

**Why it stayed hidden.** Two covers. The image boots without the index, so
every runtime gate passed. The ISO job also died sooner, at UID 1000, and did so
for weeks. One fix exposed the next.

**Fix.** `Containerfile.arch` runs `depmod` on the kernel that step already
resolved, before dracut. The tests assert reach on a line that is not a
comment, the shared `KVER`, the order against dracut, and the absence of
`|| true`.

**Lesson:** an early failure hides every later one, so a fix that works will
often reveal a second fault instead of a green cell. Read the new error as
progress and check what it says. A still-red cell is not proof that the fix
failed. The scope note in the test file matters as much.
Four other bases never call `depmod` and are right not to, because their
package managers index the tree themselves. An assertion that demanded it
everywhere would fail code that already works.

### 30. One error message, two faults (`marlin:gnome` arm64, 2026-09-17)

§28 ran `depmod` on this cell. The next build printed the same words:

```
no kernel found under /usr/lib/modules (looked for modules.dep):
7.2.6-1-aarch64-ARCH
```

The obvious read is that the fix did not reach the build. It did. The build
log shows `depmod` at step 25 of 37, and the module index is in the published
image.

**Root cause.** tacklebox has one message for a loop with two requirements:

```sh
for d in /usr/lib/modules/*/; do
  [ -f "$d/modules.dep" ] || continue
  if [ -f "$d/vmlinuz" ] && [ -f "$d/initramfs.img" ]; then
```

Past the first line, an absent `vmlinuz` ends at the same `exit 1` with the
same text about `modules.dep`. The kernel binary was the missing file.

Arch Linux ARM's `linux-aarch64` ships the kernel as `/boot/Image` alone,
where Arch's x86_64 `linux` owns `/usr/lib/modules/<kver>/vmlinuz`.
`build_scripts/bootc/ostree-layout.sh` runs `rm -rf /boot`, so on aarch64 it
deleted the only copy. The arm64 images shipped with no kernel.

`Containerfile.debian` and `Containerfile.gentoo` (twice) copy the kernel
across by hand, one step before they call that script. Gentoo's comment says why:
"Both must happen BEFORE the ostree layout below, which deletes /boot". Arch
was a fourth copy that nobody wrote.

**The evidence.** This session had no container runtime, so it read the
published image straight from the registry. Fetch the manifest with a ghcr pull
token, stream each layer through `zstd -dc | tar -t`, then grep the names.
`modules.dep` sits in layer 55. Neither `vmlinuz` nor `Image` appears in any of
the 65 layers. The section above on a published image without a container
runtime holds the recipe.

**Why it stayed hidden.** No Gate runs on arm64, so nothing booted the image
and nothing reported that it could not boot. The ISO job was the first reader
of `/usr/lib/modules/<kver>/vmlinuz`, an hour downstream and in another
repository.

**Fix.** `ostree-layout.sh` rescues the kernel into the module directory before
it clears `/boot`, which is a no-op on every variant that already has one.
`Containerfile.arch` now stops the build when `vmlinuz` is absent. It no longer
builds an initramfs for a kernel that is not there.

**Lesson:** an error message names the check that failed, not always the file
that is missing. Read the code that prints it before you conclude a fix did not
land. Where two causes share a message, the second cause reads as proof that the
first one is still there. The control that settled it was the amd64
cell of the same run, which built, booted and published from the same
Containerfile.

### 31. The ISO builds and cannot boot (`marlin:gnome` arm64, 2026-09-18)

§30 gave this cell its kernel back. `Build Live ISO` then SUCCEEDED for the
first time and produced a 6.16 GB arm64 ISO. One step later the job was still
red, at `Boot gate: verify ISO readiness`: no readiness marker in 900 seconds,
and a blank framebuffer.

**Root cause.** The live root filesystem uses a compressor the kernel cannot
read. From the guest serial console, about 648 times until the timeout:

```
mount: /run/rootfsbase: fsconfig() failed:
       Filesystem uses "zstd" compression. This is not supported.
Warning: Tacklebox: cannot loop-mount /LiveOS/marlin-gnome.rootfs.sfs
```

tacklebox squashes the live rootfs with zstd. Arch Linux ARM's `linux-aarch64`
has no zstd support in its squashfs driver, and the kernel itself says so. That
makes this a measurement, not a guess. Arch's x86_64 `linux` does support zstd,
so the amd64 cell of the same run boots and publishes. The same fault predicts
skipjack's `iso:cosmic (linux-arm64)`, which builds and then fails its gate the
same way.

**Where the fix is not.** `scripts/build-iso-tacklebox.sh` writes the recipe,
and the recipe has no compressor field. tacklebox chooses zstd. So the change
belongs upstream in tuna-os/tacklebox, or in the ARM kernel config. Do not
reach for a workaround in this repository.

**Two things this also exposed.**

The failure never stops. `/sbin/tbox-live-root` line 135 runs `return` outside
a function, so the error path aborts and dracut tries again under `A start job
is running for dracut initqueue hook (no limit)`. A mount failure with no
recovery costs a full gate timeout on each arm64 cell, in place of seconds.

The gate measures less than it reports. On the arm64 runner it prints
`tesseract not installed` and `requires Pillow and requests`, so its keyword and
forbidden-text assertions SKIP. Its verdict here was still right, because the
frame-difference check caught the blank screen on its own. Read which assertions
ran before you trust a pass from this gate on arm64.

**Lesson:** a cell that builds is not a cell that works. Three fixes in a row
can each be correct while the cell stays red. Check which STEP failed, not
whether the job did. The serial log holds the evidence, and the job log does
not carry it: pull the e2e artifact.

### 29. A gate that asked the wrong question (`Audit NVIDIA release assets`, 2026-09-17)

This job showed red on all 15 runs it ever had. It never passed once, so it
never reported anything.

**Root cause.** It checked GitHub Releases for a per-flavor tag with at least
one asset. This repository does not publish ISOs that way:

- `attach-release` in `reusable-build-artifacts.yml` defaults to `false`, so
  every cell skips "Attach ISO to GitHub Release". In a green ISO job for nvidia, that step still reads
  skipped. "Upload ISO to Cloudflare R2" succeeds next to it.
- The releases that exist are per desktop (`gnome-20260916`), not per flavor,
  so no tag ever started with `gnome-nvidia-`.
- Those releases carry no assets at all.

The audit also asked about `gnome50-nvidia`, which is in no variant of
`.github/build-config.yml`. Someone hardcoded its flavor list, and the list
then drifted.

**Why nothing caught it.** A check that stays red looks the same on day 15 as
on day 1. Nobody could tell a real fault from a broken question, so the row
carried no information.

**Fix.** The audit now lists `live-isos/<variant>-<flavor>-latest.iso` in R2,
which is where the upload step puts each ISO and the path `docs/TESTING.md`
tells users to fetch. The cell list comes from `build-config.yml`, filtered to
`build_image` and `build_iso`, so it tracks the matrix and cannot drift. That
widened the audit from 6 hardcoded names, one of them fictional, to 27 real
cells. Without R2 credentials it skips and does not fail, which is what the
upload step and `prune-r2.yml` already do for forks.

**Lesson:** a check that has never passed is not a strict check. It is an
unread one. When a gate shows red on every run it ever had, doubt the question
before the answer. Delete such a gate only after the intent behind it has
somewhere true to live.
