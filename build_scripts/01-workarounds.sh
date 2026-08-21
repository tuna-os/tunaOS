#!/bin/bash

set -euo pipefail
printf "::group:: === 00-workarounds ===\n"

source /run/context/build_scripts/lib.sh

rpmdb_stage2_guard
# This is a bucket list. We want to not have anything in this file at all.
if [[ "$IS_RHEL" = true || "$IS_CENTOS" = true ]]; then rm -f /usr/lib/bootc/install/20-rhel.toml; fi
# Remove amd-legacy.conf from upstream: TunaOS kernel is not compiled with si_support/cik_support
rm -f /usr/lib/modprobe.d/amd-legacy.conf

# Configure DNF for better timeout handling and retries on all RHEL-family systems
if [[ "$IS_ALMALINUX" = true ]] || [[ "$IS_ALMALINUXKITTEN" = true ]] || [[ "$IS_CENTOS" = true ]] || [[ "$IS_RHEL" = true ]]; then
	if [ -f /etc/dnf/dnf.conf ]; then
		echo "Configuring DNF for performance and reliability"
		# Keep fastestmirror but with reasonable timeout
		sed -i 's/^fastestmirror=.*/fastestmirror=1/' /etc/dnf/dnf.conf
		if ! grep -q "^fastestmirror=" /etc/dnf/dnf.conf; then
			echo "fastestmirror=1" >>/etc/dnf/dnf.conf
		fi

		# Disable weak deps globally — saves ~50-100 unnecessary packages
		# across all installs. Individual scripts no longer need
		# --setopt=install_weak_deps=False on every dnf call.
		if ! grep -q "^install_weak_deps=" /etc/dnf/dnf.conf; then
			echo "install_weak_deps=False" >>/etc/dnf/dnf.conf
		fi

		# Add timeout and retry settings
		if ! grep -q "^timeout=" /etc/dnf/dnf.conf; then
			echo "timeout=300" >>/etc/dnf/dnf.conf
		fi
		if ! grep -q "^retries=" /etc/dnf/dnf.conf; then
			echo "retries=10" >>/etc/dnf/dnf.conf
		fi
		if ! grep -q "^minrate=" /etc/dnf/dnf.conf; then
			echo "minrate=100" >>/etc/dnf/dnf.conf # Minimum 100 bytes/sec
		fi
		if ! grep -q "^max_parallel_downloads=" /etc/dnf/dnf.conf; then
			echo "max_parallel_downloads=10" >>/etc/dnf/dnf.conf
		fi

		echo "--- Updated /etc/dnf/dnf.conf ---"
		cat /etc/dnf/dnf.conf
		echo "--- End of dnf.conf ---"
	fi
fi

# Configure AlmaLinux and AlmaLinux Kitten repos for reliability
if [[ "$IS_ALMALINUX" = true ]] || [[ "$IS_ALMALINUXKITTEN" = true ]]; then
	echo "Configuring AlmaLinux repos for better reliability"

	# Ensure baseurl is available as fallback, but keep mirrorlist enabled
	for repo_file in /etc/yum.repos.d/almalinux*.repo; do
		if [ -f "$repo_file" ]; then
			echo "Configuring $repo_file with fallback baseurl"
			# Uncomment baseurl lines to provide fallback
			sed -i 's/^# baseurl=/baseurl=/' "$repo_file"

			# Ensure baseurl points to official repo as fallback
			if [[ "$IS_ALMALINUXKITTEN" = true ]]; then
				# For AlmaLinux Kitten: use kitten.repo.almalinux.org
				sed -i 's|baseurl=https://kitten\.[^/]*/|baseurl=https://kitten.repo.almalinux.org/|' "$repo_file"
				# shellcheck disable=SC2016
				sed -i 's|baseurl=https://\([^k][^/]*\)/\$releasever-kitten/|baseurl=https://kitten.repo.almalinux.org/\$releasever-kitten/|' "$repo_file"
			else
				# For regular AlmaLinux: use repo.almalinux.org
				# shellcheck disable=SC2016
				sed -i 's|baseurl=https://[^/]*/\$releasever/|baseurl=https://repo.almalinux.org/\$releasever/|' "$repo_file"
			fi

			echo "--- Contents of $repo_file ---"
			cat "$repo_file"
			echo "--- End of $repo_file ---"
		fi
	done
fi

