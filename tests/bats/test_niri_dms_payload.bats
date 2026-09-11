#!/usr/bin/env bats
# The niri/DMS payload contract.
#
# Both assertions here exist because a niri image can ship, boot and publish
# with its entire shell missing and nothing in the build log saying so
# (tunaOS#1009, #637). Neither failure is loud at build time: one is a config
# pointing at an absent path, the other is `|| true` on a dnf transaction.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

YQ_BIN="${YQ_BIN:-yq}"

# Strip comment lines before matching code. Prose in this repo quotes the very
# paths and package names these tests search for, so an un-stripped grep passes
# with the code deleted.
_code() { grep -v '^[[:space:]]*#' "$1"; }

@test "install-zirconium.sh creates the greeter config greetd's -C names" {
  local script="${REPO_ROOT}/build_scripts/install-zirconium.sh"
  local factory="${REPO_ROOT}/_upstream-snapshots/zirconium/mkosi.extra/usr/share/factory/etc/greetd/config.toml"
  [ -f "$factory" ]

  # The path is read from the config we actually ship, not hardcoded here, so
  # this keeps holding if upstream moves it.
  local target
  target="$(grep -oE '\-C +[^" ]+' "$factory" | head -1 | awk '{print $2}')"
  [ -n "$target" ]

  # The script must lay that exact path down. Upstream materialises it from
  # 99-zirconium-factory.conf, which we deliberately do not install.
  _code "$script" | grep -qF "$target"
  _code "$script" | grep -qF "$(dirname "$target")"

  # And the tmpfiles file we skip must still be the skipped one — if someone
  # starts installing it, this test's premise is gone and it should be revisited.
  ! _code "$script" | grep -qF '99-zirconium-factory.conf'
}

@test "install-zirconium.sh passes shellcheck" {
  if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
  run shellcheck --severity=error --exclude=SC1091 "${REPO_ROOT}/build_scripts/install-zirconium.sh"
  [ "$status" -eq 0 ]
}

@test "EL10 installs a checksum-pinned QML fallback after the COPR transaction" {
  # build_scripts/desktop/niri.sh's "base" case is dead code: install-desktop.sh
  # (what every desktop build actually runs) never calls a per-desktop
  # <name>.sh, it drives manifests/desktops/<name>.yaml instead. The fallback
  # used to be wired only into niri.sh, so it never ran in a real build even
  # though this test passed (tunaOS#2359's build_yellowfin niri leg red every
  # night since before the "fix" landed) -- assert against the manifest's
  # post_install list, the path install-desktop.sh actually resolves.
  local wrapper="${REPO_ROOT}/build_scripts/desktop/dms-qml-fallback-el10.sh"
  local manifest="${REPO_ROOT}/manifests/desktops/niri.yaml"
  local fallback="${REPO_ROOT}/build_scripts/install-dms-qml-fallback.sh"
  local versions="${REPO_ROOT}/image-versions.yaml"

  [ -x "$fallback" ]
  [ -x "$wrapper" ]
  grep -qxF '  - dms-qml-fallback-el10.sh' "$manifest"
  _code "$wrapper" | grep -qF 'build_scripts/install-dms-qml-fallback.sh'
  _code "$fallback" | grep -qF '/usr/share/quickshell/dms-greeter/DMSGreeter.qml'
  _code "$fallback" | grep -qF 'sha256sum --check --strict'
  grep -qE '^[[:space:]]+dms_qml: "v[0-9]' "$versions"
  grep -qE '^[[:space:]]+dms_qml_sha256: "[0-9a-f]{64}"' "$versions"
}

@test "dms-qml-fallback-el10.sh is sourced, not exec'd, and never calls exit" {
  # install-desktop.sh's post_install loop sources every script under
  # set -e; one that calls exit ends the whole desktop install instead of
  # just this hook (see greetd-gtkgreet.sh's header comment for the same
  # contract). install-dms-qml-fallback.sh itself DOES call exit, which is
  # exactly why this wrapper must run it as a subprocess rather than source it.
  local wrapper="${REPO_ROOT}/build_scripts/desktop/dms-qml-fallback-el10.sh"
  ! _code "$wrapper" | grep -qE '(^|[^A-Za-z])exit([^A-Za-z]|$)'
}

