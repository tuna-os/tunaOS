#!/usr/bin/env bats
# GNOME Initial Setup reads DCONF_PROFILE=gnome-initial-setup and its own
# vendor.conf (#4408). These fixtures run the real writer, real `dconf compile`
# and the build-time check that stops the build. They are configuration
# evidence, not a rendered frame.
#
# Falsification: drop the gnome-initial-setup profile block from
# gnome-set-branding.sh and "writer routes the accent into Initial Setup's
# profile" fails with accent-color=unset. Drop the vendor.conf block and
# "Ubuntu's Initial Setup pages are skipped" fails naming ubuntu_pro.
setup() {
  command -v dconf >/dev/null || skip "dconf required for real compiled-settings fixture"
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SET="${REPO_ROOT}/build_scripts/desktop/gnome-set-branding.sh"
  CHECK="${REPO_ROOT}/build_scripts/checks/verify-gnome-initial-setup.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}/usr/share/tunaos" "${ROOT}/usr/libexec" "${ROOT}/usr/share/dconf/profile" \
    "${BATS_TEST_TMPDIR}/gis-defaults"
  printf "TUNAOS_VARIANT='grouper'\nTUNAOS_GNOME_ACCENT='orange'\n" >"${ROOT}/usr/share/tunaos/identity.env"
  # The packaged profile and defaults, as gnome-initial-setup 50/51 install them.
  printf 'user-db:user\nfile-db:/usr/share/gnome-initial-setup/initial-setup-dconf-defaults\n' \
    >"${ROOT}/usr/share/dconf/profile/gnome-initial-setup"
  mkdir -p "${ROOT}/usr/share/gnome-initial-setup"
  printf '[org/gnome/desktop/lockdown]\ndisable-lock-screen=true\n' >"${BATS_TEST_TMPDIR}/gis-defaults/00-upstream-settings"
  dconf compile "${ROOT}/usr/share/gnome-initial-setup/initial-setup-dconf-defaults" "${BATS_TEST_TMPDIR}/gis-defaults"
}

# A stand-in binary: GIS keeps each PAGE() id as a string literal.
_gis_binary() {
  printf '\177ELF\0keyboard\0network\0%s\0summary\0' "$1" >"${ROOT}/usr/libexec/gnome-initial-setup"
}

