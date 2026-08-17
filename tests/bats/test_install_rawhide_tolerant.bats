#!/usr/bin/env bats
# install_rawhide_tolerant() — tunaOS#1810.
#
# rpmfusion-free-rawhide's ffmpeg-libs-8.1.2-5.fc46 Requires:
# liboapv.so.2()(64bit); Fedora rawhide's openapv-libs now provides only
# liboapv.so.3 (measured against live repodata 2026-08-17) — nothing in the
# enabled repo set satisfies the old SONAME, so the RPM Fusion multimedia
# transaction fails on bonito-rawhide even though every requested package
# name genuinely exists. install_available's `dnf repoquery --available`
# probe cannot see this (the names all resolve); the failure is in the
# depsolve, not the package list.
#
# These tests run the REAL install_rawhide_tolerant + record_package_wishlist
# functions extracted verbatim from build_scripts/lib.sh (not a
# reimplementation) against mocked dnf/rpm binaries — the same
# extract-and-run technique test_package_wishlist_gate.bats uses for
# record_package_wishlist itself.

REPO_ROOT="${REPO_ROOT:-$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)}"
LIB="${REPO_ROOT}/build_scripts/lib.sh"

setup() {
  BIN="${BATS_TEST_TMPDIR}/bin"
  mkdir -p "$BIN"
  WISH_DIR="${BATS_TEST_TMPDIR}/wish"
  mkdir -p "$WISH_DIR"
  INSTALLED_DIR="${BATS_TEST_TMPDIR}/installed"
  mkdir -p "$INSTALLED_DIR"

  FN_TOLERANT="$(awk '/^install_rawhide_tolerant\(\)/,/^}/' "$LIB")"
  FN_WISHLIST="$(awk '/^record_package_wishlist\(\)/,/^}/' "$LIB")"
  [[ -n "$FN_TOLERANT" ]]
  [[ -n "$FN_WISHLIST" ]]

  # Mock dnf:
  #   - a plain `install` (no --skip-broken) succeeds/fails per
  #     DNF_STRICT_RC and, on success, "installs" every requested name.
  #   - `install --skip-broken` always exits 0 and "installs" every
  #     requested name EXCEPT the ones listed in DNF_DROP — standing in for
  #     the real depsolver dropping only the package(s) it can't resolve.
  #   "Installing" a package means touching a marker file the rpm mock reads.
  cat >"${BIN}/dnf" <<MOCK
#!/usr/bin/env bash
skip_broken=0
pkgs=()
for arg in "\$@"; do
  case "\$arg" in
    --skip-broken) skip_broken=1 ;;
    -y|install) ;;
    -*) ;;
    *) pkgs+=("\$arg") ;;
  esac
done
if [[ \$skip_broken -eq 1 ]]; then
  for p in "\${pkgs[@]}"; do
    case " \${DNF_DROP:-} " in
      *" \$p "*) ;;
      *) touch "${INSTALLED_DIR}/\$p" ;;
    esac
  done
  exit 0
fi
if [[ "\${DNF_STRICT_RC:-1}" -eq 0 ]]; then
  for p in "\${pkgs[@]}"; do touch "${INSTALLED_DIR}/\$p"; done
fi
exit "\${DNF_STRICT_RC:-1}"
MOCK
  chmod +x "${BIN}/dnf"

  cat >"${BIN}/rpm" <<MOCK
#!/usr/bin/env bash
# rpm -q <pkg>
[[ -e "${INSTALLED_DIR}/\$2" ]]
MOCK
  chmod +x "${BIN}/rpm"
}

# Runs the real install_rawhide_tolerant (with its real record_package_wishlist
# dependency) in a fresh shell, against the mocked dnf/rpm on PATH.
run_tolerant() {
  PATH="${BIN}:/usr/bin:/bin" bash -c "
    set -uo pipefail
    ${FN_WISHLIST}
    ${FN_TOLERANT}
    install_rawhide_tolerant $*
  "
}

# ═══════════════════════════════════════════════════════════════════════════
# Pinned Fedora (non-rawhide): must behave EXACTLY like a plain dnf install —
# this is the "bonito is provably unaffected" guarantee.
# ═══════════════════════════════════════════════════════════════════════════

@test "non-rawhide + strict success: installs cleanly, no warning, no wishlist" {
  export FEDORA_VER=44
  export DNF_STRICT_RC=0
  export IMAGE_NAME=bonito
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  run run_tolerant "ffmpeg gstreamer1-plugin-libav"
  [ "$status" -eq 0 ]
  [[ "$output" != *"::warning"* ]]
  [ ! -e "${WISH_DIR}/missing-on-bonito.txt" ]
  [ -e "${INSTALLED_DIR}/ffmpeg" ]
}

