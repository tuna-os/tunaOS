#!/bin/bash

set -eo pipefail
printf "::group:: === 00-workarounds ===\n"

source /run/context/build_scripts/lib.sh
# This is a bucket list. We want to not have anything in this file at all.
if [[ "$IS_RHEL" = true || "$IS_CENTOS" = true ]]; then rm -f /usr/lib/bootc/install/20-rhel.toml; fi

# Configure AlmaLinux and AlmaLinux Kitten repos for reliability
if [[ "$IS_ALMALINUX" = true ]] || [[ "$IS_ALMALINUXKITTEN" = true ]]; then
	echo "Configuring AlmaLinux repos for better reliability"

	# Configure DNF for better timeout handling and retries
	if [ -f /etc/dnf/dnf.conf ]; then
		# Keep fastestmirror but with reasonable timeout
		sed -i 's/^fastestmirror=.*/fastestmirror=1/' /etc/dnf/dnf.conf
		if ! grep -q "^fastestmirror=" /etc/dnf/dnf.conf; then
			echo "fastestmirror=1" >>/etc/dnf/dnf.conf
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
				sed -i 's|baseurl=https://\([^k][^/]*\)/\$releasever-kitten/|baseurl=https://kitten.repo.almalinux.org/\$releasever-kitten/|' "$repo_file"
			else
				# For regular AlmaLinux: use repo.almalinux.org
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
	curl --retry 3 -Lo "/etc/yum.repos.d/compose.repo" "https://gitlab.com/redhat/centos-stream/containers/bootc/-/raw/c${MAJOR_VERSION_NUMBER}s/cs.repo"
	sed -i \
		-e "s@- (BaseOS|AppStream)@& - Compose@" \
		-e "s@\(baseos\|appstream\)@&-compose@" \
		/etc/yum.repos.d/compose.repo
	cat /etc/yum.repos.d/compose.repo
fi
echo "DEBUG info:"
echo "is_fedora: $IS_FEDORA"
echo "is_rhel: $IS_RHEL"
echo "is_almalinux: $IS_ALMALINUX"
echo "is_almalinuxkitten: $IS_ALMALINUXKITTEN"
echo "is_centos: $IS_CENTOS"

env

printf "::endgroup::\n"
