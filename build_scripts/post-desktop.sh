#!/usr/bin/env bash
# post-desktop.sh — Common post-DE finalization for all desktop variant stages.
# Runs after the DE-specific build script. Adds glib2 version lock and makes
# /opt writeable via symlink so chunkah can rechunk the stage.
set -euo pipefail
dnf versionlock add glib2
rm -rf /opt && ln -s /var/opt /opt