@test "non-rawhide + strict failure: fails hard, no skip-broken retry, no wishlist entry" {
  export FEDORA_VER=44
  export DNF_STRICT_RC=1
  export IMAGE_NAME=bonito
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  run run_tolerant "ffmpeg gstreamer1-plugin-libav"
  [ "$status" -ne 0 ]
  [[ "$output" != *"::warning"* ]]
  [ ! -e "${WISH_DIR}/missing-on-bonito.txt" ]
  [ ! -e "${INSTALLED_DIR}/ffmpeg" ]
}

@test "a release string that merely CONTAINS rawhide does not trigger tolerance" {
  # Guards the exact-match comparison: only FEDORA_VER=rawhide qualifies.
  export FEDORA_VER="not-rawhide"
  export DNF_STRICT_RC=1
  export IMAGE_NAME=bonito
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  run run_tolerant "ffmpeg"
  [ "$status" -ne 0 ]
  [[ "$output" != *"::warning"* ]]
}

# ═══════════════════════════════════════════════════════════════════════════
# Rawhide: the happy path is unaffected; the broken path is loud, not silent.
# ═══════════════════════════════════════════════════════════════════════════

@test "rawhide + strict success: no retry needed, no warning" {
  export FEDORA_VER=rawhide
  export DNF_STRICT_RC=0
  export IMAGE_NAME=bonito-rawhide
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  run run_tolerant "ffmpeg gstreamer1-plugin-libav"
  [ "$status" -eq 0 ]
  [[ "$output" != *"::warning"* ]]
  [ ! -e "${WISH_DIR}/missing-on-bonito-rawhide.txt" ]
}

@test "rawhide tolerance: strict fails, skip-broken drops only ffmpeg, loudly recorded" {
  export FEDORA_VER=rawhide
  export DNF_STRICT_RC=1
  export DNF_DROP="ffmpeg"
  export IMAGE_NAME=bonito-rawhide
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  run run_tolerant "gstreamer1-plugins-good gstreamer1-plugin-libav ffmpeg"
  [ "$status" -eq 0 ]
  [[ "$output" == *"::warning"*"tunaOS#1810"* ]]
  # the resolvable packages actually installed
  [ -e "${INSTALLED_DIR}/gstreamer1-plugin-libav" ]
  [ -e "${INSTALLED_DIR}/gstreamer1-plugins-good" ]
  # the unresolvable one did not, and is named as the reason
  [ ! -e "${INSTALLED_DIR}/ffmpeg" ]
  [ -e "${WISH_DIR}/missing-on-bonito-rawhide.txt" ]
  grep -qx "ffmpeg" "${WISH_DIR}/missing-on-bonito-rawhide.txt"
  # only the actual miss is named — resolvable packages are never blamed
  ! grep -qx "gstreamer1-plugin-libav" "${WISH_DIR}/missing-on-bonito-rawhide.txt"
  ! grep -qx "gstreamer1-plugins-good" "${WISH_DIR}/missing-on-bonito-rawhide.txt"
}

@test "rawhide tolerance: skip-broken retry recovers everything — no wishlist noise" {
  # The strict transaction can fail for reasons that clear on a plain
  # retry (a transient mirror hiccup, not #1810's depsolve break). If
  # --skip-broken ends up installing everything anyway, nothing should be
  # reported missing.
  export FEDORA_VER=rawhide
  export DNF_STRICT_RC=1
  export DNF_DROP=""
  export IMAGE_NAME=bonito-rawhide
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  run run_tolerant "ffmpeg gstreamer1-plugin-libav"
  [ "$status" -eq 0 ]
  [ -e "${INSTALLED_DIR}/ffmpeg" ]
  [ ! -e "${WISH_DIR}/missing-on-bonito-rawhide.txt" ]
}

@test "leading dnf flags are passed through and never mistaken for a missing package" {
  export FEDORA_VER=rawhide
  export DNF_STRICT_RC=1
  export DNF_DROP="ffmpeg"
  export IMAGE_NAME=bonito-rawhide
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  run run_tolerant "--exclude=openh264* gstreamer1-plugin-libav ffmpeg"
  [ "$status" -eq 0 ]
  [ -e "${WISH_DIR}/missing-on-bonito-rawhide.txt" ]
  grep -qx "ffmpeg" "${WISH_DIR}/missing-on-bonito-rawhide.txt"
  ! grep -q -- "--exclude" "${WISH_DIR}/missing-on-bonito-rawhide.txt"
  [ -e "${INSTALLED_DIR}/gstreamer1-plugin-libav" ]
}

@test "no packages requested: returns 0 without calling dnf" {
  export FEDORA_VER=rawhide
  export TUNAOS_WISHLIST_DIR="$WISH_DIR"
  export IMAGE_NAME=bonito-rawhide
  run run_tolerant ""
  [ "$status" -eq 0 ]
  [ ! -e "${WISH_DIR}/missing-on-bonito-rawhide.txt" ]
}

