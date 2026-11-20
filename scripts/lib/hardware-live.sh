#!/usr/bin/env bash
# Live ISO routing for hardware-profile flavors (tunaos.toml [hardware.*]).
#
# A hardware flavor needs boot media made for its machine. A generic live
# ISO of it would boot the wrong way or not at all, so a hardware profile
# with no live path is an error, never a silent fallback to the generic ISO.
#
# Sourced by scripts/build-iso-tacklebox.sh and by the ISO boot gate in
# .github/workflows/reusable-build-artifacts.yml. It must not change shell
# options.

_TUNAOS_HARDWARE_LIVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# tunaos_flavor_hardware <variant> <flavor>
# Prints the flavor's hardware profile name from the generated
# build_scripts/lib/hardware-profiles.json, or nothing for a generic flavor.
# TUNAOS_HARDWARE_PROFILES_JSON overrides the file (tests).
tunaos_flavor_hardware() {
	local variant="${1:?variant required}" flavor="${2:?flavor required}"
	local profiles="${TUNAOS_HARDWARE_PROFILES_JSON:-${_TUNAOS_HARDWARE_LIVE_ROOT}/build_scripts/lib/hardware-profiles.json}"
	jq -er --arg v "$variant" --arg f "$flavor" \
		'(.flavors[$v][$f].hardware // "") | strings' "$profiles"
}

# tunaos_live_iso_route <hardware> <platform>
# Prints how to build the live ISO: "generic" for a flavor without a
# hardware profile, "x13s" for the X13s profile on linux/arm64. Any other
# combination fails, naming the profile.
tunaos_live_iso_route() {
	local hardware="${1-}" platform="${2:?platform required}"
	case "${hardware}:${platform}" in
	:*) echo generic ;;
	x13s:linux/arm64) echo x13s ;;
	*)
		echo "ERROR: hardware profile '${hardware}' has no live ISO path on ${platform}." \
			"Build its ISO only after one exists; a generic ISO does not boot that hardware." >&2
		return 1
		;;
	esac
}

# tunaos_live_iso_boot_marker <route>
# Prints the serial-log regex the QEMU boot gate waits for. QEMU is not an
# X13s: the X13s media boots shim, GRUB, the Fedora loader, the kernel and
# the initrd, then the ADSP barrier stops the boot because QEMU has no ADSP.
# That stop is the proof the whole chain ran. It is not a hardware result.
tunaos_live_iso_boot_marker() {
	case "${1:?route required}" in
	generic) echo 'TUNAOS_LIVE_READY|TBOX_LIVE_READY' ;;
	x13s) echo 'Tacklebox: X13s external root blocked' ;;
	*)
		echo "ERROR: unknown live ISO route '$1'" >&2
		return 1
		;;
	esac
}
