#!/usr/bin/env bats
# live-iso/common/src/installer-recipe-backend.sh — the three on-disk-layout
# keys the GUI installer recipe carries.
#
# WHY THIS FILE EXISTS. Until this script, nothing set those keys per variant:
# system_files/etc/bootc-installer/recipe.json shipped a hardcoded
# `bootloader: systemd, composeFsBackend: true, filesystem: xfs` to all 13
# variants, and build_scripts/90-image-info.sh — the only thing that rewrites
# that file — touches branding only. That triple is wrong for the three EL10
# variants, which are traditional ostree + bootupd + GRUB with composefs
# explicitly disabled.
#
# The headless path never caught it because scripts/iso-e2e.sh probes the image
# and builds its own recipe. That is exactly how a cell can be green on LUKS
# E2E while its GUI install has never been proven — the two paths disagreed
# about the same image.
#
# Each branch below is the difference between a bootable disk and a dracut
# emergency shell, so they are checked against fixture trees in seconds rather
# than by a matrix cell that only notices when something fails to boot.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/live-iso/common/src/installer-recipe-backend.sh"

setup() {
  FIXTURE="${BATS_TEST_TMPDIR}/root"
  mkdir -p "$FIXTURE/usr/lib/ostree"
}

# A composefs pin in prepare-root.conf. `signed` counts as enabled, the same as
# yes/true/1 — that is what the probe in scripts/lib/common.sh accepts.
set_composefs() {
  printf '[composefs]\nenabled = %s\n\n[sysroot]\nreadonly = true\n' "$1" \
    >"$FIXTURE/usr/lib/ostree/prepare-root.conf"
}

# bootupd 0.2.x shape: binaries under updates/EFI/<vendor>. The EFI arch suffix
# is a parameter here (x64 / aa64) because it is a parameter in reality, and
# every fixture below that hardcoded x64 is why the arm64 blindness shipped.
add_bootupd_legacy() {
  local efiarch="${1:-x64}"
  mkdir -p "$FIXTURE/usr/lib/bootupd/updates/EFI/almalinux"
  touch "$FIXTURE/usr/lib/bootupd/updates/EFI/almalinux/grub${efiarch}.efi"
}

# Current Fedora shape: only EFI.json under bootupd/updates, versioned binaries
# under /usr/lib/efi. The probe requires ALL THREE, which is what stops a bare
# EFI.json from being read as a payload.
add_bootupd_modern() {
  local efiarch="${1:-x64}"
  mkdir -p "$FIXTURE/usr/lib/bootupd/updates" \
    "$FIXTURE/usr/lib/efi/grub2/${efiarch}" "$FIXTURE/usr/lib/efi/shim/${efiarch}"
  touch "$FIXTURE/usr/lib/bootupd/updates/EFI.json"
  touch "$FIXTURE/usr/lib/efi/grub2/${efiarch}/grub${efiarch}.efi"
  touch "$FIXTURE/usr/lib/efi/shim/${efiarch}/shim${efiarch}.efi"
}

add_systemd_boot() {
  local efiarch="${1:-x64}"
  mkdir -p "$FIXTURE/usr/lib/systemd/boot/efi"
  touch "$FIXTURE/usr/lib/systemd/boot/efi/systemd-boot${efiarch}.efi"
}

probe() {
  run bash "$SCRIPT" "$FIXTURE"
}

# ── EL10: the case that was actually broken ──────────────────────────────────

@test "el10 (bootupd payload, composefs off) installs ostree/grub2 on xfs" {
  add_bootupd_legacy
  set_composefs no
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=grub2"* ]]
  [[ "$output" == *"composeFsBackend=false"* ]]
  [[ "$output" == *"filesystem=xfs"* ]]
}

@test "el10 with no prepare-root.conf at all is still ostree/grub2/xfs" {
  # The EL10 pin is written late in Containerfile.el10; an image that never
  # got one must not fall through to the composefs branch.
  add_bootupd_legacy
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=grub2"* ]]
  [[ "$output" == *"filesystem=xfs"* ]]
}

# ── Ordering: bootupd wins over a composefs pin ──────────────────────────────

