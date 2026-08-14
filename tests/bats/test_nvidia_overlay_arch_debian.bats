#!/usr/bin/env bats
# tunaOS#624 — marlin (Arch) and flounder/flounder-sid (Debian) had no
# *-nvidia flavor at all: Containerfile.overlay's nvidia path only ever
# consumed akmods RPMs. This pins the two new package-family overlays the
# same way test_nvidia_overlay.bats pins the rpm/akmods one: a missing or
# mis-named overrides directory must be a TEST failure, never a silent
# run_buildscripts_for no-op (the exact failure mode that shipped
# driverless "*-nvidia" images on the rpm family for months).

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
ARCH_DIR="${REPO_ROOT}/build_scripts/overlay/overrides/nvidia-arch"
DEBIAN_DIR="${REPO_ROOT}/build_scripts/overlay/overrides/nvidia-debian"
ARCH_INSTALL_SH="${ARCH_DIR}/20-nvidia.sh"
DEBIAN_INSTALL_SH="${DEBIAN_DIR}/20-nvidia.sh"
VERIFY_ARCH_SH="${REPO_ROOT}/build_scripts/checks/verify-nvidia-arch.sh"
VERIFY_DEBIAN_SH="${REPO_ROOT}/build_scripts/checks/verify-nvidia-debian.sh"

# ── wiring: the silent-skip hole stays closed for both new families ───────

