#!/usr/bin/env bats
# build_scripts/bootc/ostree-layout.sh — the shared bootc filesystem layout.
#
# The script exists because four hand-written copies of the same layout drifted
# (Gentoo lost /srv, /mnt and /usr/local). These tests run it against fixture
# trees, so the invariants are checked in seconds rather than by a 40-minute
# matrix cell that only notices when something fails to boot.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/bootc/ostree-layout.sh"

# A base image's shape before the layout runs: the alias directories are real
# directories with content in them, and /var holds package-manager state.
make_fixture() {
  local root="$1"
  mkdir -p "$root"/{boot,home,root,srv,opt,mnt} "$root"/usr/local/bin \
    "$root"/var/lib/dpkg "$root"/var/cache/apt "$root"/etc/default \
    "$root"/usr/lib/tmpfiles.d
  echo stale >"$root/var/lib/dpkg/status"
  echo "HOME=/home" >"$root/etc/default/useradd"
}

setup() {
  FIXTURE="${BATS_TEST_TMPDIR}/root"
  make_fixture "$FIXTURE"
}

run_layout() {
  TUNAOS_SYSROOT="$FIXTURE" run bash "$SCRIPT" "$@"
}

@test "ostree-layout.sh: every alias becomes a symlink into /var" {
  run_layout
  [ "$status" -eq 0 ]
  [ "$(readlink "$FIXTURE/root")" = "var/roothome" ]
  [ "$(readlink "$FIXTURE/home")" = "var/home" ]
  [ "$(readlink "$FIXTURE/opt")" = "var/opt" ]
  [ "$(readlink "$FIXTURE/srv")" = "var/srv" ]
  [ "$(readlink "$FIXTURE/mnt")" = "var/mnt" ]
  [ "$(readlink "$FIXTURE/ostree")" = "sysroot/ostree" ]
  # Two levels down, so the target needs the extra ../
  [ "$(readlink "$FIXTURE/usr/local")" = "../var/usrlocal" ]
}

@test "ostree-layout.sh: /srv, /mnt and /usr/local are not dropped" {
  # The exact three Gentoo removed and never recreated. Named separately from
  # the test above so a regression says which ones went missing.
  run_layout
  [ "$status" -eq 0 ]
  for p in srv mnt usr/local; do
    [ -L "$FIXTURE/$p" ]
  done
}

@test "ostree-layout.sh: every alias target exists on disk, not only in tmpfiles" {
  # Maintainer scripts in later layers do `[ ! -d /mnt ] && mkdir /mnt`, and
  # mkdir on a dangling symlink fails with EEXIST and takes the layer with it.
  run_layout
  [ "$status" -eq 0 ]
  for d in roothome home opt srv mnt usrlocal tmp; do
    [ -d "$FIXTURE/var/$d" ]
  done
}

@test "ostree-layout.sh: /var is wiped and /var/tmp is world-writable" {
  run_layout
  [ "$status" -eq 0 ]
  [ ! -e "$FIXTURE/var/lib/dpkg/status" ]
  [ ! -d "$FIXTURE/var/cache" ]
  [ "$(stat -c '%a' "$FIXTURE/var/tmp")" = "1777" ]
  [ "$(stat -c '%a' "$FIXTURE/var/roothome")" = "700" ]
}

@test "ostree-layout.sh: declares composefs on by default" {
  run_layout
  [ "$status" -eq 0 ]
  grep -q '^\[composefs\]' "$FIXTURE/usr/lib/ostree/prepare-root.conf"
  grep -q '^enabled = yes' "$FIXTURE/usr/lib/ostree/prepare-root.conf"
  grep -q '^readonly = true' "$FIXTURE/usr/lib/ostree/prepare-root.conf"
}

@test "ostree-layout.sh: TUNAOS_COMPOSEFS=no writes a traditional ostree image" {
  TUNAOS_SYSROOT="$FIXTURE" TUNAOS_COMPOSEFS=no run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -q '^enabled = no' "$FIXTURE/usr/lib/ostree/prepare-root.conf"
}

