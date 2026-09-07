#!/usr/bin/env bash
# Install bootc from the bootc-shindig/bootc-deb apt repo.
#
# bootc is not packaged in the Ubuntu archive (0 entries across all series), so
# we pull a prebuilt .deb that tracks upstream bootc releases. The package
# Depends on dracut, ostree, libostree-dev — apt resolves those automatically.
#
# Mirrors bootc-shindig/ubuntu-bootc-remix. Run while apt is still intact.
set -xeuo pipefail

readonly BOOTC_DEB_COMMIT="252993e588048235644db12a8d4bd837c7ca6a7c"
readonly BOOTC_DEB_KEY_SHA256="79404310cea5189237644cf2d114b59803455690221414c7b45358c234969435"
key_file="$(mktemp)"
trap 'rm -f "$key_file"' EXIT

curl -fsSL \
	"https://raw.githubusercontent.com/bootc-shindig/bootc-deb/${BOOTC_DEB_COMMIT}/bootc-deb.asc" \
	-o "$key_file"
echo "${BOOTC_DEB_KEY_SHA256}  ${key_file}" | sha256sum --check --strict
gpg --dearmor -o /usr/share/keyrings/bootc-deb.gpg "$key_file"

echo "deb [signed-by=/usr/share/keyrings/bootc-deb.gpg] https://bootc-shindig.github.io/bootc-deb/debian stable main" \
	>/etc/apt/sources.list.d/bootc-deb.list

apt-get update -y
apt-get install -y bootc
