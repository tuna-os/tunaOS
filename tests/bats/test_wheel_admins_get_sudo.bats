#!/usr/bin/env bats
# Administrators are group `wheel`, and must be able to sudo with their own
# password.
#
# WHY THIS EXISTS: tuna-desktop#989's fresh-account journey created the first
# admin through GDM (`useradd -G wheel`) on marlin, and the guest journal of
# tuna-desktop CI run 41230684089 recorded
#
#   sudo[4083]: tunaadmin : user NOT in sudoers
#
# Arch (and Gentoo) ship `%wheel` commented out in /etc/sudoers and nothing in
# tunaOS granted it. 40-services.sh now writes the grant on every base and
# fails the build if visudo rejects it or the base never reads it. These tests
# execute the function against a scratch tree, with the host's visudo.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SERVICES="${REPO_ROOT}/build_scripts/40-services.sh"
POLICY="${REPO_ROOT}/build_scripts/lib/service-policy.sh"

setup() {
	command -v visudo >/dev/null 2>&1 || skip "visudo not installed on this host"
	ROOT="${BATS_TEST_TMPDIR}/root"
	mkdir -p "${ROOT}/etc/sudoers.d"
}

# Directory includes demand root-owned directories, which a test cannot make,
# so the scratch sudoers names the drop-in directly; the parse is the same.
main_sudoers_including_dropin() {
	printf 'root ALL=(ALL:ALL) ALL\n@include %s/etc/sudoers.d/10-tunaos-wheel\n' "$ROOT" >"$1"
}

grant() {
	TUNAOS_SUDOERS_ROOT="$ROOT" bash -euo pipefail -c \
		'. "$1"; tunaos_grant_wheel_sudo' _ "$POLICY"
}

@test "the grant is exactly password-required sudo for %wheel, mode 0440" {
	main_sudoers_including_dropin "${ROOT}/etc/sudoers"
	run grant
	[ "$status" -eq 0 ]
	[ "$(cat "${ROOT}/etc/sudoers.d/10-tunaos-wheel")" = '%wheel ALL=(ALL:ALL) ALL' ]
	[ "$(stat -c %a "${ROOT}/etc/sudoers.d/10-tunaos-wheel")" = 440 ]
	[[ "$output" == *"${ROOT}/etc/sudoers.d/10-tunaos-wheel: parsed OK"* ]]
	# No temporary file is left behind for sudo to read.
	[ "$(find "${ROOT}/etc/sudoers.d" -mindepth 1 | wc -l)" -eq 1 ]
}

@test "openSUSE's /usr/etc/sudoers is found when /etc/sudoers is absent" {
	mkdir -p "${ROOT}/usr/etc"
	main_sudoers_including_dropin "${ROOT}/usr/etc/sudoers"
	# Tumbleweed installs it 0444, which bare `visudo -c` refuses.
	chmod 0444 "${ROOT}/usr/etc/sudoers"
	run grant
	[ "$status" -eq 0 ]
	[[ "$output" == *"granted %wheel"* ]]
}

@test "a sudoers that never reads the drop-in fails the build" {
	printf 'root ALL=(ALL:ALL) ALL\n' >"${ROOT}/etc/sudoers"
	run grant
	[ "$status" -ne 0 ]
	[[ "$output" == *"does not include"* ]]
}

@test "a broken sudoers elsewhere in the config fails the build" {
	main_sudoers_including_dropin "${ROOT}/etc/sudoers"
	printf '%%admins ALL=(ALL:ALL\n' >>"${ROOT}/etc/sudoers"
	run grant
	[ "$status" -ne 0 ]
}

@test "an image with no sudo fails the build instead of shipping a dead grant" {
	main_sudoers_including_dropin "${ROOT}/etc/sudoers"
	run env PATH="${BATS_TEST_TMPDIR}/empty" TUNAOS_SUDOERS_ROOT="$ROOT" \
		/bin/bash -euo pipefail -c '. "$1"; tunaos_grant_wheel_sudo' _ "$POLICY"
	[ "$status" -ne 0 ]
	[[ "$output" == *"no visudo"* ]]
	[ ! -e "${ROOT}/etc/sudoers.d/10-tunaos-wheel" ]
}

@test "no grant is NOPASSWD" {
	! grep -n 'NOPASSWD' <(sed -n '/^tunaos_grant_wheel_sudo()/,/^}/p' "$POLICY")
}

@test "40-services.sh grants it before any package-manager branch exits" {
	# The apt and pacman/zypper/emerge branches end in `exit 0`; a call placed
	# after them runs on the rpm bases only.
	local call first_exit
	call=$(grep -n '^tunaos_grant_wheel_sudo$' "$SERVICES" | head -1 | cut -d: -f1)
	first_exit=$(grep -nE '^[[:space:]]+exit 0' "$SERVICES" | head -1 | cut -d: -f1)
	[ -n "$call" ]
	[ -n "$first_exit" ]
	[ "$call" -lt "$first_exit" ]
}
