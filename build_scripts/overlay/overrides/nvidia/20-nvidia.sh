#!/bin/bash
# 20-nvidia.sh — install the NVIDIA driver stack on a *-nvidia overlay.
#
# WHY THIS FILE EXISTS (tunaOS was shipping driverless "nvidia" images):
# build_scripts/overlay/nvidia.sh calls `run_buildscripts_for nvidia`, which
# resolves ${BUILD_SCRIPTS_PATH}/overrides/nvidia (lib.sh) — a directory that
# did not exist. run_buildscripts_for prints "No build script overrides for
# 'nvidia', skipping." and returns 0, so every *-nvidia image was its parent
# DE image plus three VS Code setup hooks: no kernel module, no userspace
# driver, no kargs, no nouveau blacklist. The akmods-nvidia-open RPMs were
# bind-mounted at /tmp/akmods-nvidia-open-rpms (Containerfile.overlay) and
# never consumed. Nothing could catch it: no check mentioned nvidia at all.
#
# Ported from the proven prior art for the exact same akmods bundle:
# _upstream-snapshots/bluefin-lts/build_scripts/overrides/gdx/20-nvidia.sh
# (bluefin-lts GDX consumes ghcr.io/ublue-os/akmods-nvidia-open:centos-10,
# which is what scripts/build-image-inner.sh passes for the EL10 variants;
# bonito passes coreos-stable-<N>). Deliberate differences from the port:
#
#   * No `dnf config-manager` calls. The EL10 variants have dnf4
#     (--set-enabled/--set-disabled) while bonito has dnf5 (setopt) — the two
#     syntaxes are mutually incompatible, so repos are written with enabled=0
#     baked into the file and enabled per-transaction with --enablerepo.
#   * SELinux module install and ublue-nvctk-cdi enablement are guarded on
#     the file/unit existing, because the ublue-os addons payload differs
#     between the centos-10 and coreos-stable akmods bundles.
#   * Suspend/resume/hibernate units are enabled IF the driver packaging
#     ships them. Measured against negativo17 fedora-nvidia 43 (filelists,
#     2026-08-07): that packaging ships nvidia-persistenced.service and
#     nvidia-powerd.service but NO nvidia-suspend/resume/hibernate units, so
#     on today's repo the loop is a documented no-op — it exists so a
#     packaging change that adds them cannot ship them disabled.
#
# The kmod install below globs kmod-nvidia-${KERNEL_VRA}-*.rpm — an EXACT
# kernel EVR.ARCH match. If the akmods bundle was built for a different
# kernel than this image ships, dnf receives the unexpanded glob and fails
# the build. That is deliberate: a kmod for the wrong kernel is a black
# screen on real hardware, and a loud build failure is the only place to
# learn it. build_scripts/checks/verify-nvidia.sh re-proves this and the
# rest of the contract independently at the end of the overlay.

set -xeuo pipefail

# /*
# Get Kernel Version
# */
KERNEL_NAME="kernel"
KERNEL_VRA="$(rpm -q "$KERNEL_NAME" --queryformat '%{EVR}.%{ARCH}')"
KERNEL_SUFFIX=""
QUALIFIED_KERNEL="$(rpm -qa | grep -P 'kernel-(|'"$KERNEL_SUFFIX"'-)(\d+\.\d+\.\d+)' | sed -E 's/kernel-(|'"$KERNEL_SUFFIX"'-)//' | tail -n 1)"

### install Nvidia driver packages and dependencies
# kmod-nvidia requires nvidia-kmod-common from negativo17's fedora-nvidia
# repo. Detect the Fedora release embedded in the akmods RPMs and download
# the matching repo file so DNF can resolve it. On the centos-10 akmods the
# RPMs carry no .fcNN tag, so the pinned default applies — the same release
# bluefin-lts pins for the same bundle.
FEDORA_VERSION="${FEDORA_AKMODS_VERSION:-43}"
AKMODS_FEDORA_VERSION="$(find /tmp/akmods-nvidia-open-rpms -name "*.rpm" -print | grep -oPm1 '(?<=\.fc)\d+' || true)"
if [[ -n "${AKMODS_FEDORA_VERSION}" ]]; then
	FEDORA_VERSION="${AKMODS_FEDORA_VERSION}"
fi
curl --retry 3 -fsSLo - "https://negativo17.org/repos/fedora-nvidia.repo" |
	sed "s/\$releasever/${FEDORA_VERSION}/g" |
	tee "/etc/yum.repos.d/fedora-nvidia.repo"
# Disabled at rest; enabled per-transaction below (see header for why this
# is not `dnf config-manager`).
sed -i 's/^enabled=1/enabled=0/' /etc/yum.repos.d/fedora-nvidia.repo

