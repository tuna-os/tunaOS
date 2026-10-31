#!/usr/bin/env bash
# An image's own kernel arguments, for its live boot entry.
#
# An image declares its kernel arguments in /usr/lib/bootc/kargs.d (hardware
# profiles, NVIDIA, the base image). bootc applies them to every installed
# deployment, but tacklebox writes the live entries from the recipe's `kargs`
# alone and never reads kargs.d, so without this the live session boots
# without arguments the installed system gets: a hardware profile's live
# boot would lack the very arguments its machine needs.

TUNAOS_BOOTC_KARGS_PY="$(dirname "${BASH_SOURCE[0]}")/bootc_kargs.py"

# Prints the image's kargs.d arguments for the image's own architecture, one
# per line, by bootc's rules (scripts/lib/bootc_kargs.py).
tunaos_image_kargs() {
	local image="${1:?image required}" dir arch
	dir="$(mktemp -d)" || return 1
	if ! podman run --rm --log-driver=k8s-file --security-opt label=disable \
		-v "${dir}:/tunaos-kargs" --entrypoint /bin/sh "$image" \
		-c 'uname -m >/tunaos-kargs/arch && { [ ! -d /usr/lib/bootc/kargs.d ] || cp -R /usr/lib/bootc/kargs.d /tunaos-kargs/; }'; then
		echo "ERROR: could not read /usr/lib/bootc/kargs.d from ${image}" >&2
		rm -rf "$dir"
		return 1
	fi
	arch="$(<"${dir}/arch")"
	if ! python3 "$TUNAOS_BOOTC_KARGS_PY" "${dir}/kargs.d" "$arch"; then
		echo "ERROR: ${image} has an invalid /usr/lib/bootc/kargs.d" >&2
		rm -rf "$dir"
		return 1
	fi
	rm -rf "$dir"
}

# Prints, as a JSON array, the kargs.d arguments shared by the live images of
# one ISO. tacklebox's recipe has one `kargs` list for every entry, so images
# that declare different arguments cannot share an ISO without one of them
# booting with another's arguments, or without its own: that fails here.
tunaos_live_kargs_json() {
	local image kargs first="" first_image="" list=()
	for image in "$@"; do
		kargs="$(tunaos_image_kargs "$image")" || return 1
		if [[ -z "$first_image" ]]; then
			first="$kargs"
			first_image="$image"
		elif [[ "$kargs" != "$first" ]]; then
			echo "ERROR: live images declare different kernel arguments in /usr/lib/bootc/kargs.d:" >&2
			echo "  ${first_image}: ${first//$'\n'/ }" >&2
			echo "  ${image}: ${kargs//$'\n'/ }" >&2
			echo "  tacklebox's recipe holds one kargs list for every live entry; build them as separate ISOs." >&2
			return 1
		fi
	done
	[[ -z "$first" ]] || mapfile -t list <<<"$first"
	jq -cn '$ARGS.positional' --args "${list[@]}"
}
