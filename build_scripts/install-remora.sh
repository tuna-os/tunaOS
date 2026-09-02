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
# The version is pinned for reproducible image builds, and the binary is
# checked against a pinned sha256 so a re-published release cannot change what
# lands in the image without someone noticing.
#
# Renovate bumps REMORA_VERSION but CANNOT bump the checksums below: the
# custom manager for build_scripts/*.sh captures the version line only. That
# used to be the reason this file carried no `# renovate:` marker at all --
# with the marker, a bump would leave the checksums pointing at the previous
# release and every build would fail the sha256 check.
#
# scripts/check-download-checksums.py now closes that gap: it verifies these
# checksums against the pinned release's published checksums.txt, and runs on
# every pull request that touches this file. A Renovate bump with stale
# checksums fails that check and cannot auto-merge; `--fix` rewrites them.
# So the marker is safe to have, and the pin no longer silently rots.

set -xeuo pipefail

# renovate: datasource=github-releases depName=tuna-os/remora
REMORA_VERSION="v0.4.1"
REMORA_ARCH="$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')"
case "${REMORA_ARCH}" in
amd64) REMORA_SHA256="790e80b5901c8f146047c7fd2708af4a912303a6ed48b289654700945cee98de" ;;
arm64) REMORA_SHA256="9613d37236d6ef78c46f49d4458c1a6c88e9299f6070c8d02eeb4870a209898a" ;;
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
# and release drift before an image can be published. Remora still has no
# version subcommand as of v0.4.0, so its pinned release checksum proves the
# version while this smoke test proves the installed binary can execute on the
# target arch.
remora --help | grep -Fq 'Usage: remora <command> [args]'
install -d /usr/share/tunaos/experience-contracts
printf 'version=%s\nvalidated_at_build=true\n' "${REMORA_VERSION}" \
	>/usr/share/tunaos/experience-contracts/remora
