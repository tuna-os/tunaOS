#!/bin/bash

set -xeuo pipefail

# Function to handle errors and exit
handle_error() {
    local exit_code=$?
    local cmd="$BASH_COMMAND"
    echo "ERROR: Command '$cmd' failed with exit code $exit_code." >&2
    exit "$exit_code"
}
trap 'handle_error' ERR

# Install required packages
echo "Installing DNF packages..."

# VSCode on the base image!
echo "Adding VSCode repo and installing code..."
dnf config-manager --add-repo "https://packages.microsoft.com/yumrepos/vscode" || echo "VSCode repo already added or failed to add."
dnf config-manager --set-disabled packages.microsoft.com_yumrepos_vscode || true # Disable if it's already enabled
dnf -y --enablerepo packages.microsoft.com_yumrepos_vscode --nogpgcheck install code

# Docker setup
echo "Adding Docker repo and installing Docker components..."
dnf config-manager --add-repo "https://download.docker.com/linux/centos/docker-ce.repo" || echo "Docker repo already added or failed to add."
dnf config-manager --set-disabled docker-ce-stable || true # Disable if it's already enabled
dnf -y --enablerepo docker-ce-stable install \
    docker-ce \
    docker-ce-cli \
    containerd.io \
    docker-buildx-plugin \
    docker-compose-plugin

# Libvirt setup
echo "Installing Libvirt related packages..."
dnf -y --enablerepo copr:copr.fedorainfracloud.org:ublue-os:packages install \
    libvirt \
    libvirt-daemon-kvm \
    libvirt-nss \
    cockpit-machines \
    virt-install \
    ublue-os-libvirt-workarounds

