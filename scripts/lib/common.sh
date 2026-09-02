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

# ── tacklebox runner ───────────────────────────────────────
# shellcheck source=lib/tacklebox.sh
. "${_TUNAOS_REPO_ROOT}/scripts/lib/tacklebox.sh"

# Compatibility facade: existing consumers retain the backend-probe API while
# focused consumers can avoid common.sh's repository-root cwd change.
# shellcheck source=backend.sh
. "$(dirname "${BASH_SOURCE[0]}")/backend.sh"
