#!/bin/bash
set -euo pipefail
# This script is merely a wrapper for bootc-image-builder

# Check if running with root privileges
# Check if running with root privileges
if [ "$EUID" -ne 0 ]; then
	echo "Elevating privileges with sudo..."
	exec sudo "$0" "$@"
fi

# Check if an argument is provided
if [ -z "$2" ]; then
	echo "Usage: $0 <image_type> <image_uri>"
	echo "This can be used to create an iso,ami,gce,qcow2,raw,vhd,vmdkimage."
	echo "Example: $0 iso ghcr.io/tuna-os/yellowfin:latest"
	exit 1
fi

# Create tmpdir
TMPDIR=$(mktemp -d)
mkdir -p "$TMPDIR/output"
TYPE="$1"
IMAGE_URI="$2"
TOML_FILE="$TYPE.toml"

if [ "$TYPE" = "iso" ]; then
	# TODO: enable user creation for KDE and server images, this is currently only for GNOME
	cat <<EOF >"$TMPDIR/$TOML_FILE"
[customizations.installer.kickstart]
contents = """
%post
bootc switch --mutate-in-place --transport registry --enforce-container-sigpolicy $IMAGE_URI
%end
"""

[customizations.installer.modules]
enable = [
	"org.fedoraproject.Anaconda.Modules.Storage",
	"org.fedoraproject.Anaconda.Modules.Users"
]
disable = [
	"org.fedoraproject.Anaconda.Modules.Network",
	"org.fedoraproject.Anaconda.Modules.Security",
	"org.fedoraproject.Anaconda.Modules.Services",
	"org.fedoraproject.Anaconda.Modules.Subscription",
	"org.fedoraproject.Anaconda.Modules.Timezone"
]
EOF

else
	# TODO: make the username and password setable
	cat <<EOF >"$TMPDIR/$TOML_FILE"
[[customizations.user]]
name = "centos"
password = "centos"
groups = ["wheel"]
EOF

	# Try to find an SSH key to inject
	SSH_KEY=""
	# If running under sudo, finding the real user's home
	if [ -n "${SUDO_USER:-}" ]; then
		USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
	else
		USER_HOME="$HOME"
	fi

	if [ -f "$USER_HOME/.ssh/id_ed25519.pub" ]; then
		SSH_KEY=$(cat "$USER_HOME/.ssh/id_ed25519.pub")
	elif [ -f "$USER_HOME/.ssh/id_rsa.pub" ]; then
		SSH_KEY=$(cat "$USER_HOME/.ssh/id_rsa.pub")
	fi

	if [ -n "$SSH_KEY" ]; then
		echo "key = \"$SSH_KEY\"" >>"$TMPDIR/$TOML_FILE"
		echo "Injected SSH key for user centos"
	fi

	cat <<EOF >>"$TMPDIR/$TOML_FILE"

[[customizations.filesystem]]
mountpoint = "/"
minsize = "20 GiB"
EOF
fi

echo "Generated $TOML_FILE with content:"
cat "$TMPDIR/$TOML_FILE"
echo ""

echo "Pulling image: $IMAGE_URI"
podman pull "$IMAGE_URI"

# Run the bootc-image-builder command
echo "Running bootc-image-builder..."
podman run --rm -it --privileged --pid=host \
	-v "$TMPDIR/output":/output:z \
	-v /var/lib/containers/storage:/var/lib/containers/storage \
	-v /dev:/dev \
	-v "$TMPDIR/$TOML_FILE":/config.toml \
	quay.io/centos-bootc/bootc-image-builder:latest \
	build --type "$TYPE" \
	"$IMAGE_URI"

IMAGE_NAME=$(echo "$IMAGE_URI" | awk -F'/' '{print $NF}' | awk -F':' '{print $1}')

# Find the output artifact based on type
file=$(find "$TMPDIR/output" -type f -name "*.$TYPE")
if [ -f "$file" ]; then
	mv "$file" "./${IMAGE_NAME}.$TYPE"

	# Determine target UID/GID for ownership check
	# Determine target UID/GID for ownership check
	if [ -n "${SUDO_UID:-}" ]; then
		TARGET_UID="$SUDO_UID"
		TARGET_GID="${SUDO_GID:-0}"
	else
		TARGET_UID="0"
		TARGET_GID="0"
	fi

	chown "${TARGET_UID}:${TARGET_GID}" "./${IMAGE_NAME}.$TYPE"
	echo "Image created: ${IMAGE_NAME}.$TYPE"
else
	echo "ERROR: Image was not created."
	exit 1
fi
