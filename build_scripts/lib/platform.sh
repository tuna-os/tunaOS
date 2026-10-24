#!/usr/bin/env bash

# Platform and image identity detection for build stages.
# This module is sourced by build_scripts/lib.sh; it must define functions only.
# The facade calls initialize_platform explicitly to preserve the old source
# contract while keeping detection out of the other library domains.

_platform_derive_name() {
	if [[ -n "${IMAGE_NAME:-}" ]]; then
		IMAGE_PRETTY_NAME="${IMAGE_PRETTY_NAME:-${IMAGE_NAME^}}"
	else
		IMAGE_NAME="$1"
		IMAGE_PRETTY_NAME="${IMAGE_PRETTY_NAME:-$2}"
	fi
}

initialize_platform() {
	local env_cache="${TUNAOS_ENV_CACHE:-/tmp/tunaos-build-env}"

	if [[ -f "$env_cache" ]]; then
		# shellcheck disable=SC1090
		source "$env_cache"
	else
		MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release 2>/dev/null || true; echo "${VERSION_ID:-10}"' | cut -d. -f1)"

		# Chained stages pass their intermediate TunaOS image in BASE_IMAGE. The
		# image-info record, when present, carries the original OS base instead.
		local image_info="${_IMAGE_INFO:-/usr/share/ublue-os/image-info.json}"
		if [[ -f "$image_info" ]]; then
			local base_from_info=""
			if command -v jq >/dev/null 2>&1; then
				base_from_info="$(jq -r '."base-image" // empty' "$image_info" 2>/dev/null || true)"
			else
				base_from_info="$(sed -n 's/.*"base-image": *"\([^"]*\)".*/\1/p' "$image_info" 2>/dev/null || true)"
			fi
			[[ -n "$base_from_info" ]] && BASE_IMAGE="$base_from_info"
			unset base_from_info
		fi
		if [[ -z "${BASE_IMAGE:-}" ]]; then
			BASE_IMAGE="$(sh -c '. /etc/os-release 2>/dev/null || true; echo "${BASE_IMAGE:-}"' 2>/dev/null || true)"
		fi

		IS_FEDORA=false
		IS_HUMMINGBIRD=false
		IS_ELN=false
		IS_RHEL=false
		IS_ALMALINUX=false
		IS_ALMALINUXKITTEN=false
		IS_CENTOS=false
		IS_UBUNTU=false
		IS_DEBIAN=false
		IS_ARCH=false
		IS_OPENSUSE=false
		IS_GENTOO=false

		if [[ "${BASE_IMAGE,,}" == *"hummingbird"* ]] || grep -qi "hummingbird" /etc/os-release /usr/lib/os-release 2>/dev/null; then
			IS_HUMMINGBIRD=true
			IMAGE_NAME="hummingbird"
			IMAGE_PRETTY_NAME="Hummingbird"
		fi

		# ELN must be classified before the Fedora substring check: its base
		# reference contains "fedora" but its repositories and package set do not
		# satisfy Fedora-specific build paths.
		if [[ "${BASE_IMAGE,,}" == *"eln-bootc"* ]] ||
			grep -qE '^ID=eln$' /etc/os-release /usr/lib/os-release 2>/dev/null; then
			IS_ELN=true
			_platform_derive_name "wahoo" "Wahoo"
		fi
		[[ "${BASE_IMAGE,,}" == *"fedora"* && "${BASE_IMAGE,,}" != *"hummingbird"* && "$IS_ELN" != true ]] && IS_FEDORA=true && _platform_derive_name "bonito" "Bonito"
		[[ "${BASE_IMAGE,,}" == *"red hat"* || "${BASE_IMAGE,,}" == *"rhel"* || "${BASE_IMAGE,,}" == *"redhat"* ]] && IS_RHEL=true && _platform_derive_name "redfin" "Redfin"
		[[ "${BASE_IMAGE,,}" == *"almalinux"* && "${BASE_IMAGE,,}" != *"-kitten"* ]] && IS_ALMALINUX=true && _platform_derive_name "albacore" "Albacore"
		[[ "${BASE_IMAGE,,}" == *"-kitten"* ]] && IS_ALMALINUXKITTEN=true && _platform_derive_name "yellowfin" "Yellowfin"
		[[ "${BASE_IMAGE,,}" == *"centos"* ]] && IS_CENTOS=true && _platform_derive_name "skipjack" "Skipjack"
		[[ "${BASE_IMAGE,,}" == *"ubuntu"* ]] && IS_UBUNTU=true && _platform_derive_name "grouper" "Grouper"
		[[ "${BASE_IMAGE,,}" == *"debian"* && "${BASE_IMAGE,,}" != *"ubuntu"* ]] && IS_DEBIAN=true && _platform_derive_name "flounder" "Flounder"
		[[ "${BASE_IMAGE,,}" == *"archlinux"* || "${BASE_IMAGE,,}" == *"arch-bootc"* ]] && IS_ARCH=true && _platform_derive_name "marlin" "Marlin"
		[[ "${BASE_IMAGE,,}" == *"opensuse"* ]] && IS_OPENSUSE=true && _platform_derive_name "sailfin" "Sailfin"
		[[ "${BASE_IMAGE,,}" == *"gentoo"* ]] && IS_GENTOO=true && _platform_derive_name "guppy" "Guppy"

		if [[ "$IS_UBUNTU" == true || "$IS_DEBIAN" == true ]]; then
			PKG_MGR="apt"
		elif [[ "$IS_ARCH" == true ]]; then
			PKG_MGR="pacman"
		elif [[ "$IS_OPENSUSE" == true ]]; then
			PKG_MGR="zypper"
		elif [[ "$IS_GENTOO" == true ]]; then
			PKG_MGR="emerge"
		else
			PKG_MGR="dnf"
		fi

		cat >"$env_cache" <<-ENVEOF
			MAJOR_VERSION_NUMBER="${MAJOR_VERSION_NUMBER}"
			BASE_IMAGE="${BASE_IMAGE}"
			IS_FEDORA=${IS_FEDORA}
			IS_HUMMINGBIRD=${IS_HUMMINGBIRD}
			IS_ELN=${IS_ELN}
			IS_RHEL=${IS_RHEL}
			IS_ALMALINUX=${IS_ALMALINUX}
			IS_ALMALINUXKITTEN=${IS_ALMALINUXKITTEN}
			IS_CENTOS=${IS_CENTOS}
			IS_UBUNTU=${IS_UBUNTU}
			IS_DEBIAN=${IS_DEBIAN}
			IS_ARCH=${IS_ARCH}
			IS_OPENSUSE=${IS_OPENSUSE}
			IS_GENTOO=${IS_GENTOO}
			PKG_MGR="${PKG_MGR}"
			IMAGE_NAME="${IMAGE_NAME:-}"
			IMAGE_PRETTY_NAME="${IMAGE_PRETTY_NAME:-}"
		ENVEOF

		echo "FEDORA: $IS_FEDORA"
		echo "RHEL: $IS_RHEL"
		echo "ALMALINUX: $IS_ALMALINUX"
		echo "ALMALINUXKITTEN: $IS_ALMALINUXKITTEN"
		echo "CENTOS: $IS_CENTOS"
		echo "UBUNTU: $IS_UBUNTU"
		echo "DEBIAN: $IS_DEBIAN"
		echo "PKG_MGR: $PKG_MGR"
	fi

	export MAJOR_VERSION_NUMBER BASE_IMAGE
	export IS_FEDORA IS_HUMMINGBIRD IS_ELN IS_RHEL IS_ALMALINUX
	export IS_ALMALINUXKITTEN IS_CENTOS IS_UBUNTU IS_DEBIAN
	export IS_ARCH IS_OPENSUSE IS_GENTOO PKG_MGR
	export IMAGE_NAME IMAGE_PRETTY_NAME
}

detected_os() {
	echo "Detected OS:"
	if [ "$IS_FEDORA" = true ]; then
		echo "  Fedora"
	fi
	if [ "$IS_RHEL" = true ]; then
		echo "  RHEL"
	fi
	if [ "$IS_ALMALINUX" = true ]; then
		echo "  AlmaLinux"
	fi
	if [ "$IS_ALMALINUXKITTEN" = true ]; then
		echo "  AlmaLinux-Kitten"
	fi
	if [ "$IS_CENTOS" = true ]; then
		echo "  CentOS"
	fi
	if [ "$IS_UBUNTU" = true ]; then
		echo "  Ubuntu"
	fi
	if [ "$IS_DEBIAN" = true ]; then
		echo "  Debian"
	fi
	echo "  Package manager: ${PKG_MGR}"
}

is_x86_64_v2() {
	# Check if the kernel package ends with x86_64_v2 to determine v2 architecture.
	if rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; then
		return 0
	else
		return 1
	fi
}

print_debug_info() {
	detected_os
	echo "IMAGE_NAME: $IMAGE_NAME"
	cat /etc/os-release
	cat /usr/share/ublue-os/image-info.json || true
}
