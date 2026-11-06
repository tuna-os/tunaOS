#!/usr/bin/env bash
# Align the SELinux home aliases with /etc/default/useradd HOME (tunaOS#4047).
# The mechanism, and why the alias is the thing that moves, is documented in
# build_scripts/lib/selinux-home-labels.sh.
#
# Run it after the last package transaction that can replace selinux-policy:
# the policy RPM overwrites file_contexts.subs_dist. Idempotent.
set -euo pipefail
# shellcheck source=build_scripts/lib/selinux-home-labels.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/selinux-home-labels.sh"
selhome_fix