@test "sealed image that still ships bootupd stays on the ostree path" {
  # THE ORDER IS LOAD-BEARING (scripts/lib/common.sh). bootupd is checked
  # first so this image keeps grub2 — but it is sealed, so it must still get
  # ext4. Backend and filesystem are separate questions and this is the case
  # that proves it: keying the filesystem off the backend would hand a sealed
  # rootfs to XFS, which has no fs-verity, and the install would boot into a
  # dracut emergency shell.
  add_bootupd_legacy
  set_composefs yes
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=grub2"* ]]
  [[ "$output" == *"composeFsBackend=false"* ]]
  [[ "$output" == *"filesystem=ext4"* ]]
}

@test "the modern three-part bootupd payload is recognised" {
  add_bootupd_modern
  set_composefs no
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=grub2"* ]]
}

@test "a bare EFI.json with no efi binaries is not a bootupd payload" {
  # Guards the two-form test: EFI.json alone must not claim the ostree path,
  # because an ostree install without a real payload aborts with
  # "bootupd is required for ostree-based installs".
  mkdir -p "$FIXTURE/usr/lib/bootupd/updates"
  touch "$FIXTURE/usr/lib/bootupd/updates/EFI.json"
  set_composefs yes
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=systemd"* ]]
  [[ "$output" == *"composeFsBackend=true"* ]]
}

# ── composefs-native bases ───────────────────────────────────────────────────

@test "composefs pin with no bootupd installs systemd-boot on ext4" {
  set_composefs yes
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=systemd"* ]]
  [[ "$output" == *"composeFsBackend=true"* ]]
  [[ "$output" == *"filesystem=ext4"* ]]
}

@test "enabled = signed counts as sealed" {
  set_composefs signed
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"filesystem=ext4"* ]]
}

@test "systemd-boot alone (the dakota shape) is composefs-native on xfs" {
  # No composefs pin, so nothing is sealed and xfs is correct here.
  add_systemd_boot
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=systemd"* ]]
  [[ "$output" == *"composeFsBackend=true"* ]]
  [[ "$output" == *"filesystem=xfs"* ]]
}

# ── aarch64: the same three shapes, spelled the way arm64 spells them ────────
#
# REGRESSION COVERAGE. The probe used to name grubx64/shimx64/systemd-bootx64
# literally, so on aarch64 — where the EFI suffix is aa64 — every branch missed
# and the script exited with "cannot determine the bootc backend". That failed
# the arm64 ISO for every desktop while the amd64 leg of the same cell passed,
# and nothing here noticed because every fixture above was x64. Measured on
# ghcr.io/tuna-os/albacore:kde-linux-arm64, which carries the legacy payload
# /usr/lib/bootupd/updates/EFI/almalinux/{grubaa64,shimaa64}.efi.

@test "aarch64 legacy bootupd payload (grubaa64) is recognised as ostree" {
  add_bootupd_legacy aa64
  set_composefs no
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=grub2"* ]]
  [[ "$output" == *"composeFsBackend=false"* ]]
  [[ "$output" == *"filesystem=xfs"* ]]
}

@test "aarch64 modern bootupd payload (grubaa64 + shimaa64) is recognised" {
  add_bootupd_modern aa64
  set_composefs no
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=grub2"* ]]
}

@test "aarch64 systemd-boot (systemd-bootaa64) is composefs-native" {
  add_systemd_boot aa64
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=systemd"* ]]
  [[ "$output" == *"composeFsBackend=true"* ]]
}

# ── Never guess ──────────────────────────────────────────────────────────────

@test "an unclassifiable image fails instead of guessing" {
  # No payload, no pin, no systemd-boot. A guess in either direction produces
  # an unbootable disk whose failure surfaces minutes later with nothing
  # pointing back here, so this must be fatal at ISO-build time.
  probe
  [ "$status" -ne 0 ]
  [[ "$output" == *"cannot determine the bootc backend"* ]]
}

@test "aarch64 EFI.json with grubaa64 but no shim is not a bootupd payload" {
  # The globbing must not have loosened the two-form test into a one-form test.
  # This is the arm64 twin of the bare-EFI.json guard above.
  mkdir -p "$FIXTURE/usr/lib/bootupd/updates" "$FIXTURE/usr/lib/efi/grub2/aa64"
  touch "$FIXTURE/usr/lib/bootupd/updates/EFI.json"
  touch "$FIXTURE/usr/lib/efi/grub2/aa64/grubaa64.efi"
  set_composefs yes
  probe
  [ "$status" -eq 0 ]
  [[ "$output" == *"bootloader=systemd"* ]]
  [[ "$output" == *"composeFsBackend=true"* ]]
}
