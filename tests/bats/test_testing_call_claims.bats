#!/usr/bin/env bats
# A testing call names the Fedora stream testers are actually running (#1609).
#
# The draft invited Fedora 45 Beta testers to test `bonito:gnome|kde|niri` and
# report results that feed the Fedora Magazine pitch (#1137). None of those
# images is Fedora 45:
#
#   bonito:<flavor>          → Fedora 44 (build-config pins fedora-bootc:44)
#   bonito:<flavor>-rawhide  → Rawhide, which is Fedora 46 development now that
#                              fedora-bootc publishes both 45 and 46
#
# One release behind, one ahead. And it is deliberate: FEDORA-BASE-POLICY.md
# sequences Fedora 45 base work to start only after Bonito (F44) reaches GA
# (#272). So this is not a missing build — it is outreach promising a base the
# project has decided not to carry yet, which is the "promotion outruns
# product" risk #1171 named.
#
# The tests assert the doc is HONEST about the stream, not that any particular
# version is used — the version will change, and a test pinning "44" would be
# wrong the day the base moves. What must not change is that the reader can
# tell what they are installing.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
DOC="${REPO_ROOT}/docs/FEDORA45-TESTING-CALL.md"
CONFIG="${REPO_ROOT}/.github/build-config.yml"

setup() { [ -f "$DOC" ] || skip "testing call not present on this branch"; }

@test "the doc states which Fedora stream each image is" {
  # The correction that matters: a tester must not think bonito:gnome is F45.
  run grep -Fi 'does not ship a Fedora 45 image' "$DOC"
  [ "$status" -eq 0 ]
}

@test "the image table labels the stream per row" {
  # Per-row, not one disclaimer at the top — the table is what gets copied into
  # a forum post.
  run grep -cE '^\| `ghcr\.io/tuna-os/bonito:[a-z-]+`? \(F[0-9]+' "$DOC"
  [ "$status" -eq 0 ]
  [ "$output" -ge 3 ]
}

@test "the stated stable stream matches build-config" {
  # If someone bumps bonito's base and not this doc, the doc starts lying. Read
  # the version from the config rather than hardcoding it here.
  local ver
  ver="$(awk '/^  - id: bonito$/{f=1} f && /base_image:/{print; exit}' "$CONFIG" | grep -oE 'fedora-bootc:[0-9]+' | cut -d: -f2)"
  [ -n "$ver" ]
  run grep -F "Fedora ${ver}" "$DOC"
  [ "$status" -eq 0 ]
}

# A phrase blacklist for "bonito is on Fedora 45" was here and has been removed.
# It failed in both directions: it matched this document's own sentence
# explaining why that phrasing is wrong, and it missed the original draft, whose
# claim was never phrased that way — it was implied by inviting Fedora 45 Beta
# testers to test Bonito with no stream named anywhere. Tests 1-3 assert the
# positive property instead (the stream is stated per row, and matches
# build-config), which is what actually protects a reader. Asserting the
# presence of the truth beats blacklisting one spelling of the falsehood.

@test "every command the guide tells a tester to run exists" {
  # `just vm-run` was in the draft and is not a recipe. The first command in a
  # testing guide is the one most likely to be run and least likely to be
  # checked.
  local bad=0 r
  while read -r r; do
    grep -qE "^${r}( |:)" "${REPO_ROOT}/Justfile" || { echo "NOT A RECIPE: just $r" >&2; bad=$((bad+1)); }
  done < <(grep -oE '^just [a-z0-9-]+' "$DOC" | awk '{print $2}' | sort -u)
  [ "$bad" -eq 0 ]
}

@test "referenced helper scripts exist" {
  local bad=0 s
  while read -r s; do
    [ -f "${REPO_ROOT}/${s}" ] || { echo "MISSING: $s" >&2; bad=$((bad+1)); }
  done < <(grep -oE 'scripts/[a-z0-9._-]+\.sh' "$DOC" | sort -u)
  [ "$bad" -eq 0 ]
}
