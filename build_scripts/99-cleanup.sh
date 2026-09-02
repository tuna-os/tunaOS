#!/usr/bin/env bash

set -xeuo pipefail
printf "::group:: ===Image Cleanup===\n"
source /run/context/build_scripts/lib.sh

rpmdb_stage2_guard

# Image cleanup
# Specifically called by build.sh

# The compose repos we used during the build are point in time repos that are
# not updated, so we don't want to leave them enabled.
# dnf config-manager --set-disabled baseos-compose,appstream-compose

pkg_clean

rm -rf /.gitkeep

# Clean up /run artifacts left by package manager/selinux/tuned during build (bootc lint: nonempty-run-tmp)
rm -rf /run/dnf /run/selinux-policy /run/tuned

# Clean /var/log dnf artifacts (bootc lint: var-log)
if [[ "$PKG_MGR" == "dnf" ]]; then
	rm -f /var/log/dnf5.log /var/log/dnf5.log.*
	rm -f /var/log/dnf.log /var/log/dnf.rpm.log /var/log/dnf.librepo.log /var/log/hawkey.log
fi

# Clean /var but skip mounted directories
find /var -mindepth 1 -maxdepth 1 ! -path '/var/cache' -delete 2>/dev/null || true
find /var/cache -mindepth 1 -delete 2>/dev/null || true

# Restore the dpkg database path and apt's log directory, for apt-based
# variants, immediately after the wipe above — for the exact reason
# Containerfile.debian's own comment on the FIRST /var wipe gives ("apt/dpkg
# run in later layers ... before tmpfiles has ever executed"), which applies
# here too, one wipe later.
#
# ostree-layout.sh (source: Containerfile.debian's dpkg relocation step)
# already relocates /var/lib/dpkg to /usr/lib/sysimage/dpkg and symlinks it
# back, and creates /var/log/apt, specifically so apt/dpkg keep working
# through their default paths at BUILD time — not just after boot, when
# systemd-tmpfiles would apply the tmpfiles.d entry it also writes. But this
# script runs in base-no-de AFTER that, does its own `find /var ... -delete`
# above, and base-no-de is the base every desktop flavor (gnome/kde/xfce/
# cosmic/niri) is built FROM — each running its own `apt-get install` via
# install-desktop.sh in a LATER layer, still at build time, with no boot
# (and so no systemd-tmpfiles) in between. Without this, that install runs
# against a /var with no dpkg database at the path apt/dpkg actually look at,
# and no /var/log/apt for them to write to (tunaOS#880 — flounder-sid's
# python3 postinst failed running fwupd's rtupdate hook with exit status 4;
# that hook's only command without a `|| true` is `py3clean -p fwupd
# /usr/share/fwupd`, and py3clean resolves a package's files via `dpkg -L`).
#
# Guard on the symlink's REAL target rather than PKG_MGR: cheap, and correct
# even if this script is ever reordered relative to ostree-layout.sh.
if [[ -d /usr/lib/sysimage/dpkg ]]; then
	mkdir -p /var/lib /var/log/apt
	ln -sfnT ../../usr/lib/sysimage/dpkg /var/lib/dpkg
fi

# Declare /var/cache/dnf and /var/lib/dnf in tmpfiles.d so they're recreated on first boot (bootc lint: var-tmpfiles)
# (dnf-only — apt uses /var/lib/apt/lists which is handled by its own tmpfiles.d)
if [[ "$PKG_MGR" == "dnf" ]]; then
	printf 'd /var/cache/dnf 0755 root root - -\nd /var/lib/dnf 0755 root root - -\nd /var/cache/libdnf5 0755 root root - -\nd /var/lib/dnf5 0755 root root - -\n' >/usr/lib/tmpfiles.d/dnf-cache.conf
fi

# Remove /var/lib/dnf state files left by the build (recreated by dnf on first use)
if [[ "$PKG_MGR" == "dnf" ]]; then
	rm -rf /var/lib/dnf /var/lib/dnf5
fi

# Generate tmpfiles.d entries for remaining /var/lib dirs created by packages
# (bootc lint: var-tmpfiles). These dirs/files are owned by their respective packages
# and persist correctly across bootc deployments via the /var stateful partition.
# We declare the top-level dirs so bootc lint knows they are intentional.
python3 - <<'PYEOF'
import os, stat

entries = set()
var_lib = '/var/lib'
if os.path.isdir(var_lib):
    for name in os.listdir(var_lib):
        full = os.path.join(var_lib, name)
        if os.path.isdir(full) and not os.path.islink(full):
            s = os.stat(full)
            mode = oct(stat.S_IMODE(s.st_mode))[2:]
            try:
                import pwd, grp
                u = pwd.getpwuid(s.st_uid).pw_name
                g = grp.getgrgid(s.st_gid).gr_name
            except Exception:
                u = str(s.st_uid)
                g = str(s.st_gid)
            entries.add(f'd /var/lib/{name} 0{mode} {u} {g} - -')

