#!/usr/bin/env bash
# scripts/verify-image-packages.sh
# Verifies that all expected packages from the desktop manifest are installed on the final container image.
#
# Usage: ./scripts/verify-image-packages.sh <image_ref> <flavor>

set -euo pipefail

if [[ $# -lt 2 ]]; then
	echo "Usage: $0 <image_ref> <flavor>" >&2
	exit 1
fi

IMAGE="$1"
FLAVOR="$2"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="${REPO_ROOT}/manifests/desktops/${FLAVOR}.yaml"

if [[ ! -f "$MANIFEST" ]]; then
	echo "Error: Manifest not found for flavor '${FLAVOR}' at ${MANIFEST}" >&2
	exit 1
fi

echo "Verifying package presence in image '${IMAGE}' for flavor '${FLAVOR}'..."

# 1) Detect OS type inside the container
OS_ID=$(podman run --rm --entrypoint sh "$IMAGE" -c '
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "$ID"
  else
    echo "unknown"
  fi
' 2>/dev/null || echo "unknown")

OS_ID=$(echo "$OS_ID" | tr -d '\r\n')
echo "Detected OS inside image: ${OS_ID}"

# 2) Extract package list based on OS type
PACKAGES=()
case "${OS_ID}" in
almalinux | rocky | rhel | centos)
	# Read el10 packages list from manifest
	if yq eval '.packages.el10.packages' "$MANIFEST" &>/dev/null; then
		while IFS= read -r pkg; do
			[[ -n "$pkg" && "$pkg" != "null" ]] && PACKAGES+=("$pkg")
		done < <(yq eval '.packages.el10.packages[]' "$MANIFEST" 2>/dev/null || true)
	fi
	# Also get generic packages if any
	while IFS= read -r pkg; do
		[[ -n "$pkg" && "$pkg" != "null" ]] && PACKAGES+=("$pkg")
	done < <(yq eval '.packages.el10[]' "$MANIFEST" 2>/dev/null || true)
	;;
fedora)
	# Read fedora packages list from manifest
	if yq eval '.packages.fedora.packages' "$MANIFEST" &>/dev/null; then
		while IFS= read -r pkg; do
			[[ -n "$pkg" && "$pkg" != "null" ]] && PACKAGES+=("$pkg")
		done < <(yq eval '.packages.fedora.packages[]' "$MANIFEST" 2>/dev/null || true)
	fi
	while IFS= read -r pkg; do
		[[ -n "$pkg" && "$pkg" != "null" ]] && PACKAGES+=("$pkg")
	done < <(yq eval '.packages.fedora[]' "$MANIFEST" 2>/dev/null || true)
	;;
ubuntu | debian)
	# Read apt packages list from manifest
	while IFS= read -r pkg; do
		[[ -n "$pkg" && "$pkg" != "null" ]] && PACKAGES+=("$pkg")
	done < <(yq eval '.packages.apt[]' "$MANIFEST" 2>/dev/null || true)
	;;
gentoo)
	# Read emerge packages list from manifest
	while IFS= read -r pkg; do
		[[ -n "$pkg" && "$pkg" != "null" ]] && PACKAGES+=("$pkg")
	done < <(yq eval '.packages.emerge[]' "$MANIFEST" 2>/dev/null || true)
	;;
*)
	echo "Warning: Unsupported OS ID '${OS_ID}', trying to read all package lists" >&2
	# Fallback to read any lists found
	while IFS= read -r pkg; do
		[[ -n "$pkg" && "$pkg" != "null" ]] && PACKAGES+=("$pkg")
	done < <(yq eval '.. | select(tag == "!!seq")[]' "$MANIFEST" 2>/dev/null || true)
	;;
esac