@test "nvidia-arch overrides directory exists and contains an executable matching run_buildscripts_for's pattern" {
  [ -d "$ARCH_DIR" ]
  local found=0 f
  for f in "$ARCH_DIR"/*-*.sh; do
    [ -f "$f" ] || continue
    [ -x "$f" ] || { echo "not executable: $f" >&2; continue; }
    found=1
  done
  [ "$found" -eq 1 ]
}

@test "nvidia-debian overrides directory exists and contains an executable matching run_buildscripts_for's pattern" {
  [ -d "$DEBIAN_DIR" ]
  local found=0 f
  for f in "$DEBIAN_DIR"/*-*.sh; do
    [ -f "$f" ] || continue
    [ -x "$f" ] || { echo "not executable: $f" >&2; continue; }
    found=1
  done
  [ "$found" -eq 1 ]
}

@test "verify-nvidia-arch.sh and verify-nvidia-debian.sh are executable" {
  [ -x "$VERIFY_ARCH_SH" ]
  [ -x "$VERIFY_DEBIAN_SH" ]
}

# ── install layer: the load-bearing lines of each 20-nvidia.sh ────────────

@test "nvidia-arch 20-nvidia.sh installs nvidia-open-dkms via pacman, not nvidia-open or nvidia-dkms" {
  run grep -F 'nvidia-open-dkms' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
  # nvidia-dkms no longer exists in Arch's repos (verified 2026-08-08) — a
  # regression toward it would silently break every marlin nvidia build.
  run grep -E '^\s*nvidia-dkms\s*\\?\s*$' "$ARCH_INSTALL_SH"
  [ "$status" -ne 0 ]
}

@test "nvidia-arch 20-nvidia.sh guards on IS_ARCH and asserts the dkms build tree before building" {
  run grep -F 'IS_ARCH' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F '/build' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'dkms autoinstall' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "nvidia-arch 20-nvidia.sh proves the module by finding nvidia.ko, not by trusting dkms status text" {
  run grep -F "find \"/usr/lib/modules/\${KVER}\" -name 'nvidia.ko*'" "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "nvidia-arch 20-nvidia.sh blacklists nouveau and sets the modeset karg" {
  run grep -F 'blacklist nouveau' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'nvidia-drm.modeset=1' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F '/usr/lib/bootc/kargs.d/00-nvidia.toml' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "nvidia-arch 20-nvidia.sh rebuilds the initramfs with dracut" {
  # This image never invokes mkinitcpio (the Arch default) — the file's own
  # comments say so, but the invariant that matters is that dracut actually
  # runs and force_drivers is actually set.
  run grep -E '^\s*dracut --force' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'force_drivers' "$ARCH_INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "nvidia-debian 20-nvidia.sh enables contrib/non-free/non-free-firmware before installing" {
  run grep -F 'non-free-firmware' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  # The component-enable step must run before apt-get update, which must run
  # before the driver install.
  local comp_line update_line install_line
  comp_line="$(grep -n 'non-free-firmware' "$DEBIAN_INSTALL_SH" | tail -1 | cut -d: -f1)"
  update_line="$(grep -n '^apt-get update' "$DEBIAN_INSTALL_SH" | head -1 | cut -d: -f1)"
  # The package-list line, not the header comment mentioning the same name.
  install_line="$(grep -n '^\s*nvidia-kernel-dkms \\$' "$DEBIAN_INSTALL_SH" | head -1 | cut -d: -f1)"
  [ -n "$comp_line" ] && [ -n "$update_line" ] && [ -n "$install_line" ]
  [ "$comp_line" -lt "$update_line" ]
  [ "$update_line" -lt "$install_line" ]
}

@test "nvidia-debian 20-nvidia.sh fails loudly when no apt source file has a Components: line" {
  run grep -F 'found no /etc/apt/sources.list' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -A4 -F 'if [[ "$_found_components" -eq 0 ]]; then' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  [[ "$output" == *"exit 1"* ]]
}

@test "nvidia-debian 20-nvidia.sh guards on IS_DEBIAN and asserts the dkms build tree before building" {
  run grep -F 'IS_DEBIAN' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'HEADERS_PKG' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'dkms autoinstall' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "nvidia-debian 20-nvidia.sh proves the module by finding it on disk, not by trusting dkms status text" {
  run grep -F 'find "/usr/lib/modules/${KVER}" -name "${_nv_base}.ko*"' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "nvidia-debian 20-nvidia.sh blacklists nouveau and sets the modeset karg" {
  run grep -F 'blacklist nouveau' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'nvidia-drm.modeset=1' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F '/usr/lib/bootc/kargs.d/00-nvidia.toml' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "nvidia-debian 20-nvidia.sh rebuilds the initramfs with dracut" {
  # This image never invokes update-initramfs (the Debian default) — the
  # file's own comments say so, but the invariant that matters is that
  # dracut actually runs and force_drivers is actually set.
  run grep -E '^\s*dracut --force' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'force_drivers' "$DEBIAN_INSTALL_SH"
  [ "$status" -eq 0 ]
}

# ── contract: verify-nvidia-arch.sh / verify-nvidia-debian.sh behavioral ──
#
# Same pattern as verify-nvidia.sh's own tests: TUNAOS_NVIDIA_VERIFY_ROOT
# points the real script at a fixture tree, with pacman/dpkg-query/modinfo
# stubbed on PATH.

KVER="7.1.6-arch1-1"

make_good_arch_root() {
  local r="${BATS_TEST_TMPDIR}/arch-root"
  mkdir -p \
    "$r/usr/lib/modules/${KVER}" \
    "$r/usr/lib/modprobe.d" \
    "$r/usr/lib/bootc/kargs.d" \
    "$r/usr/share/glvnd/egl_vendor.d" \
    "$r/usr/share/vulkan/icd.d" \
    "$r/usr/lib/gbm" \
    "$r/usr/lib/dracut/dracut.conf.d"
  touch "$r/usr/lib/modules/${KVER}/nvidia.ko.zst"
  echo initrd >"$r/usr/lib/modules/${KVER}/initramfs.img"
  echo "blacklist nouveau" >"$r/usr/lib/modprobe.d/00-nouveau-blacklist.conf"
  echo 'kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]' \
    >"$r/usr/lib/bootc/kargs.d/00-nvidia.toml"
  echo '{}' >"$r/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
  echo '{}' >"$r/usr/share/vulkan/icd.d/nvidia_icd.json"
  touch "$r/usr/lib/libEGL_nvidia.so.0" "$r/usr/lib/libGLX_nvidia.so.0"
  touch "$r/usr/lib/gbm/nvidia-drm_gbm.so"
  echo 'force_drivers+=" i915 amdgpu nvidia nvidia_modeset nvidia_uvm nvidia_drm "' \
    >"$r/usr/lib/dracut/dracut.conf.d/99-nvidia.conf"
  echo "$r"
}

make_arch_stub_tools() {
  mkdir -p "${BATS_TEST_TMPDIR}/bin"
  cat >"${BATS_TEST_TMPDIR}/bin/pacman" <<'STUB'
#!/usr/bin/env bash
if [[ "$1" == "-Q" ]]; then
  case "$*" in
    *nvidia-open-dkms*|*nvidia-utils*|*nvidia-settings*|*dkms*|*egl-wayland*)
      echo "Version        : 610.57.04-1" ;;
    *) exit 1 ;;
  esac
fi
STUB
  cat >"${BATS_TEST_TMPDIR}/bin/modinfo" <<'STUB'
#!/usr/bin/env bash
echo "610.57.04"
STUB
  chmod +x "${BATS_TEST_TMPDIR}/bin/"*
}

run_verify_arch() {
  PATH="${BATS_TEST_TMPDIR}/bin:$PATH" \
    TUNAOS_NVIDIA_VERIFY_ROOT="$1" \
    run bash "$VERIFY_ARCH_SH"
}

@test "verify-nvidia-arch passes on a complete driver install" {
  make_arch_stub_tools
  root="$(make_good_arch_root)"
  run_verify_arch "$root"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_NVIDIA_ARCH_CONTRACT_OK"* ]]
}

@test "verify-nvidia-arch refuses to run without pacman on PATH" {
  root="$(make_good_arch_root)"
  # Empty PATH, script invoked by absolute interpreter path so bash itself
  # doesn't need a PATH lookup — pacman must be absent here regardless of
  # what the CI/dev host happens to have installed.
  local bash_bin
  bash_bin="$(command -v bash)"
  PATH="" TUNAOS_NVIDIA_VERIFY_ROOT="$root" run "$bash_bin" "$VERIFY_ARCH_SH"
  [ "$status" -ne 0 ]
  [[ "$output" == *"only knows the pacman family"* ]]
}

@test "verify-nvidia-arch fails when the dkms module is missing" {
  make_arch_stub_tools
  root="$(make_good_arch_root)"
  rm "$root/usr/lib/modules/${KVER}/nvidia.ko.zst"
  run_verify_arch "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"TUNAOS_NVIDIA_ARCH_CONTRACT_FAIL"* ]]
  [[ "$output" == *"dkms did not build for this kernel"* ]]
}

@test "verify-nvidia-arch fails when the Wayland GBM backend is missing" {
  make_arch_stub_tools
  root="$(make_good_arch_root)"
  rm "$root/usr/lib/gbm/nvidia-drm_gbm.so"
  run_verify_arch "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nvidia-drm_gbm.so"* ]]
}

@test "verify-nvidia-arch fails when the modeset karg is absent" {
  make_arch_stub_tools
  root="$(make_good_arch_root)"
  echo 'kargs = ["rd.driver.blacklist=nouveau"]' >"$root/usr/lib/bootc/kargs.d/00-nvidia.toml"
  run_verify_arch "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nvidia-drm.modeset=1"* ]]
}

@test "verify-nvidia-arch fails when dracut force_drivers is missing" {
  make_arch_stub_tools
  root="$(make_good_arch_root)"
  rm "$root/usr/lib/dracut/dracut.conf.d/99-nvidia.conf"
  run_verify_arch "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"99-nvidia.conf"* ]]
}

make_good_debian_root() {
  local r="${BATS_TEST_TMPDIR}/debian-root"
  local nvlib="$r/usr/lib/x86_64-linux-gnu/nvidia/current"
  mkdir -p \
    "$r/usr/lib/modules/${KVER}" \
    "$r/usr/lib/modprobe.d" \
    "$r/usr/lib/bootc/kargs.d" \
    "$r/usr/share/glvnd/egl_vendor.d" \
    "$r/usr/share/vulkan/icd.d" \
    "$r/usr/lib/dracut/dracut.conf.d" \
    "$nvlib"
  # nvidia-current.ko.xz is what Debian's alternatives-managed
  # nvidia-kernel-dkms actually installs, straight from flounder's build log:
  #   Installing /lib/modules/6.12.101+deb13-amd64/updates/dkms/nvidia-current.ko.xz
  # This fixture used to write nvidia.ko.zst -- the Fedora/Arch name -- so it
  # agreed with the script's glob instead of with Debian, and the check passed
  # here while failing every real nvidia build. The sibling module is written
  # too, so a glob that grabs the wrong one cannot pass by accident.
  touch "$r/usr/lib/modules/${KVER}/nvidia-current.ko.xz"
  touch "$r/usr/lib/modules/${KVER}/nvidia-current-modeset.ko.xz"
  echo initrd >"$r/usr/lib/modules/${KVER}/initramfs.img"
  echo "blacklist nouveau" >"$r/usr/lib/modprobe.d/00-nouveau-blacklist.conf"
  echo 'kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]' \
    >"$r/usr/lib/bootc/kargs.d/00-nvidia.toml"
  echo '{}' >"$r/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
  echo '{}' >"$r/usr/share/vulkan/icd.d/nvidia_icd.json"
  touch "$nvlib/libEGL_nvidia.so.0" "$nvlib/libGLX_nvidia.so.0" "$nvlib/nvidia-drm_gbm.so"
  echo 'force_drivers+=" i915 amdgpu nvidia nvidia_modeset nvidia_uvm nvidia_drm "' \
    >"$r/usr/lib/dracut/dracut.conf.d/99-nvidia.conf"
  echo "$r"
}

make_debian_stub_tools() {
  mkdir -p "${BATS_TEST_TMPDIR}/bin"
  cat >"${BATS_TEST_TMPDIR}/bin/dpkg" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
  cat >"${BATS_TEST_TMPDIR}/bin/dpkg-query" <<'STUB'
#!/usr/bin/env bash
case "$*" in
  *nvidia-kernel-dkms*|*nvidia-driver-libs*|*nvidia-vulkan-icd*|*nvidia-settings*|*" dkms"*)
    printf '550.163.01-2' ;;
  *) exit 1 ;;
esac
STUB
  cat >"${BATS_TEST_TMPDIR}/bin/modinfo" <<'STUB'
#!/usr/bin/env bash
echo "550.163.01"
STUB
  chmod +x "${BATS_TEST_TMPDIR}/bin/"*
}

run_verify_debian() {
  PATH="${BATS_TEST_TMPDIR}/bin:$PATH" \
    TUNAOS_NVIDIA_VERIFY_ROOT="$1" \
    run bash "$VERIFY_DEBIAN_SH"
}

@test "verify-nvidia-debian passes on a complete driver install" {
  make_debian_stub_tools
  root="$(make_good_debian_root)"
  run_verify_debian "$root"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_NVIDIA_DEBIAN_CONTRACT_OK"* ]]
}

@test "verify-nvidia-debian refuses to run without dpkg on PATH" {
  root="$(make_good_debian_root)"
  # Empty PATH, script invoked by absolute interpreter path so bash itself
  # doesn't need a PATH lookup — dpkg must be absent here regardless of
  # whether the CI/dev host is itself Debian-based (this sandbox is).
  local bash_bin
  bash_bin="$(command -v bash)"
  PATH="" TUNAOS_NVIDIA_VERIFY_ROOT="$root" run "$bash_bin" "$VERIFY_DEBIAN_SH"
  [ "$status" -ne 0 ]
  [[ "$output" == *"only knows the dpkg family"* ]]
}

@test "verify-nvidia-debian fails when the dkms module is missing" {
  make_debian_stub_tools
  root="$(make_good_debian_root)"
  rm "$root/usr/lib/modules/${KVER}/nvidia-current.ko.xz"
  run_verify_debian "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"TUNAOS_NVIDIA_DEBIAN_CONTRACT_FAIL"* ]]
  [[ "$output" == *"dkms did not build for this kernel"* ]]
}

@test "verify-nvidia-debian fails when the Wayland GBM backend is missing" {
  make_debian_stub_tools
  root="$(make_good_debian_root)"
  rm "$root/usr/lib/x86_64-linux-gnu/nvidia/current/nvidia-drm_gbm.so"
  run_verify_debian "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nvidia-drm_gbm.so"* ]]
}

@test "verify-nvidia-debian fails when the modeset karg is absent" {
  make_debian_stub_tools
  root="$(make_good_debian_root)"
  echo 'kargs = ["rd.driver.blacklist=nouveau"]' >"$root/usr/lib/bootc/kargs.d/00-nvidia.toml"
  run_verify_debian "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nvidia-drm.modeset=1"* ]]
}

@test "verify-nvidia-debian fails when a stale second kernel tree survives" {
  make_debian_stub_tools
  root="$(make_good_debian_root)"
  mkdir -p "$root/usr/lib/modules/6.12.41-amd64"
  run_verify_debian "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"kernel module trees under /usr/lib/modules"* ]]
}
