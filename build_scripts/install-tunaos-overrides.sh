#!/usr/bin/env bash
# install-tunaos-overrides.sh — (re)install TunaOS-owned files that the
# projectbluefin/common payload would otherwise clobber.
#
# Every Containerfile copies the context files first and the common
# shared/bluefin layers after, so a static system_files/ entry that collides
# with a common path loses. Call this after the last common COPY: from
# 40-services.sh (base images) and at the end of install-desktop.sh
# (desktop stages, after the bluefin copy). Idempotent — safe to run twice.
#
# TUNAOS_OVERRIDE_ROOT redirects installs for tests (default /).
set -euo pipefail

ROOT="${TUNAOS_OVERRIDE_ROOT:-/}"
ASSETS="$(cd "$(dirname "${BASH_SOURCE[0]}")/assets/tunaos-overrides" && pwd)"

install -Dm0644 "$ASSETS/ujust-bash" \
	"$ROOT/usr/share/bash-completion/completions/ujust"
install -Dm0644 "$ASSETS/ujust-zsh" \
	"$ROOT/usr/share/zsh/site-functions/_ujust"
install -Dm0644 "$ASSETS/ujust-fish" \
	"$ROOT/usr/share/fish/vendor_completions.d/ujust.fish"

install -Dm0644 "$ASSETS/uupd-20-tunaos.conf" \
	"$ROOT/usr/lib/systemd/system/uupd.service.d/20-tunaos.conf"
install -Dm0644 "$ASSETS/tunaos-uupd-notify.service" \
	"$ROOT/usr/lib/systemd/system/tunaos-uupd-notify@.service"
install -Dm0755 "$ASSETS/uupd-notify" \
	"$ROOT/usr/libexec/tunaos/uupd-notify"

printf 'tunaos overrides installed (root %s)\n' "$ROOT"
