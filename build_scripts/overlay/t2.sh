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
# and a Fedora kernel must never silently win.
#
# The obstacle, finally named by dnf itself in run 34762701445:
#
#   Argument 'kernel-7.1.9-200.t2.fc44' matches only packages excluded
#   by versionlock.
#
# 10-base-packages.sh runs `dnf versionlock add kernel kernel-core …` against
# the INSTALLED Fedora kernel, which pins it at 7.2.4-200.fc44 and excludes
# every other version — the t2 build included. That one fact explains three
# earlier failures that each looked like something else:
#
#   `--from-repo=<copr> kernel` → "No match for argument 'kernel' in
#     repositories 'copr:…'". The only candidates in that repo were t2
#     versions, all locked out, so dnf reported the emptiness in the
#     vocabulary of the pin. Nothing was wrong with the pin, the repo or
#     the packages (#2494 blamed the flag's scope, and was wrong).
#   `repoquery --repo=<copr> 'kernel*'` → lists all 18. repoquery does not
#     apply versionlock's excludes, which is why the same id and options
#     succeeded and failed feet apart in one job (#2497 read that as
#     `--from-repo` being broken, and was wrong).
#   `grep -E '^(exclude|excludepkgs)=' /etc/dnf/dnf.conf /etc/yum.repos.d/`
#     → "(none)". True, and beside the point: versionlock keeps its own
#     list, which that probe never looked at (#2495 blamed the base image's
#     exclude filters, and was wrong).
#
# The two kernel swaps already in this repo both evade the lock without
# meeting it. nvidia's bypasses dnf entirely (`rpm -ivh`, overrides/nvidia/
# 10-kernel-swap.sh) and asahi's installs `kernel-16k`, a name the lock list
# does not carry. t2 installs packages named exactly `kernel`, so it is the
# first swap the lock actually bites.
#
# So unlock, swap, and re-lock on what we installed. Re-locking is the same
# thing 10-kernel-swap.sh does after its swap, for the same reason: "a later
# transaction pulling a different kernel would silently undo the whole point
# of this script." The EVR still comes from the COPR rather than a literal, so
# a COPR rebuild needs no edit here, and the `.t2.` assertion below is still
# the guarantee.
echo "== kernel packages before the swap =="
rpm -qa 'kernel*' | sort
echo "== exclude filters in force =="
grep -rHnE '^[[:space:]]*(exclude|excludepkgs)[[:space:]]*=' \
	/etc/dnf/dnf.conf /etc/yum.repos.d/ || echo "(none)"
# The probe that would have found this on day one. dnf.conf and the .repo
# files are not the only place a package can be filtered out.
echo "== versionlock entries in force =="
dnf versionlock list 2>&1 || echo "(versionlock unavailable)"

echo "== what the pinned repo offers =="
dnf -y repoquery --repo="${_T2_REPO}" --qf '%{name}-%{evr}\n' 'kernel*' || true

_t2_evr="$(dnf -y repoquery --repo="${_T2_REPO}" --qf '%{evr}\n' kernel |
	grep -E '\.t2\.' | sort -V | tail -1)"
if [ -z "${_t2_evr}" ]; then
	echo "ERROR: the t2linux repo offers no kernel build tagged .t2." >&2
	exit 1
fi
echo "t2.sh: installing kernel ${_t2_evr} from ${_T2_REPO}"

# Release the stock kernel's lock, or the install below matches nothing.
# Every name 10-base-packages.sh locks, so no straggler keeps a hold.
dnf versionlock delete kernel kernel-devel kernel-devel-matched kernel-core \
	kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt ||
	echo "t2.sh: no versionlock entries to delete"

dnf -y remove --noautoremove kernel kernel-core kernel-modules \
	kernel-modules-core || true
dnf -y install --allowerasing \
	"kernel-${_t2_evr}" \
	"kernel-core-${_t2_evr}" \
	"kernel-modules-${_t2_evr}" \
	"kernel-modules-core-${_t2_evr}"

# Re-lock, now on the t2 kernel. Leaving the image unlocked would let any
# later transaction pull a Fedora kernel back over this one.
dnf versionlock add kernel kernel-core kernel-modules kernel-modules-core ||
	echo "t2.sh: could not re-apply versionlock"
echo "== versionlock entries after the swap =="
dnf versionlock list 2>&1 || true

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
