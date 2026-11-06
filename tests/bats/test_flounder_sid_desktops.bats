#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "Debian XFCE override avoids the sid GNOME dependency" {
  local manifest="$REPO_ROOT/manifests/desktops/xfce-debian.yaml"
  [ -f "$manifest" ]
  [ "$(yq -r '.display_manager' "$manifest")" = lightdm ]
  local packages
  packages="$(yq -r '.packages.apt[]' "$manifest")"
  grep -qx lightdm <<<"$packages"
  grep -qx lightdm-gtk-greeter <<<"$packages"
  ! grep -qxE '(gdm3|gnome-shell)' <<<"$packages"
}

@test "Debian GNOME manifest keeps the extension manager optional to the transition" {
  local manifest="$REPO_ROOT/manifests/desktops/gnome-debian.yaml"
  # gnome-core remains the supported GNOME baseline; this assertion documents
  # that the extension manager is the optional package that must not reintroduce
  # a second libgjs/gnome-shell transaction during sid's transition.
  ! yq -r '.packages.apt[]' "$manifest" | grep -qx gnome-shell-extension-manager
}
