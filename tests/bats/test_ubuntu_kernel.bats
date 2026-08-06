#!/usr/bin/env bats
# build_scripts/ubuntu-kernel.sh — which kernel the apt bases get.
#
# The defect this covers: gurnard shipped noble's GA kernel, 6.8, which has no
# CONFIG_EROFS_FS_BACKED_BY_FILE (that landed in 6.12). Our images are
# composefs-native, and bootc mounts the composefs image by handing EROFS an
# open file — `source=/proc/self/fd/<n>` — so on 6.8 EROFS falls through to
# get_tree_bdev and the install dies after the disk is already partitioned and
# LUKS-formatted:
#
#   e /proc/self/fd/19: Can't lookup blockdev
#   error: ... Setting up composefs boot: Failed to mount composefs image:
#          ... Creating filesystem mount: Block device required (os error 15)
#
# (LUKS run 31071830439.) resolute's GA kernel has the symbol and noble's HWE
# kernel has it, so the assertions here are about the property, not the fix:
# the kernel is chosen by reading the .config of the kernel about to be
# installed, a base with no usable kernel fails the build instead of shipping,
# and a base whose GA kernel is fine is left alone.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/ubuntu-kernel.sh"

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  ARCHIVE="${BATS_TEST_TMPDIR}/archive"
  MODULES="${BATS_TEST_TMPDIR}/usr/lib/modules"
  BOOT="${BATS_TEST_TMPDIR}/boot"
  LOG="${BATS_TEST_TMPDIR}/apt.log"
  mkdir -p "$BIN" "$ARCHIVE" "$MODULES" "$BOOT"
  : >"$LOG"

  # A fake archive: one directory per kernel meta-package, holding the version
  # it would install and whether that kernel's .config has the symbol. Absent
  # config = the archive publishes no linux-buildinfo for it.
  publish() { # publish <meta-pkg> <kver> [y|n]
    mkdir -p "${ARCHIVE}/$1"
    echo "$2" >"${ARCHIVE}/$1/kver"
    [ -n "${3:-}" ] && echo "$3" >"${ARCHIVE}/${1}/file_backed_erofs"
    return 0
  }

  cat >"${BIN}/apt-get" <<EOF
