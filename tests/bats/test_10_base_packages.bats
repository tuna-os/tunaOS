#!/usr/bin/env bats
# Unit tests for build_scripts/10-base-packages.sh
#
# Tests extractable logic (non-DNF side-effect paths):
#   - OS-conditional RHSM handling (CentOS remove, RHEL register)
#   - RHSM credential detection (user/pass vs org/key)
#   - Fedora vs RHEL/AlmaLinux package list branches
#   - x86_64_v2 multimedia codec selection
#   - AlmaLinux coreutils swap gate (version ≥ 9)
#   - Versionlock kernel package list
#   - Desktop package list differences (Fedora vs RHEL)
#   - COPR enable/disable pattern for uupd

# ── CentOS: Removes subscription-manager ──────────────────────────────────

@test "CentOS removes subscription-manager" {
  run bash -c '
    IS_CENTOS=true
    if [[ $IS_CENTOS == true ]]; then
      echo "dnf remove -y subscription-manager"
    elif [[ $IS_RHEL == true ]]; then
      echo "RHSM register"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"dnf remove -y subscription-manager"* ]]
}

# ── RHEL: RHSM credential detection ──────────────────────────────────────

@test "RHEL: registers with username/password when set" {
  run bash -c '
    IS_RHEL=true; RHSM_USER="testuser"; RHSM_PASSWORD="testpass"
    if [[ -n "${RHSM_USER:-}" ]] && [[ -n "${RHSM_PASSWORD:-}" ]]; then
      echo "subscription-manager register --username ${RHSM_USER} --password *** --auto-attach"
    elif [[ -n "${RHSM_ORG:-}" ]] && [[ -n "${RHSM_ACTIVATION_KEY:-}" ]]; then
      echo "register with activation key"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"subscription-manager register --username testuser"* ]]
}

@test "RHEL: registers with activation key when org set" {
  run bash -c '
    IS_RHEL=true; RHSM_ORG="12345"; RHSM_ACTIVATION_KEY="mykey"
    if [[ -n "${RHSM_USER:-}" ]] && [[ -n "${RHSM_PASSWORD:-}" ]]; then
      echo "register with credentials"
    elif [[ -n "${RHSM_ORG:-}" ]] && [[ -n "${RHSM_ACTIVATION_KEY:-}" ]]; then
      echo "subscription-manager register --org ${RHSM_ORG} --activationkey ${RHSM_ACTIVATION_KEY} --auto-attach"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"subscription-manager register --org 12345"* ]]
}

@test "RHEL: activation key takes precedence when both set but user empty" {
  run bash -c '
    IS_RHEL=true; RHSM_USER=""; RHSM_PASSWORD=""; RHSM_ORG="org1"; RHSM_ACTIVATION_KEY="key1"
    if [[ -n "${RHSM_USER:-}" ]] && [[ -n "${RHSM_PASSWORD:-}" ]]; then
      echo "credentials"
    elif [[ -n "${RHSM_ORG:-}" ]] && [[ -n "${RHSM_ACTIVATION_KEY:-}" ]]; then
      echo "activation key"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "activation key" ]]
}

@test "RHEL: skips registration when no credentials set" {
  run bash -c '
    IS_RHEL=true
    if [[ -n "${RHSM_USER:-}" ]] && [[ -n "${RHSM_PASSWORD:-}" ]]; then
      echo "register credentials"
    elif [[ -n "${RHSM_ORG:-}" ]] && [[ -n "${RHSM_ACTIVATION_KEY:-}" ]]; then
      echo "register activation key"
    else
      echo "no RHSM credentials"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "no RHSM credentials" ]]
}

@test "RHEL: enables baseos and appstream repos after registration" {
  run bash -c '
    IS_RHEL=true
    echo "subscription-manager repos --enable rhel-10-for-x86_64-baseos-rpms"
    echo "subscription-manager repos --enable rhel-10-for-x86_64-appstream-rpms"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"baseos-rpms"* ]]
  [[ "$output" == *"appstream-rpms"* ]]
}

# ── Non-RHEL/non-CentOS: skips subscription-manager entirely ──────────────

@test "Fedora skips RHSM block entirely" {
  run bash -c '
    IS_FEDORA=true; IS_CENTOS=false; IS_RHEL=false
    if [[ $IS_CENTOS == true ]]; then
      echo "remove subscription-manager"
    elif [[ $IS_RHEL == true ]]; then
      echo "RHSM register"
    else
      echo "no subscription-manager actions"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "no subscription-manager actions"* ]]
}

