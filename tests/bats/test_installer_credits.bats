#!/usr/bin/env bats
# The Credits dialog must credit TunaOS, not Bluefin.
#
# WHY THIS EXISTS. bootc-installer's credits dialog resolves, in order:
#   1. recipe["credits_data"] — a GResource (/org/...) or filesystem path
#   2. its built-in /org/bootcinstaller/Installer/data/credits.json
#   3. a dev-mode file next to the module
#
# TunaOS never set (1), so it silently got (2) — which names Bluefin's
# maintainers and their roles. A Skipjack live ISO showed a correctly branded
# welcome screen above a Credits dialog listing "Bluefin Maintainer" and
# "Bluefin Maintainer Emeritus" (seen in tunaOS#1056's live-ISO screenshot).
#
# The mechanism was never broken and is documented in upstream's
# docs/live-iso.md. We simply had not used it. This asserts we do, and that
# what we point at actually exists — the same failure the variant logo had,
# where the recipe named a resource that resolved for no variant at all.

RECIPE="${BATS_TEST_DIRNAME}/../../system_files/etc/bootc-installer/recipe.json"
REPO_ROOT="${BATS_TEST_DIRNAME}/../.."

@test "recipe sets credits_data" {
  run python3 -c "
import json,sys
r=json.load(open('${RECIPE}'))
v=r.get('credits_data','')
print(v)
sys.exit(0 if v else 1)
"
  [ "$status" -eq 0 ] || {
    echo "recipe.json has no credits_data, so the Credits dialog falls back" >&2
    echo "to bootc-installer's built-in file, which credits Bluefin." >&2
    false
  }
}

@test "the credits file credits_data points at is shipped in the image" {
  run python3 -c "
import json,os,sys
r=json.load(open('${RECIPE}'))
v=r.get('credits_data','')
if v.startswith('/org/'):
    print('GResource path, not checkable here:', v); sys.exit(0)
# Filesystem paths are read from inside the flatpak, where the host's / is at
# /run/host. Strip that to find the file in this repo's system_files tree.
local = os.path.join('${REPO_ROOT}', 'system_files', v.replace('/run/host/','').lstrip('/'))
if not os.path.exists(local):
    print('credits_data points at', v, '-> expected', local, 'which does not exist')
    sys.exit(1)
json.load(open(local))
print('ok:', local)
"
  [ "$status" -eq 0 ] || {
    echo "$output" >&2
    false
  }
}

@test "our credits file does not credit Bluefin's maintainers as ours" {
  # The point of the exercise. Naming upstream projects in a 'Built On'
  # section is correct and wanted; listing Bluefin's people under our own
  # maintainer headings is not.
  run python3 -c "
import json,sys
r=json.load(open('${RECIPE}'))
v=r.get('credits_data','')
if v.startswith('/org/'): sys.exit(0)
import os
local=os.path.join('${REPO_ROOT}','system_files',v.replace('/run/host/','').lstrip('/'))
d=json.load(open(local))
bad=[]
for s in d.get('sections',[]):
    title=(s.get('title') or '').lower()
    for m in s.get('members',[]):
        role=(m.get('title') or '').lower()
        if 'maintainer' in role and 'bluefin' in role:
            bad.append(f\"{s.get('title')}/{m.get('handle')}: {m.get('title')}\")
if bad:
    print('Bluefin maintainer roles under our credits:'); [print(' ',b) for b in bad]
    sys.exit(1)
print('ok')
"
  [ "$status" -eq 0 ] || {
    echo "$output" >&2
    false
  }
}
