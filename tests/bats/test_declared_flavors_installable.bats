#!/usr/bin/env bats
# A declared flavour must have somewhere to install its desktop FROM.
#
# This is the generalisation of two bugs that shipped, both of which cost a
# full image build to discover and one of which shipped a published image:
#
#   niri on Debian (tunaOS#915)   manifests/desktops/niri.yaml has no apt
#                                 section, so install-desktop.sh installed
#                                 NOTHING and exited 0. flounder:niri was
#                                 published and installable with no compositor
#                                 in it — `command -v niri` empty.
#   cosmic on Debian (this)       cosmic.yaml HAS an apt section, but its only
#                                 source is ppa:hepp3n/cosmic-epoch under
#                                 `condition: ubuntu`, and COSMIC is packaged
#                                 in no Debian suite at all. apt exits 100:
#                                   E: Unable to locate package cosmic-comp
#                                 flounder:cosmic, LUKS run 31087927879.
#
# The two failure modes are opposite — silent success and hard failure — which
# is exactly why neither caught the other. The invariant that covers both is
# structural and checkable without building anything: for every variant, and
# every desktop flavour it declares, the manifest install-desktop.sh would
# choose must carry a non-empty section for that variant's package manager.
#
# When this fails the fix is usually to stop declaring the flavour, not to
# invent a package list. Both cases above ended that way.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"

@test "every declared desktop flavour has packages for its variant's package manager" {
  run python3 - "${REPO_ROOT}" <<'EOF'
import json, os, re, sys
import yaml

root = sys.argv[1]
cfg = yaml.safe_load(open(os.path.join(root, '.github/build-config.yml')))

# Mirrors build_scripts/lib.sh's detection, keyed off the base image.
def pkg_mgr(base):
    b = (base or '').lower()
    if 'debian' in b:
        return 'apt', 'debian'
    if 'ubuntu' in b:
        return 'apt', 'ubuntu'
    if 'arch' in b:
        return 'pacman', 'arch'
    if 'opensuse' in b or 'tumbleweed' in b:
        return 'zypper', 'suse'
    if 'gentoo' in b or 'stage3' in b:
        return 'emerge', 'gentoo'
    if 'fedora' in b:
        return 'fedora', 'fedora'
    # almalinux / centos / kitten
    return 'el10', 'el10'

# Layer flavours are built by Containerfile.overlay ON TOP of an already-built
# desktop image, so they install no desktop of their own. base has no desktop.
LAYER = ('-hwe', '-nvidia', '-asahi', '-cachyos', '-zfs', '-t2')
def desktop_of(flavor):
    if flavor == 'base' or flavor.startswith('base-'):
        return None
    d = flavor
    changed = True
    while changed:
        changed = False
        for suf in LAYER:
            if d.endswith(suf):
                d, changed = d[: -len(suf)], True
    return d or None

# install-desktop.sh's own selection: <de>-debian.yaml on Debian, <de>-arch.yaml
# on pacman, else <de>.yaml.
def manifest_for(desktop, mgr, family):
    cands = []
    if family == 'debian':
        cands.append(f'{desktop}-debian.yaml')
    if mgr == 'pacman':
        cands.append(f'{desktop}-arch.yaml')
    cands.append(f'{desktop}.yaml')
    for c in cands:
        p = os.path.join(root, 'manifests/desktops', c)
        if os.path.isfile(p):
            return p
    return None

def has_packages(section):
    """Is anything actually listed to install?"""
    if section is None:
        return False
    if isinstance(section, list):
        return len(section) > 0
    if isinstance(section, dict):
        for key in ('packages', 'groups', 'copr', 'optional', 'optional_group'):
            v = section.get(key)
            if isinstance(v, list) and v:
                return True
        return False
    return False


def source_applies(section, family):
    """Does this variant have anywhere to get those packages FROM?

    Listing packages is not the same as being able to install them. cosmic.yaml
    names twenty apt packages whose ONLY source is a `ppa:` entry carrying
    `condition: ubuntu`; on a Debian base that PPA is skipped and every name
    resolves to nothing. Checking only that the section is non-empty passes
    that exact bug — verified by re-declaring flounder:cosmic and watching it
    slip through.

    So: if a section declares repository sources and NONE of them apply to this
    variant's family, the section has no source here. A section with no `ppa`
    block at all is assumed to come from the base distro's own archive, which
    is the normal case (gnome.yaml, kde.yaml).
    """
    if not isinstance(section, dict):
        return True
    ppas = section.get('ppa')
    if not isinstance(ppas, list) or not ppas:
        return True
    if section.get('repos'):
        return True  # a plain baseurl repo, not family-conditioned
    for entry in ppas:
        cond = (entry or {}).get('condition')
        if not cond or cond == family:
            return True
    return False

bad = []
for variant in cfg['variants']:
    vid = variant['id']
    mgr, family = pkg_mgr(variant.get('base_image'))
    for fl in variant.get('flavors') or []:
        desktop = desktop_of(fl['id'])
        if desktop is None:
            continue
        mpath = manifest_for(desktop, mgr, family)
        if mpath is None:
            bad.append(f"{vid}:{fl['id']} -> no manifest for desktop '{desktop}'")
            continue
        doc = yaml.safe_load(open(mpath)) or {}
        # pacman sections live under 'pacman' in the -arch manifest.
        section = (doc.get('packages') or {}).get(mgr)
        if not has_packages(section):
            bad.append(
                f"{vid}:{fl['id']} -> {os.path.basename(mpath)} has no usable "
                f"'{mgr}' section"
            )
        elif not source_applies(section, family):
            bad.append(
                f"{vid}:{fl['id']} -> {os.path.basename(mpath)}'s '{mgr}' "
                f"section lists packages, but every repository it declares is "
                f"conditioned on another family (this one is '{family}')"
            )

for b in bad:
    print(f"FAIL: {b}")
if bad:
    print()
    print("      A declared flavour with no package source either fails the")
    print("      build (apt/dnf error) or, worse, installs nothing and ships")
    print("      a desktop-less image. Usually the fix is to stop declaring")
    print("      the flavour — see tunaOS#915 for the precedent.")
sys.exit(1 if bad else 0)
EOF
  [ "$status" -eq 0 ] || {
    echo "$output" >&2
    return 1
  }
}

@test "the check is looking at real flavours, not an empty set" {
  # A typo in the config path or the layer-suffix stripping would make the
  # test above vacuous. Assert it actually resolves a known-good pairing.
  run python3 - "${REPO_ROOT}" <<'EOF'
import os, sys, yaml
root = sys.argv[1]
cfg = yaml.safe_load(open(os.path.join(root, '.github/build-config.yml')))
pairs = [(v['id'], f['id']) for v in cfg['variants'] for f in (v.get('flavors') or [])]
assert ('marlin', 'niri') in pairs, 'marlin:niri missing — config shape changed'
assert ('flounder', 'cosmic') not in pairs, 'flounder:cosmic is back'
assert ('flounder-sid', 'cosmic') not in pairs, 'flounder-sid:cosmic is back'
# The positive control for source_applies(): gurnard is Ubuntu and pantheon.yaml
# carries a `condition: ubuntu` PPA, so the rule must ACCEPT it. Without this,
# tightening the rule until everything fails would look like a pass.
assert ('gurnard', 'pantheon') in pairs, 'gurnard:pantheon missing — lost the positive control'
print(len(pairs))
EOF
  [ "$status" -eq 0 ]
  [ "$output" -ge 100 ]
}
