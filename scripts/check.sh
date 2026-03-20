#!/usr/bin/env bash
# Check syntax of shell scripts, YAML, JSON, and workflow files.
# Installs required tools via brew if missing.
#
# Usage: scripts/check.sh [--install-deps-only]

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

INSTALL_ONLY="0"
[[ "${1:-}" == "--install-deps-only" ]] && INSTALL_ONLY="1"

if ! command -v shellcheck &>/dev/null; then brew install shellcheck; fi
if ! command -v shfmt &>/dev/null; then brew install shfmt; fi
if ! command -v yamllint &>/dev/null; then brew install yamllint; fi
if ! command -v jq &>/dev/null; then brew install jq; fi
if ! command -v actionlint &>/dev/null; then brew install actionlint; fi

[[ "$INSTALL_ONLY" == "1" ]] && exit 0

echo "Checking syntax of shell scripts..."
/usr/bin/find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -iname "*.sh" -type f -exec shellcheck --exclude=SC1091 "{}" ";"
find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.yaml" | while read -r file; do
	yamllint -c ./.yamllint.yml "$file" || { exit 1; }
done
find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.yml" | while read -r file; do
	yamllint "$file" || { exit 1; }
done
find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.json" | while read -r file; do
	jq . "$file" >/dev/null || { exit 1; }
done
find . -not -path './system_files/usr/share/gnome-shell/extensions/*' -not -path './packages-repo/*' -type f -name "*.just" | while read -r file; do
	just --unstable --fmt --check -f "$file"
done
if command -v actionlint &>/dev/null; then
	actionlint -ignore "permission \"id-token\" is unknown" \
		-ignore "SC2086" -ignore "SC2129" -ignore "SC2001" \
		-ignore "SC2034" -ignore "SC2015" -ignore "SC1001" \
		-ignore "SC2295" \
		-ignore "save-always" \
		-ignore "cannot be filtered" \
		.github/workflows/*.yml .github/workflows/*.yaml || { exit 1; }
fi
just --unstable --fmt --check -f Justfile
