#!/usr/bin/env bash

set -xeuo pipefail

printf "::group:: === 15 Shell Configuration ===\n"

source /run/context/build_scripts/lib.sh

# Install zsh
dnf -y install zsh

# Set zsh as the default shell for new users via useradd defaults
# This affects the `useradd` command behavior
if [ -f /etc/default/useradd ]; then
    sed -i 's|^SHELL=.*|SHELL=/usr/bin/zsh|' /etc/default/useradd
else
    # Create the file if it doesn't exist
    mkdir -p /etc/default
    cat > /etc/default/useradd <<'EOF'
# Default values for useradd(8)
GROUP=100
HOME=/home
INACTIVE=-1
EXPIRE=
SHELL=/usr/bin/zsh
SKEL=/etc/skel
CREATE_MAIL_SPOOL=no
EOF
fi

# Note: We do NOT modify /etc/passwd directly in the image
# - Root stays as bash for safety and compatibility
# - Existing users keep their current shell
# - Only NEW users created after this build will get zsh automatically

printf "::endgroup::\n"
