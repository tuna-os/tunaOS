#!/usr/bin/env bats
# GNOME branding: the keyfiles, the contract that reads them, and the wiring.
#
# marlin:gnome carried the wallpaper (309864 bytes), the logo (4742 bytes) and
# a plymouth symlink, and showed the stock Arch background — because no dconf
# keyfile in the tree named any of them. verify-branding.sh asked whether the
# FILE existed, it did, and the cell was green.
#
# So these tests assert the applied state, never the presence of an asset. Each
# positive case is paired with a negative control that breaks exactly one thing,
# because a contract nothing can fail is the bug that was already shipping.
#
# See docs/BRANDING.md.

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SET="${REPO_ROOT}/build_scripts/desktop/gnome-set-branding.sh"
  CHECK="${REPO_ROOT}/build_scripts/checks/verify-branding-gnome.sh"
  ROOT="$(mktemp -d)"
}

teardown() {
  [ -n "${ROOT:-}" ] && rm -rf "$ROOT"
}

# A fixture that passes: the keyfiles gnome-set-branding.sh writes, the assets
# they name, and the compiled databases dconf would have produced. Tests that
# want a failure break one piece of this and nothing else.
_fixture() {
  "$SET" "$ROOT" >/dev/null
  mkdir -p "${ROOT}/usr/share/backgrounds/tunaos" "${ROOT}/usr/share/pixmaps"
  echo png >"${ROOT}/usr/share/backgrounds/tunaos/tunaos-default.png"
  echo svg >"${ROOT}/usr/share/pixmaps/tunaos.svg"
  # `dconf update` is not available here and is not what is under test; the
  # contract asserts a non-empty compiled database, so supply one.
  echo compiled >"${ROOT}/etc/dconf/db/local"
  echo compiled >"${ROOT}/etc/dconf/db/gdm"
}

_check() {
  TUNAOS_DCONF_DB="${ROOT}/etc/dconf/db" TUNAOS_BRANDING_ROOT="$ROOT" \
    run "$CHECK" marlin
}

# ── the writer ──────────────────────────────────────────────────────────────

@test "gnome-set-branding writes a session keyfile naming the TunaOS wallpaper" {
  run "$SET" "$ROOT"
  [ "$status" -eq 0 ]
  local kf="${ROOT}/etc/dconf/db/local.d/10-tunaos-branding"
  [ -f "$kf" ]
  grep -q "^\[org/gnome/desktop/background\]" "$kf"
  grep -q "^picture-uri='file:///usr/share/backgrounds/tunaos/tunaos-default.png'" "$kf"
}

# Setting only picture-uri leaves every dark-style session on the distro
# default, which is a large share of users and looks like the bug we started
# from.
@test "gnome-set-branding sets the dark wallpaper key too" {
  "$SET" "$ROOT" >/dev/null
  grep -q "^picture-uri-dark='file://" "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding"
}

# The greeter reads its own database. A logo written only to local.d never
# reaches the login screen, which is the first branded surface a user sees.
@test "gnome-set-branding brands the greeter in gdm.d, not local.d" {
  "$SET" "$ROOT" >/dev/null
  local kf="${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
  [ -f "$kf" ]
  grep -q "^\[org/gnome/login-screen\]" "$kf"
  grep -q "^logo='/usr/share/pixmaps/tunaos.svg'" "$kf"
}

# These are defaults, not policy. A user who picks their own wallpaper keeps it.
@test "gnome-set-branding writes no dconf locks" {
  "$SET" "$ROOT" >/dev/null
  [ ! -d "${ROOT}/etc/dconf/db/local.d/locks" ]
  [ -z "$(find "${ROOT}/etc/dconf/db" -name 'locks' -print -quit)" ]
}

@test "gnome-set-branding is idempotent" {
  "$SET" "$ROOT" >/dev/null
  local first
  first="$(cat "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding")"
  "$SET" "$ROOT" >/dev/null
  [ "$(cat "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding")" = "$first" ]
}

# ── the contract ────────────────────────────────────────────────────────────

@test "contract passes on a tree gnome-set-branding branded" {
  _fixture
  _check
  [ "$status" -eq 0 ]
  echo "$output" | grep -q "TUNAOS_BRANDING_GNOME_OK variant=marlin"
}

# The negative control for the whole exercise: assets present, nothing applied.
# This is precisely the marlin:gnome state that passed verify-branding.sh.
@test "contract FAILS an image with the assets but no keyfile" {
  mkdir -p "${ROOT}/etc/dconf/db/local.d" "${ROOT}/etc/dconf/db/gdm.d" \
    "${ROOT}/usr/share/backgrounds/tunaos" "${ROOT}/usr/share/pixmaps"
  echo png >"${ROOT}/usr/share/backgrounds/tunaos/tunaos-default.png"
  echo svg >"${ROOT}/usr/share/pixmaps/tunaos.svg"
  _check
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "sets picture-uri"
  echo "$output" | grep -q "TUNAOS_BRANDING_GNOME_FAIL"
}

@test "contract FAILS when picture-uri names a file not in the image" {
  _fixture
  rm "${ROOT}/usr/share/backgrounds/tunaos/tunaos-default.png"
  _check
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "which is not in the image"
}

