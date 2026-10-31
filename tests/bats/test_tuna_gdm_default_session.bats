#!/usr/bin/env bats

setup() {
  REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
  SCRIPT="${REPO_ROOT}/build_scripts/desktop/tuna-gdm-default-session.sh"
  ROOT="${BATS_TEST_TMPDIR}/root"
  mkdir -p "${ROOT}"
  export TUNAOS_GDM_DEFAULT_ROOT="${ROOT}"
  install_gdm "GDM 48.0" gdm
}

install_gdm() {
  local version="$1" name="${2:-gdm}" capability="${3:-yes}"
  mkdir -p "${ROOT}/usr/bin"
  printf '#!/bin/sh\nprintf "%%s\\n" "%s"\n' "$version" >"${ROOT}/usr/bin/${name}"
  if [ "$capability" = yes ]; then
    printf '# daemon/FallbackSession\n' >>"${ROOT}/usr/bin/${name}"
  fi
  chmod +x "${ROOT}/usr/bin/${name}"
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

@test "GDM 51 explicitly clears inherited vendor and legacy sessions without touching user records" {
  install_gdm "GDM 51.1.1"
  mkdir -p "${ROOT}/usr/share/accountsservice/user-templates" \
    "${ROOT}/etc/accountsservice/user-templates" "${ROOT}/var/lib/AccountsService/users"
  printf '[User]\nXSession=gnome\nSession=gnome\nIcon=vendor.png\n' \
    >"${ROOT}/usr/share/accountsservice/user-templates/standard"
  printf '[Template]\nEnvironmentFiles=/etc/os-release;\n[User]\nXSession=gnome\nSession=tuna\nIcon=local.png\n[Other]\nSession=keep\n' \
    >"${ROOT}/etc/accountsservice/user-templates/administrator"
  printf '[User]\nSession=gnome\n' >"${ROOT}/var/lib/AccountsService/users/saved"
  cp "${ROOT}/var/lib/AccountsService/users/saved" "${ROOT}/saved.before"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  for type in standard administrator; do
    template="${ROOT}/etc/accountsservice/user-templates/${type}"
    [ "$(awk '/^\[/ { group = $0 } group == "[User]" && /^Session=/ { print }' "$template")" = "Session=" ]
    grep -Fqx 'XSession=gnome' "$template"
  done
  grep -Fqx 'Icon=vendor.png' "${ROOT}/etc/accountsservice/user-templates/standard"
  grep -Fqx 'Icon=local.png' "${ROOT}/etc/accountsservice/user-templates/administrator"
  grep -Fqx 'EnvironmentFiles=/etc/os-release;' "${ROOT}/etc/accountsservice/user-templates/administrator"
  grep -Fqx 'Session=keep' "${ROOT}/etc/accountsservice/user-templates/administrator"
  grep -Fqx 'Session=gnome' "${ROOT}/usr/share/accountsservice/user-templates/standard"
  cmp "${ROOT}/saved.before" "${ROOT}/var/lib/AccountsService/users/saved"
  [ "$(find "${ROOT}/var/lib/AccountsService/users" -type f | wc -l)" -eq 1 ]
}

@test "both policies are byte-idempotent and preserve existing records" {
  mkdir -p "${ROOT}/var/lib/AccountsService/users"
  printf '[User]\nSession=other\n' >"${ROOT}/var/lib/AccountsService/users/saved"
  cp "${ROOT}/var/lib/AccountsService/users/saved" "${ROOT}/saved.before"
  for version in 47.0 48.0 50.3 51.1.1; do
    install_gdm "GDM ${version}"
    run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    cp "${ROOT}/etc/gdm/custom.conf" "${ROOT}/config.before"
    for type in standard administrator; do
      cp "${ROOT}/etc/accountsservice/user-templates/${type}" "${ROOT}/${type}.before"
    done
    run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    cmp "${ROOT}/config.before" "${ROOT}/etc/gdm/custom.conf"
    for type in standard administrator; do
      cmp "${ROOT}/${type}.before" "${ROOT}/etc/accountsservice/user-templates/${type}"
    done
    cmp "${ROOT}/saved.before" "${ROOT}/var/lib/AccountsService/users/saved"
  done
}

@test "gdm3 installed version selects the same GDM 51 policy" {
  rm "${ROOT}/usr/bin/gdm"
  install_gdm "GDM 51.1.1" gdm3
  mkdir -p "${ROOT}/etc/gdm3"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  grep -Fqx 'Session=' "${ROOT}/etc/accountsservice/user-templates/standard"
  grep -Fqx 'FallbackSession=tuna' "${ROOT}/etc/gdm3/custom.conf"
}

@test "missing unparseable and incapable GDM cannot select empty templates" {
  rm "${ROOT}/usr/bin/gdm"
  for version in missing unknown 51.1.1; do
    if [ "$version" != missing ]; then
      install_gdm "$version" gdm no
      if [ "$version" = 51.1.1 ]; then
        install_gdm "GDM ${version}" gdm no
      fi
    fi
    run bash "$SCRIPT"
    [ "$status" -eq 0 ]
    for type in standard administrator; do
      grep -Fqx 'Session=tuna' "${ROOT}/etc/accountsservice/user-templates/${type}"
    done
  done
}

@test "fallback is written in daemon even when another group has the key" {
  mkdir -p "${ROOT}/etc/gdm"
  printf '[daemon]\nAutomaticLoginEnable=false\n[Other]\nFallbackSession=keep\n' \
    >"${ROOT}/etc/gdm/custom.conf"
  run bash "$SCRIPT"
  [ "$status" -eq 0 ]
  [ "$(awk '/^\[/ { group = $0 } group == "[daemon]" && /^FallbackSession=/ { print }' "${ROOT}/etc/gdm/custom.conf")" = "FallbackSession=tuna" ]
  grep -Fqx 'FallbackSession=keep' "${ROOT}/etc/gdm/custom.conf"
}
