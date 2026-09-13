#!/usr/bin/env bash
# t2.sh — Fedora T2 Mac hardware overlay for x86_64 bootc images.
#
# The T2 Linux project maintains the kernel and userspace packages in its COPR.
# Broadcom firmware is intentionally absent: Apple does not permit redistribution.
# Bootsahi Legacy transfers a locally extracted payload during installation.
set -xeuo pipefail

if [ "$(uname -m)" != "x86_64" ]; then
	echo "ERROR: the T2 overlay only applies to x86_64 builds" >&2
	exit 1
fi

. /etc/os-release
if [ "${ID}" != "fedora" ]; then
	echo "ERROR: the initial T2 profile is supported only on Fedora (bonito)" >&2
	exit 1
fi

dnf -y copr enable sharpenedblade/t2linux
_T2_REPO="copr:copr.fedorainfracloud.org:sharpenedblade:t2linux"

# The COPR kernel is required for the T2 bridge/keyboard/trackpad/audio stack,
# and a Fedora kernel must never silently win. Every build of this flavor has
# died here, on both shapes of the transaction:
#
#   Failed to resolve the transaction:
#   No match for argument 'kernel' in repositories 'copr:...:sharpenedblade:t2linux'
#
# That message names the wrong culprit, and it cost one wrong fix. It is not a
# repo that lacks the package and it is not a flag whose scope surprised us:
# the enabled chroot is fedora-44, and its metadata has carried the whole set
# (kernel, -core, -modules, -modules-core at 7.1.9-200.t2.fc44) since
# 2026-08-23, three weeks before run 34756027748 failed to find it. dnf even
# downloaded that metadata in the same step that then matched nothing.
#
# The base image filters the packages out. `quay.io/fedora/fedora-bootc` ships
# repo-level `exclude=kernel*` in its own .repo files, and a repo-level exclude
# applies to the CANDIDATE SET of every repo — so kernel is invisible to the
# solver no matter which repo it is pinned to, and dnf reports that absence in
# the vocabulary of the pin. The nvidia overlay hit exactly this and documented
# it (overrides/nvidia/10-kernel-swap.sh, "filtered out by exclude filtering",
# bonito 31454139305, every *-nvidia job); it also records that clearing only
# the [main] exclude via `--setopt=exclude=` is NOT enough, because that leaves
# the per-repo ones standing. So clear both, per repo and glob-wide.
#
# `dnf remove` above was never affected: removal reads the rpmdb, which no
# exclude filter touches. That asymmetry is why the failure looked like a
# missing package rather than a hidden one.
#
# The pin stays, and so does the assertion after it. The assertion is the real
# guarantee here — twice now the flags have not meant what they appeared to.
#
# The two probes print the evidence rather than assuming it: if the exclude
# theory is ever wrong, the log says which filters were actually in force and
# what the pinned repo actually offered, instead of only "No match".
echo "== kernel packages before the swap =="
rpm -qa 'kernel*' | sort
echo "== exclude filters in force =="
grep -rHnE '^[[:space:]]*(exclude|excludepkgs)[[:space:]]*=' \
	/etc/dnf/dnf.conf /etc/yum.repos.d/ || echo "(none)"

dnf -y remove --noautoremove kernel kernel-core kernel-modules \
	kernel-modules-core || true

echo "== what the pinned repo offers =="
dnf -y repoquery --repo="${_T2_REPO}" \
	--setopt='excludepkgs=' --setopt='*.excludepkgs=' \
	--setopt='exclude=' --setopt='*.exclude=' \
	--qf '%{name}-%{evr}\n' 'kernel*' || true

dnf -y install --allowerasing \
	--from-repo="${_T2_REPO}" \
	--setopt='excludepkgs=' --setopt='*.excludepkgs=' \
	--setopt='exclude=' --setopt='*.exclude=' \
	kernel kernel-core kernel-modules kernel-modules-core

# The guarantee, asserted rather than assumed. `.t2.` is the COPR's dist tag.
_t2_kver="$(rpm -q kernel --qf '%{VERSION}-%{RELEASE}\n' | tail -1)"
case "${_t2_kver}" in
*.t2.*) echo "t2.sh: kernel ${_t2_kver} is the t2linux build" ;;
*)
	echo "ERROR: installed kernel is not the t2linux build: ${_t2_kver}" >&2
	exit 1
	;;
esac
dnf -y install t2linux-release iwd

install -d /etc/NetworkManager/conf.d
cat >/etc/NetworkManager/conf.d/10-t2-wifi.conf <<'EOF'
[device]
wifi.backend=iwd
EOF

# Do not install broadcom-wl: T2 Macs use the in-kernel brcmfmac driver plus
# firmware extracted locally by Bootsahi Legacy.
if rpm -q broadcom-wl >/dev/null 2>&1; then
	echo "ERROR: broadcom-wl must not be present in a T2 image" >&2
	exit 1
fi

# Keep the image publishable only when the T2 metapackage and the in-tree Wi-Fi
# driver are actually present in the selected kernel.
rpm -q t2linux-release
KVER=$(find /usr/lib/modules -maxdepth 1 -mindepth 1 -type d -printf '%T@ %f\n' | sort -rn | head -1 | cut -d' ' -f2-)
[ -n "${KVER}" ] && [ -d "/usr/lib/modules/${KVER}" ] || {
	echo "ERROR: no T2 kernel module directory found" >&2
	exit 1
}
find "/usr/lib/modules/${KVER}" -type f -name 'brcmfmac.ko*' -print -quit | grep -q .
