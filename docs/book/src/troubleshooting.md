# Troubleshooting

Common build and runtime issues, their causes, and solutions.

## Build Failures

### Package install failures (DNF errors)

**Symptoms:** `Error: Unable to find a match`, download failures, or mirror errors during `dnf install`.

**Cause:** Network instability, mirror unavailability, or package version conflicts.

**Solutions:**
- The build scripts use `dnf_retry` (4 attempts with exponential backoff) — let it retry
- Check `.build-logs/` for the variant-specific error log
- For persistent mirror issues, try building from a different network or use CI
- Run `just clean-cache` and rebuild to force fresh metadata

### "No more mirrors to try" (AlmaLinux/CentOS)

**Symptoms:** All DNF operations fail with mirror errors, especially on ARM64.

**Solutions:**
```bash
# Clear DNF cache and rebuild
just clean-cache
just build yellowfin gnome

# Or use GHCR image as base (skip DNF steps)
# This only works for chain builds, not from-scratch base builds
```

### gnome-shell file conflicts (Skipjack)

**Symptoms:** `file /usr/share/glib-2.0/schemas/org.gnome.shell.gschema.xml conflicts between attempted installs of gnome-shell-49.4 and gnome-shell-common-48.3`.

**Cause:** CentOS Stream 10 ships gnome-shell 48.x; TunaOS installs gnome-shell 49.x from COPR. The older `gnome-shell-common` package contains files that conflict.

**Status:** Fixed upstream in `tuna-os/github-copr#23` (Obsoletes: gnome-shell-common). Rebuild expected to resolve.

**Workaround (if rebuilding before COPR update):**
```bash
# In gnome.sh, before the compat install:
dnf -y remove gnome-shell-common || true
```

### "bootc container lint" warnings (Bonito/Fedora)

**Symptoms:** Build succeeds but `bootc container lint --fatal-warnings` reports up to 3 failures on Bonito.

**Cause:** Fedora-specific tmpfiles.d paths may not be fully cleaned up in the container.

**Investigation:** Remove `|| true` from `cleanup.sh` for `IS_FEDORA` blocks, capture the exact warnings, then fix the underlying path issues.

**Workaround:** These warnings are non-fatal for image functionality. They're suppressed with `|| true` until underlying issues are addressed.

### "image not known" after rechunking

**Symptoms:** After `chunkah` rechunking and `podman load`, subsequent `podman build` fails with "image not known".

**Cause:** BTRFS storage driver index bug — loaded images may not be immediately visible.

**Solution:** The build pipeline runs `podman system prune -af` before loading to work around this. If you encounter it manually:
```bash
podman system prune -af
# Then rebuild
```

### SELinux denials during build

**Symptoms:** `AVC denials` or `Permission denied` during `podman build`.

**Solution:** The Justfile automatically adds `--security-opt label=disable`. Always use `just build`, not raw `podman build`. If you must run manually:
```bash
podman build --security-opt label=disable ...
```

### Containerfile "FROM" resolution errors

**Symptoms:** `Error: unable to resolve reference "ghcr.io/ublue-os/akmods-nvidia-open:centos-10"` or similar.

**Solutions:**
- Verify network connectivity to `ghcr.io`
- Authenticate to GHCR if hitting rate limits:
  ```bash
  echo "$GITHUB_TOKEN" | podman login ghcr.io -u YOUR_USERNAME --password-stdin
  ```
- Check that the tag exists: `skopeo list-tags docker://ghcr.io/ublue-os/akmods-nvidia-open`

## ISO Build Issues

### tacklebox download failure

**Symptoms:** `scripts/build-iso-tacklebox.sh` fails to pull `ghcr.io/tuna-os/tacklebox:latest`.

**Solutions:**
```bash
# Build tacklebox from source
export TACKLEBOX_FROM_SOURCE=1
just iso yellowfin gnome

# Or manually build
git clone https://github.com/tuna-os/tacklebox.git
cd tacklebox && go build -o tacklebox ./cmd/tacklebox
```

### ISO build requires root

**Symptoms:** `Error: operation requires root privileges` during `just iso`.

**Cause:** tacklebox needs loopback device access for ISO creation.

**Solution:** Run with `sudo` (handled automatically by the build script).

### Boot fails on ISO

**Symptoms:** ISO builds successfully but fails to boot (black screen, kernel panic).

**Checklist:**
1. Verify the ISO boots in a VM first (`just demo-iso yellowfin gnome`)
2. Check that your hardware supports UEFI boot (no legacy BIOS support)
3. Ensure secure boot is disabled or keys are enrolled

## Runtime Issues

### Desktop fails to start

**Symptoms:** Boot succeeds but desktop environment doesn't launch.

**Diagnosis:**
```bash
# Check display manager status
systemctl status gdm   # GNOME
systemctl status sddm  # KDE

# Check for failed services
systemctl --failed

# View journal
journalctl -b -p err
```

### Flatpak apps not available

**Symptoms:** Flatpak commands fail or apps are missing.

**Solutions:**
```bash
# Verify Flathub remote
flatpak remotes

# Add Flathub if missing
flatpak remote-add --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo

# Repair installation
flatpak repair
```

### Homebrew not working

**Symptoms:** `brew: command not found` or brew install failures.

**Solutions:**
```bash
# Homebrew is installed at /var/home/linuxbrew
eval "$(/var/home/linuxbrew/bin/brew shellenv)"

# Check if brew is installed
ls /var/home/linuxbrew/bin/brew
```

### Boot fails after switch

**Symptoms:** `bootc switch` succeeded but system won't boot.

**Recovery:**
```bash
# From GRUB/systemd-boot menu, select previous deployment
# Or from a rescue environment:
bootc rollback
```

## Logs and Diagnostics

### Where to find logs

| Log | Location |
|-----|----------|
| Build logs | `.build-logs/<variant>-<flavor>.log` |
| Build cache | `.rpm-cache/` |
| System journal | `journalctl -b` |
| bootc status | `bootc status` |
| Image info | `cat /etc/tunaos-release` |

### Getting help

- **GitHub Issues:** [Report a bug](https://github.com/tuna-os/tunaOS/issues)
- **Matrix Chat:** [#tunaos:reilly.asia](https://matrix.to/#/%23tunaos:reilly.asia)
- **Universal Blue Discord:** [Discord](https://discord.gg/WEu6BdFEtp)
