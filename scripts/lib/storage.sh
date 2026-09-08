#!/usr/bin/env bash
# Rootless-to-root podman storage transfer helpers.
# This library intentionally has no source-time side effects.

tunaos_import_to_root_storage() {
	local image="${1:?image required}"
	if podman image exists "$image"; then
		return 0
	fi

	local real_user="${SUDO_USER:-$(logname 2>/dev/null || echo)}"
	if [[ -z "$real_user" ]]; then
		echo "ERROR: ${image} not in root storage and no SUDO_USER to import from" >&2
		echo "       Build the image first: just <variant> <flavor>" >&2
		return 1
	fi
	echo "==> Importing ${image} from ${real_user}'s podman storage into root's..."

	local real_uid
	real_uid=$(id -u "$real_user" 2>/dev/null || echo)
	if [[ -z "$real_uid" ]]; then
		echo "ERROR: cannot resolve uid for ${real_user}" >&2
		return 1
	fi

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
