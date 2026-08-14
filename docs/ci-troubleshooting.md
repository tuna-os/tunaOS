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
| 20 | Network pull stalls indefinitely mid-blob — zero output for 2+ hours before a hard `timeout 1800` (added defensively once #19 made the pull real) started firing instead | Serial log showed 41 layers pulling cleanly in under a minute (~1/sec), then complete silence starting the blob copy for layer 42/65 — no error, no further progress, ever. First theory: QEMU SLIRP Path-MTU-Discovery blackhole, fixed by clamping the guest's own interface MTU to 1400. **Disproven by a second run**: with the MTU clamp applied, the pull stalled on the exact same blob (`sha256:a525a8e1...`) for the same ~29 minutes. Checked whether that blob was anomalously large via GHCR's manifest API directly (`skopeo` isn't installed on this box; used `curl`+the registry's token endpoint instead) — it's 77MB, unremarkable next to several 200-400MB layers earlier in the same manifest that pulled fine. So this isn't a size- or MTU-triggered fragmentation issue; root cause is unresolved (plausibly SLIRP NAT connection-tracking flakiness under the GitHub Actions runner's own nested virtualization) | Stopped trying to prevent the stall and instead made it recoverable: pre-pull the image with `podman pull` in a retry loop (4 attempts, 600s each) before invoking fisherman. `podman pull` skips layers already present in local storage, so a retry after a stall only has to re-fetch the blob that didn't finish, not the whole image; once the image is local, fisherman's `bootcViaContainer` `CheckImage()` finds it and skips its own pull entirely. The guest-side MTU clamp (bug #20 v1) is left in place since it's harmless, but is not the operative fix. **Superseded by bug #21** — the real fix eliminates the network pull entirely. |
| 21 | Network pull stall (bug #20) is a symptom: the ISO already embeds an offline payload store (`LiveOS/store.squashfs.img`, built by tacklebox's `BuildOfflineStore()`) but the live system never mounts it, so fisherman's only option was the network path | tacklebox correctly builds an overlay-driver containers-storage of the payload image and places it at `LiveOS/store.squashfs.img` on the ISO (confirmed by reading tacklebox's `offline_store.go` and `build.go`). However: (1) the live system had no systemd mount unit to loop-mount it, (2) `/etc/containers/storage.conf` had no `additionalimagestores` entry pointing at the mount point, so podman/buildah/bootc could never find images inside the additional store even if it were mounted. Pattern: projectbluefin/dakota-iso's approach (their `configure-live.sh` mounts/registers the store), adapted for tacklebox's separate-store format (dakota-iso has since moved to embedding the store directly in the main squashfs as VFS at `/var/lib/containers/storage`, but the mount-based approach is correct for tacklebox's current output). | **Part 1 — `customize-live.sh`**: Added `var-lib-superiso\x2dstore.mount` systemd unit (loop-mounts `LiveOS/store.squashfs.img` → `/var/lib/superiso-store`), enabled via `local-fs.target.wants`. Added `/etc/containers/storage.conf.d/99-tunaos-offline-store.conf` with `additionalimagestores = ["/var/lib/superiso-store"]`. The existing `fuse-overlayfs` mount_program config (bug #10) is still required — the live rootfs is overlayfs and the additional store is overlay-driver. **Part 2 — `scripts/iso-e2e.sh`**: Probes the guest for `podman image exists localhost/<v>:<f>` (dev ISOs) and `ghcr.io/tuna-os/<v>:<f>` (production ISOs); if found, sets recipe `image` to `containers-storage:<ref>` — no network pull needed. Falls back to the bug #20 retry loop only when the offline store is absent (older ISOs). `targetImgref` always names the GHCR production ref so the installed system tracks the right image for updates. |

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
concluded "image absent" — then fell through to the SSH image transfer that
`scripts/iso-e2e.sh` documents at length as physically impossible (a ~4.9G tar
into a tmpfs upperdir on a 4096M guest, #941). A missing tool read as a missing
image.

**Fix, matching the two layers.**

- `Containerfile.gentoo` emerges `app-containers/podman`.
- `customize-live.sh` asserts `command -v podman` next to its `sudo`
  assertion, so the next base to omit it fails the ISO build in seconds rather
  than hour three of a matrix cell.
- The store index is read out of the guest once with `cat` and parsed on the
  **host** (`store_records_image`), so the probe needs nothing from the guest
  that the diagnostic dump has not already proven it can do. Matching is on
  `names` only, never `names-history`: containers-storage will not resolve a
  ref that was retagged away, so answering yes for one is the same dead end by
  another road.
- Podman-shaped diagnostics are gated on the guest actually having podman, so
  a skopeo-only base says so once instead of printing `command not found` a
  dozen times and leaving the cause to be inferred from an absent `Found`
  line.

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

build_scripts/checks/verify-desktop-experience.sh  # contract check (build + runtime)
  ├── build mode: creates /usr/share/tunaos/experience-contracts/<desktop>
  └── runtime mode: gated checks with diagnostic FAIL markers on ttyS0

Containerfile.overlay (OVERLAY_TYPE=nvidia)
  └── build_scripts/overlay/nvidia.sh               # NVIDIA AKMOD RPM install
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

---

### 9. GHCR `permission_denied: write_package` on experimental variants

**Affected workflows:** `Build Flounder-sid` (`flounder-sid`), `Build Guppy` (`guppy`), `Build Sailfin` (`sailfin`), `Build Marlin` (`marlin`), `Build Flounder` (`flounder`), `Build Grouper` (`grouper`).

**Symptom:**
```
Error: writing blob: initiating layer upload to /v2/tuna-os/flounder-sid/blobs/uploads/ in ghcr.io: denied: permission_denied: write_package
```

**Root cause:**
When new experimental variant container images are pushed to GitHub Container Registry (`ghcr.io/tuna-os/<variant>`) for the first time, GitHub automatically creates the package under the organization namespace. By default, newly created GHCR packages do NOT inherit write permissions for the repository's `GITHUB_TOKEN` from GitHub Actions workflows.

Even though `reusable-build-image.yml` declares `permissions: packages: write`, GitHub Container Registry enforces package-level access controls. If the `tuna-os/<variant>` package settings do not explicitly grant Actions access to `tuna-os/tunaOS`, `podman push` fails with `permission_denied: write_package`.

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

**Symptom 1 (Base image pull EOF):**
```
Error: pulling image quay.io/fedora/fedora-bootc:rawhide: unexpected EOF / CDN blob transfer dropped mid-pull
```
**Symptom 2 (Desktop contract gate failure):**
```
ERROR: desktop experience contract marker was not emitted
==> Screenshot 10-ready stddev=0
```

**Root cause & Mitigations:**
1. **Quay CDN blob drop:** `reusable-build-image.yml` includes an explicit 4-attempt retry loop with exponential backoff (`sudo podman pull --platform "${PLATFORM}" "$BASE"`) before invoking `just build`. If `quay.io` drops a blob transfer, local podman retries the pull instead of failing the job.
2. **Desktop contract gate / Rawhide desktop breakage:** Rawhide packages rolling Fedora development builds. When desktop packages or display manager defaults temporarily break in Rawhide, or when systemd target initialization changes, the boot gate in `reusable-build-image.yml` times out waiting for `TUNAOS_DESKTOP_CONTRACT_OK`.
   - Gate artifacts (`serial.log`, `10-ready.png`) uploaded to the Actions run provide diagnostic evidence to identify whether failure is due to display manager startup (`gdm`, `greetd`, `sddm`), missing systemd units (`graphical.target`), or package breakage.
   - Unpublished/failing `bonito-rawhide` tags are automatically skipped from the published ISO matrix (`publish-iso-groups.yml`) via `#674` so a broken Rawhide build does not block stable ISO releases.

---

### 11. Podman/crun cache mount options rejected (`rw + bind conflict`)

**Affected workflows:** `LUKS E2E`, Containerfile builds utilizing `--mount=type=cache,rw,...` options.

**Symptom:**
```
resolving mountpoints: invalid options "rw, shared, rw, bind", can only specify 1 'rw' or 'ro' option
```

**Root cause:**
Older versions of `crun` / `podman` on certain runner environments (e.g. Blacksmith or legacy GitHub runners) exhibit a mount-parsing bug when explicit `rw` options are passed to `--mount=type=cache,rw,...`. Because `type=cache` mounts default to read-write (`rw`) mode automatically, specifying an explicit `rw` flag causes `crun` to concatenate duplicate `rw` flags (`rw, shared, rw, bind`), causing `crun` to reject the mount initialization.

**Fix & Prevention:**
1. **Omit explicit `rw` in cache mounts**: When specifying buildah/podman cache mounts in Containerfiles or build scripts, omit the redundant `rw` modifier (e.g. use `--mount=type=cache,id=...` instead of `--mount=type=cache,rw,id=...`).
2. **Runner `crun` version alignment**: Ensure GitHub Actions runner environments update `crun` to `v1.14.1+` where mount option parsing deduplicates default access modes.

---

### 12. Installer Walkthrough Automation & Frontend Drivers (#577)

**Affected workflows:** `Installer Walkthrough / Screenshots` (`installer-screenshots.yml`), `Installer Smoke` (`installer-smoke.yml`).

**Symptom:**
```
Drift in fixed-sleep sendkey choreography (ret/tab/tab/ret) causing screenshot capture drift or installer navigation failure across different desktop frontends.
```

**Root cause & Modernized Driver Design:**
1. **Blind sendkey choreography drift**: Fixed sleeps (`sleep 45/60/60`s) and fixed key counts break when GUI installers (`bootc-installer` and the per-desktop `org.tunaos.Installer*` forks) change screen layouts or load times.
2. **State-aware stepping driver**: Replaced blind choreography in `scripts/run-walkthrough.sh` with the state-aware driver in `scripts/installer-walkthrough.py`. It polls QEMU screendumps, detects framebuffer stabilization (hash/stddev delta), performs OCR matching against `tests/installer-screens.yaml`, and advances screens dynamically (`welcome -> disk -> encryption -> summary -> install -> done`).
3. **Per-desktop frontend keymaps & assertions**: Frontends (`org.bootcinstaller.Installer`, `org.tunaos.InstallerKde`, etc.) declare per-desktop keymaps and screen contracts. Framebuffer stddev assertions are enforced on compositors with GL rendering (GNOME, KDE, COSMIC) while recorded for virgl-dependent compositors (Niri, XFCE).
4. **Hardened installed-disk gate**: After UI installation completes, `iso-e2e.sh --disk` boots `install-disk.qcow2`, injects the test passphrase, and verifies both LUKS encryption and desktop experience contract (`TUNAOS_DESKTOP_CONTRACT_OK`) as a blocking gate.

---

### 13. Debian COSMIC Desktop Package Gap (`flounder:cosmic` & `flounder-sid:cosmic`) (#924)

**Affected variants:** `flounder:cosmic`, `flounder-sid:cosmic`.

**Symptom:**
```
flounder:cosmic exit=1 missing required command: cosmic-comp
flounder-sid:cosmic exit=1 missing required command: cosmic-comp
```

**Root cause:**
Debian 13 (Trixie), Sid (unstable), and experimental repos do not ship COSMIC desktop packages (`cosmic-comp`, `cosmic-session`, etc.) natively in Debian archives. The `manifests/desktops/cosmic.yaml` PPA declaration `ppa:hepp3n/cosmic-epoch` specifies `condition: ubuntu`, which is skipped on Debian builds to prevent ABI-skewed Ubuntu binary package installation. As a result, apt soft-fails missing package names, producing published container images with no compositor.

**Resolution Strategy & Upstream Packaging:**
1. **Upstream DEB packaging track**: `tuna-os/tunaos-packages#152` is the original Debian-specific ask; the comprehensive plan (widen every COSMIC recipe to Debian *and* Ubuntu, publish them to our own apt repo, then retire `ppa:hepp3n/cosmic-epoch` entirely — the same third-party dependency that also causes grouper:cosmic's failures) is tracked in `tuna-os/tunaos#964`.
2. **Concrete progress, verified 2026-08-09**: of the 14 COSMIC recipes, 5 (`pop-icon-theme`, `cosmic-icon-theme`, `cosmic-randr`, `cosmic-panel`, `cosmic-comp`) are gate-proven for both the `ubuntu` and `debian` Tideforge targets (`tunaos-packages` issues #204, #210, #214, #216), and 4 of those 5 are already published to `repo.tunaos.org/tideforge/<distro>/` via `.github/workflows/publish-tideforge-debs.yml` (a manually-dispatched, incrementally-widened matrix — `cosmic-comp`'s publish entry hasn't landed yet even though its gate has). The other 9, including `cosmic-session` (which must land last — it `Requires` the other ten), are not yet gate-widened. `manifests/desktops/cosmic.yaml`'s `apt:` block still points at the PPA and must stay that way until all 14 are published — `cosmic-session`'s own recipe currently ships with an intentionally empty `ubuntu`/`debian` runtime-`Depends` list for exactly this reason, so pointing `flounder`/`grouper` at that repo today would trade a working PPA build for an unsatisfiable-`Depends` apt failure.
3. **Matrix Visibility**: The flavor remains declared in `.github/build-config.yml` and reported as red in post-publish contract sweeps (`desktop-contract-sweep.yml` / #921) to maintain transparent tracking rather than silently shrinking matrix coverage. Rebuilding after packaging updates will replace existing tags cleanly without destructive registry actions.

---

### 14. Promotion Criteria for Experimental Variants to Nightly Build Schedule (#641)

**Affected variants:** `grouper`, `marlin`, `flounder-sid`, `guppy`, `sailfin`, `flounder`.

**Policy & Criteria:**
An experimental variant (`experimental: true`) is eligible for promotion to the nightly build schedule (`schedule: cron: "0 1 * * *"`) once it meets the following criteria:
1. **Clean Image Build**: All declared DE/flavor stages build green without failures.
2. **ISO & Disk Boot Gate**: For variants with `build_iso: true` (e.g. `grouper`, `marlin`), the ISO build and QEMU disk boot gate (`iso-e2e.sh --disk`) complete cleanly emitting `TUNAOS_DESKTOP_CONTRACT_OK`.
3. **No Soft Failures / Missing Compositors**: Post-publish desktop contract sweep verifies essential desktop commands (e.g. `niri`, `cosmic-comp`, `nautilus`, `sddm`) are present and functional.

**Variant Status & Promotion Tracking:**
- `grouper` (Ubuntu 26.04): Promoted once image and ISO e2e boot gates pass cleanly.
- `marlin` (Arch): Promoted upon passing image and ISO e2e gates.
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
- `flounder:cosmic` & `flounder-sid:cosmic`: Missing `cosmic-comp` (Ubuntu PPA condition skipped on Debian).
- `grouper:gnome`: Missing `gnome-keyring` (absent from apt list).
- `KDE on PlasmaLogin`: Display manager unit enablement skipped due to hardcoded DM name or base-stage timing.

**Root cause:**
1. **Build-time vs Published Artifact Gating**: Build-time checks run only during initial image assembly, not against published registry tags on GHCR (`ghcr.io/tuna-os/*`). Stale tags or un-gated apt builds could be published despite missing binaries.
2. **Apt Soft Failures**: Package managers on apt paths didn't hard-fail on missing optional packages, soft-skipping missing compositors or desktop utilities.

**Solution Architecture:**
1. **Scheduled Post-Publish Sweep (`desktop-contract-sweep.yml`)**: Executes `build_scripts/checks/verify-desktop-experience.sh` nightly against all 47 published matrix cells.
2. **Four Explicit Cell Verdicts**:
   - `pass`: Image pulled, verified, and satisfies full desktop contract.
   - `fail`: Image pulled but fails required binary or unit assertions.
   - `missing`: No published image tag in registry.
   - `error`: Network or registry pull failure.
3. **Display Manager Enablement Assertion**: Verifies display manager units (`gdm`, `sddm`, `plasmalogin`, `greetd`) are actively enabled in the image layer rather than merely present as installed unit files.

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
Encryption, unlock, boot and the in-guest desktop contract all genuinely passed — the *only* failing signal is `scripts/lib/pixel-gate.sh`'s pixel gate, and specifically its `shot=absent` path.

**Root cause — not a new defect, a timing gap:** `scripts/lib/pixel-gate.sh` commit `e20fd037` (#1102, merged 2026-08-08T02:42 UTC) added exactly this case — `shot=absent` *and* `contract=ok` — as an advisory `absent_contract_ok` verdict (`fatal=0`), on the evidence of `gurnard:pantheon` and `grouper:xfce` hitting the identical pattern. Every one of the six failing job logs checked here (`yellowfin:gnome` run 31226672079, `yellowfin:kde`/`niri`/`cosmic` same run, `albacore:gnome`/`kde`/`cosmic` runs 31224487929/31224494825) is timestamped **before** `e20fd037` landed — they ran the *old* pixel-gate logic, which had no `contract=ok` carve-out and fell through to the fatal `absent` branch instead. None of these cells has been re-dispatched since the fix merged, so `MATRIX-STATUS.md`'s "35/52 green" — sourced from the newest available run per cell — is reporting genuinely stale verdicts for these six, not current ones.

**Lesson:** before treating a red LUKS E2E cell as an open bug to diagnose, check the failing job's evidence lines against `git log` for `scripts/lib/pixel-gate.sh` (or whatever check actually failed) — `fatal=1` on an old run doesn't mean the current tree would still produce it. A cell only needs new investigation once it fails again on a run that started *after* the relevant fix.

**Action taken:** re-dispatched `LUKS E2E` (`workflow_dispatch`) for `variant=yellowfin,flavor=all` (run [31286843546](https://github.com/tuna-os/tunaOS/actions/runs/31286843546)) and `variant=albacore,flavor=all` (run [31286849405](https://github.com/tuna-os/tunaOS/actions/runs/31286849405)) to get fresh, post-fix verdicts. Not yet observed to completion — a multi-cell LUKS sweep runs well past a single investigation session; check those runs' actual conclusions before assuming this note means the cells are already green.

**Separate, still-open, NOT covered by the above:** `yellowfin:xfce` (same run, job 93022287474) fails during the **image build** itself — `dracut-install: ERROR: installing '/root'` plus `error: Linting: Checks failed: 2`, retried 3 times, never reaching the LUKS/pixel-gate stage at all. `albacore:gnome/kde/cosmic` log the identical `dracut-install`/lint messages during their own builds but the build still *succeeds* there (non-fatal, matching `bootc container lint`'s documented warn-only default — see #10 above), so this is not simply "the same bug, sometimes fatal" — `yellowfin:xfce`'s build genuinely dies and needs its own root-cause pass, not a re-dispatch.
