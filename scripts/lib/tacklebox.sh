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
			"$tacklebox_image")
	fi

	local -a build_cmd=("${tb[@]}" build "$(realpath "$recipe_file")" \
		--iso "$(realpath "$iso_out")" \
		--output-base "$(realpath "$out_dir")" \
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
