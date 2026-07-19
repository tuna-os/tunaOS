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
	if ! sudo -u "$real_user" podman save "$image" 2>/dev/null | podman load; then
		echo "ERROR: failed to import ${image} from ${real_user}" >&2
		return 1
	fi

	if ! podman image exists "$image"; then
		echo "ERROR: ${image} still not present after import" >&2
		return 1
	fi
}

# ── Flavor → human title ────────────────────────────────────────────────────
# Render a flavor id (e.g. "gnome-nvidia-hwe") into the title shown in the
# systemd-boot menu of a grouped ISO (e.g. "GNOME (NVIDIA, HWE)"). Keeping the
# mapping here means the boot-menu labels stay consistent across the single-
# flavor and grouped-ISO build paths.
tunaos_flavor_title() {
	local flavor="${1:?flavor required}"
	local base="$flavor" mods=() suffix=""

	# Peel hardware modifiers off the end so the desktop name is left bare.
	if [[ "$base" == *-nvidia-hwe ]]; then
		mods=("NVIDIA" "HWE")
		base="${base%-nvidia-hwe}"
	elif [[ "$base" == *-nvidia ]]; then
		mods=("NVIDIA")
		base="${base%-nvidia}"
	elif [[ "$base" == *-hwe ]]; then
		mods=("HWE")
		base="${base%-hwe}"
	fi

	local name
	case "$base" in

	gnome) name="GNOME" ;;
	kde) name="KDE Plasma" ;;
	cosmic) name="COSMIC" ;;
	niri) name="Niri" ;;
	base) name="Base" ;;
	*) name="${base^}" ;;
	esac

	if ((${#mods[@]})); then
		local joined="${mods[0]}" i
		for ((i = 1; i < ${#mods[@]}; i++)); do
			joined+=", ${mods[i]}"
		done
		suffix=" (${joined})"
	fi
	printf '%s%s\n' "$name" "$suffix"
}

# ── Desktop session for a flavor ────────────────────────────────────────────
# Map a flavor id to its desktop session so tacklebox's livesys-* sets autologin
# for the right session manager. Hardware modifiers (-hwe/-nvidia) don't change
# the desktop, so a prefix match is sufficient.
tunaos_flavor_desktop() {
	local flavor="${1:?flavor required}"
	case "$flavor" in
	kde*) echo "kde" ;;
	niri*) echo "niri" ;;
	cosmic*) echo "cosmic" ;;
	xfce*) echo "xfce" ;;
	gnome* | *) echo "gnome" ;;
	esac
}

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

	"${tb[@]}" build "$(realpath "$recipe_file")" \
		--iso "$(realpath "$iso_out")" \
		--output-base "$(realpath "$out_dir")" \
		--yes
}