@test "ostree-layout.sh: rejects a TUNAOS_COMPOSEFS value it does not understand" {
  # A typo must not silently produce `enabled = tru` — prepare-root.conf is
  # parsed loosely and a bad value reads as "off", which boots to emergency.
  TUNAOS_SYSROOT="$FIXTURE" TUNAOS_COMPOSEFS=tru run bash "$SCRIPT"
  [ "$status" -ne 0 ]
  [ ! -f "$FIXTURE/usr/lib/ostree/prepare-root.conf" ]
}

@test "ostree-layout.sh: output feeds dracut-config.sh's composefs probe" {
  # These two scripts communicate only through prepare-root.conf. If the format
  # one writes stops matching the pattern the other greps for, every composefs
  # variant silently loses its erofs driver — so assert the handshake, not each
  # side's spelling.
  run_layout
  [ "$status" -eq 0 ]
  mkdir -p "$FIXTURE/usr/lib/modules/6.0.0-test"
  : >"$FIXTURE/usr/lib/modules/6.0.0-test/erofs.ko"
  : >"$FIXTURE/usr/lib/modules/6.0.0-test/overlay.ko"
  TUNAOS_SYSROOT="$FIXTURE" run bash "${REPO_ROOT}/build_scripts/bootc/dracut-config.sh"
  [ "$status" -eq 0 ]
  [[ "$output" == *"composefs: 1"* ]]
  grep -q 'add_drivers.*erofs' "$FIXTURE/usr/lib/dracut/dracut.conf.d/30-bootc-container-build.conf"
}

@test "ostree-layout.sh: is idempotent" {
  # bootc builds re-run layers; a second pass must not fail on the symlinks the
  # first one created.
  run_layout
  [ "$status" -eq 0 ]
  run_layout
  [ "$status" -eq 0 ]
  [ "$(readlink "$FIXTURE/usr/local")" = "../var/usrlocal" ]
}

@test "ostree-layout.sh: points useradd at /var/home when the file exists" {
  run_layout
  [ "$status" -eq 0 ]
  grep -q '^HOME=/var/home$' "$FIXTURE/etc/default/useradd"
}

@test "ostree-layout.sh: passes shellcheck" {
  if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
  run shellcheck --severity=error --exclude=SC1091 "$SCRIPT"
  [ "$status" -eq 0 ]
}

# ── Containerfile wiring ─────────────────────────────────────────────────────

@test "no Containerfile writes prepare-root.conf by hand where the script is wired" {
  # The point of the shared script is that there is one place to change. A
  # Containerfile that calls it AND printfs its own prepare-root.conf has two.
  for f in Containerfile.arch Containerfile.debian Containerfile.gentoo; do
    grep -q 'bootc/ostree-layout.sh' "${REPO_ROOT}/$f"
    ! grep -q "printf '\[composefs\]" "${REPO_ROOT}/$f"
  done
}

@test "every variant lays out the filesystem before building the initramfs" {
  # dracut-config.sh reads prepare-root.conf, which ostree-layout.sh writes.
  # Reversed, the initramfs is built with composefs undetected and no erofs
  # driver — an image that cannot mount its own root, and silent about it.
  #
  # Gentoo was excluded here while it built its initramfs first and called no
  # dracut-config.sh at all. It now does both, in this order, and the per-stage
  # version of this check lives in test_gentoo_dracut_config.bats — that file
  # also records what the omission cost (LUKS run 31232170155).
  for f in Containerfile.arch Containerfile.debian Containerfile.gentoo; do
    local layout dracut
    layout=$(grep -n 'bootc/ostree-layout.sh' "${REPO_ROOT}/$f" | head -1 | cut -d: -f1)
    dracut=$(grep -n 'bootc/dracut-config.sh' "${REPO_ROOT}/$f" | head -1 | cut -d: -f1)
    [ -n "$layout" ]
    [ -n "$dracut" ]
    [ "$layout" -lt "$dracut" ]
  done
}

