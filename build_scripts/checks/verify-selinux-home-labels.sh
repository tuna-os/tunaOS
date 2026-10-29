#!/usr/bin/env bash
# Build gate (tunaOS#4047): fail when a home directory would be labelled
# default_t. sshd cannot read ~/.ssh/authorized_keys and GNOME session
# processes cannot read ~/.local/share under that label, and restorecon cannot
# repair it because the policy itself resolves the path to default_t.
#
# Checks both /home and /var/home (an ostree system reaches the same file by
# either name) against the generated file_contexts.homedirs after libselinux's
# alias rewriting, and against matchpathcon when run on a live root.
set -euo pipefail
# shellcheck source=build_scripts/lib/selinux-home-labels.sh
source "$(dirname "${BASH_SOURCE[0]}")/../lib/selinux-home-labels.sh"
selhome_check