dnf -y install --enablerepo="fedora-nvidia" \
	/tmp/akmods-nvidia-open-rpms/kmods/kmod-nvidia-"${KERNEL_VRA}"-*.rpm \
	/tmp/akmods-nvidia-open-rpms/ublue-os/*.rpm

# Get the kmod-nvidia version to ensure driver packages match
KMOD_VERSION="$(rpm -q --queryformat '%{VERSION}' kmod-nvidia)"
# Determine the expected package version format (epoch:version-release)
NVIDIA_PKG_VERSION="3:${KMOD_VERSION}"

# The nvidia-container-toolkit repo file ships in the ublue-os addons RPMs
# installed above; enable it for this transaction only.
dnf -y install --enablerepo="fedora-nvidia" --enablerepo="nvidia-container-toolkit" \
	"libnvidia-fbc-${NVIDIA_PKG_VERSION}" \
	"nvidia-driver-${NVIDIA_PKG_VERSION}" \
	"nvidia-driver-cuda-${NVIDIA_PKG_VERSION}" \
	"nvidia-settings-${NVIDIA_PKG_VERSION}" \
	nvidia-container-toolkit
# Leave the toolkit repo disabled at rest, matching the fedora-nvidia repo.
if [[ -f /etc/yum.repos.d/nvidia-container-toolkit.repo ]]; then
	sed -i 's/^enabled=1/enabled=0/' /etc/yum.repos.d/nvidia-container-toolkit.repo
fi

# Ensure the version of the Nvidia module matches the driver
DRIVER_VERSION="$(rpm -q --queryformat '%{VERSION}' nvidia-driver)"
if [ "$KMOD_VERSION" != "$DRIVER_VERSION" ]; then
	echo "Error: kmod-nvidia version ($KMOD_VERSION) does not match nvidia-driver version ($DRIVER_VERSION)"
	exit 1
fi

tee /usr/lib/modprobe.d/00-nouveau-blacklist.conf <<'EOF'
blacklist nouveau
options nouveau modeset=0
EOF

install -d /usr/lib/bootc/kargs.d
tee /usr/lib/bootc/kargs.d/00-nvidia.toml <<'EOF'
kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]
EOF

## nvidia post-install steps
# Container toolkit CDI generation service + SELinux module, both from the
# ublue-os addons payload — guarded because the payload differs between the
# centos-10 and coreos-stable akmods bundles (see header).
if [[ -f /usr/lib/systemd/system/ublue-nvctk-cdi.service ]]; then
	systemctl enable ublue-nvctk-cdi.service
fi
if [[ -f /usr/share/selinux/packages/nvidia-container.pp ]]; then
	semodule --verbose --install /usr/share/selinux/packages/nvidia-container.pp
fi

# Suspend/resume/hibernate units: enable when the driver packaging ships
# them. Measured no-op on negativo17 fedora-nvidia 43 today — see header.
for _nv_unit in nvidia-suspend nvidia-resume nvidia-hibernate; do
	if [[ -f "/usr/lib/systemd/system/${_nv_unit}.service" ]]; then
		systemctl enable "${_nv_unit}.service"
	fi
done

# Universal Blue specific Initramfs fixes
# nvidia-modeset.conf may not exist on all architectures (e.g. arm64/SBSA)
if [[ -f /etc/modprobe.d/nvidia-modeset.conf ]]; then
	cp /etc/modprobe.d/nvidia-modeset.conf /usr/lib/modprobe.d/nvidia-modeset.conf
fi
# we must force driver load to fix black screen on boot for nvidia desktops.
# 99-nvidia.conf ships in negativo17's nvidia-kmod-common (measured in its
# filelists) — installed above as a nvidia-driver dependency chain member.
if [[ ! -f /usr/lib/dracut/dracut.conf.d/99-nvidia.conf ]]; then
	echo "ERROR: /usr/lib/dracut/dracut.conf.d/99-nvidia.conf is missing —" >&2
	echo "       nvidia-kmod-common did not install; the initramfs would omit" >&2
	echo "       the driver and real hardware would boot to a black screen." >&2
	exit 1
fi
sed -i 's@omit_drivers@force_drivers@g' /usr/lib/dracut/dracut.conf.d/99-nvidia.conf
# as we need forced load, also must pre-load intel/amd iGPU else chromium web browsers fail to use hardware acceleration
sed -i 's@ nvidia @ i915 amdgpu nvidia @g' /usr/lib/dracut/dracut.conf.d/99-nvidia.conf

# Make sure initramfs is rebuilt after nvidia drivers or kernel replacement
/usr/bin/dracut --no-hostonly --kver "$QUALIFIED_KERNEL" --reproducible --tmpdir /boot --zstd -v --add ostree -f "/lib/modules/$QUALIFIED_KERNEL/initramfs.img"
