#!/bin/bash

# Check if an argument is provided
if [ -z "$1" ]; then
	echo "Usage: $0 <image_uri>"
	echo "Example: $0 ghcr.io/tuna-os/yellowfin:latest"
	exit 1
fi

IMAGE_URI="$1"
TOML_FILE="iso.toml"
ROOTFS="xfs"

# Create the TOML file with dynamic content
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

echo "Generated $TOML_FILE with content:"
cat "$TOML_FILE"
echo ""

# Pull the image
echo "Pulling image: $IMAGE_URI"
sudo podman pull "$IMAGE_URI"

# Run the bootc-image-builder command
echo "Running bootc-image-builder..."
sudo podman run --rm -it --privileged \
	-v "$(pwd)":/output \
	-v /var/lib/containers/storage:/var/lib/containers/storage \
	-v "$(pwd)/$TOML_FILE":/config.toml \
	quay.io/centos-bootc/bootc-image-builder:latest \
	build --type iso --rootfs $ROOTFS --use-librepo=False \
	"$IMAGE_URI"

echo "Script finished."