@test "dms-qml-fallback-el10.sh passes shellcheck" {
  if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
  run shellcheck --severity=error --exclude=SC1091 "${REPO_ROOT}/build_scripts/desktop/dms-qml-fallback-el10.sh"
  [ "$status" -eq 0 ]
}

@test "DMS QML fallback passes shellcheck" {
  if ! command -v shellcheck &>/dev/null; then skip "shellcheck not installed"; fi
  run shellcheck --severity=error --exclude=SC1091 "${REPO_ROOT}/build_scripts/install-dms-qml-fallback.sh"
  [ "$status" -eq 0 ]
}

@test "every DMS package is asked of a COPR that can resolve it" {
  if ! command -v "$YQ_BIN" &>/dev/null; then skip "yq not installed"; fi
  local manifest="${REPO_ROOT}/manifests/desktops/niri.yaml"

  # dms-greeter and quickshell* are built in avengemedia/danklinux; dms and
  # dms-cli in avengemedia/dms-git. dnf fails a whole transaction on one
  # unmatched name and install-desktop.sh swallows that with `|| true`, so a
  # package named against the wrong repo silently takes its whole block with
  # it. Assert the property — the block that names a package can see the repo
  # that builds it — rather than any one spelling of the manifest.
  local os n i repo opts pkgs
  for os in fedora el10; do
    n="$("$YQ_BIN" -r ".packages.${os}.copr | length" "$manifest")"
    for ((i = 0; i < n; i++)); do
      repo="$("$YQ_BIN" -r ".packages.${os}.copr[$i].repo" "$manifest")"
      opts="$("$YQ_BIN" -r ".packages.${os}.copr[$i].options // \"\"" "$manifest")"
      pkgs="$("$YQ_BIN" -r ".packages.${os}.copr[$i].packages[]?" "$manifest")"

      # Which repos can this transaction see: its own, plus any --enablerepo.
      local visible="${repo} ${opts}"

      if grep -qE '^(dms-greeter|quickshell(-git)?)$' <<<"$pkgs"; then
        [[ "$visible" == *danklinux* ]]
      fi
      if grep -qE '^dms(-cli)?$' <<<"$pkgs"; then
        [[ "$visible" == *dms-git* ]]
      fi
    done
  done
}

@test "DMS packages stay in their publishing COPRs" {
  if ! command -v "$YQ_BIN" &>/dev/null; then skip "yq not installed"; fi
  local manifest="${REPO_ROOT}/manifests/desktops/niri.yaml"
  local os n i repo pkgs
  for os in fedora el10; do
    n="$($YQ_BIN -r ".packages.${os}.copr | length" "$manifest")"
    local danklinux=0 dmsgit=0
    for ((i = 0; i < n; i++)); do
      repo="$($YQ_BIN -r ".packages.${os}.copr[$i].repo" "$manifest")"
      pkgs="$($YQ_BIN -r ".packages.${os}.copr[$i].packages[]?" "$manifest")"
      [[ "$repo" == avengemedia/danklinux ]] && danklinux=1
      [[ "$repo" == avengemedia/dms-git ]] && dmsgit=1
      if [[ "$repo" == avengemedia/danklinux ]]; then
        grep -qx 'dms-greeter' <<<"$pkgs"
        grep -qx 'quickshell-git' <<<"$pkgs"
        ! grep -qxE 'dms(-cli)?' <<<"$pkgs"
      elif [[ "$repo" == avengemedia/dms-git ]]; then
        grep -qx 'dms' <<<"$pkgs"
        grep -qx 'dms-cli' <<<"$pkgs"
        ! grep -qxE 'dms-greeter|quickshell(-git)?' <<<"$pkgs"
      fi
    done
    [ "$danklinux" -eq 1 ]
    [ "$dmsgit" -eq 1 ]
  done
}

@test "install-desktop.sh does not run a package-less dnf install" {
  # `packages: []` is the enable-only idiom (write the repo file so a later
  # block can --enablerepo it). Running dnf install with no arguments there
  # is a guaranteed error hidden by `|| true`, which trains readers to ignore
  # exactly the line a real failure would appear on.
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  _code "$script" | grep -qF '${#_TD_COPR_PKGS[@]} == 0'
}
