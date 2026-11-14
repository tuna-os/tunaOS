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

@test "detector finds an early -virgl line in a kernel log larger than a pipe" {
  touch "${TUNAOS_DRI_DIR}/renderD128"
  {
    echo '[    4.114331] [drm] features: -virgl +edid -resource_blob -host_visible'
    for i in $(seq 1 3000); do
      echo "[ ${i}.000000] later kernel line ${i} padded past the 64 KiB pipe buffer"
    done
  } > "$TUNAOS_KERNEL_LOG"

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
  grep -qF '/run/tunaos-software-gl ]]' "$GENERATOR"
  grep -qF '/dev/dri/renderD*' "$GENERATOR"
  grep -qF 'WLR_RENDERER=pixman' "$GENERATOR"
}

# tunaOS#3969: gnome-shell SIGSEGVs in libgallium when LIBGL_ALWAYS_SOFTWARE=1
# is forced on a Mesa older than 26.0.2 (albacore: 25.2.7-4.el10.alma.5).
# Falsification: with the generator's old unconditional echo, the first two
# tests below fail (LIBGL_ALWAYS_SOFTWARE=1 is printed for gnome-shell + 25.2.7).
fake_tree() {
  export TUNAOS_GL_ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${TUNAOS_GL_ROOT}/usr/lib64" "${TUNAOS_GL_ROOT}/usr/bin"
}

@test "gnome-shell on Mesa older than 26.0.2 is not forced onto software GL" {
  fake_tree
  : > "${TUNAOS_GL_ROOT}/usr/bin/gnome-shell"; chmod +x "${TUNAOS_GL_ROOT}/usr/bin/gnome-shell"
  : > "${TUNAOS_GL_ROOT}/usr/lib64/libgallium-25.2.7.so"
  run "$GENERATOR"
  [ "$status" -eq 0 ]
  [[ "$output" != *LIBGL_ALWAYS_SOFTWARE* ]]
}

@test "Mesa 26.0.1 is older than 26.0.2 but 26.10.0 is newer (numeric order)" {
  fake_tree
  : > "${TUNAOS_GL_ROOT}/usr/bin/gnome-shell"; chmod +x "${TUNAOS_GL_ROOT}/usr/bin/gnome-shell"
  : > "${TUNAOS_GL_ROOT}/usr/lib64/libgallium-26.0.1.so"
  run "$GENERATOR"
  [[ "$output" != *LIBGL_ALWAYS_SOFTWARE* ]]
  rm "${TUNAOS_GL_ROOT}/usr/lib64/libgallium-26.0.1.so"
  : > "${TUNAOS_GL_ROOT}/usr/lib64/libgallium-26.10.0.so"
  run "$GENERATOR"
  [[ "$output" == *LIBGL_ALWAYS_SOFTWARE=1* ]]
}

@test "gnome-shell on Mesa 26.0.2 or newer keeps software GL" {
  fake_tree
  : > "${TUNAOS_GL_ROOT}/usr/bin/gnome-shell"; chmod +x "${TUNAOS_GL_ROOT}/usr/bin/gnome-shell"
  : > "${TUNAOS_GL_ROOT}/usr/lib64/libgallium-26.0.2.so"
  run "$GENERATOR"
  [[ "$output" == *LIBGL_ALWAYS_SOFTWARE=1* ]]
}

@test "a session without gnome-shell keeps software GL whatever the Mesa" {
  fake_tree
  : > "${TUNAOS_GL_ROOT}/usr/lib64/libgallium-25.2.7.so"
  run "$GENERATOR"
  [[ "$output" == *LIBGL_ALWAYS_SOFTWARE=1* ]]
  [[ "$output" == *KWIN_COMPOSE=Q* ]]
}

@test "a machine with working 3D gets no software GL at all" {
  fake_tree
  mkdir -p "${TUNAOS_GL_ROOT}/dev/dri"; touch "${TUNAOS_GL_ROOT}/dev/dri/renderD128"
  run "$GENERATOR"
  [ -z "$output" ]
}
