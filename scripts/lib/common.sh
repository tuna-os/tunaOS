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

# ── tacklebox runner ───────────────────────────────────────
# shellcheck source=lib/tacklebox.sh
. "${_TUNAOS_REPO_ROOT}/scripts/lib/tacklebox.sh"

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
