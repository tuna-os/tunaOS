#!/usr/bin/env bash

set -xeuo pipefail
printf "::group:: ===Image Cleanup===\n"
source /run/context/build_scripts/lib.sh

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

jq . /usr/share/ublue-os/image-info.json

detected_os

printf "::endgroup::\n"
