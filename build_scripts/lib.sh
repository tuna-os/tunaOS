#!/usr/bin/env bash

# This file is intended to be sourced by other scripts, not executed directly.

set -euo pipefail

# Do not rely on any of these scripts existing in a specific path
# Make the names as descriptive as possible and everything that uses dnf for package installation/removal should have `packages-` as a prefix.

CONTEXT_PATH="$(realpath "$(dirname "$0")/..")" # should return /run/context
BUILD_SCRIPTS_PATH="$(realpath "$(dirname "$0")")"
SCRIPTS_PATH="$(realpath "$(dirname "$0")/scripts")"
DESKTOP_FLAVOR="${DESKTOP_FLAVOR:-gnome}"
export SCRIPTS_PATH
export DESKTOP_FLAVOR

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
		if command -v jq >/dev/null 2>&1; then
			BASE_IMAGE="$(jq -r '.["base-image"] // empty' "${_IMAGE_INFO}" 2>/dev/null || true)"
		else
			BASE_IMAGE="$(sed -n 's/.*"base-image": *"\([^"]*\)".*/\1/p' "${_IMAGE_INFO}" 2>/dev/null || true)"
		fi
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

is_x86_64_v2() {
	# Check if the kernel package ends with x86_64_v2 to determine v2 architecture
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

run_buildscripts_for() {
	WHAT=$1
	shift
	local override_path="${BUILD_SCRIPTS_PATH}/overrides/$WHAT"
	if [ ! -d "$override_path" ]; then
		echo "No build script overrides for '$WHAT', skipping."
		return 0
	fi
	# Complex "find" expression here since there might not be any overrides
	find "$override_path" -maxdepth 1 -iname "*-*.sh" -type f -print0 | sort --zero-terminated --sort=human-numeric | while IFS= read -r -d $'\0' script; do
		if [ "${CUSTOM_NAME:-}" != "" ]; then
			WHAT=$CUSTOM_NAME
		fi
		printf "::group:: ===$WHAT-%s===\n" "$(basename "$script")"
		"$(realpath "$script")"
		printf "::endgroup::\n"
	done
}

copy_systemfiles_for() {
	WHAT=$1
	shift
	local override_path="${CONTEXT_PATH}/overrides/$WHAT"
	DISPLAY_NAME=$WHAT
	if [ "${CUSTOM_NAME:-}" != "" ]; then
		DISPLAY_NAME=$CUSTOM_NAME
	fi
	if [ ! -d "$override_path" ]; then
		echo "No system file overrides for '$WHAT', skipping."
		return 0
	fi
	printf "::group:: ===%s-file-copying===\n" "${DISPLAY_NAME}"
	cp -rvf "$override_path/." / || cp -rf "$override_path/." / || true
	printf "::endgroup::\n"
}

# Run a command and emit a GitHub Actions ::warning on failure instead of
# silently swallowing the error with || true.  Use for operations that are
# important enough to surface in the build summary but not build-fatal
# (e.g. versionlock changes, optional removes, RHSM registration).
#
# Usage: warn_on_fail subscription-manager register --username "${RHSM_USER}" ...
#        warn_on_fail dnf -y versionlock delete glib2
warn_on_fail() {
	local cmd="$1"
	shift
	if ! "$cmd" "$@"; then
		local caller_script
		caller_script="$(basename "${BASH_SOURCE[1]:-?}")"
		printf '::warning title=Operation failed (%s on %s)::%s %s exited with %d (called from %s)\n' \
			"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$cmd" "$*" "$?" "$caller_script"
	fi
}

# Run `bootc container lint` and SURFACE its findings instead of silently
# swallowing them. The lint is the product-quality gate for bootc images
# (#272: bonito's three failures were hidden behind `warn_on_fail`, which
# emits a one-line ::warning and discards the actual check output — so nobody
# could see *what* failed, let alone fix it).
#
# Behaviour:
#   * Always runs the lint, capturing combined stdout+stderr.
#   * On failure, echoes the full output inside a collapsed ::group:: and
#     mirrors it into $GITHUB_STEP_SUMMARY so the findings are visible in the
#     run summary, not buried in 10k lines of build log.
#   * Fails the build when BOOTC_LINT_FATAL=1 (default: warn-only, preserving
#     today's behaviour). Flip a variant to fatal once its findings are fixed.
#
# Usage: lint_image            # lints the in-build root (bootc container lint)
lint_image() {
	local fatal="${BOOTC_LINT_FATAL:-0}"
	local out rc=0
	out="$(bootc container lint --fatal-warnings 2>&1)" || rc=$?

	if ((rc == 0)); then
		echo "bootc container lint: OK (${IMAGE_NAME:-?} ${MAJOR_VERSION_NUMBER:-?})"
		return 0
	fi

	# Surface the findings prominently.
	printf '::group::bootc container lint findings (%s %s)\n%s\n::endgroup::\n' \
		"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$out"

	if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
		local fence='```'
		{
			printf '### ⚠️ bootc container lint — %s %s\n\n' "${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}"
			printf '%s\n%s\n%s\n' "$fence" "$out" "$fence"
		} >>"$GITHUB_STEP_SUMMARY"
	fi

	if [[ "$fatal" == "1" ]]; then
		printf '::error title=bootc lint failed (%s)::lint reported failures (exit %d); see the grouped findings above\n' \
			"${IMAGE_NAME:-?}" "$rc"
		return "$rc"
	fi

	printf '::warning title=bootc lint findings (%s)::lint reported failures (exit %d) — surfaced above, not build-fatal (set BOOTC_LINT_FATAL=1 to enforce)\n' \
		"${IMAGE_NAME:-?}" "$rc"
	return 0
}

# ---- Package manager abstraction (PKG_MGR) ----
# These wrappers let build scripts call a single command regardless of
# whether the base image is RPM-based (dnf) or deb-based (apt-get).
# Scripts that still call dnf directly (e.g. install_from_copr) are
# intentionally RPM-only and guarded by [[ $PKG_MGR == dnf ]] checks.

# Install packages. On apt, skips recommended/suggested packages to keep
# the image lean (mirrors --setopt=install_weak_deps=False on dnf).
pkg_install() {
	if [[ "$PKG_MGR" == "apt" ]]; then
		mkdir -p /var/lib/apt/lists/partial /var/lib/dpkg /var/cache/apt/archives/partial
		apt-get update -qq
		apt-get install -y --no-install-recommends -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" "$@" || {
			dpkg --configure -a --force-depends || true
			# Retry WITH the package list: a bare `apt-get -f install`
			# succeeds without installing anything, silently swallowing
			# real failures (e.g. a nonexistent package name shipped a
			# desktop-less flounder:kde while the build stayed green).
			apt-get install -y -f --no-install-recommends "$@"
		}
	elif [[ "$PKG_MGR" == "pacman" ]]; then
		pacman -S --noconfirm --needed "$@"
	elif [[ "$PKG_MGR" == "zypper" ]]; then
		zypper_retry --non-interactive in --no-recommends "$@"
	elif [[ "$PKG_MGR" == "emerge" ]]; then
		emerge --verbose --getbinpkg "$@"
	elif [[ "$PKG_MGR" == "dnf" ]]; then
		dnf_retry install -y --setopt=install_weak_deps=False "$@"
	else
		echo "pkg_install: unknown PKG_MGR '${PKG_MGR}'" >&2
		return 1
	fi
}

# Remove packages. `apt-get purge` removes config files too (equivalent
# to dnf's default `remove` behavior on EL/Fedora).
pkg_remove() {
	if [[ "$PKG_MGR" == "apt" ]]; then
		apt-get purge -y "$@"
	elif [[ "$PKG_MGR" == "pacman" ]]; then
		pacman -Rns --noconfirm "$@" 2>/dev/null || true
	elif [[ "$PKG_MGR" == "zypper" ]]; then
		zypper --non-interactive rm "$@"
	elif [[ "$PKG_MGR" == "emerge" ]]; then
		emerge --deselect "$@"
	elif [[ "$PKG_MGR" == "dnf" ]]; then
		dnf_retry remove -y "$@"
	else
		echo "pkg_remove: unknown PKG_MGR '${PKG_MGR}'" >&2
		return 1
	fi
}

# Refresh package metadata.
#
# Every branch is explicit and dnf is one of them rather than the fallthrough.
# An `else dnf ...` tail reads as "the default" and is really "everything I did
# not think about": it is how 40-services.sh sent Arch down the dnf path
# (#1015) and how pkg_clean below killed every sailfin build with
# "lib.sh: line 366: dnf: command not found" after 99-cleanup.sh was wired into
# Containerfile.opensuse. An unknown manager should say so, not run dnf.
pkg_refresh() {
	case "$PKG_MGR" in
	apt) apt-get update ;;
	pacman) pacman -Sy --noconfirm ;;
	zypper) zypper_retry --non-interactive --gpg-auto-import-keys refresh ;;
	emerge) emerge --sync --quiet || emaint sync -a ;;
	dnf) dnf makecache ;;
	*)
		echo "pkg_refresh: unknown PKG_MGR '${PKG_MGR}'" >&2
		return 1
		;;
	esac
}

