#!/usr/bin/env bats
# ADOPTERS.md says only what it can back up (tunaOS#1348).
#
# #1348's point is that the adopters list carries zero external adopters while
# Q4 positions the project as "Mature", and that the file is cited as evidence
# in the DistroWatch (#1333) and CNCF (#1340) pitches. Collecting real adopters
# is outreach work no agent can originate. What IS checkable is that the file
# does not appear to have adopters it does not have.
#
# Two ways it did:
#
#  1. A 24-row table headed "Ecosystem & Downstream Projects" in a file that
#     opens "organizations and projects that use TunaOS". Every one of those 24
#     is an UPSTREAM or a service TunaOS consumes — 7 base OSes, 5 desktop
#     environments it packages, registries, build services. None is downstream.
#     A reader checking the evidence would find Debian, Fedora, KDE and
#     elementary OS apparently listed as adopters.
#
#  2. The adopters KPI (#1463) counts "production/evaluation entry count", and
#     the two Development & Evaluation entries are the maintainer and TunaOS's
#     own CI — so the >=2 target was met by self-reference on the day it was
#     written, with zero external adopters.
#
# These tests pin the labelling and the KPI scope. They deliberately do NOT
# assert an adopter count: going from zero to one is the outreach work this
# issue is actually about, and a test demanding it would just be red until
# someone else did it.

REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
ADOPTERS="${REPO_ROOT}/ADOPTERS.md"
METRICS="${REPO_ROOT}/ADOPTION-METRICS.md"

@test "the dependency table is not labelled downstream" {
  # "Downstream" is the specific word that turns a dependency list into
  # apparent adoption.
  run grep -nE '^## .*Downstream' "$ADOPTERS"
  [ "$status" -ne 0 ]
}

@test "the dependency table says plainly that its entries are not adopters" {
  # A reader who lands mid-file, or an editor skimming for evidence, has to hit
  # the disclaimer before the 24 rows.
  run grep -F 'These are not adopters' "$ADOPTERS"
  [ "$status" -eq 0 ]
}

@test "the disclaimer comes before the dependency rows, not after them" {
  local dis rows
  dis="$(grep -n 'These are not adopters' "$ADOPTERS" | head -1 | cut -d: -f1)"
  rows="$(grep -nE '^\| \[' "$ADOPTERS" | awk -F: -v d="$dis" '$1 > d {print $1; exit}')"
  [ -n "$dis" ]
  [ -n "$rows" ]
  [ "$dis" -lt "$rows" ]
}

@test "the adopters KPI counts external entries only" {
  # Without the word, the metric is satisfiable by the project listing itself.
  run grep -nE '^\| Community \|.*adopters.*ADOPTERS\.md' "$METRICS"
  [ "$status" -eq 0 ]
  [[ "$output" == *"xternal"* ]]
}

@test "the KPI's baseline and target measure the same unit" {
  # The original read baseline "0 production entries" against target ">=2-3
  # public evaluator/production entries" — different units, which is the gap
  # the self-entries slipped through.
  local row
  row="$(grep -E '^\| Community \|.*adopters.*ADOPTERS\.md' "$METRICS" | head -1)"
  [ -n "$row" ]
  local baseline target
  baseline="$(echo "$row" | awk -F'|' '{print $5}')"
  target="$(echo "$row" | awk -F'|' '{print $6}')"
  [[ "$baseline" == *"xternal"* ]]
  [[ "$target" == *"xternal"* ]]
}

@test "the self-entries are marked as not counting toward adoption" {
  # The maintainer and the CI are legitimate dogfooding records. The problem is
  # only that they were countable.
  # Matched on one line: the sentence wraps, and grep is line-oriented.
  run grep -F '**not** external adoption' "$ADOPTERS"
  [ "$status" -eq 0 ]
}

@test "no production adopter is claimed while the section is empty" {
  # Guards the direction that actually matters for credibility: if someone adds
  # a Production Users row, the "None listed yet" placeholder must go with it,
  # so the file can never both claim and disclaim at once.
  if grep -qF '(None listed yet' "$ADOPTERS"; then
    local after
    after="$(awk '/^## Production Users/{f=1;next} /^## /{f=0} f' "$ADOPTERS" | grep -cE '^\| \[' || true)"
    [ "$after" -eq 0 ]
  fi
}
