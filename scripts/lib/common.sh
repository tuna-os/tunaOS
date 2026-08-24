#!/usr/bin/env bash
# scripts/lib/common.sh — shared helpers sourced by scripts/build-*.sh and
# friends. Not meant to be executed directly.
#
# Pulls together the four bits of boilerplate that every build script was
# re-implementing in slightly different ways:
#   1. cd to the repo root so paths are reliable
#   2. detect host arch → podman --platform string
#   3. resolve a (variant, flavor, repo) tuple into an OCI image reference
#   4. import a localhost/* image from the invoking user's storage into
#      root podman storage (sudo'd build scripts need this)
#
# Source style:
#   #!/usr/bin/env bash
#   set -euo pipefail
#   # shellcheck source=lib/common.sh
#   . "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
#
# Then the script just calls the helpers below. The caller is responsible
# for `set -euo pipefail`; libraries shouldn't leak shell options into
# their caller's environment.

# Move to the repo root. We use this file's own path (always at
# scripts/lib/common.sh under the repo root) rather than $BASH_SOURCE[1]
# — the latter is empty when sourced from an interactive shell and would
# crash under `set -u` before the caller's `cd` could run.
_TUNAOS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$_TUNAOS_REPO_ROOT" || {
	echo "ERROR: cannot enter repo root ${_TUNAOS_REPO_ROOT}" >&2
	exit 1
}

# Compatibility facade: existing callers retain these helpers while focused
# consumers can source the side-effect-free flavor contract directly.
# shellcheck source=flavor.sh
. "$(dirname "${BASH_SOURCE[0]}")/flavor.sh"

# ── Image-ref resolution ────────────────────────────────────────────────────
# Given (variant, flavor, repo, tag) → OCI image reference string.
# `repo` is one of: local | ghcr | registry
# `tag` defaults to the flavor name.
# If `variant` already looks like a ref (contains `:` or `/`) it's returned
# as-is so callers can pass `ghcr.io/foo/bar:tag` directly.
tunaos_image_ref() {
	local variant="${1:?variant required}"
	local flavor="${2:-gnome}"
	local repo="${3:-local}"
	local tag="${4:-${flavor}}"

	# Already a ref? Pass through unchanged.
	if [[ "$variant" == *":"* || "$variant" == *"/"* ]]; then
		echo "$variant"
		return
	fi

	local owner="${GITHUB_REPOSITORY_OWNER:-tuna-os}"
	case "$repo" in
	local)
		echo "localhost/${variant}:${tag}"
		;;
	ghcr)
		GITHUB_REPOSITORY_OWNER="$owner" bash ./scripts/published-image-ref.sh "$variant" "$tag" ghcr
		;;
	registry)
		bash ./scripts/published-image-ref.sh "$variant" "$tag" registry
		;;
	*)
		echo "ERROR: unknown repo '${repo}' (expected: local | ghcr | registry)" >&2
		return 1
		;;
	esac
}

# ── Cross-storage image import ──────────────────────────────────────────────
# Some scripts run via `sudo` (e.g. build-iso-tacklebox.sh)
# which uses root's podman storage, while developers usually build images
# into their unprivileged user's storage. This helper copies the image over
# without re-pulling from the registry.
#
# Returns 0 if the image now exists in root storage (or was already there),
# non-zero otherwise.
tunaos_import_to_root_storage() {
	local image="${1:?image required}"

	# Already there? Done.
	if podman image exists "$image"; then
		return 0
	fi

	# Find the user who invoked sudo. logname() falls back to SUDO_USER
	# (the latter being absent if the script was launched outside sudo).
	local real_user="${SUDO_USER:-$(logname 2>/dev/null || echo)}"
	if [[ -z "$real_user" ]]; then
		echo "ERROR: ${image} not in root storage and no SUDO_USER to import from" >&2
		echo "       Build the image first: just <variant> <flavor>" >&2
		return 1
	fi

	echo "==> Importing ${image} from ${real_user}'s podman storage into root's..."

	# XDG_RUNTIME_DIR must be set explicitly. `sudo -u "$real_user"` from a
	# root context inherits no user session, so rootless podman falls back to
	# root's /run/containers/storage, cannot write there, and dies with
	#   "RunRoot ... is not writable ... acquiring runtime init lock:
	#    open /run/libpod/alive.lck: permission denied"
	# Its stderr was being sent to /dev/null, so all the caller ever saw was
	# `podman load` choking on an empty stream ("index.json: not a directory"),
	# which points at the wrong end of the pipe entirely.
	local real_uid
	real_uid=$(id -u "$real_user" 2>/dev/null || echo)
	if [[ -z "$real_uid" ]]; then
		echo "ERROR: cannot resolve uid for ${real_user}" >&2
		return 1
	fi

	# /run/user/<uid> only exists where systemd-logind has created a session.
	# Blacksmith runners have none, so pointing at it produced:
	#
	#   Failed to get rootless runtime dir: lstat /run/user/1001: no such file
	#   error creating temporary file: No such file or directory
	#   invalid internal status, try resetting the pause process with
	#   "podman system migrate"
	#
	# and the pipe then fed `podman load` nothing, which reported the useless
	# "payload does not match any of the supported image formats". Fall back to
	# a private directory owned by the user — the same shape
	# build-iso-tacklebox.sh already uses for its dropped-privilege podman ops.
	local xdg_dir="/run/user/${real_uid}"
	if [[ ! -d "$xdg_dir" ]]; then
		xdg_dir="/tmp/tbox-xdg-${real_user}"
		install -d -o "$real_user" -g "$(id -g "$real_user")" -m 700 "$xdg_dir" || {
			echo "ERROR: cannot create a runtime dir for ${real_user} at ${xdg_dir}" >&2
			return 1
		}
	fi

	local save_err
	save_err=$(mktemp)
	if ! sudo -u "$real_user" env "XDG_RUNTIME_DIR=${xdg_dir}" \
		podman save "$image" 2>"$save_err" | podman load; then
		echo "ERROR: failed to import ${image} from ${real_user}" >&2
		[[ -s "$save_err" ]] && {
			echo "--- podman save (as ${real_user}) said:" >&2
			cat "$save_err" >&2
		}
		rm -f "$save_err"
		return 1
	fi
	rm -f "$save_err"

	if ! podman image exists "$image"; then
		echo "ERROR: ${image} still not present after import" >&2
		return 1
	fi
}

