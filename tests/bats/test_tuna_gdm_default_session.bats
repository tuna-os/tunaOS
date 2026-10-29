#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/build_scripts/desktop/tuna-gdm-default-session.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}"
  export TUNAOS_GDM_DEFAULT_ROOT="${ROOT}"
}

@test "fallback session pins Tuna on a fresh image" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx '[daemon]' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  [ "$(grep -c '^FallbackSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "fallback session fills in an existing daemon section" {
  mkdir -p "${ROOT}/etc/gdm"
  printf '[daemon]\nAutomaticLoginEnable=false\n' >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx '[daemon]' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  grep -Fqx 'AutomaticLoginEnable=false' "${ROOT}/etc/gdm/custom.conf"
  [ "$(grep -c '^FallbackSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "fallback session replaces a non-Tuna fallback" {
  mkdir -p "${ROOT}/etc/gdm"
  printf '[daemon]\nFallbackSession=gnome\n' >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  run grep -Fxq 'FallbackSession=gnome' "${ROOT}/etc/gdm/custom.conf"
  [ "$status" -ne 0 ]
}

@test "the DefaultSession key GDM never reads is replaced, not kept" {
  # Published marlin:tuna (2026-10-28) shipped only DefaultSession=tuna.desktop,
  # and a fresh GDM 51.1 login started GNOME (tuna-os/tuna-desktop#813).
  mkdir -p "${ROOT}/etc/gdm"
  printf '# GDM configuration storage\n\n[daemon]\nDefaultSession=tuna.desktop\n\n[security]\n' \
    >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm/custom.conf"
  run grep -q '^DefaultSession=' "${ROOT}/etc/gdm/custom.conf"
  [ "$status" -ne 0 ]
  grep -Fqx '[security]' "${ROOT}/etc/gdm/custom.conf"
}

@test "running twice leaves one fallback session" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(grep -c '^FallbackSession=' "${ROOT}/etc/gdm/custom.conf")" -eq 1 ]
}

@test "fallback session uses the Debian config path" {
  mkdir -p "${ROOT}/etc/gdm3"
  printf '[daemon]\n' >"${ROOT}/etc/gdm3/daemon.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm3/custom.conf"
  [ ! -e "${ROOT}/etc/gdm/custom.conf" ]
}

@test "new-account templates keep the distribution template and select Tuna" {
  # Every published Tuna flavor ships AccountsService's upstream template
  # with an empty Session (2026-10-29 image survey, tuna-os/tunaOS#4055).
  mkdir -p "${ROOT}/usr/share/accountsservice/user-templates"
  for type in standard administrator; do
    printf '[Template]\n#EnvironmentFiles=/etc/os-release;\n\n[User]\nSession=\nIcon=${HOME}/.face\n' \
      >"${ROOT}/usr/share/accountsservice/user-templates/${type}"
  done
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  for type in standard administrator; do
    template="${ROOT}/etc/accountsservice/user-templates/${type}"
    [ "$(grep -c '^Session=' "$template")" -eq 1 ]
    grep -Fqx 'Session=tuna' "$template"
    grep -Fqx 'Icon=${HOME}/.face' "$template"
    grep -Fqx '[Template]' "$template"
    # Session=tuna sits in [User], not [Template].
    [ "$(awk '/^\[/ { group = $0 } $0 == "Session=tuna" { print group }' "$template")" = "[User]" ]
  done
  # The distribution's own templates are untouched.
  grep -Fqx 'Session=' "${ROOT}/usr/share/accountsservice/user-templates/standard"
}

@test "new-account templates are written without a distribution template" {
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  for type in standard administrator; do
    template="${ROOT}/etc/accountsservice/user-templates/${type}"
    grep -Fqx '[User]' "$template"
    grep -Fqx 'Session=tuna' "$template"
  done
}

@test "an existing /etc template gains Session=tuna in its User group" {
  mkdir -p "${ROOT}/etc/accountsservice/user-templates"
  printf '[User]\nIcon=/usr/share/pixmaps/faces/fish.png\n\n[Other]\nSession=keep\n' \
    >"${ROOT}/etc/accountsservice/user-templates/standard"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  template="${ROOT}/etc/accountsservice/user-templates/standard"
  grep -Fqx 'Icon=/usr/share/pixmaps/faces/fish.png' "$template"
  grep -Fqx 'Session=keep' "$template"
  [ "$(awk '/^\[/ { group = $0 } $0 == "Session=tuna" { print group }' "$template")" = "[User]" ]
  run bash "$SCRIPT"
  [ "$(grep -c '^Session=tuna' "$template")" -eq 1 ]
}