#!/usr/bin/env bash
echo "apt-get \$*" >>"${LOG}"
case " \$* " in
  *" -s "*)
      for a in "\$@"; do
        [ -f "${ARCHIVE}/\${a}/kver" ] || continue
        echo "Inst linux-image-\$(cat "${ARCHIVE}/\${a}/kver") (1:0 Ubuntu [amd64])"
      done
      ;;
  *" download "*)
      kver=\${!#}; kver=\${kver#linux-buildinfo-}
      flag=""
      for d in "${ARCHIVE}"/*; do
        [ "\$(cat "\${d}/kver" 2>/dev/null)" = "\$kver" ] || continue
        [ -f "\${d}/file_backed_erofs" ] && flag="\$(cat "\${d}/file_backed_erofs")"
      done
      [ -n "\$flag" ] || exit 1
      mkdir -p "buildinfo/usr/lib/linux/\${kver}"
      {
        echo "CONFIG_EROFS_FS=m"
        [ "\$flag" = y ] && echo "CONFIG_EROFS_FS_BACKED_BY_FILE=y"
      } >"buildinfo/usr/lib/linux/\${kver}/config"
      tar -cf "linux-buildinfo-\${kver}_amd64.deb" -C buildinfo .
      rm -rf buildinfo
      ;;
  *" install "*)
      # Stage what a real kernel install leaves behind, for the kver that the
      # requested meta-package resolves to.
      for a in "\$@"; do
        [ -f "${ARCHIVE}/\${a}/kver" ] || continue
        kver="\$(cat "${ARCHIVE}/\${a}/kver")"
        mkdir -p "${MODULES}/\${kver}"
        echo "vmlinuz-\${kver}" >"${BOOT}/vmlinuz-\${kver}"
      done
      ;;
esac
exit 0
EOF

  # apt-cache search: names only, one "<pkg> - description" line per match.
  cat >"${BIN}/apt-cache" <<EOF
#!/usr/bin/env bash
pattern="\${!#}"
for d in "${ARCHIVE}"/*; do
  [ -d "\$d" ] || continue
  name="\$(basename "\$d")"
  [[ "\$name" =~ \$pattern ]] && echo "\$name - a kernel"
done
exit 0
EOF

  # dpkg-deb -x on the tarball the download stub wrote.
  cat >"${BIN}/dpkg-deb" <<'EOF'
#!/usr/bin/env bash
[ "$1" = "-x" ] || exit 1
mkdir -p "$3" && tar -xf "$2" -C "$3"
EOF

  # Only --print-architecture is faked (so the asahi arch guard answers the same
  # on any test host); --compare-versions is the real thing, because the version
  # fallback's ordering is exactly what is under test.
  cat >"${BIN}/dpkg" <<EOF
#!/usr/bin/env bash
if [ "\$1" = "--print-architecture" ]; then
  cat "${BATS_TEST_TMPDIR}/arch" 2>/dev/null || echo amd64
  exit 0
fi
exec "$(command -v dpkg)" "\$@"
EOF

  # The script's cleanup is `rm -rf "${APT_LISTS_DIR}"/*`. Left at its default
  # that is the HOST's /var/lib/apt/lists: unwritable on the GitHub runner, so
  # rm exits non-zero and `set -e` failed every success-path test here; and
  # writable anywhere the suite runs as root, where it silently deleted them.
  APT_LISTS="${BATS_TEST_TMPDIR}/apt-lists"
  mkdir -p "$APT_LISTS"
  : >"${APT_LISTS}/keep"

  chmod +x "${BIN}/apt-get" "${BIN}/apt-cache" "${BIN}/dpkg-deb" "${BIN}/dpkg"
  PATH="${BIN}:${PATH}"
  export PATH MODULES_DIR="${MODULES}" BOOT_DIR="${BOOT}" APT_LISTS_DIR="${APT_LISTS}"
}

run_script() {
  run env MODULES_DIR="$MODULES" BOOT_DIR="$BOOT" APT_LISTS_DIR="$APT_LISTS" bash "$SCRIPT"
}

installed_pkg() {
  # The meta-package the (non-simulated) install was asked for.
  grep -E '^apt-get .* install ' "$LOG" | grep -v ' -s ' |
    grep -oE 'linux-generic(-hwe-[0-9.]+)?' | head -1
}

@test "a GA kernel that can mount composefs is left alone (resolute)" {
  publish linux-generic 7.0.0-29-generic y
  publish linux-generic-hwe-24.04 7.0.0-28-generic y
  run_script
  [ "$status" -eq 0 ]
  [ "$(installed_pkg)" = "linux-generic" ]
}

@test "a GA kernel without file-backed erofs is replaced by HWE (noble)" {
  publish linux-generic 6.8.0-137-generic n
  publish linux-generic-hwe-24.04 7.0.0-28-generic y
  run_script
  [ "$status" -eq 0 ]
  [ "$(installed_pkg)" = "linux-generic-hwe-24.04" ]
  # And the staged vmlinuz is the HWE one, not a 6.8 left over from the probe.
  [ -f "${MODULES}/7.0.0-28-generic/vmlinuz" ]
}

@test "the build fails when no available kernel can mount composefs" {
  publish linux-generic 6.8.0-137-generic n
  publish linux-generic-hwe-24.04 6.11.0-1-generic n
  run_script
  [ "$status" -ne 0 ]
  [[ "$output" == *"CONFIG_EROFS_FS_BACKED_BY_FILE"* ]]
  # Nothing was installed: the failure must precede the 40-minute build, not
  # follow a kernel we already know cannot boot the image.
  [ -z "$(installed_pkg)" ]
}

@test "the build fails when the release has no HWE kernel at all" {
  publish linux-generic 6.8.0-137-generic n
  run_script
  [ "$status" -ne 0 ]
  [ -z "$(installed_pkg)" ]
}

@test "no published .config falls back to the version the support landed in" {
  # linux-buildinfo is not published for every kernel on every arch. Absent a
  # config, 6.8 must still be rejected and 6.12+ still accepted — a release
  # name would answer neither.
  publish linux-generic 6.8.0-137-generic
  publish linux-generic-hwe-24.04 6.12.0-1-generic
  run_script
  [ "$status" -eq 0 ]
  [ "$(installed_pkg)" = "linux-generic-hwe-24.04" ]
}

@test "the version fallback accepts a GA kernel new enough on its own" {
  publish linux-generic 6.17.0-5-generic
  run_script
  [ "$status" -eq 0 ]
  [ "$(installed_pkg)" = "linux-generic" ]
}

@test "the asahi path is not routed through the composefs kernel choice" {
  # ENABLE_ASAHI installs a 16K-page asahi kernel from a PPA; it must not be
  # silently swapped for linux-generic-hwe by the branch above.
  publish linux-generic 6.8.0-137-generic n
  run env ENABLE_ASAHI=1 MODULES_DIR="$MODULES" BOOT_DIR="$BOOT" bash "$SCRIPT"
  # It fails on this amd64 test host by design (asahi is arm64-only), but the
  # point is where: before any generic-kernel selection.
  [[ "$output" == *"requires an arm64 build"* ]]
  [ -z "$(installed_pkg)" ]
}

# The harness above can only protect the host if the script honours the
# override. A hardcoded path would make every test here run against the real
# /var/lib/apt/lists again — unwritable on CI (so `set -e` kills the success
# paths) and writable under root (so the suite deletes them).
@test "the apt-lists cleanup is overridable, not a hardcoded host path" {
  run grep -n 'rm -rf /var/lib/apt/lists' "$SCRIPT"
  [ "$status" -ne 0 ]
  # Both exits from the script clean up; both must go through the variable.
  # Anchored on the whole command so the comment explaining it does not count.
  run bash -c "grep -cF 'apt-get clean -y && rm -rf \"\${APT_LISTS_DIR}\"/*' '$SCRIPT'"
  [ "$output" -eq 2 ]
}
