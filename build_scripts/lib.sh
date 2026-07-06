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
	MAJOR_VERSION_NUMBER="$(sh -c '. /usr/lib/os-release ; echo ${VERSION_ID%.*}')"

	# Determine the true OS base image for OS detection.
	# For chained builds (nvidia, HWE) the BASE_IMAGE env var is set via Containerfile
	# ARG/ENV to the intermediate TunaOS stage image (e.g. ghcr.io/tuna-os/yellowfin:gnome50),
	# not the original OS base. Use image-info.json written by the previous stage when
	# available — it records the true OS base from stage 1.
	_IMAGE_INFO="/usr/share/ublue-os/image-info.json"
	if [[ -f "${_IMAGE_INFO}" ]]; then
		BASE_IMAGE="$(jq -r '.["base-image"] // empty' "${_IMAGE_INFO}" 2>/dev/null)"
	fi
	if [[ -z "${BASE_IMAGE:-}" ]]; then
		BASE_IMAGE="$(sh -c '. /etc/os-release ; echo ${BASE_IMAGE}')"
	fi

	# OS Detection Flags
	IS_FEDORA=false
	IS_RHEL=false
	IS_ALMALINUX=false
	IS_ALMALINUXKITTEN=false
	IS_CENTOS=false
	IS_UBUNTU=false
	IS_DEBIAN=false

	[[ "${BASE_IMAGE,,}" == *"fedora"* ]] && IS_FEDORA=true && IMAGE_NAME="bonito" && IMAGE_PRETTY_NAME="Bonito"
	[[ "${BASE_IMAGE,,}" == *"red hat"* || "${BASE_IMAGE,,}" == *"rhel"* || "${BASE_IMAGE,,}" == *"redhat"* ]] && IS_RHEL=true && IMAGE_NAME="redfin" && IMAGE_PRETTY_NAME="Redfin"
	[[ "${BASE_IMAGE,,}" == *"almalinux"* && "${BASE_IMAGE,,}" != *"-kitten"* ]] && IS_ALMALINUX=true && IMAGE_NAME="albacore" && IMAGE_PRETTY_NAME="Albacore"
	[[ "${BASE_IMAGE,,}" == *"-kitten"* ]] && IS_ALMALINUXKITTEN=true && IMAGE_NAME="yellowfin" && IMAGE_PRETTY_NAME="Yellowfin"
	[[ "${BASE_IMAGE,,}" == *"centos"* ]] && IS_CENTOS=true && IMAGE_NAME="skipjack" && IMAGE_PRETTY_NAME="Skipjack"
	[[ "${BASE_IMAGE,,}" == *"ubuntu"* ]] && IS_UBUNTU=true && IMAGE_NAME="grouper" && IMAGE_PRETTY_NAME="Grouper"
	[[ "${BASE_IMAGE,,}" == *"debian"* && "${BASE_IMAGE,,}" != *"ubuntu"* ]] && IS_DEBIAN=true && IMAGE_NAME="flounder" && IMAGE_PRETTY_NAME="Flounder"

	# Package manager dimension
	if [[ "$IS_UBUNTU" == true || "$IS_DEBIAN" == true ]]; then
		PKG_MGR="apt"
	else
		PKG_MGR="dnf"
	fi

	# Write cache for subsequent sources within this RUN
	cat > "$_TUNAOS_ENV_CACHE" <<-ENVEOF
		MAJOR_VERSION_NUMBER="${MAJOR_VERSION_NUMBER}"
		BASE_IMAGE="${BASE_IMAGE}"
		IS_FEDORA=${IS_FEDORA}
		IS_RHEL=${IS_RHEL}
		IS_ALMALINUX=${IS_ALMALINUX}
		IS_ALMALINUXKITTEN=${IS_ALMALINUXKITTEN}
		IS_CENTOS=${IS_CENTOS}
		IS_UBUNTU=${IS_UBUNTU}
		IS_DEBIAN=${IS_DEBIAN}
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
export IS_RHEL
export IS_ALMALINUX
export IS_ALMALINUXKITTEN
export IS_CENTOS
export IS_UBUNTU
export IS_DEBIAN
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
	cp -avf "$override_path/." /
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
			apt-get install -y -f --no-install-recommends
		}
	else
		dnf_retry install -y --setopt=install_weak_deps=False "$@"
	fi
}