# ── Flavor → human title ────────────────────────────────────────────────────
# Render a flavor id (e.g. "gnome-nvidia-hwe") into the title shown in the
# systemd-boot menu of a grouped ISO (e.g. "GNOME (NVIDIA, HWE)"). Keeping the
# The compatibility import above keeps boot-menu labels consistent for legacy
# common.sh consumers.
# Implementation provided by scripts/lib/flavor.sh.

# ── Desktop session for a flavor ────────────────────────────────────────────
# The side-effect-free flavor library owns the desktop-session mapping.
# Implementation provided by scripts/lib/flavor.sh.

# ── tacklebox runner ────────────────────────────────────────────────────────
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

# ── bootc storage backend detection (tunaOS#954) ──────────────────────────
#
# Ported from tuna-os/wootc payload/deployer/deploy.sh:867-949, deliberately
# faithfully rather than simplified. It PROBES IMAGE CONTENT; the variant name
# is not a signal. tunaOS had three divergent name-based rules — a five-prefix
# allowlist in build-qcow2.sh (already stale: gurnard from #943 was missing and
# would have failed its first build), a bare `== grouper` test in iso-e2e.sh,
# and a separate expression in the Justfile.
#
# THE ORDER IS LOAD-BEARING.
#
#   1. bootupd PAYLOAD present  → ostree. Checked FIRST so composefs-SEALED
#      ostree images (bluefin, bonito, yellowfin) keep the ostree path even
#      though they also set `enabled = yes` in branch 2.
#   2. else prepare-root.conf composefs enabled → composefs-native. Reaching
#      here means there is NO bootupd payload, so an ostree install is
#      impossible and bootc aborts with
#         error: Installing to disk: bootupd is required for ostree-based installs
#      which is exactly the Gate failure that has kept flounder, marlin,
#      grouper and sailfin unpublished since 2026-07-13.
#   3. else ships systemd-boot → composefs-native (the dakota shape).
#   4. else unknown — never guessed.
#
# The bootloader is NOT a backend signal. Per the bootc docs a composefs
# install may use either bootupd/GRUB or systemd-boot. The old tunaOS test was
# `systemd-boot present && ! command -v bootupctl`, which mis-classified
# precisely these images: marlin ships the bootupctl BINARY at
# /usr/sbin/bootupctl but has no /usr/lib/bootupd payload.
#
# bootupd 0.2.x kept binaries under updates/EFI/<vendor>; current Fedora keeps
# versioned binaries under /usr/lib/efi with only EFI.json under bootupd/
# updates — hence the two-form branch-1 test.
#
# shellcheck disable=SC2016  # the $-free sh body is intentionally unexpanded
TUNAOS_BACKEND_PROBE_SH='
if { ls /usr/lib/bootupd/updates/EFI/*/grubx64.efi >/dev/null 2>&1 ||
     { test -f /usr/lib/bootupd/updates/EFI.json &&
       find /usr/lib/efi/grub2 -type f -name grubx64.efi -print -quit 2>/dev/null | grep -q . &&
       find /usr/lib/efi/shim -type f -name shimx64.efi -print -quit 2>/dev/null | grep -q .; }; }; then
    echo BACKEND=ostree
elif grep -A8 "^\[composefs\]" /usr/lib/ostree/prepare-root.conf 2>/dev/null \
     | grep -qiE "enabled[[:space:]]*=[[:space:]]*(yes|true|1|signed)"; then
    echo BACKEND=composefs-native
elif test -f /usr/lib/systemd/boot/efi/systemd-bootx64.efi; then
    echo BACKEND=composefs-native
else
    echo BACKEND=unknown
fi
grep -A8 "^\[composefs\]" /usr/lib/ostree/prepare-root.conf 2>/dev/null \
  | grep -qiE "enabled[[:space:]]*=[[:space:]]*(yes|true|1|signed)" && echo SEALED=1 || echo SEALED=0
'

# probe_image_backend <image-ref> [podman-prefix...]
# Echoes two lines: BACKEND=<ostree|composefs-native|unknown> and SEALED=<0|1>.
# Returns non-zero if the image could not be inspected — callers must treat
# that as fatal rather than defaulting. A silent fallback to ostree/grub2 on a
# composefs image produces a disk that boots into a dracut emergency shell with
# nothing in the log explaining why (wootc hit exactly this).
probe_image_backend() {
	local ref="${1:?probe_image_backend <image-ref>}"
	shift
	local -a runner=("$@")
	[[ ${#runner[@]} -eq 0 ]] && runner=(podman)
	timeout 300 "${runner[@]}" run --rm --entrypoint="" "$ref" sh -c "$TUNAOS_BACKEND_PROBE_SH"
}
