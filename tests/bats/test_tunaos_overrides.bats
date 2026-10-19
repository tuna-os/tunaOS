#!/usr/bin/env bats
# BATS tests for the TunaOS common-payload overrides (ujust completions,
# uupd notification drop-in + notifier).
#
# The projectbluefin/common layers are copied AFTER the context files in
# every Containerfile, so these files are (re)installed by
# build_scripts/install-tunaos-overrides.sh after the last common COPY
# (called from 40-services.sh and install-desktop.sh).

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
INSTALLER="${REPO_ROOT}/build_scripts/install-tunaos-overrides.sh"
ASSETS="${REPO_ROOT}/build_scripts/assets/tunaos-overrides"

@test "installer: exists, executable, strict mode" {
	[ -x "$INSTALLER" ]
	grep -q 'set -euo pipefail' "$INSTALLER"
}

@test "installer: installs all six files under override root" {
	root="$(mktemp -d)"
	TUNAOS_OVERRIDE_ROOT="$root" bash "$INSTALLER" >/dev/null
	[ -f "$root/usr/share/bash-completion/completions/ujust" ]
	[ -f "$root/usr/share/zsh/site-functions/_ujust" ]
	[ -f "$root/usr/share/fish/vendor_completions.d/ujust.fish" ]
	[ -f "$root/usr/lib/systemd/system/uupd.service.d/20-tunaos.conf" ]
	[ -f "$root/usr/lib/systemd/system/tunaos-uupd-notify@.service" ]
	[ -x "$root/usr/libexec/tunaos/uupd-notify" ]
	rm -rf "$root"
}

@test "installer: installed files match assets byte-for-byte" {
	root="$(mktemp -d)"
	TUNAOS_OVERRIDE_ROOT="$root" bash "$INSTALLER" >/dev/null
	cmp "$ASSETS/ujust-bash" "$root/usr/share/bash-completion/completions/ujust"
	cmp "$ASSETS/ujust-zsh" "$root/usr/share/zsh/site-functions/_ujust"
	cmp "$ASSETS/ujust-fish" "$root/usr/share/fish/vendor_completions.d/ujust.fish"
	cmp "$ASSETS/uupd-20-tunaos.conf" "$root/usr/lib/systemd/system/uupd.service.d/20-tunaos.conf"
	cmp "$ASSETS/tunaos-uupd-notify.service" "$root/usr/lib/systemd/system/tunaos-uupd-notify@.service"
	cmp "$ASSETS/uupd-notify" "$root/usr/libexec/tunaos/uupd-notify"
	rm -rf "$root"
}

@test "installer: idempotent" {
	root="$(mktemp -d)"
	TUNAOS_OVERRIDE_ROOT="$root" bash "$INSTALLER" >/dev/null
	run env TUNAOS_OVERRIDE_ROOT="$root" bash "$INSTALLER"
	[ "$status" -eq 0 ]
	rm -rf "$root"
}

@test "bash completion: registers for ujust, injects justfile" {
	run grep -E 'complete .* -F _ujust ujust' "$ASSETS/ujust-bash"
	[ "$status" -eq 0 ]
	run grep -c 'complete .*-F .* just$' "$ASSETS/ujust-bash"
	[ "$output" -eq 0 ]
	run grep -F -- '--justfile' "$ASSETS/ujust-bash"
	[ "$status" -eq 0 ]
	run grep -F '/usr/share/ublue-os/just/00-entry.just' "$ASSETS/ujust-bash"
	[ "$status" -eq 0 ]
}

@test "zsh completion: compdef ujust, injects justfile" {
	run head -1 "$ASSETS/ujust-zsh"
	[ "$output" = '#compdef ujust' ]
	run grep -E '_clap_dynamic_completer_just' "$ASSETS/ujust-zsh"
	[ "$status" -ne 0 ]
	run grep -F -- '--justfile' "$ASSETS/ujust-zsh"
	[ "$status" -eq 0 ]
}

@test "fish completion: targets ujust command, injects justfile" {
	run grep -E -- '--command ujust' "$ASSETS/ujust-fish"
	[ "$status" -eq 0 ]
	run grep -cE -- '--command just([ "}]|$)' "$ASSETS/ujust-fish"
	[ "$output" -eq 0 ]
	run grep -F -- '--justfile' "$ASSETS/ujust-fish"
	[ "$status" -eq 0 ]
}

@test "uupd drop-in: disables restart spam, wires notifier" {
	run grep -E '^Restart=no' "$ASSETS/uupd-20-tunaos.conf"
	[ "$status" -eq 0 ]
	run grep -E '^OnFailure=tunaos-uupd-notify@%n\.service' "$ASSETS/uupd-20-tunaos.conf"
	[ "$status" -eq 0 ]
}

@test "notifier unit: runs the notify script with the failed unit" {
	run grep -F 'ExecStart=/usr/libexec/tunaos/uupd-notify %i' "$ASSETS/tunaos-uupd-notify.service"
	[ "$status" -eq 0 ]
}

@test "notifier script: icon, retry action, never fails pipeline" {
	run grep -F 'ICON="software-update-available"' "$ASSETS/uupd-notify"
	[ "$status" -eq 0 ]
	run grep -F -- '--icon="$ICON"' "$ASSETS/uupd-notify"
	[ "$status" -eq 0 ]
	run grep -F -- '--action=retry=' "$ASSETS/uupd-notify"
	[ "$status" -eq 0 ]
	run tail -1 "$ASSETS/uupd-notify"
	[ "$output" = 'exit 0' ]
}

@test "wiring: 40-services and install-desktop call the installer" {
	run grep -c 'install-tunaos-overrides.sh' "${REPO_ROOT}/build_scripts/40-services.sh"
	[ "$output" -ge 2 ]
	run grep -c 'install-tunaos-overrides.sh' "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
	[ "$output" -ge 1 ]
}

@test "shellcheck: installer and notifier are clean" {
	if ! command -v shellcheck &>/dev/null; then
		skip "shellcheck not installed"
	fi
	run shellcheck --exclude=SC1091 "$INSTALLER"
	[ "$status" -eq 0 ]
	run shellcheck "$ASSETS/uupd-notify"
	[ "$status" -eq 0 ]
}
