#!/usr/bin/env bash
# Generate a QCOW2 disk image using bootc install to-disk (via loopback in a privileged container).
#
# Usage: scripts/build-qcow2.sh <variant> [flavor] [repo] [tag]
#   variant  - image variant name, or a full image ref (if it contains ':' or '/')
#   flavor   - gnome | kde | etc. (default: gnome)
#   repo     - local | ghcr (default: local)
#   tag      - image tag (default: <flavor>)

set -euo pipefail
# shellcheck source=lib/backend.sh
. "$(dirname "${BASH_SOURCE[0]}")/lib/backend.sh"
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

# For local images, sync from user podman to sudo podman so containers-storage
# can find it inside the privileged container.
# For remote images, use docker:// as the source so bootc pulls directly from
# the registry inside the container — this avoids the fd3 additional-store issue
# where containers-storage can find the image manifest but fails to copy the
# layers when creating the ostree deployment.
AUTH_VOL_ARGS=()
if [[ "${IMG_REF}" == localhost/* ]]; then
	echo "==> Syncing $IMG_REF from user podman into root podman storage..."
	podman save "$IMG_REF" | sudo podman load
	SOURCE_IMGREF="containers-storage:${IMG_REF}"
else
	SOURCE_IMGREF="docker://${IMG_REF}"
	# Mount the podman auth file so bootc can authenticate with private registries.
	for auth_path in /run/containers/0/auth.json /root/.config/containers/auth.json; do
		if [[ -f "$auth_path" ]]; then
			AUTH_VOL_ARGS=("-v" "${auth_path}:/run/containers/0/auth.json:ro")
			echo "==> Mounting registry auth from ${auth_path}"
			break
		fi
	done
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
# --experimental-unified-storage was removed in newer bootc (it became the default).
# Probe the image's bootc to see if the flag is still accepted.
UNIFIED_STORAGE_ARGS=()
if sudo podman run --rm "${AUTH_VOL_ARGS[@]}" --security-opt label=disable \
	"$IMG_REF" bootc install to-disk --help 2>&1 | grep -q 'experimental-unified-storage'; then
	UNIFIED_STORAGE_ARGS=(--experimental-unified-storage)
fi

# Storage backend, probed from IMAGE CONTENT — never from the variant name.
# This was a hardcoded allowlist of five prefixes that had already gone stale:
# gurnard (#943) was missing and would have failed its first build with
# "bootupd is required for ostree-based installs". See probe_image_backend.
COMPOSEFS_ARGS=()
if ! PROBE=$(probe_image_backend "$IMG_REF" sudo podman); then
	echo "ERROR: could not probe $IMG_REF for its bootc backend" >&2
	exit 1
fi
echo "==> image probe: $(echo "$PROBE" | tr '\n' ' ')"
grep -q '^BACKEND=composefs-native$' <<<"$PROBE" && COMPOSEFS_ARGS=(--composefs-backend)
# SEALED is independent of the backend: a composefs-sealed rootfs needs
# fs-verity, which XFS lacks. On the xfs default from 00-tunaos.toml the
# initramfs fails initrd-switch-root and drops to a dracut emergency shell.
grep -q '^SEALED=1$' <<<"$PROBE" && COMPOSEFS_ARGS+=(--filesystem ext4)

sudo podman run \
	--rm \
	--privileged \
	--pid=host \
	-v /dev:/dev \
	-v /var/lib/containers:/var/lib/containers \
	-v "${RAW_ABS}:/disk.img" \
	-v "${INSTALL_TOML}:/usr/lib/bootc/install/00-tunaos.toml:ro" \
	"${SSH_VOL_ARGS[@]}" \
	"${AUTH_VOL_ARGS[@]}" \
	--security-opt label=disable \
	"$IMG_REF" \
	bootc install to-disk \
	--via-loopback \
	--generic-image \
	"${UNIFIED_STORAGE_ARGS[@]}" \
	"${COMPOSEFS_ARGS[@]}" \
	"${SSH_KEY_ARGS[@]}" \
	--source-imgref "${SOURCE_IMGREF}" \
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
