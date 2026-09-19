#!/usr/bin/env bash
# Tacklebox acquisition and execution helpers.
#
# This library is sourced by common.sh as a compatibility facade. It must not
# change shell options or the caller's working directory.

# Resolve tacklebox (the published container image by default, or a pinned
# source build when TACKLEBOX_FROM_SOURCE=1) and build the ISO described by
# <recipe_file>. Shared by build-iso-tacklebox.sh (single flavor) and
# build-iso-group.sh (grouped dedup). Must run as root — tacklebox needs
# loopback + sgdisk + mkfs.
#
# Usage: tunaos_run_tacklebox <recipe_file> <out_dir> <iso_out>
tunaos_run_tacklebox() {
	local recipe_file="${1:?recipe_file required}"
	local out_dir="${2:?out_dir required}"
	local iso_out="${3:?iso_out required}"
	# Tacklebox currently reports a live-customize phase only as
	# "running N script(s)". If a nested operation stalls, the surrounding
	# 90-minute Actions job used to end as a bare cancellation with neither an
	# actionable error nor its later diagnostic steps (#1772). Bound the whole
	# invocation below that job limit so the failure says what happened and the
	# workflow still has time to upload its evidence. Workflows with a reviewed
	# longer budget may override this, but an unbounded value is never accepted.
	local timeout_seconds="${TUNAOS_TACKLEBOX_TIMEOUT_SECONDS:-4800}"
	[[ "$timeout_seconds" =~ ^[1-9][0-9]*$ ]] || {
		echo "ERROR: TUNAOS_TACKLEBOX_TIMEOUT_SECONDS must be a positive integer" >&2
		return 2
	}

	local tacklebox_image="${TACKLEBOX_IMAGE:-ghcr.io/tuna-os/tacklebox:latest}"
	local from_source="${TACKLEBOX_FROM_SOURCE:-0}"

	# Tacklebox defaults its post-customize podman commit to 600 seconds. That
	# is too short for several multi-gigabyte desktop layers on CI (#1893), so
	# TunaOS gives it 30 minutes while the outer deadline above still catches a
	# real wedge. Keep this local: the library must not alter its caller's
	# environment after the function returns. Export it so both the host binary
	# and the container forwarding path below receive the same value.
	local TBOX_CUSTOMIZE_COMMIT_TIMEOUT="${TBOX_CUSTOMIZE_COMMIT_TIMEOUT:-1800}"
	[[ "$TBOX_CUSTOMIZE_COMMIT_TIMEOUT" =~ ^(0|[1-9][0-9]*)$ ]] || {
		echo "ERROR: TBOX_CUSTOMIZE_COMMIT_TIMEOUT must be a non-negative integer" >&2
		return 2
	}
	export TBOX_CUSTOMIZE_COMMIT_TIMEOUT

	# Make the two execution paths agree about the environment.
	#
	# The host-binary path (TACKLEBOX_FROM_SOURCE=1) runs tacklebox as an
	# ordinary child process, so it inherits every exported TBOX_* knob for
	# free. The container path does not: `podman run <image>` starts from the
	# image's own environment and drops the caller's. A workflow that exports
	# a tacklebox knob — weekly-desktop-screenshots.yml sets
	# TBOX_CUSTOMIZE_NETWORK=host — therefore had it silently ignored on the
	# container path, which is the same trap that workflow's comment records
	# hitting once already. Forward the exported TBOX_* names explicitly so a
	# knob set for a build takes effect however tacklebox is run.
	#
	# The filter is deliberately name-agnostic. tunaOS does not need to know
	# which knobs tacklebox understands, so one added there reaches it the day
	# it lands with no change on this side. That includes the commit deadline
	# above, added upstream for tunaOS#2034 after the 600s default killed the
	# ISO builds tracked in tunaOS#1893.
	#
	# Not --env-host: that hands the container the runner's entire
	# environment, GITHUB_TOKEN and registry credentials included.
	local -a tbox_env=() tbox_names=()
	local _tbox_name
	for _tbox_name in $(compgen -e); do
		[[ "$_tbox_name" == TBOX_* ]] || continue
		tbox_env+=(--env "${_tbox_name}=${!_tbox_name}")
		tbox_names+=("${_tbox_name}=${!_tbox_name}")
	done

	local -a tb
	if [[ "$from_source" == "1" ]]; then
		# Pin the source SHA so CI doesn't silently track a moving HEAD.
		local sha cache bin
		sha="${TACKLEBOX_SHA:-$(grep '^\s*tacklebox:' image-versions.yaml 2>/dev/null | sed 's/.*"\(.*\)".*/\1/')}"
		sha="${sha:-3b4598273efb2f71d17515947e442f0e6b26a6c5}"
		cache="${TACKLEBOX_CACHE:-/var/cache/tunaos/tacklebox}"
		bin="${cache}/tacklebox"

		if [[ ! -x "$bin" ]] || [[ "$("$bin" version 2>/dev/null || echo)" != *"$sha"* ]]; then
			echo "==> Building tacklebox @ ${sha}..." >&2
			mkdir -p "$cache"
			(
				cd "$cache" || exit 1
				if [[ ! -d .git ]]; then
					git clone --quiet https://github.com/tuna-os/tacklebox.git .
				else
					git fetch --quiet origin
				fi
				git -c advice.detachedHead=false checkout --quiet "$sha"
				local go_bin=""
				for g in /home/linuxbrew/.linuxbrew/bin/go /usr/bin/go go; do
					if command -v "$g" &>/dev/null; then
						go_bin="$g"
						break
					fi
				done
				if [[ -z "$go_bin" ]]; then
					echo "ERROR: go not found; install go 1.22+ to build tacklebox" >&2
					exit 1
				fi
				"$go_bin" build -o tacklebox ./cmd/tacklebox
			)
		fi
		[[ -x "$bin" ]] || {
			echo "ERROR: tacklebox binary missing after build" >&2
			return 1
		}
		tb=("$bin")
	else
		echo "==> Using tacklebox image: ${tacklebox_image}" >&2
		podman pull "$tacklebox_image" >/dev/null
		tb=(podman run --rm --privileged
			--security-opt label=disable
			-v /var/lib/containers:/var/lib/containers
			-v /dev:/dev
			-v "$(realpath "$out_dir"):$(realpath "$out_dir")"
			-v "$(realpath "$recipe_file"):$(realpath "$recipe_file"):ro"
			"${tbox_env[@]}"
			"$tacklebox_image")
	fi

	# Say which knobs are in play either way: on the host path the inheritance
	# is invisible, and a knob that turns out not to have been set is the first
	# thing to check when a build behaves as though it were unset.
	if ((${#tbox_names[@]})); then
		echo "==> Tacklebox environment: ${tbox_names[*]}" >&2
	fi

	local -a build_cmd=("${tb[@]}" build "$(realpath "$recipe_file")"
	--iso "$(realpath "$iso_out")"
	--output-base "$(realpath "$out_dir")"
	--yes)

	echo "==> Running tacklebox with a ${timeout_seconds}s deadline" >&2
	if timeout --foreground --kill-after=120 "$timeout_seconds" "${build_cmd[@]}"; then
		return 0
	else
		local rc=$?
		if [[ "$rc" -eq 124 || "$rc" -eq 137 ]]; then
			echo "::error::tacklebox exceeded its ${timeout_seconds}s deadline; " \
				"see tunaOS#1772 and the workflow diagnostics below" >&2
			podman ps -a 2>&1 || true
		fi
		return "$rc"
	fi
}