# Clean package manager caches to minimize final image size.
pkg_clean() {
	case "$PKG_MGR" in
	apt)
		apt-get clean
		rm -rf /var/lib/apt/lists/*
		mkdir -p /var/lib/apt/lists/partial
		;;
	pacman) pacman -Scc --noconfirm 2>/dev/null || true ;;
	zypper) zypper clean --all 2>/dev/null || true ;;
	# Gentoo's caches are the distfiles and the binpkg tree; portage has no
	# "clean" verb for them, and eclean is in gentoolkit which the stage3 does
	# not ship. Remove the paths directly, as Containerfile.gentoo:107 already
	# does for /var/tmp/portage.
	emerge) rm -rf /var/cache/distfiles/* /var/tmp/portage/* 2>/dev/null || true ;;
	dnf) dnf clean all ;;
	*)
		echo "pkg_clean: unknown PKG_MGR '${PKG_MGR}'" >&2
		return 1
		;;
	esac
}

# Run `dnf` with retries to absorb transient mirror flakes (EPEL / AlmaLinux /
# CentOS mirrors fail with curl SSL_ERROR_SYSCALL / partial-file errors a few
# times a week, which previously broke whole CI builds — see albacore failing
# on `gum` downloads in .build-logs/). Re-runs on failure with backoff,
# clearing metadata between attempts so DNF picks a different mirror.
#
# Does NOT mask intrinsic errors (transaction conflicts, missing packages) —
# those fail identically on every attempt; the loop returns the last DNF
# exit code so callers still see real errors.
#
# It used to retry those identically-failing transactions anyway, though:
# `nothing provides X` / `No match for argument` are dnf's own resolver
# telling you the *repo content* can't satisfy the request, which four
# attempts and `dnf clean metadata` cannot change — clearing metadata just
# re-downloads the same repodata that already says the provider is missing.
# Measured on tuna-os/tunaos#1555 (Hummingbird's public-hummingbird repo
# missing libjsoncpp.so.26/librhash.so.1 providers): ~50s of pure sleep
# wasted per doomed call, three separate calls in one job. Detecting that
# class of error and returning immediately doesn't change any caller's
# pass/fail outcome (the transaction was always going to fail) — it just
# stops paying for retries that can't work.
#
# Usage: dnf_retry install -y foo bar
#        dnf_retry -y install --setopt=… foo
dnf_retry() {
	local max_attempts="${DNF_RETRY_ATTEMPTS:-4}"
	local attempt=1
	local rc=0
	local out
	local tmp_out
	tmp_out=$(mktemp)
	while ((attempt <= max_attempts)); do
		if dnf "$@" 2>&1 | tee "$tmp_out"; then
			rm -f "$tmp_out"
			return 0
		fi
		rc="${PIPESTATUS[0]}"
		out=$(cat "$tmp_out")
		# Resolver-level failures: the repo's own metadata says the
		# request can't be satisfied. Every attempt sees the same
		# repodata (clean metadata just re-fetches it), so retrying
		# is certain to reproduce the identical failure.
		if [[ "$out" == *"nothing provides"* || "$out" == *"No match for argument"* || "$out" == *"Problem: conflicting requests"* ]]; then
			echo "dnf attempt ${attempt}/${max_attempts}: unresolvable transaction (not a transient error) — not retrying" >&2
			rm -f "$tmp_out"
			return "$rc"
		fi
		echo "dnf attempt ${attempt}/${max_attempts} failed (exit ${rc}); clearing metadata and retrying..." >&2
		dnf clean metadata || true
		sleep "$((attempt * 5))"
		attempt=$((attempt + 1))
	done
	rm -f "$tmp_out"
	echo "dnf failed after ${max_attempts} attempts" >&2
	return "$rc"
}

# zypper's counterpart to dnf_retry, and for the same reason.
#
# Tumbleweed publishes snapshots continuously, and a build that lands mid-sync
# gets a repomd.xml pointing at a primary.xml that the mirror has already
# rotated away:
#
#   Repository 'openSUSE-Tumbleweed-Oss' is invalid.
#   [repo-oss|...] Failed to retrieve new repository metadata.
#    - File './repodata/<hash>-primary.xml.zst' not found on medium ...
#   Warning: Skipping repository 'openSUSE-Tumbleweed-Oss' because of the above error.
#
# zypper treats that as a WARNING and carries on with the repositories that did
# refresh — so the build continues with the main repository silently absent and
# dies later somewhere unrelated, wearing a misleading message:
#
#   Package 'systemd-network' not found.        (it is in repo-oss)
#   ...40-services.sh... exit status 104
#
# That killed sailfin:niri in LUKS run 31089226102 with nothing wrong in the
# tree. dnf has had dnf_retry for exactly this class since #1015; the zypper
# path never got one, which is the same one-of-N-package-managers gap as the
# openssh install and the pcsc omit line.
#
# Like dnf_retry this does NOT mask intrinsic errors — an unresolvable package
# fails identically every attempt and the last exit code is returned.
#
# Usage: zypper_retry --non-interactive in --no-recommends foo bar
zypper_retry() {
	local max_attempts="${ZYPPER_RETRY_ATTEMPTS:-4}"
	local attempt=1
	local rc=0
	while ((attempt <= max_attempts)); do
		zypper "$@" && return 0 || rc=$?
		echo "zypper attempt ${attempt}/${max_attempts} failed (exit ${rc}); refreshing metadata and retrying..." >&2
		# Force a full re-download rather than trusting the cache that just
		# failed — the stale-repomd case above is invisible otherwise.
		zypper --non-interactive --gpg-auto-import-keys refresh --force || true
		sleep "$((attempt * 5))"
		attempt=$((attempt + 1))
	done
	echo "zypper failed after ${max_attempts} attempts" >&2
	return "$rc"
}

# Record packages a best-effort installer skipped: a GitHub Actions warning
# per miss (the fold-group log line alone is easy to scroll past) and an
# append to the in-image wishlist file that travels with the build.
# Downstream consumers — CI summary jobs, scripts/report-missing-packages.sh,
# and the fatal checks/verify-package-wishlist.sh gate — read that file
# instead of re-parsing build logs.
#
# Callers pass their own name first (BASH_SOURCE[1] resolved at THEIR frame —
# resolving it here would always say lib.sh), then the missed package names.
# TUNAOS_WISHLIST_DIR relocates the wishlist for tests.
record_package_wishlist() {
	local caller_script="$1"
	shift
	local misses=("$@")
	[[ ${#misses[@]} -eq 0 ]] && return 0

	local miss
	for miss in "${misses[@]}"; do
		printf '::warning title=Missing package (%s on %s)::%s is requested by %s but not in the active repos. Consider packaging it for EL10 via tuna-os/tunaos-packages.\n' \
			"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$miss" "$caller_script"
	done

	local wishlist="${TUNAOS_WISHLIST_DIR:-/usr/share/tunaos}/missing-on-${IMAGE_NAME:-unknown}.txt"
	mkdir -p "$(dirname "$wishlist")"
	{
		printf '# Generated by build_scripts/lib.sh:record_package_wishlist\n'
		printf '# image=%s major_version=%s caller=%s timestamp=%s\n' \
			"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$caller_script" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		for miss in "${misses[@]}"; do
			printf '%s\n' "$miss"
		done
	} >>"$wishlist"
}

# Install only the packages that the active DNF repo set can actually
# resolve. The lower-bound case is "your upstream Fedora package list
# is half-missing on EL10"; the upper-bound is "you've enabled a COPR
# that ships half of them". The function probes each package, installs
# the survivors as one transaction, and logs the misses so the next
# porter sees the shrinking gap.
#
# Optional `--copr <slug>` flags enable additional COPRs for the
# duration of the probe+install, then disable them again — keeping
# the COPR enablement out of the final image config when you only
# need a one-shot package pull. Pass `--copr` multiple times to stack.
#
# Usage:
#   install_available pkg1 pkg2 pkg3
#   install_available --copr ublue-os/packages kcm_ublue uupd
#   install_available --copr avengemedia/danklinux --copr avengemedia/dms-git \
#       quickshell-git dms dms-cli dms-greeter
#
# Notes:
# - `dnf repoquery --available --qf '%{name}\n' "$pkg" | grep -qx "$pkg"`
#   is intentionally strict: bare `dnf repoquery pkg` matches partial
#   names (probing `pam-u2f` also matches `pam-u2f-doc`) which falsely
#   classifies non-existent packages as available.
# - Logs go through `::group::` markers so the build output stays
#   foldable in CI.
install_available() {
	local coprs=()
	while [[ "${1:-}" == "--copr" ]]; do
		coprs+=("$2")
		shift 2
	done
	local pkgs=("$@")
	if [[ ${#pkgs[@]} -eq 0 ]]; then
		echo "install_available: no packages requested" >&2
		return 0
	fi

	# Track which COPRs we enabled so we only disable those.
	local enabled_coprs=()
	for copr in "${coprs[@]}"; do
		if dnf -y copr enable "$copr"; then
			enabled_coprs+=("$copr")
		else
			echo "install_available: failed to enable copr ${copr} (skipping)" >&2
		fi
	done

	local available=() missing=()
	for pkg in "${pkgs[@]}"; do
		if dnf repoquery --available --qf '%{name}\n' "$pkg" 2>/dev/null | grep -qx "$pkg"; then
			available+=("$pkg")
		else
			missing+=("$pkg")
		fi
	done

	if [[ ${#missing[@]} -gt 0 ]]; then
		printf '::group:: install_available: %d skipped (not in active repos)\n' "${#missing[@]}"
		printf '  %s\n' "${missing[@]}"
		printf '::endgroup::\n'

		record_package_wishlist \
			"$(basename "${BASH_SOURCE[1]:-install_available}")" \
			"${missing[@]}"
	fi

	if [[ ${#available[@]} -gt 0 ]]; then
		printf '::group:: install_available: installing %d package(s)\n' "${#available[@]}"
		printf '  %s\n' "${available[@]}"
		printf '::endgroup::\n'

		# Build the enablerepo flag set so the install can see the
		# packages from the just-enabled COPRs even though they're
		# being disabled again right after.
		local enablerepo_args=()
		for copr in "${enabled_coprs[@]}"; do
			local repo_id
			repo_id="copr:copr.fedorainfracloud.org:$(echo "$copr" | tr '/' ':')"
			enablerepo_args+=("--enablerepo=${repo_id}")
		done
		dnf -y install --setopt=install_weak_deps=False \
			"${enablerepo_args[@]}" \
			"${available[@]}" ||
			dnf -y install --skip-broken --setopt=install_weak_deps=False \
				"${enablerepo_args[@]}" \
				"${available[@]}" || {
			for single_pkg in "${available[@]}"; do
				dnf -y install --skip-broken "${enablerepo_args[@]}" "$single_pkg" 2>/dev/null || true
			done
		}
	fi

	# Take the COPRs back out of the repo set so we don't leave them
	# enabled in the final image (mirrors the install_from_copr
	# pattern below).
	for copr in "${enabled_coprs[@]}"; do
		dnf -y copr disable "$copr" || true
	done
}

# Tolerate an unresolvable RPM Fusion Rawhide transaction without killing
# the whole variant (tunaOS#1810). Fedora Rawhide and RPM Fusion Rawhide
# are two independently-built repos; when Fedora bumps a shared library's
# SONAME before RPM Fusion rebuilds against it, packages in the enabled
# repo set can go unresolvable even though every requested name is real.
# Measured 2026-08-17 against live repodata: Fedora rawhide's openapv-libs
# now provides only `liboapv.so.3` (0.3.0.0-1.fc46), but
# rpmfusion-free-rawhide's ffmpeg-libs-8.1.2-5.fc46 still
# `Requires: liboapv.so.2()(64bit)` — nothing in either repo provides that
# SONAME anymore. That is a depsolve failure, not a missing package name,
# so install_available's `dnf repoquery --available` probe (which only
# checks that the name exists) cannot see it: "ffmpeg" genuinely exists,
# only its dependency chain does not resolve.
#
# Strategy: try the transaction exactly as given first. On any release
# OTHER than rawhide, or whenever the strict transaction succeeds,
# behavior is identical to a plain `dnf -y install` — pinned bonito (and
# every other non-rawhide Fedora build) is provably unaffected. Only when
# FEDORA_VER=rawhide AND the strict transaction fails do we retry once
# with --skip-broken, then diff the originally-requested package list
# against what's actually installed afterward to name exactly what
# dropped out. Those names are routed through the same loud path
# install_available uses: a ::warning per miss, and an append to
# /usr/share/tunaos/missing-on-<image>.txt (record_package_wishlist) — so
# checks/verify-package-wishlist.sh still gates the miss against
# checks/package-miss-allowlist.txt. The omission is recorded, not
# silent, and criterion no_silent_omissions has real evidence to point at.
#
# Which Fedora is this buildroot, in the form the rpmfusion release RPMs and
# the rawhide-tolerance gate below both need: a number for pinned releases,
# the literal string "rawhide" for Rawhide.
#
# `rpm -E %fedora` alone cannot answer that: on Rawhide it expands to the
# NEXT numeric release (46 today) and NEVER to "rawhide", so a gate comparing
# against "rawhide" can never fire from it. Measured: bonito-rawhide run
# 32002010101 printed "install_rawhide_tolerant: transaction failed on 46;
# not tolerating" and the base failed on the exact skew the tolerance exists
# for. os-release is the discriminator — Rawhide images carry "Rawhide" in
# VERSION/PRETTY_NAME, branched and released images do not.
#
# OS_RELEASE is overridable for tests only; production callers use the default.
detect_fedora_ver() {
	local ver
	ver="$(rpm -E %fedora 2>/dev/null || true)"
	if [[ -z "$ver" || "$ver" == "%fedora" ]] \
		|| grep -qi rawhide "${OS_RELEASE:-/etc/os-release}" 2>/dev/null; then
		echo rawhide
	else
		echo "$ver"
	fi
}

# Usage: install_rawhide_tolerant [dnf-flag ...] pkg1 pkg2 pkg3 ...
# (leading `-`-prefixed args are treated as dnf flags, e.g. --exclude=...,
# everything after the first non-flag arg is a package name)
install_rawhide_tolerant() {
	local opts=()
	while [[ "${1:-}" == -* ]]; do
		opts+=("$1")
		shift
	done
	local pkgs=("$@")
	if [[ ${#pkgs[@]} -eq 0 ]]; then
		echo "install_rawhide_tolerant: no packages requested" >&2
		return 0
	fi

	if dnf -y install "${opts[@]}" "${pkgs[@]}"; then
		return 0
	fi

	if [[ "${FEDORA_VER:-}" != "rawhide" ]]; then
		echo "install_rawhide_tolerant: transaction failed on ${FEDORA_VER:-non-rawhide Fedora}; not tolerating (only Rawhide gets the --skip-broken retry — pinned Fedora releases stay strict)." >&2
		return 1
	fi

	printf '::warning title=Rawhide multimedia transaction unresolvable (tunaOS#1810)::[%s] failed to resolve as a strict dnf transaction on Fedora Rawhide (an rpmfusion-rawhide/Fedora-rawhide packaging skew). Retrying with --skip-broken so this costs codecs, not the whole variant.\n' "${pkgs[*]}"

	dnf -y install --skip-broken "${opts[@]}" "${pkgs[@]}" || true

	local missing=() pkg
	for pkg in "${pkgs[@]}"; do
		rpm -q "$pkg" &>/dev/null || missing+=("$pkg")
	done

	if [[ ${#missing[@]} -eq 0 ]]; then
		echo "install_rawhide_tolerant: --skip-broken retry actually installed everything requested; the earlier failure was transient." >&2
		return 0
	fi

	record_package_wishlist \
		"$(basename "${BASH_SOURCE[1]:-install_rawhide_tolerant}")" \
		"${missing[@]}"

	echo "install_rawhide_tolerant: proceeding without: ${missing[*]}" >&2
	return 0
}

# tunaOS#1823 probe: stage-2 on a fresh Rawhide base fails with sqlite error
# 11 ("database disk image is malformed") on every RPM install once the
# transaction is large — small overlays pass, desktop-sized ones fail, both
# arches, across all dnf retries and full build attempts. Rebuilding the
# rpmdb inherited from the base layer BEFORE the first stage-2 rpm write is
# the cheap discriminating experiment the issue asks for:
#
#   rebuild FAILS                        -> the base's rpmdb is malformed at
#                                           rest (base rpm wrote a bad db)
#   rebuild ok, transaction then ok      -> inherited-db/overlayfs-copy-up
#                                           was the problem; probe graduates
#                                           to a fix
#   rebuild ok, transaction still fails  -> corruption happens DURING the
#                                           transaction (sqlite-on-overlayfs)
#
# Deliberately a no-op off Rawhide, and never fails the build itself: the
# transaction that follows is the real verdict either way, and a probe that
# can kill a green pinned-Fedora build would cost more than it measures.
rawhide_rpmdb_probe() {
	# EXPERIMENT for tunaOS#1823. The comment above says this is "a no-op off
	# Rawhide". It was not. detect_fedora_ver (above) maps an UNEXPANDED
	# %fedora to "rawhide", and %fedora is undefined on every non-Fedora dnf
	# image -- so "this is not a Fedora at all" was being read as "this is
	# Rawhide", and the Rawhide-only copy-up ran on CentOS, RHEL and Alma too.
	#
	# Measured on skipjack (quay.io/centos-bootc/centos-bootc:stream10,
	# IS_CENTOS=true, IS_FEDORA=false), run 32534198668:
	#
	#   ++ rpm -E %fedora
	#   ++ ver=%fedora
	#   ++ [[ %fedora == \%\f\e\d\o\r\a ]]
	#   ++ echo rawhide
	#   + [[ rawhide == \r\a\w\h\i\d\e ]]
	#
	# detect_fedora_ver's fallback is sound where it was designed to be used:
	# 10-base-packages.sh only reaches it inside an `elif [[ $IS_FEDORA == true
	# ]]` branch, where an unexpanded macro really can only mean an odd
	# prerelease. This function consumed it with no such guard.
	#
	# Whether that misfire is inert or load-bearing on EL10 is exactly what
	# this branch measures, and it is NOT obvious: #1912 and #1916 fixed real
	# EL10 corruption with this same round-trip and salvage, and if EL10 cells
	# have been reaching that code THROUGH the misdetection, gating it here
	# reverts those fixes. The nvidia surface is unaffected either way --
	# overlay/overrides/nvidia/10-kernel-swap.sh carries its own deliberately
	# fatal copy, and describes itself as this probe "graduating on a stable
	# base", which reads as though the two were always meant to be separate.
	#
	# Read the result before merging. If EL10 desktop cells behave identically
	# with this gate in place, the misfire was inert and the scope can simply
	# be made honest. If they change, this line must NOT land as-is and EL10
	# needs its own named entry point instead.
	[[ "${IS_FEDORA:-false}" == true ]] || return 0
	[[ "$(detect_fedora_ver)" == "rawhide" ]] || return 0
	# tunaOS#1823, PROVEN FIX ported from the nvidia overlay (run
	# 32339591457, 2026-08-20): the sqlite corruption class is rpm writing
	# into a db directory that still lives in a LOWER overlay layer.
	# Recreating the resolved directory natively in the upper layer (copy
	# lands upper, rm whiteouts the lower dir, mv is a same-device rename)
	# made albacore's base-nvidia kernel swap — previously 100% red on the
	# malformed-db storm — build clean end to end. Same shape here, before
	# the first stage-2 rpm write on the inherited Rawhide base.
	local _rpmdb_path _rpmdb_dir
	_rpmdb_path="$(rpm --eval '%_dbpath' 2>/dev/null || true)"
	_rpmdb_dir="$(readlink -f "$_rpmdb_path" 2>/dev/null || true)"
	if [[ -n "$_rpmdb_dir" && -d "$_rpmdb_dir" ]]; then
		echo "::notice title=rpmdb copy-up (tunaOS#1823)::${_rpmdb_path} resolves to ${_rpmdb_dir}; recreating it in the upper layer before the first stage-2 rpm write"
		cp -a "$_rpmdb_dir" "${_rpmdb_dir}.tbox-copyup"
		rm -rf "$_rpmdb_dir"
		mv "${_rpmdb_dir}.tbox-copyup" "$_rpmdb_dir"
	fi
	# The rebuild's rename endgame fails under this overlay even against
	# an upper-native dir (measured twice on the nvidia surface) — but a
	# db corrupted AT REST by an earlier stage's writes needs the
	# rebuild's PRODUCT, and rpm builds it fine before throwing it away
	# at the rename, printing its own recovery instruction ("replace
	# files in ... with files from .../rpmrebuilddb.NN"). Same salvage as
	# 10-kernel-swap.sh: file-level swap, no directory rename needed.
	local _rpmdb_parent _rebuilt
	_rpmdb_parent="${_rpmdb_dir%/*}"
	rm -rf "${_rpmdb_parent}"/rpmrebuilddb.* "${_rpmdb_parent}"/rpmold.* 2>/dev/null || true
	if rpm --rebuilddb; then
		echo "TUNAOS_RPMDB_PROBE=rebuilt"
	else
		_rebuilt="$(find "${_rpmdb_parent}" -maxdepth 1 -name 'rpmrebuilddb.*' 2>/dev/null | head -1 || true)"
		if [[ -n "$_rpmdb_dir" && -d "$_rpmdb_dir" && -n "$_rebuilt" && -d "$_rebuilt" ]]; then
			echo "::notice title=rpmdb salvage (tunaOS#1823)::salvaging the completed rebuild file-level from ${_rebuilt}"
			rm -rf "${_rpmdb_dir:?}"/*
			cp -a "$_rebuilt"/. "$_rpmdb_dir"/
			rm -rf "$_rebuilt" "${_rpmdb_parent}"/rpmold.*
			echo "TUNAOS_RPMDB_PROBE=rebuilt-salvaged"
		else
			echo "TUNAOS_RPMDB_PROBE=rebuild-failed-nonfatal"
			echo "::warning title=rpmdb probe (tunaOS#1823)::rpm --rebuilddb failed and left no rebuilt db to salvage; proceeding — the stage-2 transaction is the real verdict"
		fi
	fi
	# A rebuild from an already-malformed db is LOSSY: it keeps whatever the
	# failing SELECT managed to read. On the stock ubuntu-latest storage the
	# corruption recurs after every layer commit, each salvage compounds the
	# loss, and by install-desktop the db has dropped system-release — after
	# which dnf cannot resolve $releasever and every later stage dies on
	# 'metalink?repo=epel-$releasever' 404s that look like a repo outage
	# (runs 32392181047 / 32394645068). Name the data loss here instead.
	if ! rpm -q --whatprovides 'system-release(releasever)' >/dev/null 2>&1; then
		echo "::error title=rpmdb data loss (tunaOS#1823)::the rebuilt rpmdb no longer provides system-release(releasever) — the salvage was lossy and dnf's \$releasever detection is gone. This build cannot produce a valid image; fix the runner's container storage (see #1893) instead of chasing the downstream epel-\$releasever 404s."
		return 1
	fi
	return 0
}

# Stage-2 rpmdb guard: every RUN layer that does dnf inherits the rpmdb in a
# LOWER overlay layer and can corrupt it under an mmap'd write (#1823).
# install-desktop.sh calls the probe directly; the other desktop scripts that
# run dnf (gnome-extensions, kcm-ublue, niri, xfce) call this wrapper, which
# no-ops off the dnf path.
rpmdb_stage2_guard() {
	[[ "${PKG_MGR:-}" == dnf ]] || return 0
	rawhide_rpmdb_probe
}

# systemctl enable wrapper that tolerates the unit-not-present case.
# Build scripts run in a multi-stage container build where some units may
# only exist on certain variants (e.g. tailscaled on EL10 but not on EL9).
# The vanilla `systemctl enable` returns non-zero on a missing unit, which
# under `set -e` would abort the build for an entirely-expected condition.
#
# Idempotent: enabling an already-enabled unit is a no-op.
safe_enable() {
	if systemctl list-unit-files "$1" &>/dev/null || [[ -f "/usr/lib/systemd/system/$1" ]]; then
		systemctl enable "$1" || true
	fi
}

# Mirror of safe_enable for disabling. Same rationale — units that don't
# exist on a given variant shouldn't trip the build.
safe_disable() {
	if systemctl list-unit-files "$1" &>/dev/null || [[ -f "/usr/lib/systemd/system/$1" ]]; then
		systemctl disable "$1" || true
	fi
}

# Which unit actually is the KDE display manager on this image.
#
# Plasma 6.6 renamed SDDM to PlasmaLogin. EL10 pulls plasma-login-manager in
# as a plasma-group dependency, and its scriptlet claims the
# display-manager.service alias *before* the later explicit `sddm` install --
# whose own enable then fails with "already exists and is a symlink to
# plasmalogin.service" and is swallowed by safe_enable's `|| true`. The image
# consequently booted plasmalogin while every check asserted sddm.
#
# Fedora/Debian/Ubuntu/Arch still ship real sddm, so this resolves per image
# rather than renaming across the board.
#
# _KDE_DM_ROOT exists so the bats tests can point this at a fake tree. It is
# never set during a build; without it a test would just inherit whatever the
# host happens to have installed and pass for the wrong reason.
kde_dm_unit() {
	if [[ -e "${_KDE_DM_ROOT:-}/usr/lib/systemd/system/plasmalogin.service" ]] ||
		{ [[ -z "${_KDE_DM_ROOT:-}" ]] &&
			systemctl list-unit-files plasmalogin.service --no-legend 2>/dev/null |
			grep -q '^plasmalogin.service'; }; then
		echo plasmalogin.service
	else
		echo sddm.service
	fi
}

# Install the dnf copr/config-manager plugin providers, one transaction each.
#
# These used to be listed in a single `dnf -y install A B C D`. dnf fails the
# WHOLE transaction when any one name is unmatched, and the dnf5-* virtual
# provides do not exist on EL10 — so AlmaLinux Kitten and CentOS Stream 10
# installed NONE of the four, including dnf-command(copr), which is the one
# they do have. That is the "Unable to find a match: dnf5-command(copr)
# dnf5-command(config-manager)" in #1016: dnf names only the unmatched ones,
# and the `|| true` then hides that nothing was installed at all.
#
# The consequence was not log noise. With no copr plugin, the `dnf copr
# enable` below fails, the COPR repo is never enabled, and the install falls
# back to the base repos — so a package that only exists in COPR goes missing
# from the image with every step reporting success.
#
# One transaction per name costs a few seconds of metadata resolution and
# lets each distro install whichever names it actually has.
install_dnf_plugin_providers() {
	local _pkg
	for _pkg in 'dnf5-command(copr)' 'dnf-command(copr)' \
		'dnf5-command(config-manager)' 'dnf-command(config-manager)'; do
		dnf -y install "$_pkg" 2>/dev/null || true
	done
}

# apt counterpart to install_available: install only the names this release
# actually has, and say loudly which it skipped.
#
# Use this ONLY for packages that legitimately vary across releases. apt fails
# the whole transaction on one unknown name, so a single package that landed in
# Ubuntu after 24.04 takes the entire base install down with it — which is what
# `E: Unable to locate package fastfetch/glow/gum` did to every gurnard build
# (noble) even though they resolve fine on grouper (resolute).
#
# Deliberately NOT applied to the whole base list. Silently reducing a required
# package set is how an image ships without something it needs and still exits
# 0; the skip has to be visible and the required list has to stay strict.
apt_install_available() {
	local want=("$@") have=() skipped=() pkg
	for pkg in "${want[@]}"; do
		# `apt-cache show` prints nothing and exits 0 for an unknown name, so
		# test for the Package: stanza rather than the exit status.
		if apt-cache show "$pkg" 2>/dev/null | grep -q '^Package:'; then
			have+=("$pkg")
		else
			echo "apt_install_available: not in this release, skipping: ${pkg}" >&2
			skipped+=("$pkg")
		fi
	done
	# Same wishlist as the dnf path — without this, apt images had no miss
	# record at all, so the verify-package-wishlist.sh gate covered every
	# family except the one where the fastfetch/glow/gum variance actually
	# lives.
	if [[ ${#skipped[@]} -gt 0 ]]; then
		record_package_wishlist \
			"$(basename "${BASH_SOURCE[1]:-apt_install_available}")" \
			"${skipped[@]}"
	fi
	if ((${#have[@]} == 0)); then
		echo "apt_install_available: none of the requested packages exist here" >&2
		return 0
	fi
	pkg_install "${have[@]}"
}

install_from_copr() {
	COPR_NAME=$1
	shift
	PRIORITY=""

	# Check if priority is specified as first argument after COPR_NAME
	if [[ $# -gt 0 && $1 =~ ^[0-9]+$ ]]; then
		PRIORITY=$1
		shift
	fi

	install_dnf_plugin_providers

	# A COPR repo that never enabled is the failure mode #1016 describes, and
	# the fallback below hides it. Say so in the build log, greppably, so the
	# next "package mysteriously absent" starts from evidence.
	if ! dnf -y copr enable "$COPR_NAME"; then
		echo "TUNAOS_COPR_ENABLE_FAILED repo=${COPR_NAME} — packages from it will fall back to base repos" >&2
	fi

	REPO_ID="copr:copr.fedorainfracloud.org:$(echo "$COPR_NAME" | tr '/' ':')"

	# Set priority if specified
	if [[ -n "$PRIORITY" ]]; then
		if [[ $IS_FEDORA == true ]]; then
			dnf config-manager setopt "${REPO_ID}.priority=${PRIORITY}" || true
		else
			dnf config-manager --set-enabled --setopt "${REPO_ID}.priority=${PRIORITY}" || true
		fi
	fi

	dnf -y --enablerepo "${REPO_ID}" install "$@" || dnf -y install "$@" || true
	dnf -y copr disable "$COPR_NAME" || true
}

# _yq_array — Read YAML array into a bash array variable.
# Usage: _yq_array <array_name> <yq_args...>
_yq_array() {
	local _arr_name="$1"
	shift
	readarray -t "$_arr_name" < <($YQ "$@" 2>/dev/null || true)
}

# emit_packages_manifest — Write normalized JSON package manifest to /usr/share/tunaos/packages.json
# Usage: emit_packages_manifest
emit_packages_manifest() {
	local img_name="${IMAGE_NAME:-unknown}"
	local img_flavor="${DESKTOP_FLAVOR:-gnome}"
	local pkg_mgr="${PKG_MGR:-unknown}"
	local target_dir="/usr/share/tunaos"
	local target_file="${target_dir}/packages.json"
	local tmp_file="/tmp/packages.json.tmp"

	mkdir -p "${target_dir}"

	local raw_pkgs=""
	if command -v rpm >/dev/null 2>&1; then
		raw_pkgs="$(rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}\n' 2>/dev/null | LC_ALL=C sort -u || true)"
	elif command -v dpkg-query >/dev/null 2>&1; then
		raw_pkgs="$(dpkg-query -W -f '${Package}\t${Version}\n' 2>/dev/null | LC_ALL=C sort -u || true)"
	elif command -v pacman >/dev/null 2>&1; then
		raw_pkgs="$(pacman -Q 2>/dev/null | tr ' ' '\t' | LC_ALL=C sort -u || true)"
	elif command -v qlist >/dev/null 2>&1; then
		raw_pkgs="$(qlist -ICv 2>/dev/null | awk '{
			name=$0;
			sub(/-[0-9].*/, "", name);
			sub(/^[^\/]*\//, "", name);
			ver=$0;
			sub(/^.*-/, "", ver);
			print name "\t" ver;
		}' | LC_ALL=C sort -u || true)"
	fi

	python3 -c '
import json, sys

img_name = sys.argv[1]
img_flavor = sys.argv[2]
pkg_mgr = sys.argv[3]
raw = sys.stdin.read().strip()

packages = []
if raw:
    for line in raw.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            packages.append({"name": parts[0], "version": parts[1]})
        elif len(parts) == 1 and parts[0]:
            packages.append({"name": parts[0], "version": ""})

manifest = {
    "image": img_name,
    "flavor": img_flavor,
    "pkg_manager": pkg_mgr,
    "count": len(packages),
    "packages": packages
}

with open(sys.argv[4], "w") as f:
    json.dump(manifest, f, indent=2)
' "$img_name" "$img_flavor" "$pkg_mgr" "$tmp_file" < <(printf '%s\n' "$raw_pkgs")

	mv "$tmp_file" "$target_file"
	chmod 0644 "$target_file"
	echo "emit_packages_manifest: wrote $(wc -l <"$target_file") lines to ${target_file}"
}

