#!/usr/bin/env bash
# Generate a QCOW2 disk image using bootc install to-disk (via loopback in a privileged container).
#
# Usage: scripts/build-qcow2.sh <variant> [flavor] [repo] [tag]
#   variant  - image variant name, or a full image ref (if it contains ':' or '/')
#   flavor   - gnome | kde | etc. (default: gnome)
#   repo     - local | ghcr (default: local)
#   tag      - image tag (default: <flavor>)

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VARIANT="${1:-}"
FLAVOR="${2:-gnome}"
REPO="${3:-local}"
TAG="${4:-}"

if [[ -z "$VARIANT" ]]; then
	echo "Usage: build-qcow2.sh <variant> [flavor] [repo] [tag]" >&2
	exit 1
fi

IMG_REF=""
OUTPUT_NAME=""
if [[ "$VARIANT" == *":"* || "$VARIANT" == *"/"* ]]; then
	IMG_REF="$VARIANT"
	OUTPUT_NAME=$(echo "$VARIANT" | awk -F'/' '{print $NF}' | awk -F':' '{print $1}')
else
	if [ "$REPO" = "local" ]; then
		just build "$VARIANT" "$FLAVOR"
	fi
	[[ -z "$TAG" ]] && TAG="$FLAVOR"
	if [ "$REPO" = "ghcr" ]; then
		IMG_REF="ghcr.io/${repo_organization:-tuna-os}/${VARIANT}:${TAG}"
	elif [ "$REPO" = "local" ]; then
		IMG_REF="localhost/${VARIANT}:${TAG}"
	else
		exit 1
	fi
	OUTPUT_NAME="$VARIANT"
fi

OUTPUT="${OUTPUT_NAME}.qcow2"
RAW_FILE="${OUTPUT_NAME}.raw"
echo "==> Generating $OUTPUT from $IMG_REF using bootc install to-disk..."

# Ensure root podman storage has the LATEST version of this image BEFORE starting
# the privileged container. bootc reads the image via the container's fd3
# additional-store (a snapshot of the host /var/lib/containers taken at startup),
# so the image must be present BEFORE the container is launched.
if [[ "${IMG_REF}" == localhost/* ]]; then
	echo "==> Syncing $IMG_REF from user podman into root podman storage..."
	podman save "$IMG_REF" | sudo podman load
else
	echo "==> Pulling $IMG_REF into root podman storage..."
	sudo podman pull "${IMG_REF}"
fi

# Create a sparse raw disk file (40 GiB)
rm -f "$RAW_FILE"
truncate -s 40G "$RAW_FILE"
RAW_ABS="$(realpath "$RAW_FILE")"

INSTALL_TOML="$(pwd)/system_files/usr/lib/bootc/install/00-tunaos.toml"

# Collect the local user's SSH public keys to inject into root's authorized_keys
SSH_PUBKEYS_FILE=""
TMPKEYS=$(mktemp)
for pub in ~/.ssh/id_ed25519.pub ~/.ssh/id_rsa.pub ~/.ssh/id_ecdsa.pub ~/.ssh/id_dsa.pub; do
	[[ -f "$pub" ]] && cat "$pub" >>"$TMPKEYS"
done
# Also pick up any additional id_*.pub files not already included
while IFS= read -r pub; do
	cat "$pub" >>"$TMPKEYS"
done < <(find ~/.ssh -maxdepth 1 -name 'id_*.pub' 2>/dev/null | grep -vE 'id_ed25519|id_rsa|id_ecdsa|id_dsa' || true)
# Also include the Lima VM key so Lima-booted VMs are accessible via SSH
[[ -f ~/.lima/_config/user.pub ]] && cat ~/.lima/_config/user.pub >>"$TMPKEYS"
if [[ -s "$TMPKEYS" ]]; then
	SSH_PUBKEYS_FILE="$TMPKEYS"
	echo "==> Injecting SSH authorized keys for root from ~/.ssh/id_*.pub..."
else
	rm -f "$TMPKEYS"
	echo "==> No local SSH public keys found; skipping root SSH key injection."
fi

SSH_VOL_ARGS=()
SSH_KEY_ARGS=()
if [[ -n "$SSH_PUBKEYS_FILE" ]]; then
	SSH_VOL_ARGS=("-v" "${SSH_PUBKEYS_FILE}:/run/root-authorized-keys:ro")
	SSH_KEY_ARGS=("--root-ssh-authorized-keys" "/run/root-authorized-keys")
fi

echo "==> Running bootc install to-disk (this takes a few minutes)..."
sudo podman run \
	--rm \
	--privileged \
	--pid=host \
	-v /dev:/dev \
	-v /var/lib/containers:/var/lib/containers \
	-v "${RAW_ABS}:/disk.img" \
	-v "${INSTALL_TOML}:/usr/lib/bootc/install/00-tunaos.toml:ro" \
	"${SSH_VOL_ARGS[@]}" \
	--security-opt label=disable \
	"$IMG_REF" \
	bootc install to-disk \
	--via-loopback \
	--generic-image \
	--experimental-unified-storage \
	"${SSH_KEY_ARGS[@]}" \
	--source-imgref "containers-storage:${IMG_REF}" \
	/disk.img

[[ -n "$SSH_PUBKEYS_FILE" ]] && rm -f "$SSH_PUBKEYS_FILE"

# Convert raw → qcow2 for Lima/QEMU consumption
echo "==> Converting raw → qcow2..."
if ! command -v qemu-img &>/dev/null; then
	echo "Error: 'qemu-img' not found. Install qemu-img (e.g. sudo dnf install qemu-img)"
	exit 1
fi
qemu-img convert -f raw -O qcow2 -p "$RAW_FILE" "$OUTPUT"
rm -f "$RAW_FILE"
sudo chown "${SUDO_UID:-$(id -u)}:${SUDO_GID:-$(id -g)}" "$OUTPUT" 2>/dev/null || chown "$(id -u):$(id -g)" "$OUTPUT" 2>/dev/null || true
echo "✓ Created $OUTPUT"
