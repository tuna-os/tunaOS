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
# and a Fedora kernel must never silently win. Every attempt to express that
# with `--from-repo` has died the same way, on three different shapes:
#
#   No match for argument 'kernel' in repositories 'copr:...:sharpenedblade:t2linux'
#
# Two diagnoses were wrong before the probes below went in, and both are worth
# naming so nobody re-derives them. It is NOT the flag constraining the remove
# spec (#2494), and it is NOT the base image's exclude filters: run 34760267199
# printed every exclude in force and the answer was
#
#   == exclude filters in force ==
#   (none)
#
# What that run did show, in the same job, seconds apart, with the same repo id
# and the same options:
#
#   dnf repoquery --repo=copr:...:t2linux 'kernel*'   → kernel-7.1.9-200.t2.fc44
#                                                        kernel-core-…, +16 more
#   dnf install  --from-repo=copr:...:t2linux kernel  → No match for argument
#
# So the repo is right, the id is right, the packages are there, and the
# options are fine. `--from-repo` is the one thing that differs, and under it
# dnf loads no repository at all — its "Updating and loading repositories:"
# line is empty on the install and names the COPR on the repoquery.
#
# So stop asking a flag to carry the guarantee. Read the version the COPR
# actually offers, then install that exact EVR with every repo enabled. Fedora
# ships 7.2.4-200.fc44 and the COPR 7.1.9-200.t2.fc44, so an exact EVR can only
# resolve to the t2 build — the pin is in the argument itself, where it cannot
# be reinterpreted. Leaving the other repos enabled is deliberate: the kernel's
# own dependencies resolve from them or from what is already installed, which
# is what `--repo` would have cut off.
#
# asahi.sh solves the same problem the same way, by making the argument
# unambiguous (it installs kernel-16k, a name Fedora does not ship) rather than
# by constraining the source. The assertion after this is the real guarantee.
echo "== kernel packages before the swap =="
rpm -qa 'kernel*' | sort
echo "== exclude filters in force =="
grep -rHnE '^[[:space:]]*(exclude|excludepkgs)[[:space:]]*=' \
	/etc/dnf/dnf.conf /etc/yum.repos.d/ || echo "(none)"

echo "== what the pinned repo offers =="
dnf -y repoquery --repo="${_T2_REPO}" --qf '%{name}-%{evr}\n' 'kernel*' || true

_t2_evr="$(dnf -y repoquery --repo="${_T2_REPO}" --qf '%{evr}\n' kernel |
	grep -E '\.t2\.' | sort -V | tail -1)"
if [ -z "${_t2_evr}" ]; then
	echo "ERROR: the t2linux repo offers no kernel build tagged .t2." >&2
	exit 1
fi
echo "t2.sh: installing kernel ${_t2_evr} from ${_T2_REPO}"

dnf -y remove --noautoremove kernel kernel-core kernel-modules \
	kernel-modules-core || true
dnf -y install --allowerasing \
	"kernel-${_t2_evr}" \
	"kernel-core-${_t2_evr}" \
	"kernel-modules-${_t2_evr}" \
	"kernel-modules-core-${_t2_evr}"

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