# ═══════════════════════════════════════════════════════════════════════════
# Wiring: the specific 10-base-packages.sh call site this exists for.
# ═══════════════════════════════════════════════════════════════════════════

@test "10-base-packages.sh routes the RPM Fusion multimedia set through install_rawhide_tolerant" {
  local f="${REPO_ROOT}/build_scripts/10-base-packages.sh"
  run awk '/install_rawhide_tolerant "/,/^$/' "$f"
  [[ "$output" == *"ffmpeg"* ]]
  [[ "$output" == *"gstreamer1-plugin-libav"* ]]
}

@test "10-base-packages.sh never routes buildah/podman/skopeo through install_rawhide_tolerant" {
  # These are load-bearing on every release, rawhide included — the
  # tolerance must be scoped to exactly the multimedia set.
  local f="${REPO_ROOT}/build_scripts/10-base-packages.sh"
  run awk '/install_rawhide_tolerant "/,/^$/' "$f"
  [[ "$output" != *"buildah"* ]]
  [[ "$output" != *"podman"* ]]
  [[ "$output" != *"skopeo"* ]]
}

@test "package-miss-allowlist.txt declares ffmpeg acceptable to miss, scoped to the rawhide note" {
  local allow="${REPO_ROOT}/build_scripts/checks/package-miss-allowlist.txt"
  run grep -B2 -x "ffmpeg" "$allow"
  [ "$status" -eq 0 ]
  [[ "$output" == *"rawhide"* ]]
}

# --- detect_fedora_ver: the gate above is only reachable if FEDORA_VER can
# actually say "rawhide". `rpm -E %fedora` never does (it expands to the
# numeric next release on Rawhide), so the derivation must consult
# os-release. Run 32002010101 is the measured failure: "transaction failed
# on 46; not tolerating" on a genuine Rawhide image.

extract_detect() {
  FN_DETECT="$(awk '/^detect_fedora_ver\(\)/,/^}/' "$LIB")"
  [[ -n "$FN_DETECT" ]]
}

@test "detect_fedora_ver: pinned release stays numeric" {
  extract_detect
  cat >"${BIN}/rpm" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == "-E" && "$2" == "%fedora" ]] && { echo 44; exit 0; }
exit 1
MOCK
  chmod +x "${BIN}/rpm"
  printf 'PRETTY_NAME="Fedora Linux 44 (Container Image)"\nVERSION_ID=44\n' \
    >"${BATS_TEST_TMPDIR}/os-release"
  run env PATH="${BIN}:$PATH" OS_RELEASE="${BATS_TEST_TMPDIR}/os-release" \
    bash -c "$FN_DETECT; detect_fedora_ver"
  [[ "$status" -eq 0 ]]
  [[ "$output" == "44" ]]
}

@test "detect_fedora_ver: rawhide os-release wins over the numeric expansion" {
  extract_detect
  cat >"${BIN}/rpm" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == "-E" && "$2" == "%fedora" ]] && { echo 46; exit 0; }
exit 1
MOCK
  chmod +x "${BIN}/rpm"
  printf 'PRETTY_NAME="Fedora Linux Rawhide (Container Image Prerelease)"\nVERSION_ID=46\n' \
    >"${BATS_TEST_TMPDIR}/os-release"
  run env PATH="${BIN}:$PATH" OS_RELEASE="${BATS_TEST_TMPDIR}/os-release" \
    bash -c "$FN_DETECT; detect_fedora_ver"
  [[ "$status" -eq 0 ]]
  [[ "$output" == "rawhide" ]]
}

@test "detect_fedora_ver: unexpanded %fedora falls back to rawhide" {
  extract_detect
  cat >"${BIN}/rpm" <<'MOCK'
#!/usr/bin/env bash
[[ "$1" == "-E" && "$2" == "%fedora" ]] && { echo '%fedora'; exit 0; }
exit 1
MOCK
  chmod +x "${BIN}/rpm"
  printf 'PRETTY_NAME="Fedora Linux 44 (Container Image)"\n' \
    >"${BATS_TEST_TMPDIR}/os-release"
  run env PATH="${BIN}:$PATH" OS_RELEASE="${BATS_TEST_TMPDIR}/os-release" \
    bash -c "$FN_DETECT; detect_fedora_ver"
  [[ "$status" -eq 0 ]]
  [[ "$output" == "rawhide" ]]
}

@test "10-base-packages derives FEDORA_VER through detect_fedora_ver" {
  grep -q 'FEDORA_VER="\$(detect_fedora_ver)"' \
    "${REPO_ROOT}/build_scripts/10-base-packages.sh"
  ! grep -q 'FEDORA_VER="\$(rpm -E %fedora)"' \
    "${REPO_ROOT}/build_scripts/10-base-packages.sh"
}
