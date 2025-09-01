#!/bin/bash
# This script is merely a wrapper for bootc-image-builder

# Check if running with root privileges
if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit
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
# TODO: make this setable
ROOTFS="xfs"




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
	"org.fedoraproject.Anaconda.Modules.Storage"
]
disable = [
	"org.fedoraproject.Anaconda.Modules.Network",
	"org.fedoraproject.Anaconda.Modules.Security",
	"org.fedoraproject.Anaconda.Modules.Services",
	"org.fedoraproject.Anaconda.Modules.Users",
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

[[customizations.filesystem]]
mountpoint = "/"
minsize = "20 GiB"
EOF
fi

echo "Generated $TOML_FILE with content:"
cat "$TMPDIR/$TOML_FILE"
echo ""

echo "Pulling image: $IMAGE_URI"
sudo podman pull "$IMAGE_URI"


ARGS="--type $TYPE "
ARGS+="--rootfs $ROOTFS "
ARGS+="--use-librepo=False"


# Run the bootc-image-builder command
echo "Running bootc-image-builder..."
podman run --rm -it --privileged \
	-v "$TMPDIR/output":/output:z \
	-v /var/lib/containers/storage:/var/lib/containers/storage \
	-v "$TMPDIR/$TOML_FILE":/config.toml \
	quay.io/centos-bootc/bootc-image-builder:latest \
	build "$ARGS" \
	"$IMAGE_URI"

IMAGE_NAME=$(echo "$IMAGE_URI" | awk -F'/' '{print $NF}' | awk -F':' '{print $1}')

# Find the output artifact based on type
file=$(find "$TMPDIR/output" -type f -name "*.$TYPE")
if [ -f "$file" ]; then
	mv "$file" "./${IMAGE_NAME}.$TYPE"
	chown "$(id -u):$(id -g)" "./${IMAGE_NAME}.$TYPE"
	echo "Image created: ${IMAGE_NAME}.$TYPE"
else
	echo "ERROR: Image was not created."
	exit 1
fi

