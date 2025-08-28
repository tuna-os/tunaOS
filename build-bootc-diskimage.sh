#!/bin/bash
# This script is merely a wrapper for bootc-image-builder
# Check if an argument is provided
if [ -z "$2" ]; then
	echo "Usage: $0 <image_type> <image_uri>"
	echo "This can be used to create an iso,ami,gce,qcow2,raw,vhd,vmdkimage."
	echo "Example: $0 iso ghcr.io/tuna-os/yellowfin:latest"
	exit 1
fi

TYPE="$1"
IMAGE_URI="$2"
TOML_FILE="$TYPE.toml"
# TODO: make this setable
ROOTFS="xfs"

if [ "$TYPE" = "iso" ]; then
# TODO: enable user creation for KDE and server images, this is currently only for GNOME
	# Create the TOML file with dynamic content for ISO
	cat <<EOF >"$TOML_FILE"
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

else; then
# TODO: make the username and password setable
cat <<EOF >"$TOML_FILE"
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
cat "$TOML_FILE"
echo ""

# Pull the image
echo "Pulling image: $IMAGE_URI"
sudo podman pull "$IMAGE_URI"

# Run the bootc-image-builder command
echo "Running bootc-image-builder..."
sudo podman run --rm -it --privileged \
	-v "$(pwd)":/output:z \
	-v /var/lib/containers/storage:/var/lib/containers/storage \
	-v "$(pwd)/$TOML_FILE":/config.toml \
	quay.io/centos-bootc/bootc-image-builder:latest \
	build --type iso --rootfs $ROOTFS --use-librepo=False \
	"$IMAGE_URI"

echo "Script finished."
