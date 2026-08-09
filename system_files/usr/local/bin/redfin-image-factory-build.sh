#!/usr/bin/env bash
# system_files/usr/local/bin/redfin-image-factory-build.sh — rebuild local
# Redfin images and apply them to this system, on a schedule
# (tuna-os/tunaos#609).
#
# Adaptation of renner0e/server's bootc-image-factory for TunaOS Redfin
# (RHEL 10, local-build only — the EULA forbids publishing images). Runs the
# TunaOS build for the configured flavors from a local repo checkout, then
# switches the running system to the freshly built image, applies any pending
# updates, and prunes superseded bootc images.
#
# Configure via environment (systemd: /etc/default/redfin-image-factory):
#   TUNAOS_REPO      repo checkout to build from (default: /etc/bootc-image-factory/tunaos)
#   REDFIN_FLAVORS   space-separated flavors to rebuild (default: "gnome kde")
#   RHSM_USER / RHSM_PASSWORD, or RHSM_ORG / RHSM_ACTIVATION_KEY
#                    (passed through to `just build`, see docs/rhel-setup.md)
#
# The unit files bootc-image-factory-build.{service,timer} ship in the image;
# enable the timer only on Redfin systems:
#   sudo systemctl enable --now bootc-image-factory-build.timer
set -euo pipefail

REPO="${TUNAOS_REPO:-/etc/bootc-image-factory/tunaos}"
FLAVORS="${REDFIN_FLAVORS:-gnome kde}"

if [[ ! -d "${REPO}" ]]; then
    echo "redfin-image-factory: repo missing at ${REPO} — clone tunaos/tunaos there first" >&2
    exit 1
fi
if ! command -v just >/dev/null 2>&1; then
    echo "redfin-image-factory: 'just' not found (dnf install just)" >&2
    exit 1
fi

echo "==> redfin image factory: rebuilding [${FLAVORS}] from ${REPO}"
cd "${REPO}"
git pull --ff-only || true

for flavor in ${FLAVORS}; do
    echo "==> just build redfin ${flavor}"
    just build redfin "${flavor}"
done

# Switch to the first flavor's fresh build, then update + prune. The remaining
# flavors stay available in containers-storage for a later `bootc switch`.
first_flavor="${FLAVORS%% *}"
echo "==> bootc switch --transport=containers-storage localhost/redfin:${first_flavor}"
bootc switch --quiet --transport=containers-storage "localhost/redfin:${first_flavor}"
bootc update --quiet
podman image prune --force --filter=label=containers.bootc=1 --filter "until=168h" 2>/dev/null || true

echo "==> redfin image factory: done"
