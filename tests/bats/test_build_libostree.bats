#!/usr/bin/env bats
# build_scripts/bootc/build-libostree.sh
#
# The defect this covers: Containerfile.ubuntu pulls the *sid* bootc toolchain
# for both Ubuntu releases it serves. sid ships no libostree (its packaged one
# satisfies bootc), which holds on resolute (2025.7) and does not on noble
# (2024.5) — so gurnard:pantheon shipped a bootc that could not load, built
# clean, linted clean, booted clean, and died in `bootc install to-filesystem`
# inside the VM with
#
#   bootc: /lib/x86_64-linux-gnu/libostree-1.so.1: version `LIBOSTREE_2025.2'
#          not found (required by bootc)
#
# (LUKS run 31067479874). So the assertions here are about the two properties
# that let that happen: the decision must be made by asking the bootc we ship
# whether it loads (not by a release name or a version table that goes stale),
# and the answer must be re-checked after the build rather than assumed.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
SCRIPT="${REPO_ROOT}/build_scripts/bootc/build-libostree.sh"

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  OUT="${BATS_TEST_TMPDIR}/output"
  SRC="${BATS_TEST_TMPDIR}/src"
  LOG="${BATS_TEST_TMPDIR}/cmds.log"
  mkdir -p "$BIN" "${OUT}/usr/bin" "$SRC"
  : >"$LOG"

  # Pins deliberately unlike the real ones: a hardcoded version in the script
  # would pass against the real file and fail here.
  cat >"${BATS_TEST_TMPDIR}/image-versions.yaml" <<'EOF'
downloads:
  bootc: "v1.16.7"
  ostree: "v9999.1"
  composefs: "v8888.2"
EOF

  # DESTDIR is passed as an environment variable to meson and as an argument to
  # make, so record it either way — it is the difference between staging the
  # libs for the image and only installing them in the throwaway builder.
  for cmd in apt-get ldconfig make meson ninja; do
    cat >"${BIN}/${cmd}" <<EOF
#!/usr/bin/env bash
echo "${cmd} \$* DESTDIR=\${DESTDIR:-}" >>"${LOG}"
exit 0
EOF
    chmod +x "${BIN}/${cmd}"
  done

  # git clone stands up a source tree the script can configure and make in.
  cat >"${BIN}/git" <<EOF
#!/usr/bin/env bash
echo "git \$*" >>"${LOG}"
dest="\${!#}"
mkdir -p "\$dest"
printf '#!/usr/bin/env bash\nexit 0\n' >"\$dest/autogen.sh"
printf '#!/usr/bin/env bash\necho "configure \$*" >>"${LOG}"\nexit 0\n' >"\$dest/configure"
chmod +x "\$dest/autogen.sh" "\$dest/configure"
EOF
  chmod +x "${BIN}/git"

  cat >"${BIN}/dpkg-architecture" <<'EOF'
#!/usr/bin/env bash
echo "x86_64-linux-gnu"
EOF
  chmod +x "${BIN}/dpkg-architecture"

  printf '#!/usr/bin/env bash\necho 1\n' >"${BIN}/nproc"
  chmod +x "${BIN}/nproc"
}

# $1: what the fake bootc does — "loads", "too-old", "too-old-forever", "other".
# The body is a quoted heredoc so the backtick in ld.so's real message survives
# verbatim; only the state directory is interpolated, on its own line.
fake_bootc() {
  echo "$1" >"${BATS_TEST_TMPDIR}/bootc.mode"
  {
    echo '#!/usr/bin/env bash'
    echo "STATE='${BATS_TEST_TMPDIR}'"
    cat <<'EOF'
mode="$(cat "${STATE}/bootc.mode")"
n=$(( $(cat "${STATE}/bootc.calls" 2>/dev/null || echo 0) + 1 ))
echo "$n" >"${STATE}/bootc.calls"
case "$mode" in
  loads) echo "bootc 1.16.7"; exit 0 ;;
  other)
    echo "bootc: error while loading shared libraries: libcurl.so.4: cannot open shared object file" >&2
    exit 127 ;;
  too-old-forever) : ;;
  # The source build is what makes the second answer different.
  too-old) [ "$n" -gt 1 ] && { echo "bootc 1.16.7"; exit 0; } ;;
