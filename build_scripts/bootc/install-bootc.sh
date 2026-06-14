#!/usr/bin/env bash
# Install bootc from the bootc-shindig/bootc-deb apt repo.
#
# bootc is not packaged in the Ubuntu archive (0 entries across all series), so
# we pull a prebuilt .deb that tracks upstream bootc releases. The package
# Depends on dracut, ostree, libostree-dev — apt resolves those automatically.
#
# Mirrors bootc-shindig/ubuntu-bootc-remix. Run while apt is still intact.
set -xeuo pipefail

curl -fsSL https://raw.githubusercontent.com/bootc-shindig/bootc-deb/refs/heads/main/bootc-deb.asc \
    | gpg --dearmor -o /usr/share/keyrings/bootc-deb.gpg

echo "deb [signed-by=/usr/share/keyrings/bootc-deb.gpg] https://bootc-shindig.github.io/bootc-deb/debian stable main" \
    > /etc/apt/sources.list.d/bootc-deb.list

apt-get update -y
apt-get install -y bootc