if [[ ${#PACKAGES[@]} -eq 0 ]]; then
	echo "No packages defined in manifest for OS '${OS_ID}' / flavor '${FLAVOR}'."
	exit 0
fi

echo "Checking ${#PACKAGES[@]} packages..."

FAILED=0
for pkg in "${PACKAGES[@]}"; do
	# Ignore wildcards or groups
	if [[ "$pkg" == "@"* ]]; then
		continue
	fi

	case "${OS_ID}" in
	almalinux | rocky | rhel | centos | fedora)
		if ! podman run --rm --entrypoint rpm "$IMAGE" -q "$pkg" &>/dev/null; then
			echo "❌ Missing package: ${pkg}"
			FAILED=1
		else
			echo "✓ ${pkg}"
		fi
		;;
	ubuntu | debian)
		if ! podman run --rm --entrypoint dpkg-query "$IMAGE" -W -f='${Status}' "$pkg" 2>/dev/null | grep -q "ok installed"; then
			echo "❌ Missing package: ${pkg}"
			FAILED=1
		else
			echo "✓ ${pkg}"
		fi
		;;
	gentoo)
		# Check if package is installed in portage db /var/db/pkg/category/name-*
		# If package has no category, check under all categories
		CHECK_CMD=""
		if [[ "$pkg" == *"/"* ]]; then
			CHECK_CMD="[ -d /var/db/pkg/${pkg}-* ] || ls -d /var/db/pkg/${pkg}-[0-9]* &>/dev/null"
		else
			CHECK_CMD="ls -d /var/db/pkg/*/${pkg}-[0-9]* &>/dev/null"
		fi

		if ! podman run --rm --entrypoint sh "$IMAGE" -c "${CHECK_CMD}" &>/dev/null; then
			echo "❌ Missing package: ${pkg}"
			FAILED=1
		else
			echo "✓ ${pkg}"
		fi
		;;
	*)
		# Generic fallback: try rpm, then dpkg
		if ! podman run --rm --entrypoint sh "$IMAGE" -c "rpm -q ${pkg} &>/dev/null || dpkg -s ${pkg} &>/dev/null" &>/dev/null; then
			echo "❌ Missing package: ${pkg}"
			FAILED=1
		else
			echo "✓ ${pkg}"
		fi
		;;
	esac
done

# 3) Verify CLI commands are present and runnable
echo "Verifying CLI commands..."
CLI_COMMANDS=(just glow gum tailscale skopeo git)
for cmd in "${CLI_COMMANDS[@]}"; do
	if ! podman run --rm --entrypoint sh "$IMAGE" -c "command -v ${cmd} &>/dev/null" &>/dev/null; then
		echo "❌ Missing CLI command: ${cmd}"
		FAILED=1
	else
		echo "✓ CLI command: ${cmd}"
	fi
done

# 4) Verify systemd service unit files are present
echo "Verifying systemd service unit files..."
SYSTEMD_SERVICES=(tailscaled.service systemd-resolved.service)

# Add flavor-specific display manager service
case "${FLAVOR}" in
gnome) SYSTEMD_SERVICES+=(gdm.service) ;;
kde) SYSTEMD_SERVICES+=(sddm.service) ;;
niri | cosmic) SYSTEMD_SERVICES+=(greetd.service) ;;
esac

for svc in "${SYSTEMD_SERVICES[@]}"; do
	# Check in typical systemd system directories: /usr/lib/systemd/system/ or /lib/systemd/system/
	CHECK_SVC_CMD="[ -f /usr/lib/systemd/system/${svc} ] || [ -f /lib/systemd/system/${svc} ]"
	if ! podman run --rm --entrypoint sh "$IMAGE" -c "${CHECK_SVC_CMD}" &>/dev/null; then
		echo "❌ Missing systemd service file: ${svc}"
		FAILED=1
	else
		echo "✓ systemd service file: ${svc}"
	fi
done

if [[ $FAILED -eq 1 ]]; then
	echo "Error: Verification failed. Some packages, CLI commands, or service files are missing." >&2
	exit 1
fi

echo "Success: All expected packages, CLI commands, and service files are present!"
exit 0
