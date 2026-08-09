#!/usr/bin/env bats
# Unit tests for tests/functional/run.sh — tier-1 functional checks for a
# booted image (tuna-os/tunaos#576).
#
# run.sh is designed to run inside a booted guest over SSH; these tests stub
# its external commands (systemctl, bootc, flatpak) and point FUNCTIONAL_ROOT
# at a fake rootfs so the dispatcher logic — per-desktop DM mapping, the
# failed-unit allowlist, and the pass/fail paths — is exercised without a VM.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
RUN_SCRIPT="${REPO_ROOT}/tests/functional/run.sh"

setup() {
	TEST_ROOT="$(mktemp -d)"
	STUB_BIN="${TEST_ROOT}/stub-bin"
	mkdir -p "${STUB_BIN}"
	export PATH="${STUB_BIN}:${PATH}"

	# Healthy stubs by default; individual tests override as needed.
	cat >"${STUB_BIN}/systemctl" <<'SYSCTL'
#!/usr/bin/env bash
case "$1" in
is-system-running) echo "running"; exit 0 ;;
is-active)
	case "$2" in
	graphical.target | display-manager.service) echo "active"; exit 0 ;;
	*) exit 1 ;;
	esac
	;;
show) echo "gdm.service"; exit 0 ;;
--failed) exit 0 ;;
*) exit 0 ;;
esac
SYSCTL
	cat >"${STUB_BIN}/bootc" <<'BOOTC'
#!/usr/bin/env bash
exit 0
BOOTC
	cat >"${STUB_BIN}/flatpak" <<'FLATPAK'
#!/usr/bin/env bash
echo "flathub"
FLATPAK
	chmod +x "${STUB_BIN}/systemctl" "${STUB_BIN}/bootc" "${STUB_BIN}/flatpak"
	ln -sf /bin/true "${STUB_BIN}/gnome-shell"

	# Fake rootfs: session entry + branding artifacts + Flathub preconfig.
	mkdir -p "${TEST_ROOT}/usr/share/wayland-sessions" \
		"${TEST_ROOT}/usr/share/ublue-os" \
		"${TEST_ROOT}/etc/bootc-installer" \
		"${TEST_ROOT}/etc/flatpak/remotes.d"
	: >"${TEST_ROOT}/usr/share/wayland-sessions/gnome.desktop"
	: >"${TEST_ROOT}/etc/bootc-installer/recipe.json"
	: >"${TEST_ROOT}/etc/flatpak/remotes.d/flathub.flatpakrepo"
	echo '{"image-name":"yellowfin","image-vendor":"tuna-os"}' \
		>"${TEST_ROOT}/usr/share/ublue-os/image-info.json"

	export FUNCTIONAL_ROOT="${TEST_ROOT}"
}

teardown() {
	rm -rf "${TEST_ROOT}"
}

@test "run.sh: healthy gnome system passes" {
	run bash "${RUN_SCRIPT}" gnome yellowfin
	[ "$status" -eq 0 ]
	[[ "$output" == *"ok - "* ]]
	[[ "$output" != *"not ok -"* ]]
}

@test "run.sh: allowlisted failed units do not fail the run" {
	cat >"${STUB_BIN}/systemctl" <<'SYSCTL'
#!/usr/bin/env bash
case "$1" in
is-system-running) echo "running"; exit 0 ;;
is-active)
	case "$2" in
	graphical.target | display-manager.service) echo "active"; exit 0 ;;
	*) exit 1 ;;
	esac
	;;
show) echo "gdm.service"; exit 0 ;;
--failed)
	echo "  libstoragemgmt.service loaded failed failed libstoragemgmt"
	echo "  mcelog.service         loaded failed failed mcelog"
	exit 0
	;;
*) exit 0 ;;
esac
SYSCTL
	chmod +x "${STUB_BIN}/systemctl"
	run bash "${RUN_SCRIPT}" gnome
	[ "$status" -eq 0 ]
	[[ "$output" == *"allowlisted failed unit"* ]]
	[[ "$output" != *"not ok -"* ]]
}

@test "run.sh: non-allowlisted failed unit fails the run" {
	cat >"${STUB_BIN}/systemctl" <<'SYSCTL'
#!/usr/bin/env bash
case "$1" in
is-system-running) echo "running"; exit 0 ;;
is-active)
	case "$2" in
	graphical.target | display-manager.service) echo "active"; exit 0 ;;
	*) exit 1 ;;
	esac
	;;
show) echo "gdm.service"; exit 0 ;;
--failed)
	echo "  tunaos-broken.service   loaded failed failed tunaos-broken"
	exit 0
	;;
*) exit 0 ;;
esac
SYSCTL
	chmod +x "${STUB_BIN}/systemctl"
	run bash "${RUN_SCRIPT}" gnome
	[ "$status" -ne 0 ]
	[[ "$output" == *"blocking failed units"* ]]
	[[ "$output" == *"not ok - no failed systemd units outside allowlist"* ]]
}

@test "run.sh: wrong display manager for the desktop fails" {
	cat >"${STUB_BIN}/systemctl" <<'SYSCTL'
#!/usr/bin/env bash
case "$1" in
is-system-running) echo "running"; exit 0 ;;
is-active)
	case "$2" in
	graphical.target) echo "active"; exit 0 ;;
	display-manager.service) echo "active"; exit 0 ;;
	*) exit 1 ;;
	esac
	;;
show) echo "lightdm.service"; exit 0 ;;
--failed) exit 0 ;;
*) exit 0 ;;
esac
SYSCTL
	chmod +x "${STUB_BIN}/systemctl"
	run bash "${RUN_SCRIPT}" gnome
	[ "$status" -ne 0 ]
	[[ "$output" == *"not ok - display manager matches gnome"* ]]
}

@test "run.sh: missing session binary fails" {
	rm -f "${STUB_BIN}/gnome-shell"
	run bash "${RUN_SCRIPT}" gnome
	[ "$status" -ne 0 ]
	[[ "$output" == *"not ok - gnome-shell is installed"* ]]
}

@test "run.sh: branding variant mismatch fails" {
	echo '{"image-name":"albacore","image-vendor":"tuna-os"}' \
		>"${TEST_ROOT}/usr/share/ublue-os/image-info.json"
	run bash "${RUN_SCRIPT}" gnome yellowfin
	[ "$status" -ne 0 ]
	[[ "$output" == *"not ok - image-info.json image-name is yellowfin"* ]]
}

@test "run.sh: unknown desktop exits 2" {
	run bash "${RUN_SCRIPT}" not-a-desktop
	[ "$status" -eq 2 ]
	[[ "$output" == *"unknown desktop"* ]]
}