# Enable the same compose repos during our build that the centos-bootc image
# uses during its build.  This avoids downgrading packages in the image that
# have strict NVR requirements.
if [[ "$IS_CENTOS" = true ]] && ! [[ "$IS_ALMALINUX" = true ]]; then
	curl --retry 3 --fail -Lo "/etc/yum.repos.d/compose.repo" "https://gitlab.com/redhat/centos-stream/containers/bootc/-/raw/c${MAJOR_VERSION_NUMBER}s/cs.repo"
	sed -i \
		-e "s@- (BaseOS|AppStream)@& - Compose@" \
		-e "s@\(baseos\|appstream\)@&-compose@" \
		-e "/^\[.*compose\]/a skip_if_unavailable=True" \
		/etc/yum.repos.d/compose.repo
	cat /etc/yum.repos.d/compose.repo
fi
# ── Ubuntu: free UID 1000 for a real user ───────────────────────────────────
#
# docker.io/library/ubuntu ships a packaged cloud account at UID 1000.
# Measured on the pinned gurnard base
# (ubuntu:noble@sha256:561618e2c15bf2397621dd04f96926663a3b5616c189cf7e38db7e82f5c538ea),
# by extracting /etc/passwd from its single layer:
#
#   ubuntu:x:1000:1000:Ubuntu:/home/ubuntu:/bin/bash
#
# Two things follow, and the second is what made this visible.
#
# 1. The first REAL user an installed gurnard/grouper creates lands at 1001,
#    while a passwordless phantom account holds the UID every desktop
#    session, flatpak permission and $XDG_RUNTIME_DIR path assumes. Nothing
#    in tunaOS references this account -- it is dead weight from the cloud
#    image lineage.
#
# 2. The live ISO cannot be built at all. tacklebox's CustomizeLive prepends
#    its embedded src/live/baseline.sh, which creates the live user with an
#    unconditional `--uid 1000`:
#
#      >>> [customize] (1/2) baseline.sh
#      useradd: UID 1000 is not unique
#      Error: live customize for gurnard-pantheon: ... exit status 4
#
#    (gurnard run 32484024591, both linux-amd64 and linux-arm64.) tunaOS
#    hit exactly this bug in its OWN live-iso/common/src/customize-live.sh
#    and fixed it there by asking for 1000 only when it is free -- but that
#    script runs as (2/2) and never gets the chance.
#
# Removing the account fixes the shipped image on its own merits and frees
# the UID as a consequence. Deliberately narrow: only an account that is
# still the stock one -- name `ubuntu`, UID exactly 1000 -- is removed, so a
# base image that stops shipping it, renumbers it, or an operator who has
# repurposed the name is left alone rather than silently altered.
if [[ "${IS_UBUNTU:-false}" = true ]]; then
	if [[ "$(id -u ubuntu 2>/dev/null || echo -)" == "1000" ]]; then
		echo "removing the stock cloud account 'ubuntu' (UID 1000)"
		# --remove deletes /home/ubuntu. bootc images make /home a symlink to
		# a var/home that is empty in the container layer, so that half can
		# legitimately fail; the account removal is what has to succeed.
		userdel --remove ubuntu 2>/dev/null || userdel ubuntu
		getent group ubuntu >/dev/null && groupdel ubuntu 2>/dev/null || true
		# cloud-init's sudoers drop-in names the account just deleted, which
		# leaves a rule for a user that no longer exists. Removed only when
		# it actually mentions `ubuntu`: on a base that repurposed the file
		# for something else, deleting it would revoke unrelated sudo.
		if grep -q '\bubuntu\b' /etc/sudoers.d/90-cloud-init-users 2>/dev/null; then
			rm -f /etc/sudoers.d/90-cloud-init-users
		fi
	fi
	# Not fatal, but named where it can be seen. If UID 1000 is still taken
	# the live ISO build WILL fail later in tacklebox's baseline.sh with
	# "useradd: UID 1000 is not unique" -- a message that arrives an hour
	# downstream, in another repo's code, with no mention of this image.
	if getent passwd 1000 >/dev/null; then
		echo "WARNING: UID 1000 is still taken; the live ISO build will fail:"
		getent passwd 1000
	fi
fi

echo "Build variant info:"
echo "is_fedora: $IS_FEDORA"
echo "is_rhel: $IS_RHEL"
echo "is_almalinux: $IS_ALMALINUX"
echo "is_almalinuxkitten: $IS_ALMALINUXKITTEN"
echo "is_centos: $IS_CENTOS"

printf "::endgroup::\n"
