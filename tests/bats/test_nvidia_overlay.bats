#!/usr/bin/env bats
# The NVIDIA overlay must actually install a driver, and the contract must
# actually verify one.
#
# Failure mode these tests pin: run_buildscripts_for (build_scripts/lib.sh)
# resolves ${BUILD_SCRIPTS_PATH}/overrides/<what> and RETURNS 0 when the
# directory is missing ("No build script overrides ... skipping"). For the
# nvidia overlay that silent skip published *-nvidia images containing no
# kernel module, no userspace driver, no kargs and no nouveau blacklist —
# the akmods RPMs were bind-mounted and never consumed. A missing or
# mis-named overrides/nvidia directory must be a TEST failure here, never a
# silent no-op again.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
NVIDIA_DIR="${REPO_ROOT}/build_scripts/overlay/overrides/nvidia"
INSTALL_SH="${NVIDIA_DIR}/20-nvidia.sh"
VERIFY_SH="${REPO_ROOT}/build_scripts/checks/verify-nvidia.sh"
OVERLAY_SH="${REPO_ROOT}/build_scripts/overlay/nvidia.sh"

# ── wiring: the silent-skip hole stays closed ──────────────────────────────

@test "nvidia overrides directory exists where run_buildscripts_for looks" {
  # nvidia.sh executes with $0 = build_scripts/overlay/nvidia.sh, so lib.sh's
  # BUILD_SCRIPTS_PATH is build_scripts/overlay and the resolved overrides
  # path is build_scripts/overlay/overrides/nvidia. Anywhere else is skipped.
  run test -d "$NVIDIA_DIR"
  [ "$status" -eq 0 ]
}

