#!/usr/bin/env bash

# Build platform detection and cached environment initialization.
# Sourcing this module is side-effect free; callers opt in through
# initialize_build_platform.

initialize_build_platform() {
	# ── Cached OS Detection ──────────────────────────────────────────────────────
	# OS detection (reading os-release, image-info.json, deriving IS_* flags) runs
	# every time lib.sh is sourced. Since each Containerfile RUN invokes a fresh
	# shell, we cache the results to /tmp/tunaos-build-env on first detection.
	# Subsequent sources within the same RUN (e.g. gnome.sh sourcing lib.sh after
	# 10-base-packages already ran) skip the expensive detection entirely.
	_TUNAOS_ENV_CACHE="/tmp/tunaos-build-env"

	if [[ -f "$_TUNAOS_ENV_CACHE" ]]; then
		# shellcheck disable=SC1090
		source "$_TUNAOS_ENV_CACHE"
	else
		MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release 2>/dev/null || true; echo "${VERSION_ID:-10}"' | cut -d. -f1)"

		# Determine the true OS base image for OS detection.
		# For chained builds (nvidia, HWE) the BASE_IMAGE env var is set via Containerfile
		# ARG/ENV to the intermediate TunaOS stage image (e.g. ghcr.io/tuna-os/yellowfin:gnome),
		# not the original OS base. Use image-info.json written by the previous stage when
		# available — it records the true OS base from stage 1.
		_IMAGE_INFO="/usr/share/ublue-os/image-info.json"
		if [[ -f "${_IMAGE_INFO}" ]]; then
			# Read into a scratch var and only override when it actually yielded
			# something. Assigning straight into BASE_IMAGE DESTROYS a
			# caller-provided value whenever the file exists but carries no
			# `base-image` key -- `// empty` returns the empty string, and the
			# fallback below then cannot tell "no one told us" from "we just threw
			# it away".
			#
			# Not hypothetical: ublue-derived hosts ship
			# /usr/share/ublue-os/image-info.json with image-name / image-ref /
			# image-flavor / image-vendor / image-tag and NO base-image. Sourcing
			# lib.sh there with BASE_IMAGE=quay.io/fedora/fedora-bootc:43 exported
			# leaves BASE_IMAGE empty, so every IS_* flag is derived from nothing
			# and the variant is misidentified. That is what made ten OS-detection
			# tests fail on such a host while passing in CI, where the file does
			# not exist -- the tests were right and the library was wrong.
			_base_from_info=""
			if command -v jq >/dev/null 2>&1; then
				_base_from_info="$(jq -r '.["base-image"] // empty' "${_IMAGE_INFO}" 2>/dev/null || true)"
			else
				_base_from_info="$(sed -n 's/.*"base-image": *"\([^"]*\)".*/\1/p' "${_IMAGE_INFO}" 2>/dev/null || true)"
			fi
			[[ -n "${_base_from_info}" ]] && BASE_IMAGE="${_base_from_info}"
			unset _base_from_info
		fi
		if [[ -z "${BASE_IMAGE:-}" ]]; then
			BASE_IMAGE="$(sh -c '. /etc/os-release 2>/dev/null || true; echo "${BASE_IMAGE:-}"' 2>/dev/null || true)"
		fi

		# OS Detection Flags
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
		# The IS_* flags below are derived from the base image. The variant NAME is
		# not derivable from it — several variants share a base family — so the
		# names here are a FALLBACK for builds that pass no IMAGE_NAME, never an
		# override of one that did.
		#
		# They used to be plain assignments, which clobbered the real value:
		# gurnard (ubuntu:noble) built with IMAGE_NAME=grouper, so it would have
		# taken grouper's name, pretty name and fish codename into os-release and
		# image-info.json — an image that calls itself another variant. Verified in
		# LUKS run 31059184838, which logged IMAGE_NAME=grouper while building
		# gurnard:pantheon.
		#
		# For sailfin and guppy the old fallbacks were not even variant names —
		# "opensuse" and "gentoo" — which 90-image-info.sh rejects outright ("no
		# scientific fish codename defined for variant"). That was latent until
		# those two Containerfiles started running 90-image-info.sh.
		_derive_name() { # family-default name, family-default pretty name
			if [[ -n "${IMAGE_NAME:-}" ]]; then
				# The build told us the name, so the pretty name has to come from
				# THAT, not from the family default — otherwise gurnard, whose name
				# survives, still picks up "Grouper" here. Observed in run
				# 31059184838: IMAGE_NAME=gurnard, IMAGE_PRETTY_NAME=Grouper.
				# 90-image-info.sh independently computes "${IMAGE_NAME^}", so the
				# family default would disagree with what actually reaches
				# os-release. Match it.
				IMAGE_PRETTY_NAME="${IMAGE_PRETTY_NAME:-${IMAGE_NAME^}}"
			else
				IMAGE_NAME="$1"
				IMAGE_PRETTY_NAME="${IMAGE_PRETTY_NAME:-$2}"
			fi
		}
		# ELN is tested BEFORE the fedora substring test, and excluded from it,
		# for the same reason hummingbird is: its base image reference
		# (registry.fedoraproject.org/eln-bootc) contains "fedora", so the
		# unguarded test below matches it and every Bonito-specific Fedora path
		# fires against a base that cannot satisfy them. Measured on the pinned
		# digest, 2026-08-25: no epel-release, no versionlock plugin, no
		# rpmfusion-*-release-eln, and `dnf repoquery` finds no ffmpeg,
		# gstreamer1-plugins-ugly, tailscale or `just`. The Fedora branch of
		# 10-base-packages.sh installs rpmfusion-{free,nonfree}-release-${FEDORA_VER}
		# by URL, and there is no ELN branch of RPM Fusion to install.
		#
		# os-release is the primary signal because it is unambiguous and travels
		# with the image (ID=eln, VERSION_ID=11, VARIANT_ID=eln); the BASE_IMAGE
		# test is the fallback for chained stages whose image-info.json is not
		# written yet.
		if [[ "${BASE_IMAGE,,}" == *"eln-bootc"* ]] ||
			grep -qE '^ID=eln$' /etc/os-release /usr/lib/os-release 2>/dev/null; then
			IS_ELN=true
			_derive_name "wahoo" "Wahoo"
		fi
		[[ "${BASE_IMAGE,,}" == *"fedora"* && "${BASE_IMAGE,,}" != *"hummingbird"* && "${IS_ELN}" != true ]] && IS_FEDORA=true && _derive_name "bonito" "Bonito"
		[[ "${BASE_IMAGE,,}" == *"red hat"* || "${BASE_IMAGE,,}" == *"rhel"* || "${BASE_IMAGE,,}" == *"redhat"* ]] && IS_RHEL=true && _derive_name "redfin" "Redfin"
		[[ "${BASE_IMAGE,,}" == *"almalinux"* && "${BASE_IMAGE,,}" != *"-kitten"* ]] && IS_ALMALINUX=true && _derive_name "albacore" "Albacore"
		[[ "${BASE_IMAGE,,}" == *"-kitten"* ]] && IS_ALMALINUXKITTEN=true && _derive_name "yellowfin" "Yellowfin"
		[[ "${BASE_IMAGE,,}" == *"centos"* ]] && IS_CENTOS=true && _derive_name "skipjack" "Skipjack"
		[[ "${BASE_IMAGE,,}" == *"ubuntu"* ]] && IS_UBUNTU=true && _derive_name "grouper" "Grouper"
		[[ "${BASE_IMAGE,,}" == *"debian"* && "${BASE_IMAGE,,}" != *"ubuntu"* ]] && IS_DEBIAN=true && _derive_name "flounder" "Flounder"
		[[ "${BASE_IMAGE,,}" == *"archlinux"* || "${BASE_IMAGE,,}" == *"arch-bootc"* ]] && IS_ARCH=true && _derive_name "marlin" "Marlin"
		[[ "${BASE_IMAGE,,}" == *"opensuse"* ]] && IS_OPENSUSE=true && _derive_name "sailfin" "Sailfin"
		[[ "${BASE_IMAGE,,}" == *"gentoo"* ]] && IS_GENTOO=true && _derive_name "guppy" "Guppy"

		# Package manager dimension
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

		# Write cache for subsequent sources within this RUN
		cat >"$_TUNAOS_ENV_CACHE" <<-ENVEOF
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

	export MAJOR_VERSION_NUMBER
	export BASE_IMAGE
	export IS_FEDORA
	export IS_HUMMINGBIRD
	export IS_RHEL
	export IS_ALMALINUX
	export IS_ALMALINUXKITTEN
	export IS_CENTOS
	export IS_UBUNTU
	export IS_DEBIAN
	export IS_ARCH
	export IS_OPENSUSE
	export IS_GENTOO
	export PKG_MGR
	export IMAGE_NAME
	export IMAGE_PRETTY_NAME

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
}
