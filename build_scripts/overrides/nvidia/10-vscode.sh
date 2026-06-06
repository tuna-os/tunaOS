#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 10 VS Code ===\n"

source /run/context/build_scripts/lib.sh

# Import Microsoft GPG key
rpm --import https://packages.microsoft.com/keys/microsoft.asc

# Add VS Code repository
cat <<EOF >/etc/yum.repos.d/vscode.repo
[code]
name=Visual Studio Code
baseurl=https://packages.microsoft.com/yumrepos/vscode
enabled=1
gpgcheck=1
gpgkey=https://packages.microsoft.com/keys/microsoft.asc
EOF

# Install VS Code
dnf install -y code

printf "::endgroup::\n"
