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

# ── Platform detection ──────────────────────────────────────────────────────
# Return the podman --platform string that matches the host kernel.
# Honors a pre-set $platform env var (used in CI to pin a non-host platform).
tunaos_host_platform() {
	if [[ -n "${platform:-}" ]]; then
		echo "${platform}"
		return
	fi
	local arch
	arch=$(uname -m)
	case "$arch" in
	x86_64)
		# Detect the x86_64-v2 microarchitecture via the kernel RPM
		# (Centos Stream 10 / AlmaLinux 10 split between baseline and v2).
		if rpm -q kernel 2>/dev/null | grep -q "x86_64_v2$"; then
			echo "linux/amd64/v2"
		else
			echo "linux/amd64"
		fi
		;;
	arm64 | aarch64)
		echo "linux/arm64"
		;;
	*)
		echo "ERROR: unsupported arch '${arch}' — supported: x86_64, arm64" >&2
		return 1
		;;
	esac
}

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
		echo "ghcr.io/${owner}/${variant}:${tag}"
		;;
	registry)
		echo "${REGISTRY:-localhost:5000}/${variant}:${tag}"
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
	if ! sudo -u "$real_user" podman save "$image" 2>/dev/null | podman load; then
		echo "ERROR: failed to import ${image} from ${real_user}" >&2
		return 1
	fi

	if ! podman image exists "$image"; then
		echo "ERROR: ${image} still not present after import" >&2
		return 1
	fi
}
