#!/usr/bin/env bats

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "Debian XFCE override avoids the sid GNOME dependency" {
  local manifest="$REPO_ROOT/manifests/desktops/xfce-debian.yaml"
  [ -f "$manifest" ]
  grep -q '^display_manager: lightdm$' "$manifest"
  grep -q '^    - lightdm$' "$manifest"
  grep -q '^    - lightdm-gtk-greeter$' "$manifest"
  ! grep -q 'gdm3\|gnome-shell' "$manifest"
}

@test "Debian GNOME manifest keeps the extension manager optional to the transition" {
  local manifest="$REPO_ROOT/manifests/desktops/gnome-debian.yaml"
  # gnome-core remains the supported GNOME baseline; this assertion documents
  # that the extension manager is the optional package that must not reintroduce
  # a second libgjs/gnome-shell transaction during sid's transition.
  ! grep -q '^    - gnome-shell-extension-manager$' "$manifest"
}
