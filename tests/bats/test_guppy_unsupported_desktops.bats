#!/usr/bin/env bats
# Gentoo's main tree does not currently provide what three of the five desktop
# manifests need, for two different reasons. Keep those flavors out of Guppy's
# published matrix, and keep the reason for each next to the omission.
#
#   niri, cosmic — no ebuild in ::gentoo at all (tunaOS#923).
#   gnome        — an ebuild exists, but ::gentoo tops out at GNOME 49.9,
#                  below the 50 floor verify-desktop-experience.sh enforces,
#                  so the cell is guaranteed red (tunaOS#2450).
#
# This is deliberately a repository-level guard: adding a flavor is otherwise
# easy to do in build-config.yml, while the failure only appears after the
# Gentoo image has spent time compiling its base.
#
# The second assertion used to be `{'gnome','kde','xfce'} <= flavors` — "known
# Gentoo desktop coverage disappeared". That wording made dropping gnome for a
# measured reason indistinguishable from dropping it by accident, so this file
# failed the very change that removed a guaranteed-red cell. The property
# worth keeping is not "gnome is declared"; it is "no desktop leaves the matrix
# without a recorded reason". So an undeclared flavor must now be named in the
# `NOT declared, and not an oversight:` block, and re-adding one stays a
# reviewable edit in both places.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "guppy does not publish Gentoo desktops without a usable package source" {
  run python3 - "${REPO_ROOT}" <<'EOF'
import os, sys
import yaml

root = sys.argv[1]
cfg = yaml.safe_load(open(os.path.join(root, '.github/build-config.yml')))
guppy = next(v for v in cfg['variants'] if v['id'] == 'guppy')
flavors = {f['id'] for f in guppy.get('flavors', [])}

unsupported = {'niri', 'cosmic', 'gnome'}
found = sorted(flavors & unsupported)
assert not found, f'guppy declares unsupported Gentoo flavors: {found}'

# The desktops Gentoo can actually satisfy today. Losing one of these IS the
# silent regression this file was written to catch.
assert {'kde', 'xfce'} <= flavors, 'known Gentoo desktop coverage disappeared'
print(','.join(sorted(flavors)))
EOF
  [ "$status" -eq 0 ]
}

@test "every desktop guppy omits is named in the omission block, with a reason" {
  run python3 - "${REPO_ROOT}" <<'EOF'
import os, re, sys

root = sys.argv[1]
text = open(os.path.join(root, '.github/build-config.yml')).read()

# The guppy variant's own comment block, not any other variant's.
start = text.index('  - id: guppy')
end = text.index('\n  - id: ', start + 10)
block = text[start:end]
marker = 'NOT declared, and not an oversight:'
assert marker in block, 'guppy lost its omission block'
block = block[block.index(marker):]

for flavor in ('gnome', 'niri', 'cosmic'):
    entry = re.search(rf'^\s*#\s+{flavor}\s+[-—]\s+(.+)$', block, re.M)
    assert entry, (
        f'guppy omits {flavor} but the omission block does not say why. '
        'A desktop may leave the matrix for a measured reason; it may not '
        'leave silently.')
    assert len(entry.group(1).strip()) > 20, (
        f'the reason recorded for {flavor} is too short to be one')
EOF
  [ "$status" -eq 0 ]
}

@test "the Gentoo installer explains the Niri and COSMIC ebuild gap" {
  local script="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  grep -qF 'Gentoo has no ${_TD_DESKTOP} ebuilds in the main tree' "$script"
  grep -qF 'do not declare guppy:${_TD_DESKTOP}' "$script"
  grep -qF 'until an upstream or' "$script"
}