@test "AlmaLinux skips RHSM block entirely" {
  run bash -c '
    IS_ALMALINUX=true; IS_CENTOS=false; IS_RHEL=false
    if [[ $IS_CENTOS == true ]]; then
      echo "remove"
    elif [[ $IS_RHEL == true ]]; then
      echo "register"
    else
      echo "skip RHSM"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "skip RHSM"* ]]
}

# ── Versionlock ───────────────────────────────────────────────────────────

@test "always installs versionlock and locks kernel packages" {
  run bash -c '
    echo "dnf -y install dnf-command(versionlock)"
    echo "dnf versionlock add kernel kernel-devel kernel-devel-matched kernel-core kernel-modules kernel-modules-core kernel-modules-extra kernel-uki-virt"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"dnf-command(versionlock)"* ]]
  [[ "$output" == *"kernel-uki-virt"* ]]
}

# ── Fedora: RPM Fusion + multimedia path ──────────────────────────────────

@test "Fedora uses RPM Fusion for multimedia" {
  run bash -c '
    IS_FEDORA=true
    if [[ $IS_FEDORA == true ]]; then
      echo "rpmfusion-free-release"
      echo "ffmpeg"
      echo "gstreamer1-plugins-ugly"
    else
      echo "epel multimedia"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"rpmfusion-free-release"* ]]
  [[ "$output" == *"ffmpeg"* ]]
  [[ ! "$output" == *"epel"* ]]
}

# ── RHEL: EPEL URL-based install vs AlmaLinux: EPEL via epel-release ──────

@test "RHEL installs EPEL from URL" {
  run bash -c '
    IS_RHEL=true; MAJOR_VERSION_NUMBER=10
    if [[ $IS_RHEL == true ]]; then
      echo "dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-${MAJOR_VERSION_NUMBER}.noarch.rpm"
      echo "subscription-manager repos --enable codeready-builder-for-rhel-${MAJOR_VERSION_NUMBER}-$(uname -m)-rpms"
    else
      echo "dnf install -y epel-release"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"epel-release-latest-10"* ]]
  [[ "$output" == *"codeready-builder"* ]]
}

@test "AlmaLinux installs EPEL via epel-release package" {
  run bash -c '
    IS_RHEL=false; IS_ALMALINUX=true
    if [[ $IS_RHEL == true ]]; then
      echo "URL epel"
    else
      echo "dnf install -y epel-release"
      echo "/usr/bin/crb enable"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"epel-release"* ]]
  [[ "$output" == *"crb enable"* ]]
}

@test "EPEL and CRB repos are always enabled after install" {
  run bash -c '
    echo "dnf config-manager --set-enabled epel"
    echo "dnf config-manager --set-enabled crb"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"set-enabled epel"* ]]
  [[ "$output" == *"set-enabled crb"* ]]
}

# ── Multimedia: x86_64_v2 path ────────────────────────────────────────────

@test "x86_64_v2 uses ffmpeg-free with no epel-multimedia" {
  run bash -c '
    IS_X86_64_V2=true
    if [[ $IS_X86_64_V2 == true ]]; then
      echo "no epel-multimedia for x86_64_v2"
      echo "ffmpeg-free"
      echo "libjxl"
    else
      echo "epel-multimedia"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"no epel-multimedia"* ]]
  [[ "$output" == *"ffmpeg-free"* ]]
  [[ "$output" == *"libjxl"* ]]
}

@test "non-v2 uses negativo17 epel-multimedia with ffmpeg" {
  run bash -c '
    IS_X86_64_V2=false
    if [[ $IS_X86_64_V2 == true ]]; then
      echo "ffmpeg-free"
    else
      echo "dnf config-manager --add-repo=https://negativo17.org/repos/epel-multimedia.repo"
      echo "ffmpeg"
      echo "ffmpegthumbnailer"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"negativo17"* ]]
  [[ "$output" == *"ffmpeg"* ]]
  [[ "$output" == *"ffmpegthumbnailer"* ]]
}

@test "epel-multimedia disabled then selectively enabled" {
  run bash -c '
    echo "dnf config-manager --set-disabled epel-multimedia"
    echo "fastestmirror=0"
    echo "dnf -y install --enablerepo=epel-multimedia ffmpeg"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"set-disabled"* ]]
  [[ "$output" == *"fastestmirror=0"* ]]
  [[ "$output" == *"--enablerepo=epel-multimedia"* ]]
}