_compile() {
  local dir
  for dir in "${ROOT}"/etc/dconf/db/*.d; do
    dconf compile "${dir%.d}" "$dir"
  done
}

_check() {
  run env TUNAOS_BRANDING_ROOT="$ROOT" "$CHECK" grouper
}

@test "writer routes the accent into Initial Setup's profile" {
  _gis_binary password
  "$SET" "$ROOT" >/dev/null
  _compile
  [ "$(cat "${ROOT}/etc/dconf/profile/gnome-initial-setup")" = "$(printf 'user-db:user\nsystem-db:gnome-initial-setup\nfile-db:/usr/share/gnome-initial-setup/initial-setup-dconf-defaults')" ]
  _check
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_INITIAL_SETUP_OK variant=grouper accent='orange' ubuntu_pages=absent"* ]]
  [ ! -e "${ROOT}/etc/gnome-initial-setup/vendor.conf" ]
}

@test "packaged profile alone fails: the schema default colours the pill" {
  # The state every GNOME image shipped before #4408 was fixed.
  _gis_binary password
  _check
  [ "$status" -eq 1 ]
  [[ "$output" == *"accent-color=unset, want 'orange'"* ]]
  [[ "$output" == *"TUNAOS_INITIAL_SETUP_FAIL variant=grouper failures=1"* ]]
}

@test "an accent only in the gdm database does not reach Initial Setup" {
  # PR #4621 wrote the accent to gdm.d; GDM never gives Initial Setup that profile.
  _gis_binary password
  mkdir -p "${ROOT}/etc/dconf/db/gdm.d" "${ROOT}/etc/dconf/profile"
  printf "[org/gnome/desktop/interface]\naccent-color='orange'\n" >"${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
  printf 'user-db:user\nsystem-db:gdm\n' >"${ROOT}/etc/dconf/profile/gdm"
  _compile
  _check
  [ "$status" -eq 1 ]
  [[ "$output" == *"accent-color=unset"* ]]
}

@test "a profile that names an uncompiled database fails and says so" {
  _gis_binary password
  "$SET" "$ROOT" >/dev/null
  _check
  [ "$status" -eq 1 ]
  [[ "$output" == *"is not compiled (run dconf update)"* ]]
}

@test "Ubuntu's Initial Setup pages are skipped through the /etc vendor.conf" {
  _gis_binary ubuntu_pro
  : >"${ROOT}/usr/share/gnome-initial-setup/vendor.conf"
  "$SET" "$ROOT" >/dev/null
  _compile
  grep -qx 'skip=welcome;ubuntu_pro;ubuntu_insights;appearance;apps' "${ROOT}/etc/gnome-initial-setup/vendor.conf"
  _check
  [ "$status" -eq 0 ]
  [[ "$output" == *"ubuntu_pages=skipped"* ]]
}

@test "an Ubuntu build whose vendor.conf shows Ubuntu Pro fails" {
  _gis_binary ubuntu_pro
  "$SET" "$ROOT" >/dev/null
  _compile
  printf '[pages]\nskip=welcome;ubuntu_insights;appearance;apps\n' >"${ROOT}/etc/gnome-initial-setup/vendor.conf"
  _check
  [ "$status" -eq 1 ]
  [[ "$output" == *"not skipped by /etc/gnome-initial-setup/vendor.conf: ubuntu_pro"* ]]
}

@test "the packaged vendor.conf is ignored once /etc has one" {
  # GIS loads /etc and never merges /usr/share, so a skip list there is dead.
  _gis_binary ubuntu_pro
  "$SET" "$ROOT" >/dev/null
  _compile
  printf '[pages]\nskip=welcome;ubuntu_pro;ubuntu_insights;appearance;apps\n' >"${ROOT}/usr/share/gnome-initial-setup/vendor.conf"
  printf '[pages]\nskip=software\n' >"${ROOT}/etc/gnome-initial-setup/vendor.conf"
  _check
  [ "$status" -eq 1 ]
}

@test "writer keeps existing vendor.conf keys and is idempotent" {
  _gis_binary ubuntu_pro
  mkdir -p "${ROOT}/etc/gnome-initial-setup"
  printf '[pages]\nskip=software\nexisting_user_only=language;keyboard\n[other]\nx=1\n' \
    >"${ROOT}/etc/gnome-initial-setup/vendor.conf"
  "$SET" "$ROOT" >/dev/null
  "$SET" "$ROOT" >/dev/null
  [ "$(cat "${ROOT}/etc/gnome-initial-setup/vendor.conf")" = "$(printf '[pages]\nskip=software;welcome;ubuntu_pro;ubuntu_insights;appearance;apps\nexisting_user_only=language;keyboard\n[other]\nx=1')" ]
  [ "$(grep -cx system-db:gnome-initial-setup "${ROOT}/etc/dconf/profile/gnome-initial-setup")" -eq 1 ]
}

@test "an image without Initial Setup reports it and passes" {
  _check
  [ "$status" -eq 0 ]
  [[ "$output" == *"TUNAOS_INITIAL_SETUP_OK variant=grouper status=not-installed"* ]]
}

@test "both desktop install paths run the Initial Setup check after the writer" {
  for f in install-desktop.sh configure-desktop-runtime.sh; do
    writer="$(grep -n 'gnome-set-branding.sh' "${REPO_ROOT}/build_scripts/desktop/${f}" | head -1 | cut -d: -f1)"
    check="$(grep -n 'checks/verify-gnome-initial-setup.sh"\? ' "${REPO_ROOT}/build_scripts/desktop/${f}" | head -1 | cut -d: -f1)"
    [ -n "$writer" ] && [ -n "$check" ] && [ "$writer" -lt "$check" ]
  done
}
