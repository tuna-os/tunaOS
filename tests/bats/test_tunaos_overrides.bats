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

@test "installer: installs immutable completion and boot compatibility link" {
	root="$(mktemp -d)"
	TUNAOS_OVERRIDE_ROOT="$root" bash "$INSTALLER" >/dev/null
	[ -f "$root/usr/share/bash-completion/completions/ujust" ]
	[ -f "$root/etc/bash_completion.d/ujust" ]
	[ -f "$root/usr/share/zsh/site-functions/_ujust" ]
	[ -f "$root/usr/share/fish/vendor_completions.d/ujust.fish" ]
	[ -f "$root/usr/lib/tmpfiles.d/tunaos-ujust.conf" ]
	[ -L "$root/var/usrlocal/share/zsh/site-functions/_ujust" ]
	[ "$(readlink "$root/var/usrlocal/share/zsh/site-functions/_ujust")" = "/usr/share/zsh/site-functions/_ujust" ]
	[ -f "$root/usr/lib/systemd/system/uupd.service.d/20-tunaos.conf" ]
	[ -f "$root/usr/lib/systemd/system/tunaos-uupd-notify@.service" ]
	[ -x "$root/usr/libexec/tunaos/uupd-notify" ]
	rm -rf "$root"
}

@test "installer: installed files match assets byte-for-byte" {
	root="$(mktemp -d)"
	TUNAOS_OVERRIDE_ROOT="$root" bash "$INSTALLER" >/dev/null
	cmp "$ASSETS/ujust-bash" "$root/usr/share/bash-completion/completions/ujust"
	cmp "$ASSETS/ujust-bash" "$root/etc/bash_completion.d/ujust"
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
@test "tmpfiles recreates the compatibility link after an empty or existing /var" {
	if ! command -v systemd-tmpfiles >/dev/null 2>&1; then
		skip "systemd-tmpfiles not installed"
	fi
	for state in empty preexisting; do
		root="$(mktemp -d)"
		TUNAOS_OVERRIDE_ROOT="$root" bash "$INSTALLER" >/dev/null
		if [[ "$state" == empty ]]; then
			rm -rf "$root/var"
		else
			rm -f "$root/var/usrlocal/share/zsh/site-functions/_ujust"
			printf stale >"$root/var/usrlocal/share/zsh/site-functions/_ujust"
		fi
		systemd-tmpfiles --root="$root" --create "$root/usr/lib/tmpfiles.d/tunaos-ujust.conf"
		[ -L "$root/var/usrlocal/share/zsh/site-functions/_ujust" ]
		[ "$(readlink "$root/var/usrlocal/share/zsh/site-functions/_ujust")" = "/usr/share/zsh/site-functions/_ujust" ]
		rm -rf "$root"
	done
}

@test "arch base: installs bash-completion (loader for eager ujust file)" {
	run grep -E '^\s+bash-completion \\$' "${REPO_ROOT}/Containerfile.arch"
	[ "$status" -eq 0 ]
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

@test "uupd drop-in: disables restart spam and duplicate upstream notices" {
	run grep -E '^Restart=no' "$ASSETS/uupd-20-tunaos.conf"
	[ "$status" -eq 0 ]
	run grep -E '^OnFailure=tunaos-uupd-notify@%n\.service' "$ASSETS/uupd-20-tunaos.conf"
	[ "$status" -eq 0 ]
	run grep -E '^PrivateMounts=yes$' "$ASSETS/uupd-20-tunaos.conf"
	[ "$status" -eq 0 ]
	run grep -E '^InaccessiblePaths=/usr/bin/machinectl$' "$ASSETS/uupd-20-tunaos.conf"
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

@test "notifier: retries when machinectl returns a CRLF action" {
	root="$(mktemp -d)"
	bin="$root/bin"
	mkdir -p "$bin" "$root/home"
	cat >"$bin/loginctl" <<'EOF'
#!/bin/sh
printf '1000 tester\n'
EOF
	cat >"$bin/getent" <<EOF
#!/bin/sh
printf 'tester:x:1000:1000::%s:/bin/bash\n' "$root/home"
EOF
	cat >"$bin/systemctl" <<EOF
#!/bin/sh
printf '%s\n' "\$*" >"$root/systemctl.log"
EOF
	cat >"$bin/machinectl" <<'EOF'
#!/bin/sh
printf 'retry\r\n'
EOF
	cat >"$bin/notify-send" <<'EOF'
#!/bin/sh
exit 0
EOF
	chmod +x "$bin"/*
	run env PATH="$bin:$PATH" \
		TUNAOS_MACHINECTL="$bin/machinectl" \
		TUNAOS_NOTIFY_SEND="$bin/notify-send" \
		bash "$ASSETS/uupd-notify" uupd.service
	[ "$status" -eq 0 ]
	[ "$(cat "$root/systemctl.log")" = "start uupd.service" ]
	rm -rf "$root"
}

@test "wiring: shared and overlay stages re-assert the installer" {
	services="${REPO_ROOT}/build_scripts/40-services.sh"
	shared_line="$(grep -n '^/run/context/build_scripts/install-tunaos-overrides.sh$' "$services" | cut -d: -f1)"
	apt_line="$(grep -n '^if \[\[ "\${PKG_MGR:-}" == "apt" \]\]' "$services" | cut -d: -f1)"
	[ -n "$shared_line" ]
	[ "$shared_line" -lt "$apt_line" ]
	[ "$(grep -c '^/run/context/build_scripts/install-tunaos-overrides.sh$' "$services")" -eq 1 ]
	grep -qF 'install-tunaos-overrides.sh' "${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
	grep -qF '/run/context/build_scripts/install-tunaos-overrides.sh' "${REPO_ROOT}/Containerfile.overlay"
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
