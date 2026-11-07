# Boot Diagnostics and Gate Workflow

Back to the [index](README.md).

## Glossary of Components

| Tool | Role | Source |
|------|------|--------|
| **tacklebox** | ISO builder — takes a recipe.json with bootable environments and produces a combined ISO with dedup squashfs | `github.com/tuna-os/tacklebox` |
| **fisherman** | Disk installer — takes a recipe.json with disk/image/encryption params and runs the full install (partition, format, bootc install, flatpaks, hostname) | `github.com/tuna-os/fisherman` |
| **bootc-installer** | GTK/libadwaita installer frontend — wraps fisherman for GUI installs | `github.com/tuna-os/bootc-installer` |
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
  └── build_scripts/desktop/install-desktop.sh # DE install + graphical.target fix (BUILD LAYER ONLY!)
        └── creates tunaos-desktop-contract.service (TimeoutStartSec=30)
              └── calls build_scripts/checks/verify-desktop-experience.sh --runtime
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

The proper fix is to use `fisherman` (from `tuna-os/fisherman`) with a recipe.json.
The recipe selects the backend:

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

See [`recipe.go` in `tuna-os/fisherman`](https://github.com/tuna-os/fisherman/blob/dev/fisherman/internal/recipe/recipe.go)
for the full Recipe struct with all fields.

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
