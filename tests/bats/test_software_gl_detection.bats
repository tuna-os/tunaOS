#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
DETECTOR="${REPO_ROOT}/system_files/usr/libexec/tunaos/detect-software-gl"
GENERATOR="${REPO_ROOT}/system_files/usr/lib/systemd/user-environment-generators/60-tunaos-software-gl"
UNIT="${REPO_ROOT}/system_files/usr/lib/systemd/system/tunaos-software-gl-detect.service"
PRESET="${REPO_ROOT}/system_files/usr/lib/systemd/system-preset/50-tunaos.preset"
SERVICES="${REPO_ROOT}/build_scripts/40-services.sh"

setup() {
  export TUNAOS_DRI_DIR="${BATS_TEST_TMPDIR}/dri"
  export TUNAOS_SOFTWARE_GL_FLAG="${BATS_TEST_TMPDIR}/software-gl"
  export TUNAOS_KERNEL_LOG="${BATS_TEST_TMPDIR}/kernel.log"
  mkdir -p "$TUNAOS_DRI_DIR"
  : > "$TUNAOS_KERNEL_LOG"
}

@test "detector requests software GL when no render node exists" {
  run "$DETECTOR"
  [ "$status" -eq 0 ]
  [ -f "$TUNAOS_SOFTWARE_GL_FLAG" ]
}

@test "detector leaves working render nodes on hardware GL" {
  touch "${TUNAOS_DRI_DIR}/renderD128"
  printf '%s\n' '[drm] features: +virgl +edid +resource_blob +host_visible' > "$TUNAOS_KERNEL_LOG"

  run "$DETECTOR"
  [ "$status" -eq 0 ]
  [ ! -e "$TUNAOS_SOFTWARE_GL_FLAG" ]
}

@test "detector catches virtio-gpu without virgl despite its render node" {
  touch "${TUNAOS_DRI_DIR}/renderD128"
  cat > "$TUNAOS_KERNEL_LOG" <<'EOF'
[drm] pci: virtio-vga detected at 0000:00:02.0
[drm] features: -virgl +edid -resource_blob -host_visible
[drm] number of cap sets: 0
EOF

  run "$DETECTOR"
  [ "$status" -eq 0 ]
  [ -f "$TUNAOS_SOFTWARE_GL_FLAG" ]
}

@test "detector does not force software when the privileged evidence is unavailable" {
  touch "${TUNAOS_DRI_DIR}/renderD128"
  export TUNAOS_KERNEL_LOG="${BATS_TEST_TMPDIR}/missing"
  run "$DETECTOR"
  [ "$status" -eq 0 ]
  [ ! -e "$TUNAOS_SOFTWARE_GL_FLAG" ]
}

@test "boot detector runs before greeters and survives first-boot presets" {
  grep -qF 'Before=display-manager.service systemd-user-sessions.service' "$UNIT"
  grep -qF 'WantedBy=multi-user.target' "$UNIT"
  grep -qF 'systemctl enable tunaos-software-gl-detect.service' "$SERVICES"
  grep -qF 'enable tunaos-software-gl-detect.service' "$PRESET"
}

@test "session generator consumes the detector flag and retains no-node fallback" {
  grep -qF '[[ ! -e /run/tunaos-software-gl ]]' "$GENERATOR"
  grep -qF "compgen -G '/dev/dri/renderD*'" "$GENERATOR"
  grep -qF 'WLR_RENDERER=pixman' "$GENERATOR"
}