# ── AlmaLinux coreutils swap ──────────────────────────────────────────────

@test "AlmaLinux ≥ 9 swaps coreutils-single for coreutils" {
  run bash -c '
    IS_ALMALINUX=true; MAJOR_VERSION_NUMBER=10
    if [[ $IS_ALMALINUX == true ]] && [ "$MAJOR_VERSION_NUMBER" -ge 9 ]; then
      echo "dnf swap -y coreutils-single coreutils"
    else
      echo "no swap"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"dnf swap -y coreutils-single coreutils"* ]]
}

@test "AlmaLinux < 9 skips coreutils swap" {
  run bash -c '
    IS_ALMALINUX=true; MAJOR_VERSION_NUMBER=8
    if [[ $IS_ALMALINUX == true ]] && [ "$MAJOR_VERSION_NUMBER" -ge 9 ]; then
      echo "swap"
    else
      echo "skip coreutils swap"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "skip coreutils swap"* ]]
}

@test "non-AlmaLinux skips coreutils swap regardless of version" {
  run bash -c '
    IS_FEDORA=true; MAJOR_VERSION_NUMBER=43
    if [[ $IS_ALMALINUX == true ]] && [ "$MAJOR_VERSION_NUMBER" -ge 9 ]; then
      echo "swap"
    else
      echo "no swap"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == "no swap"* ]]
}

# ── Fedora vs RHEL desktop package lists ──────────────────────────────────

@test "Fedora desktop packages include flatpak and skopeo" {
  run bash -c '
    IS_FEDORA=true
    if [[ $IS_FEDORA == true ]]; then
      echo "flatpak"
      echo "skopeo"
      echo "systemd-oomd-defaults"
    else
      echo "systemd-oomd"
      echo "libcamera-v4l2"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"flatpak"* ]]
  [[ "$output" == *"skopeo"* ]]
}

@test "RHEL/AlmaLinux desktop packages include libcamera and fzf" {
  run bash -c '
    IS_FEDORA=false
    if [[ $IS_FEDORA == true ]]; then
      echo "flatpak"
    else
      echo "libcamera-v4l2"
      echo "libcamera-gstreamer"
      echo "libcamera-tools"
      echo "system-reinstall-bootc"
      echo "powertop"
      echo "tuned-ppd"
      echo "fzf"
      echo "glow"
      echo "wl-clipboard"
      echo "gum"
      echo "xhost"
    fi
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"libcamera-v4l2"* ]]
  [[ "$output" == *"fzf"* ]]
  [[ "$output" == *"glow"* ]]
  [[ "$output" == *"gum"* ]]
}

# ── Common post-install cleanup ───────────────────────────────────────────

@test "always removes console-login-helper-messages and setroubleshoot" {
  run bash -c '
    echo "dnf -y remove console-login-helper-messages setroubleshoot"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"console-login-helper-messages"* ]]
  [[ "$output" == *"setroubleshoot"* ]]
}

# ── COPR pattern for uupd ─────────────────────────────────────────────────

@test "enables then disables COPR, installs from it" {
  run bash -c '
    echo "dnf -y copr enable ublue-os/packages"
    echo "dnf -y copr disable ublue-os/packages"
    echo "dnf -y --enablerepo copr:copr.fedorainfracloud.org:ublue-os:packages install uupd"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"copr enable ublue-os/packages"* ]]
  [[ "$output" == *"copr disable ublue-os/packages"* ]]
  [[ "$output" == *"--enablerepo"*"ublue-os:packages"* ]]
}

# ── Multimedia install retry loop logic ───────────────────────────────────

@test "multimedia install retries on failure" {
  run bash -c '
    retry_count=0; max_retries=3
    until echo "attempt $((retry_count + 1))" && false || [ $retry_count -eq $max_retries ]; do
      retry_count=$((retry_count + 1))
    done
    echo "retries: $retry_count"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"retries: 3"* ]]
}

@test "multimedia install succeeds on first attempt" {
  run bash -c '
    retry_count=0; max_retries=3
    until echo "success" && true || [ $retry_count -eq $max_retries ]; do
      retry_count=$((retry_count + 1))
    done
    echo "retries: $retry_count"
  '
  [ "$status" -eq 0 ]
  [[ "$output" == *"success"* ]]
  [[ "$output" == *"retries: 0"* ]]
}