# Remove packages. `apt-get purge` removes config files too (equivalent
# to dnf's default `remove` behavior on EL/Fedora).
pkg_remove() {
	if [[ "$PKG_MGR" == "apt" ]]; then
		apt-get purge -y "$@"
	else
		dnf_retry remove -y "$@"
	fi
}

# Refresh package metadata.
pkg_refresh() {
	if [[ "$PKG_MGR" == "apt" ]]; then
		apt-get update
	else
		dnf makecache
	fi
}

# Clean package manager caches to minimize final image size.
pkg_clean() {
	if [[ "$PKG_MGR" == "apt" ]]; then
		apt-get clean
		rm -rf /var/lib/apt/lists/*
		mkdir -p /var/lib/apt/lists/partial
	else
		dnf clean all
	fi
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
# Usage: dnf_retry install -y foo bar
#        dnf_retry -y install --setopt=… foo
dnf_retry() {
	local max_attempts="${DNF_RETRY_ATTEMPTS:-4}"
	local attempt=1
	local rc=0
	while ((attempt <= max_attempts)); do
		dnf "$@" && return 0 || rc=$?
		echo "dnf attempt ${attempt}/${max_attempts} failed (exit ${rc}); clearing metadata and retrying..." >&2
		dnf clean metadata || true
		sleep "$((attempt * 5))"
		attempt=$((attempt + 1))
	done
	echo "dnf failed after ${max_attempts} attempts" >&2
	return "$rc"
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

		# Surface each miss as a GitHub Actions warning so the PR /
		# workflow-run summary view shows them inline (the
		# `::group::` block above folds, easy to miss). Title carries
		# the active image name so a `gh run view --json annotations`
		# call can grep by variant.
		local caller_script
		caller_script="$(basename "${BASH_SOURCE[1]:-install_available}")"
		for miss in "${missing[@]}"; do
			printf '::warning title=Missing package (%s on %s)::%s is requested by %s but not in the active repos. Consider packaging it for EL10 via tuna-os/github-copr.\n' \
				"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$miss" "$caller_script"
		done

		# Write the wishlist into the image so it travels with the
		# build. Downstream consumers (CI summary jobs, doc generators,
		# the `report-missing-packages.sh` script) can read this file
		# instead of re-parsing build logs.
		local wishlist=/usr/share/tunaos/missing-on-${IMAGE_NAME:-unknown}.txt
		mkdir -p "$(dirname "$wishlist")"
		{
			printf '# Generated by build_scripts/lib.sh:install_available\n'
			printf '# image=%s major_version=%s caller=%s timestamp=%s\n' \
				"${IMAGE_NAME:-?}" "${MAJOR_VERSION_NUMBER:-?}" "$caller_script" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
			for miss in "${missing[@]}"; do
				printf '%s\n' "$miss"
			done
		} >>"$wishlist"
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
			"${available[@]}"
	fi

	# Take the COPRs back out of the repo set so we don't leave them
	# enabled in the final image (mirrors the install_from_copr
	# pattern below).
	for copr in "${enabled_coprs[@]}"; do
		dnf -y copr disable "$copr" || true
	done
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

install_from_copr() {
	COPR_NAME=$1
	shift
	PRIORITY=""

	# Check if priority is specified as first argument after COPR_NAME
	if [[ $# -gt 0 && $1 =~ ^[0-9]+$ ]]; then
		PRIORITY=$1
		shift
	fi

	dnf -y copr enable "$COPR_NAME"

	# Set priority if specified
	if [[ -n "$PRIORITY" ]]; then
		REPO_ID="copr:copr.fedorainfracloud.org:$(echo "$COPR_NAME" | tr '/' ':')"
		if [[ $IS_FEDORA == true ]]; then
			dnf config-manager setopt "${REPO_ID}.priority=${PRIORITY}"
		else
			dnf config-manager --set-enabled --setopt "${REPO_ID}.priority=${PRIORITY}"
		fi
	fi

	dnf -y --enablerepo "copr:copr.fedorainfracloud.org:$(echo "$COPR_NAME" | tr '/' ':')" install "$@"
	dnf -y copr disable "$COPR_NAME"
}