esac
echo "bootc: /lib/x86_64-linux-gnu/libostree-1.so.1: version \`LIBOSTREE_2025.3' not found (required by bootc)" >&2
exit 1
EOF
  } >"${OUT}/usr/bin/bootc"
  chmod +x "${OUT}/usr/bin/bootc"
}

run_script() {
  PATH="${BIN}:${PATH}" \
  OUTPUT_DIR="$OUT" \
  VERSIONS_FILE="${BATS_TEST_TMPDIR}/image-versions.yaml" \
  SRC_DIR="$SRC" \
    run bash "$SCRIPT"
}

@test "build-libostree.sh: a base whose packaged libostree loads bootc builds nothing" {
  # This is grouper/resolute. Building ostree there would be pure waste, and
  # worse, would start shipping a lib the base did not ask for.
  fake_bootc loads
  run_script
  [ "$status" -eq 0 ]
  run grep -c '^git clone' "$LOG"
  [ "$output" = "0" ]
}

@test "build-libostree.sh: a base whose packaged libostree cannot load bootc gets a source build" {
  fake_bootc too-old
  run_script
  [ "$status" -eq 0 ]
  grep -q 'git clone.*ostree.git' "$LOG"
  grep -q 'git clone.*composefs.git' "$LOG"
}

@test "build-libostree.sh: the versions built are the image-versions.yaml pins" {
  # Not a copy of them in the script, which is how a Renovate bump silently
  # stops taking effect.
  fake_bootc too-old
  run_script
  [ "$status" -eq 0 ]
  grep -q -- '--branch v9999.1 .*ostree.git' "$LOG"
  grep -q -- '--branch v8888.2 .*composefs.git' "$LOG"
}

@test "build-libostree.sh: the libs land in the toolchain tree, not only in the builder" {
  # DESTDIR=/output is what the variant build COPYs; installing only into the
  # builder's own / would leave the image exactly as broken as before, with a
  # green build log.
  fake_bootc too-old
  run_script
  [ "$status" -eq 0 ]
  grep -q "make install DESTDIR=${OUT}" "$LOG"
  grep -q "meson install -C build DESTDIR=${OUT}" "$LOG"
  # And into the builder too, so the post-build assertion tests the new lib.
  grep -q "make install DESTDIR=$" "$LOG"
  grep -q "meson install -C build DESTDIR=$" "$LOG"
}

@test "build-libostree.sh: libdir is the multiarch dir the archive lib would occupy" {
  # Anywhere else and there can be two libostrees in the image with ld.so
  # picking between them — the multiarch copy wins, which is the 2024.5 one.
  fake_bootc too-old
  run_script
  [ "$status" -eq 0 ]
  grep -q -- '--libdir=/usr/lib/x86_64-linux-gnu' "$LOG"
  grep -q -- 'configure .*--libdir=/usr/lib/x86_64-linux-gnu' "$LOG"
  grep -q -- '--with-composefs' "$LOG"
}

@test "build-libostree.sh: a bootc broken for some other reason fails instead of building ostree" {
  # A missing libcurl is not fixed by compiling ostree for ten minutes, and
  # papering over it would put the real error back inside the VM.
  fake_bootc other
  run_script
  [ "$status" -ne 0 ]
  [[ "$output" == *"libostree is not why"* ]]
  [[ "$output" == *"libcurl.so.4"* ]]
  run grep -c '^git clone' "$LOG"
  [ "$output" = "0" ]
}

@test "build-libostree.sh: a build that did not fix bootc fails the build" {
  # The whole defect was a bootc that only proved unloadable at install time.
  # If the source lib is not the fix either, that has to be loud here.
  fake_bootc too-old-forever
  run_script
  [ "$status" -ne 0 ]
  [[ "$output" == *"still does not load"* ]]
  [[ "$output" == *"v9999.1"* ]]
}

@test "build-libostree.sh: a missing pin is an error, not an empty --branch" {
  fake_bootc too-old
  : >"${BATS_TEST_TMPDIR}/image-versions.yaml"
  run_script
  [ "$status" -ne 0 ]
  [[ "$output" == *"no 'ostree:' pin"* ]]
}

@test "build-libostree.sh: refuses to run before the toolchain pull" {
  # BOOTC_BIN is the whole input to the decision; without it the script would
  # have to guess, and guessing is what shipped the broken image.
  rm -f "${OUT}/usr/bin/bootc"
  run_script
  [ "$status" -ne 0 ]
  [[ "$output" == *"no bootc at"* ]]
}