# Specifically handle /var/lib/selinux subdirs as they often contain non-directory files
selinux_lib = '/var/lib/selinux'
if os.path.isdir(selinux_lib):
    for name in os.listdir(selinux_lib):
        full = os.path.join(selinux_lib, name)
        if os.path.isdir(full):
            entries.add(f'd /var/lib/selinux/{name} 0755 root root - -')

if entries:
    with open('/usr/lib/tmpfiles.d/tunaos-var-lib.conf', 'w') as f:
        f.write('# Auto-generated: top-level /var/lib dirs created by package installation\n')
        for e in sorted(entries):
            f.write(e + '\n')
    print(f"Generated tmpfiles.d entries for {len(entries)} /var/lib dirs")

# Do the same for /var/log
log_entries = set()
var_log = '/var/log'
if os.path.isdir(var_log):
    for name in os.listdir(var_log):
        full = os.path.join(var_log, name)
        if os.path.isdir(full) and not os.path.islink(full):
            s = os.stat(full)
            mode = oct(stat.S_IMODE(s.st_mode))[2:]
            try:
                import pwd, grp
                u = pwd.getpwuid(s.st_uid).pw_name
                g = grp.getgrgid(s.st_gid).gr_name
            except Exception:
                u = str(s.st_uid)
                g = str(s.st_gid)
            log_entries.add(f'd /var/log/{name} 0{mode} {u} {g} - -')

if log_entries:
    with open('/usr/lib/tmpfiles.d/tunaos-var-log.conf', 'w') as f:
        f.write('# Auto-generated: top-level /var/log dirs\n')
        for e in sorted(log_entries):
            f.write(e + '\n')
PYEOF

mkdir -p /var /boot

# /var/tmp must EXIST in the built image, not merely be declared in tmpfiles.d.
#
# tacklebox rebuilds the live-ISO initramfs by running dracut inside the
# published image (`podman run ... --entrypoint /bin/sh <image>`). There is no
# boot in that path, so systemd-tmpfiles never runs and never creates it, and
# dracut's --tmpdir defaults to /var/tmp:
#
#   realpath: /var/tmp: No such file or directory
#   dracut[F]: Invalid tmpdir '/var/tmp'.
#
# tacklebox reports that as "does the image ship dracut?", which is why #1010
# was filed as flounder missing dracut. dracut is installed and running — it is
# the tmpdir that is absent.
#
# Containerfile.debian:181 and Containerfile.arch:156 already create it in
# their base stages for exactly this reason. Then this script's `find /var
# -mindepth 1 -maxdepth 1 -delete` above removes it again, and the `mkdir -p
# /var /boot` on the line above does not put it back — so wiring 99-cleanup.sh
# into those Containerfiles silently undid a fix that was already there.
#
# Recreate it here, where it is deleted, so every variant gets it rather than
# each base stage having to re-solve it. 1777 is the standard mode; the
# symlink guard matches how the rest of this script treats /var entries.
if [[ ! -L /var/tmp ]]; then
	mkdir -p /var/tmp
	chmod 1777 /var/tmp
fi

# Make /usr/local writeable, if /usr/local exists skip
ls /usr/local || ln -s /var/usrlocal /usr/local

# image-info.json sometimes has restrictive permissions from the build
# process, preventing non-root processes from reading it (breaks
# fastfetch, uupd, and other tools that source image metadata).
# This chmod is a workaround — root cause should be fixed in the
# Containerfile or the tool that creates the file.
chmod 644 /usr/share/ublue-os/image-info.json

# Clean up remaining /var artifacts to satisfy bootc lint
# Guard with existence checks — some paths don't exist on CentOS/AlmaLinux.
[ -d /var/lib/rhsm ] && rm -rf /var/lib/rhsm/*
[ -d /var/log/rhsm ] && rm -rf /var/log/rhsm/*
[ -d /var/spool/plymouth ] && rm -rf /var/spool/plymouth/*
[ -d /var/roothome/buildinfo ] && rm -rf /var/roothome/buildinfo

# The --fix option (containers/bootc#1152) was closed without merging.
# lint_image runs `bootc container lint --fatal-warnings`, surfaces every
# finding into the build-log group + GitHub step summary (so e.g. bonito's
# three Fedora findings are visible and fixable — #272), and only fails the
# build when BOOTC_LINT_FATAL=1. Default stays warn-only so one new finding
# doesn't break every image at once; flip a variant to fatal in its build job
# once its findings are cleared.
lint_image

# Fatal gate over the install_available wishlist: every package a
# best-effort installer skipped must be declared acceptable in
# checks/package-miss-allowlist.txt. Runs here because 99-cleanup is the
# one script every family's Containerfile runs last, i.e. after every
# install_available call has had its say. See the check's header for why
# a warn-only wishlist quietly made every probed package optional forever.
/run/context/build_scripts/checks/verify-package-wishlist.sh

if command -v jq >/dev/null 2>&1; then
	jq . /usr/share/ublue-os/image-info.json || true
else
	cat /usr/share/ublue-os/image-info.json || true
fi

detected_os

printf "::endgroup::\n"
