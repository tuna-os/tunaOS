#!/usr/bin/env bats
# Gentoo's main tree does not currently provide the packages needed by the
# Niri or COSMIC manifests. Keep those flavors out of Guppy's published matrix
# until there is a maintained package source and a passing build.
#
# This is deliberately a repository-level guard: adding a flavor is otherwise
# easy to do in build-config.yml, while the failure only appears after the
# Gentoo image has spent time compiling its base.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "guppy does not publish Gentoo desktops without main-tree ebuilds" {
  run python3 - "${REPO_ROOT}" <<'EOF'
import os, sys
import yaml

root = sys.argv[1]
cfg = yaml.safe_load(open(os.path.join(root, '.github/build-config.yml')))
guppy = next(v for v in cfg['variants'] if v['id'] == 'guppy')
flavors = {f['id'] for f in guppy.get('flavors', [])}
unsupported = {'niri', 'cosmic'}
found = sorted(flavors & unsupported)
assert not found, f'guppy declares unsupported Gentoo flavors: {found}'
assert {'gnome', 'kde', 'xfce'} <= flavors, 'known Gentoo desktop coverage disappeared'
print(','.join(sorted(flavors)))
EOF
  [ "$status" -eq 0 ]
}

@test "the Gentoo installer explains the Niri and COSMIC ebuild gap" {
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  grep -qF 'Gentoo has no ${_TD_DESKTOP} ebuilds in the main tree' "$script"
  grep -qF 'do not declare guppy:${_TD_DESKTOP}' "$script"
  grep -qF 'until an upstream or' "$script"
}