@test "contract FAILS when only the light wallpaper key is set" {
  _fixture
  sed -i '/^picture-uri-dark=/d' "${ROOT}/etc/dconf/db/local.d/10-tunaos-branding"
  _check
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "picture-uri-dark is unset"
}

@test "contract FAILS when the greeter has no logo" {
  _fixture
  rm "${ROOT}/etc/dconf/db/gdm.d/10-tunaos-branding"
  _check
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "gdm.d sets the login-screen logo"
}

# A keyfile nothing compiled is a keyfile nothing reads — the session is
# unbranded exactly as if the file were absent.
@test "contract FAILS on keyfiles with no compiled database" {
  _fixture
  rm "${ROOT}/etc/dconf/db/local"
  _check
  [ "$status" -ne 0 ]
  echo "$output" | grep -q "run dconf update"
}

# The contract is on the state, not on our script having run. Any mechanism
# that leaves the session branded has to pass, or it blocks the next one.
@test "contract passes on branding written by something other than our script" {
  mkdir -p "${ROOT}/etc/dconf/db/local.d" "${ROOT}/etc/dconf/db/gdm.d" \
    "${ROOT}/usr/share/backgrounds/tunaos" "${ROOT}/usr/share/pixmaps"
  echo png >"${ROOT}/usr/share/backgrounds/tunaos/tunaos-default.png"
  echo svg >"${ROOT}/usr/share/pixmaps/tunaos.svg"
  cat >"${ROOT}/etc/dconf/db/local.d/99-somebody-elses-defaults" <<'EOF'
[org/gnome/desktop/background]
picture-uri='file:///usr/share/backgrounds/tunaos/tunaos-default.png'
picture-uri-dark='file:///usr/share/backgrounds/tunaos/tunaos-default.png'
EOF
  cat >"${ROOT}/etc/dconf/db/gdm.d/99-somebody-elses-defaults" <<'EOF'
[org/gnome/login-screen]
logo='/usr/share/pixmaps/tunaos.svg'
EOF
  echo compiled >"${ROOT}/etc/dconf/db/local"
  echo compiled >"${ROOT}/etc/dconf/db/gdm"
  _check
  [ "$status" -eq 0 ]
}

# ── the wiring ──────────────────────────────────────────────────────────────

# There are two desktop install paths: install-desktop.sh for the dnf, zypper,
# pacman and portage bases, configure-desktop-runtime.sh for Ubuntu and Debian.
# kde-set-look-and-feel.sh landed in one of them and half the matrix shipped
# unbranded. Assert both, by name, so the next desktop cannot repeat it.
@test "both desktop install paths call gnome-set-branding" {
  for path in build_scripts/desktop/install-desktop.sh \
    build_scripts/desktop/configure-desktop-runtime.sh; do
    grep -q "gnome-set-branding.sh" "${REPO_ROOT}/${path}" ||
      { echo "${path} never calls gnome-set-branding.sh" >&2; return 1; }
  done
}

@test "both desktop install paths install the gnome branding contract" {
  for path in build_scripts/desktop/install-desktop.sh \
    build_scripts/desktop/configure-desktop-runtime.sh; do
    grep -q "verify-branding-gnome.sh" "${REPO_ROOT}/${path}" ||
      { echo "${path} never runs verify-branding-gnome.sh at build time" >&2; return 1; }
    grep -q "/usr/libexec/tunaos/verify-branding-gnome" "${REPO_ROOT}/${path}" ||
      { echo "${path} never installs verify-branding-gnome for the runtime unit" >&2; return 1; }
  done
}

# The runtime unit only runs what BRANDING_EXTRA names. Installing the checker
# without wiring it leaves a binary nothing invokes — green for the wrong
# reason, which is the failure mode this whole change exists to close.
@test "the gnome checker is wired into the desktop contract unit" {
  for path in build_scripts/desktop/install-desktop.sh \
    build_scripts/desktop/configure-desktop-runtime.sh; do
    grep -q 'BRANDING_EXTRA="ExecStart=-/usr/libexec/tunaos/verify-branding-gnome' \
      "${REPO_ROOT}/${path}" ||
      { echo "${path} installs the gnome checker but never runs it" >&2; return 1; }
  done
}

# ── os-release identity ─────────────────────────────────────────────────────

# Every variant shipped HOME_URL and DOCUMENTATION_URL pointing at
# projectbluefin.io, inherited from the upstream script. The contract only read
# SUPPORT_URL and BUG_REPORT_URL, which were already ours, so nothing noticed.
@test "os-release URLs all point at TunaOS" {
  local info="${REPO_ROOT}/build_scripts/90-image-info.sh"
  run grep -E '^(HOME_URL|DOCUMENTATION_URL|SUPPORT_URL|BUG_SUPPORT_URL)=' "$info"
  [ "$status" -eq 0 ]
  [ "$(echo "$output" | wc -l)" -eq 4 ]
  echo "$output" | grep -qv 'tuna' && {
    echo "an os-release URL points away from TunaOS:" >&2
    echo "$output" >&2
    return 1
  }
  return 0
}

@test "the branding contract checks all four os-release URLs" {
  grep -q 'for field in HOME_URL DOCUMENTATION_URL SUPPORT_URL BUG_REPORT_URL' \
    "${REPO_ROOT}/build_scripts/checks/verify-branding.sh"
}
