#!/bin/bash
# remora — local layering CLI (github.com/tuna-os/remora).
#
# Split out of 26-packages-post.sh so a base that cannot run that whole script
# can still get remora. Containerfile.opensuse is exactly that case: it runs
# none of the numbered build_scripts, because 26-packages-post.sh ends by
# rebuilding the initramfs with Fedora kernel-naming assumptions
# (`rpm -qa | grep -P 'kernel-...'` does not yield openSUSE's kernel-default)
# and would clobber the composefs/bootc initramfs that Containerfile.opensuse
# builds and then verifies. Sailfin therefore shipped with no remora at all,
# and every sailfin Gate failed on reason=remora_not_found — a desktop that
# booted fine was reported as broken.
#
# The binary is static Go and works on every base (dnf/zypper/pacman/apt),
# so there is nothing distro-specific to guard here.
#
# The version is pinned for reproducible image builds. Deliberately NO
# `# renovate:` marker: the custom manager for build_scripts/*.sh would bump
# REMORA_VERSION without touching the checksums below, and the sha256 check
# would then fail every build.

set -xeuo pipefail

REMORA_VERSION="v0.2.0"
REMORA_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
case "${REMORA_ARCH}" in
amd64) REMORA_SHA256="39c774ab76dbdbf95ff11a32e5083e24fa01f88804161c24998c0a21e368175a" ;;
arm64) REMORA_SHA256="3454ac72a376c974f433b5c8db14470d908dd43fc3ddc27e19e47e70c5ab2c3b" ;;
*)
	echo "ERROR: unsupported Remora architecture: ${REMORA_ARCH}" >&2
	exit 1
	;;
esac

REMORA_DOWNLOADS_DIR="${DOWNLOADS_DIR:-/var/tmp/tunaos-downloads}"
mkdir -p "$REMORA_DOWNLOADS_DIR"

curl --retry 3 --fail -L \
	"https://github.com/tuna-os/remora/releases/download/${REMORA_VERSION}/remora-linux-${REMORA_ARCH}" \
	-o "$REMORA_DOWNLOADS_DIR/remora"
printf '%s  %s\n' "${REMORA_SHA256}" "$REMORA_DOWNLOADS_DIR/remora" | sha256sum --check --strict
install -Dm0755 "$REMORA_DOWNLOADS_DIR/remora" /usr/bin/remora
rm "$REMORA_DOWNLOADS_DIR/remora"

# Treat the downloaded binary as an image contract, not merely a successful
# HTTP transfer. This catches wrong-architecture assets, truncated releases,
# and release drift before an image can be published. Remora v0.2.0 has no
# version subcommand, so its pinned release checksum proves the version while
# this smoke test proves the installed binary can execute on the target arch.
remora --help | grep -Fq 'Usage: remora <command> [args]'
install -d /usr/share/tunaos/experience-contracts
printf 'version=%s\nvalidated_at_build=true\n' "${REMORA_VERSION}" \
	>/usr/share/tunaos/experience-contracts/remora