@test "nvidia overrides directory contains an executable matching run_buildscripts_for's find pattern" {
  # run_buildscripts_for finds only `-maxdepth 1 -iname "*-*.sh" -type f`.
  # A script named without a hyphen (e.g. nvidia.sh) would be skipped.
  local found=0 f
  for f in "$NVIDIA_DIR"/*-*.sh; do
    [ -f "$f" ] || continue
    [ -x "$f" ] || { echo "not executable: $f" >&2; continue; }
    found=1
  done
  [ "$found" -eq 1 ]
}

@test "overlay nvidia.sh runs the overrides and then the fatal contract" {
  run grep -F 'run_buildscripts_for nvidia' "$OVERLAY_SH"
  [ "$status" -eq 0 ]
  # Bare call (no `|| true`, no `-`): under set -e a failed contract fails
  # the build.
  run grep -E '^/run/context/build_scripts/checks/verify-nvidia\.sh$' "$OVERLAY_SH"
  [ "$status" -eq 0 ]
  # And the auditor ships in the image for the published-image sweep.
  run grep -F '/usr/libexec/tunaos/verify-nvidia' "$OVERLAY_SH"
  [ "$status" -eq 0 ]
}

# ── install layer: the load-bearing lines of 20-nvidia.sh ──────────────────

@test "20-nvidia.sh installs the akmods kmod with an exact kernel EVR match" {
  # The glob kmod-nvidia-${KERNEL_VRA}-*.rpm is the mechanism that makes a
  # kernel/kmod mismatch a loud dnf failure instead of a black screen.
  run grep -F '/tmp/akmods-nvidia-open-rpms/kmods/kmod-nvidia-"${KERNEL_VRA}"-*.rpm' "$INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F "KERNEL_VRA=\"\$(rpm -q \"\$KERNEL_NAME\" --queryformat '%{EVR}.%{ARCH}')\"" "$INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "20-nvidia.sh refuses version skew between kmod and userspace driver" {
  run grep -F '"$KMOD_VERSION" != "$DRIVER_VERSION"' "$INSTALL_SH"
  [ "$status" -eq 0 ]
  # The mismatch branch must exit non-zero, not warn.
  run grep -A2 -F '"$KMOD_VERSION" != "$DRIVER_VERSION"' "$INSTALL_SH"
  [[ "$output" == *"exit 1"* ]]
}

@test "20-nvidia.sh blacklists nouveau and sets the modeset karg" {
  run grep -F 'blacklist nouveau' "$INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F 'nvidia-drm.modeset=1' "$INSTALL_SH"
  [ "$status" -eq 0 ]
  run grep -F '/usr/lib/bootc/kargs.d/00-nvidia.toml' "$INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "20-nvidia.sh avoids dnf config-manager (dnf4/dnf5 split across variants)" {
  # EL10 variants carry dnf4 (--set-enabled), bonito carries dnf5 (setopt);
  # either spelling breaks the other family. Repos are enabled per
  # transaction instead.
  # Match only code, not the header comment that documents this rule.
  run grep -E '^[^#]*dnf config-manager' "$INSTALL_SH"
  [ "$status" -ne 0 ]
  # The repo is derived (epel-nvidia vs fedora-nvidia) and enabled
  # per-transaction through the variable, never hardcoded.
  run grep -F -- '--enablerepo="${NVIDIA_REPO_ID}"' "$INSTALL_SH"
  [ "$status" -eq 0 ]
}

@test "20-nvidia.sh rebuilds the initramfs after installing the driver" {
  run grep -E 'dracut .*--kver "\$QUALIFIED_KERNEL"' "$INSTALL_SH"
  [ "$status" -eq 0 ]
}

# ── contract: verify-nvidia.sh behavioral tests against a fixture root ─────
#
# The script takes TUNAOS_NVIDIA_VERIFY_ROOT (same pattern as
# TUNAOS_OS_RELEASE in verify-branding.sh) and resolves rpm/modinfo/
# systemctl from PATH, so the real logic runs against a fake tree and stub
# tools. Each mutation below was verified to fail before the corresponding
# fixture piece existed.

KVER="6.12.0-55.el10.x86_64"

make_stub_tools() {
  # rpm stub: answers -q kernel and -q <pkg> --queryformat %{VERSION}.
  mkdir -p "${BATS_TEST_TMPDIR}/bin"
  cat > "${BATS_TEST_TMPDIR}/bin/rpm" <<STUB
#!/usr/bin/env bash
args="\$*"
case "\$args" in
  *"-q kernel"*) echo "${KVER}"; exit 0 ;;
  *kmod-nvidia*|*nvidia-driver-cuda*|*nvidia-container-toolkit*) printf '580.10.01'; exit 0 ;;
  *nvidia-driver*) printf '580.10.01'; exit 0 ;;
esac
exit 1
STUB
  cat > "${BATS_TEST_TMPDIR}/bin/modinfo" <<'STUB'
#!/usr/bin/env bash
echo "580.10.01"
STUB
  cat > "${BATS_TEST_TMPDIR}/bin/systemctl" <<'STUB'
#!/usr/bin/env bash
exit 0
STUB
  chmod +x "${BATS_TEST_TMPDIR}/bin/"*
}

make_good_root() {
  local r="${BATS_TEST_TMPDIR}/root"
  mkdir -p \
    "$r/usr/lib/modules/${KVER}/extra/nvidia" \
    "$r/usr/lib/modprobe.d" \
    "$r/usr/lib/bootc/kargs.d" \
    "$r/usr/share/glvnd/egl_vendor.d" \
    "$r/usr/share/vulkan/icd.d" \
    "$r/usr/lib64/gbm" \
    "$r/usr/lib/dracut/dracut.conf.d" \
    "$r/usr/lib/systemd/system"
  touch "$r/usr/lib/modules/${KVER}/extra/nvidia/nvidia.ko.xz"
  echo "blacklist nouveau" > "$r/usr/lib/modprobe.d/00-nouveau-blacklist.conf"
  echo 'kargs = ["rd.driver.blacklist=nouveau", "modprobe.blacklist=nouveau", "nvidia-drm.modeset=1"]' \
    > "$r/usr/lib/bootc/kargs.d/00-nvidia.toml"
  echo '{}' > "$r/usr/share/glvnd/egl_vendor.d/10_nvidia.json"
  echo '{}' > "$r/usr/share/vulkan/icd.d/nvidia_icd.x86_64.json"
  touch "$r/usr/lib64/libEGL_nvidia.so.0" "$r/usr/lib64/libGLX_nvidia.so.0"
  touch "$r/usr/lib64/gbm/nvidia-drm_gbm.so"
  echo 'force_drivers+=" i915 amdgpu nvidia nvidia-drm "' \
    > "$r/usr/lib/dracut/dracut.conf.d/99-nvidia.conf"
  echo "$r"
}

run_verify() {
  PATH="${BATS_TEST_TMPDIR}/bin:$PATH" \
    TUNAOS_NVIDIA_VERIFY_ROOT="$1" \
    run bash "$VERIFY_SH"
}

@test "verify-nvidia passes on a complete driver install" {
  make_stub_tools
  root="$(make_good_root)"
  run_verify "$root"
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_NVIDIA_CONTRACT_OK"* ]]
}

@test "verify-nvidia fails when the kmod is for a different kernel" {
  make_stub_tools
  root="$(make_good_root)"
  rm "$root/usr/lib/modules/${KVER}/extra/nvidia/nvidia.ko.xz"
  run_verify "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"TUNAOS_NVIDIA_CONTRACT_FAIL"* ]]
}

@test "verify-nvidia fails on kmod/userspace version skew" {
  make_stub_tools
  # Re-stub rpm so nvidia-driver reports a different version. Order matters:
  # the kmod-nvidia arm must match before the nvidia-driver arm, since
  # "kmod-nvidia" contains "nvidia-driver" as a substring? It does not — but
  # keep the arms explicit so the stub stays legible.
  cat > "${BATS_TEST_TMPDIR}/bin/rpm" <<STUB
#!/usr/bin/env bash
args="\$*"
case "\$args" in
  *"-q kernel"*) echo "${KVER}"; exit 0 ;;
  *kmod-nvidia*) printf '580.10.01'; exit 0 ;;
  *nvidia-driver-cuda*|*nvidia-container-toolkit*) printf '580.10.01'; exit 0 ;;
  *nvidia-driver*) printf '570.99.99'; exit 0 ;;
esac
exit 1
STUB
  chmod +x "${BATS_TEST_TMPDIR}/bin/rpm"
  root="$(make_good_root)"
  run_verify "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"version skew"* ]]
}

@test "verify-nvidia fails when the Wayland GBM backend is missing" {
  make_stub_tools
  root="$(make_good_root)"
  rm "$root/usr/lib64/gbm/nvidia-drm_gbm.so"
  run_verify "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nvidia-drm_gbm.so"* ]]
}

@test "verify-nvidia fails when the modeset karg is absent" {
  make_stub_tools
  root="$(make_good_root)"
  echo 'kargs = ["rd.driver.blacklist=nouveau"]' \
    > "$root/usr/lib/bootc/kargs.d/00-nvidia.toml"
  run_verify "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nvidia-drm.modeset=1"* ]]
}

@test "verify-nvidia fails when a shipped suspend unit is disabled" {
  make_stub_tools
  root="$(make_good_root)"
  touch "$root/usr/lib/systemd/system/nvidia-suspend.service"
  cat > "${BATS_TEST_TMPDIR}/bin/systemctl" <<'STUB'
#!/usr/bin/env bash
exit 1
STUB
  chmod +x "${BATS_TEST_TMPDIR}/bin/systemctl"
  run_verify "$root"
  [ "$status" -ne 0 ]
  [[ "$output" == *"nvidia-suspend.service is shipped but not enabled"* ]]
}

# ── kernel alignment (10-kernel-swap.sh) ───────────────────────────────────
#
# First contact (kde-nvidia proof run 31189433990): the exact-EVR gate fired
# because yellowfin's Kitten kernel and the akmods kmod kernel disagreed.
# The fix is bluefin-lts's mechanism — swap the image kernel to the one in
# the akmods /kernel-rpms cache, mounted from the SAME image as the kmods —
# so equality holds by construction. These tests run the real script against
# fixtures (TUNAOS_AKMODS_DIR / TUNAOS_KERNEL_RPMS_DIR / TUNAOS_AKMODS_CERT_DIR)
# with rpm/dnf/curl/uname stubbed on PATH.

SWAP_SH="${NVIDIA_DIR}/10-kernel-swap.sh"
AKMODS_KVER="6.12.0-247.el10.x86_64"

@test "kernel-swap exists, is executable, and sorts before the driver install" {
  [ -x "$SWAP_SH" ]
  # run_buildscripts_for sorts human-numerically; 10- must precede 20-.
  local first
  first="$(find "$NVIDIA_DIR" -maxdepth 1 -iname '*-*.sh' -type f | sort | head -1)"
  [ "$(basename "$first")" = "10-kernel-swap.sh" ]
}

@test "Containerfile.overlay mounts the akmods kernel cache alongside the kmods" {
  # Both mounts must come from the SAME akmods stage — that identity is the
  # by-construction guarantee.
  grep -qF 'from=akmods_nvidia_open,src=/rpms,dst=/tmp/akmods-nvidia-open-rpms' "${REPO_ROOT}/Containerfile.overlay"
  grep -qF 'from=akmods_nvidia_open,src=/kernel-rpms,dst=/tmp/kernel-rpms' "${REPO_ROOT}/Containerfile.overlay"
}

make_swap_stubs() {
  # $1 = EVR.ARCH that stubbed `rpm -q kernel` reports as installed
  mkdir -p "${BATS_TEST_TMPDIR}/bin"
  cat > "${BATS_TEST_TMPDIR}/bin/uname" <<'STUB'
#!/usr/bin/env bash
echo x86_64
STUB
  cat > "${BATS_TEST_TMPDIR}/bin/rpm" <<STUB
#!/usr/bin/env bash
echo "rpm \$*" >> "${BATS_TEST_TMPDIR}/tool.log"
case "\$*" in
  *"-q kernel"*) echo "$1"; exit 0 ;;
esac
exit 0
STUB
  cat > "${BATS_TEST_TMPDIR}/bin/dnf" <<STUB
#!/usr/bin/env bash
echo "dnf \$*" >> "${BATS_TEST_TMPDIR}/tool.log"
exit 0
STUB
  cat > "${BATS_TEST_TMPDIR}/bin/curl" <<STUB
#!/usr/bin/env bash
exit 0
STUB
  chmod +x "${BATS_TEST_TMPDIR}/bin/"*
}

make_swap_fixture() {
  mkdir -p "${BATS_TEST_TMPDIR}/akmods/kmods" "${BATS_TEST_TMPDIR}/kernel-rpms"
  touch "${BATS_TEST_TMPDIR}/akmods/kmods/kmod-nvidia-${AKMODS_KVER}-580.10.01-1.el10.x86_64.rpm"
  for p in kernel kernel-core kernel-modules kernel-modules-core kernel-modules-extra; do
    touch "${BATS_TEST_TMPDIR}/kernel-rpms/${p}-${AKMODS_KVER}.rpm"
  done
}

run_swap() {
  PATH="${BATS_TEST_TMPDIR}/bin:$PATH" \
    TUNAOS_AKMODS_DIR="${BATS_TEST_TMPDIR}/akmods" \
    TUNAOS_KERNEL_RPMS_DIR="${BATS_TEST_TMPDIR}/kernel-rpms" \
    TUNAOS_AKMODS_CERT_DIR="${BATS_TEST_TMPDIR}/certs" \
    run bash "$SWAP_SH"
}

@test "kernel-swap prints both bundle listings before touching anything" {
  make_swap_stubs "$AKMODS_KVER"
  make_swap_fixture
  run_swap
  [ "$status" -eq 0 ]
  [[ "$output" == *"akmods bundle contents"* ]]
  [[ "$output" == *"kmod-nvidia-${AKMODS_KVER}"* ]]
  [[ "$output" == *"akmods kernel cache contents"* ]]
  [[ "$output" == *"kernel-core-${AKMODS_KVER}.rpm"* ]]
}

@test "kernel-swap is a no-op when the image kernel already matches" {
  make_swap_stubs "$AKMODS_KVER"
  make_swap_fixture
  run_swap
  [ "$status" -eq 0 ]
  [[ "$output" == *"no swap needed"* ]]
  # No erase and no kernel install happened.
  ! grep -q 'rpm --erase' "${BATS_TEST_TMPDIR}/tool.log"
  ! grep -q 'dnf -y install' "${BATS_TEST_TMPDIR}/tool.log"
}

@test "kernel-swap replaces a mismatched kernel with the akmods one" {
  make_swap_stubs "6.12.0-250.el10.x86_64"  # the first-contact Kitten kernel
  make_swap_fixture
  run_swap
  [ "$status" -eq 0 ]
  [[ "$output" == *"swapping image kernel"* ]]
  grep -q -- '--erase kernel' "${BATS_TEST_TMPDIR}/tool.log"
  grep -q "dnf -y install .*kernel-core-${AKMODS_KVER}.rpm" "${BATS_TEST_TMPDIR}/tool.log"
}

@test "kernel-swap fails loudly when the cache holds no kernel at all" {
  make_swap_stubs "$AKMODS_KVER"
  make_swap_fixture
  rm "${BATS_TEST_TMPDIR}/kernel-rpms/"*
  run_swap
  [ "$status" -ne 0 ]
  [[ "$output" == *"could not detect a kernel version"* ]]
}

@test "kernel-swap refuses to run on non-x86_64" {
  make_swap_stubs "$AKMODS_KVER"
  make_swap_fixture
  cat > "${BATS_TEST_TMPDIR}/bin/uname" <<'STUB'
#!/usr/bin/env bash
echo aarch64
STUB
  chmod +x "${BATS_TEST_TMPDIR}/bin/uname"
  run_swap
  [ "$status" -ne 0 ]
  [[ "$output" == *"only supports x86_64"* ]]
}

@test "20-nvidia.sh derives the userspace repo family from the akmods dist tag" {
  # .elNN → epel-nvidia, .fcNN → fedora-nvidia, fallback fedora-43. The el
  # arm must be checked FIRST (an .el10 bundle must never land on Fedora
  # userspace — first contact showed the centos-10 bundle is .el10-tagged).
  grep -qF 'AKMODS_EL_VERSION=' "$INSTALL_SH"
  grep -qF 'NVIDIA_REPO_ID="epel-nvidia"' "$INSTALL_SH"
  run awk '/AKMODS_EL_VERSION.\}. \]\]/{print NR; exit}' "$INSTALL_SH"
  local el_line="$output"
  run awk '/AKMODS_FEDORA_VERSION.\}. \]\]/{print NR; exit}' "$INSTALL_SH"
  [ -n "$el_line" ] && [ -n "$output" ] && [ "$el_line" -lt "$output" ]
  # Both driver transactions must enable the derived repo, not a hardcoded one.
  run grep -c -- '--enablerepo="${NVIDIA_REPO_ID}"' "$INSTALL_SH"
  [ "$output" -eq 2 ]
}

@test "every *-nvidia flavor in build-config is linux/amd64 only" {
  command -v python3 >/dev/null || skip "python3 not installed"
  python3 -c "import yaml" 2>/dev/null || skip "pyyaml not installed"
  run python3 -c "
import yaml
d = yaml.safe_load(open('${REPO_ROOT}/.github/build-config.yml'))
bad = [(v['id'], f['id'], f.get('platforms'))
       for v in d['variants'] for f in v['flavors']
       if 'nvidia' in f['id'] and f.get('platforms') != ['linux/amd64']]
assert not bad, bad
print('ok')
"
  [ "$status" -eq 0 ]
}
