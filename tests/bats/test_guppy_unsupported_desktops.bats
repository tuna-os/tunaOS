#!/usr/bin/env bats
# Gentoo's main tree does not currently provide what two of the five desktop
# manifests need. Keep those flavors out of Guppy's published matrix, and keep
# the reason for each next to the omission.
#
#   niri, cosmic — no ebuild in ::gentoo at all (tunaOS#923).
#
# gnome was on this list from 2026-09-11 to 2026-10-07: ::gentoo topped out at
# GNOME 49.9, below the 50 floor verify-desktop-experience.sh enforces
# (tunaOS#2450). ::gentoo now has GNOME 50 under ~amd64, and gnome.yaml's
# emerge_accept_keywords accepts it, so gnome is declared again. The last two
# tests in this file hold the keyword list and the binhost lock together.
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

unsupported = {'niri', 'cosmic'}
found = sorted(flavors & unsupported)
assert not found, f'guppy declares unsupported Gentoo flavors: {found}'

# The desktops Gentoo can actually satisfy today. Losing one of these IS the
# silent regression this file was written to catch.
assert {'gnome', 'kde', 'xfce'} <= flavors, 'known Gentoo desktop coverage disappeared'
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

for flavor in ('niri', 'cosmic'):
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

@test "guppy:gnome accepts the ~amd64 GNOME 50 set it needs to meet the floor" {
  run python3 - "${REPO_ROOT}" <<'EOF'
import os, sys
import yaml

root = sys.argv[1]
manifest = yaml.safe_load(
    open(os.path.join(root, 'manifests/desktops/gnome.yaml')))
keywords = set(manifest.get('emerge_accept_keywords') or [])

# ::gentoo stable stops at GNOME 49, and the floor is 50. Without these
# keywords, guppy:gnome installs 49 and fails verify-desktop-experience.sh.
# Each package below has its GNOME 50 ebuild under ~amd64 only, measured
# with emerge --pretend against ::gentoo on 2026-10-07.
core = {
    'gnome-base/gnome-shell', 'x11-wm/mutter', 'gnome-base/gdm',
    'gnome-base/gnome-session', 'gnome-base/gsettings-desktop-schemas',
    'gnome-base/gnome-control-center', 'gnome-base/gnome-settings-daemon',
    'sys-apps/xdg-desktop-portal-gnome',
}
missing = sorted(core - keywords)
assert not missing, f'gnome.yaml emerge_accept_keywords lacks {missing}'

# A version in the atom pins one ebuild and breaks on the next ::gentoo
# bump. package.accept_keywords takes the bare category/name.
pinned = sorted(k for k in keywords if k[:1] in '<>=~' or k.count('/') != 1)
assert not pinned, f'use bare category/name atoms, not {pinned}'
EOF
  [ "$status" -eq 0 ]
}

@test "the binhost lock does not mask packages accepted as ~amd64" {
  local script="${REPO_ROOT}/build_scripts/desktop/gentoo-binhost-version-lock.sh"
  local install="${REPO_ROOT}/build_scripts/desktop/install-desktop.sh"
  grep -qF '/etc/portage/package.accept_keywords' "$script"
  grep -qF 'if key in keyworded:' "$script"
  # The keyword file must exist before the lock reads it.
  run python3 - "$install" <<'EOF'
import sys
body = open(sys.argv[1]).read()
kw = body.index('emerge_accept_keywords')
lock = body.index('gentoo-binhost-version-lock.sh"')
assert kw < lock, 'install-desktop.sh writes the keywords after the lock runs'
EOF
  [ "$status" -eq 0 ]
}