@test "gentoo carries one layout block per stage, not two copies of the text" {
  # The `system` and `desktop` stages had byte-identical 25-line RUN blocks.
  # Each stage still needs its own call; what must not come back is the body.
  local f="${REPO_ROOT}/Containerfile.gentoo"
  # Count invocations, not mentions — the header comment above each call names
  # the script too, and matching that would pass with the calls deleted.
  local calls
  calls=$(grep -v '^[[:space:]]*#' "$f" | grep -c 'bootc/ostree-layout.sh')
  [ "$calls" -eq 2 ]
  [ "$(grep -c 'bootc-base-dirs.conf' "$f")" -eq 0 ]
}

# ── the kernel rescue ────────────────────────────────────────────────────────
#
# /boot is wiped by this script, and on some bases it holds the only copy of
# the kernel. marlin's arm64 images shipped with no kernel at all for exactly
# this reason, and the ISO failure surfaced an hour downstream in another
# repository, so these cases are checked here rather than by a matrix cell.

@test "ostree-layout.sh: rescues a kernel that only exists as /boot/Image" {
  mkdir -p "$FIXTURE/usr/lib/modules/7.2.6-1-aarch64-ARCH"
  echo real-kernel >"$FIXTURE/boot/Image"

  run_layout
  [ "$status" -eq 0 ]
  [ "$(cat "$FIXTURE/usr/lib/modules/7.2.6-1-aarch64-ARCH/vmlinuz")" = "real-kernel" ]
}

@test "ostree-layout.sh: rescues a kernel that only exists as /boot/vmlinuz-<ver>" {
  mkdir -p "$FIXTURE/usr/lib/modules/6.12.0-deb"
  echo real-kernel >"$FIXTURE/boot/vmlinuz-6.12.0-deb"

  run_layout
  [ "$status" -eq 0 ]
  [ "$(cat "$FIXTURE/usr/lib/modules/6.12.0-deb/vmlinuz")" = "real-kernel" ]
}

# Image.gz is not EFI-bootable on aarch64, and Arch Linux ARM ships both.
@test "ostree-layout.sh: prefers the uncompressed kernel over Image.gz" {
  mkdir -p "$FIXTURE/usr/lib/modules/7.2.6-1-aarch64-ARCH"
  echo real-kernel >"$FIXTURE/boot/Image"
  echo compressed >"$FIXTURE/boot/Image.gz"

  run_layout
  [ "$status" -eq 0 ]
  [ "$(cat "$FIXTURE/usr/lib/modules/7.2.6-1-aarch64-ARCH/vmlinuz")" = "real-kernel" ]
}

# Every variant but Arch ARM is already in this state. Overwriting the kernel
# the package manager installed with whatever /boot happens to hold would be a
# regression on all of them.
@test "ostree-layout.sh: leaves an existing vmlinuz alone" {
  mkdir -p "$FIXTURE/usr/lib/modules/6.16.1-arch1-1"
  echo installed >"$FIXTURE/usr/lib/modules/6.16.1-arch1-1/vmlinuz"
  echo decoy >"$FIXTURE/boot/vmlinuz-linux"

  run_layout
  [ "$status" -eq 0 ]
  [ "$(cat "$FIXTURE/usr/lib/modules/6.16.1-arch1-1/vmlinuz")" = "installed" ]
}

# The toolchain and common images run this script and carry no kernel by
# design, so an absent one is not an error to raise here.
@test "ostree-layout.sh: an image with no kernel at all still lays out" {
  mkdir -p "$FIXTURE/usr/lib/modules/6.1.0"

  run_layout
  [ "$status" -eq 0 ]
  [ ! -e "$FIXTURE/usr/lib/modules/6.1.0/vmlinuz" ]
}

# Guessing here ships an image that boots the wrong kernel, which is worse
# than stopping the build.
@test "ostree-layout.sh: refuses to guess between two kernel trees" {
  mkdir -p "$FIXTURE/usr/lib/modules/6.1.0" "$FIXTURE/usr/lib/modules/6.2.0"
  echo real-kernel >"$FIXTURE/boot/Image"

  run_layout
  [ "$status" -ne 0 ]
  [[ "$output" == *"more than one kernel tree"* ]]
}
